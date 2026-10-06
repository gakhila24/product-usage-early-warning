"""
Synthetic Narrative Layer — Design Doc Section 2.5
=====================================================
Generates a deterministic, templated narrative per account-month from real
columns only (never invented), for the LATEST month per account (panel_month_seq
= 12) to keep the demo index a manageable size -- the same template applies to
every historical month identically.

Indexed with TF-IDF (scikit-learn) rather than a neural embedding model, since
this sandbox has no network access to call an embedding API. TF-IDF over a
templated, controlled vocabulary is a legitimate stand-in for this demo and
genuinely supports "find similar accounts by narrative text" queries; swapping
in real sentence embeddings (e.g., via the Claude API or a local model) later
is a drop-in replacement for `vectorize()` below -- said explicitly so this
isn't mistaken for the production-grade approach.
"""
import pickle
import sqlite3
from pathlib import Path

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "churn_data.db"


def describe_trend(pct):
    if pd.isna(pct):
        return "no trailing trend data yet"
    direction = "up" if pct > 0 else "down"
    return f"{direction} {abs(pct):.0f}% over 90 days"


def build_narrative(row) -> str:
    parts = [
        f"{row.account_id} ({row.segment}, {row.region}, {row.industry})",
        f"engagement {describe_trend(row.usage_trend_90d_pct)}",
    ]
    if row.high_priority_tickets_90d and row.high_priority_tickets_90d > 0:
        parts.append(f"{int(row.high_priority_tickets_90d)} high-priority ticket(s) in the last 90 days")
    if pd.notna(row.nps_last_survey):
        parts.append(f"latest NPS {int(row.nps_last_survey)}")
    if row.days_since_last_csm_touchpoint and row.days_since_last_csm_touchpoint > 60:
        parts.append(f"no CSM touchpoint in {int(row.days_since_last_csm_touchpoint)} days")
    if not row.executive_sponsor_engaged:
        parts.append("no executive sponsor engagement in the last 90 days")
    if row.champion_turnover_flag_90d:
        parts.append("champion turnover flagged in the last 90 days")
    # 2026-10 addition: the model's risk band, payment/renewal context and key flags are now part of the narrative
    # text, so free-text questions such as "which accounts are Critical?", "Enterprise accounts with payment
    # risk" or "High-risk accounts renewing in 90 days" have vocabulary to match against in the TF-IDF index.
    if getattr(row, "risk_band", None):
        parts.append(f"{row.risk_band} risk band (score {row.risk_score:.0f})")
    if row.invoice_overdue_flag or (row.payment_failure_90d_count and row.payment_failure_90d_count > 0):
        parts.append("payment risk: overdue invoice or failed payments")
    if pd.notna(row.days_to_renewal) and 0 <= row.days_to_renewal <= 90:
        parts.append(f"renewing in {int(row.days_to_renewal)} days (renewal within 90 days)")
    parts.append(f"ARR run-rate ${row.arr_run_rate_usd:,.0f}")
    parts.append(
        "intervention currently logged" if row.intervention_triggered_flag
        else "no intervention currently logged"
    )
    return " — ".join(parts) + "."


def main():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        """
        SELECT m.*, a.segment, a.industry, a.region, a.csm_owner, s.risk_score, s.risk_band
        FROM account_monthly_metrics_enriched m
        JOIN accounts a ON a.account_id = m.account_id
        LEFT JOIN model_scores s ON s.account_id = m.account_id AND s.panel_month_seq = m.panel_month_seq
        WHERE m.panel_month_seq = 12
        """,
        conn,
    )
    conn.close()

    df["narrative"] = df.apply(build_narrative, axis=1)
    narratives = df[["account_id", "as_of_month", "narrative"]]
    narratives.to_csv(DATA_DIR / "narratives.csv", index=False)

    vectorizer = TfidfVectorizer(max_features=500, stop_words="english")
    matrix = vectorizer.fit_transform(narratives["narrative"])
    with open(DATA_DIR / "narrative_index.pkl", "wb") as f:
        pickle.dump({"vectorizer": vectorizer, "matrix": matrix,
                     "account_ids": narratives["account_id"].tolist()}, f)

    print("=== Sample narratives ===")
    for n in narratives["narrative"].head(3):
        print(f"- {n}")

    print("\n=== Demo semantic search: find accounts similar to ACC-30005 ===")
    query_idx = narratives.index[narratives["account_id"] == "ACC-30005"]
    if len(query_idx):
        qvec = matrix[query_idx[0]]
        sims = cosine_similarity(qvec, matrix).flatten()
        top = sims.argsort()[::-1][1:6]
        for i in top:
            print(f"  {narratives.iloc[i]['account_id']}  (similarity={sims[i]:.3f})")

    print(f"\nWrote narratives.csv + narrative_index.pkl to {DATA_DIR}")


if __name__ == "__main__":
    main()
