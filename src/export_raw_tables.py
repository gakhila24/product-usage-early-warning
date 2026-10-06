"""
Export row-level tables for the legacy static dashboard so its global filter
bar genuinely drives every chart (spec requirement: "every KPI/chart via the
shared aggregations.js functions — do not hardcode numbers in components"),
rather than shipping pre-filtered static numbers that only look interactive.

Note: the new React "Signal" UI (see /frontend) does NOT use this file --
it calls the live Flask API in api.py directly, so every chart there is
driven by a real HTTP request rather than embedded JSON. This script is kept
only for regenerating the legacy single-file static dashboard artifact
(frontend_static/dashboard.html), which embeds this JSON directly since a
published static page can't call a live backend.
"""
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_PATH = Path(__file__).resolve().parent.parent / "frontend_static" / "raw_data.json"

LATEST_COLS = [
    "account_id", "segment", "region", "industry", "csm_owner", "contract_type",
    "arr_run_rate_usd", "monthly_spend_usd", "days_to_renewal", "risk_score", "risk_band",
    "heuristic_risk_score", "heuristic_risk_band", "churned_within_90d",
    "support_friction_score", "technical_friction_score", "feature_abandonment_rate_90d",
    "feature_adoption_score", "seat_utilization_pct", "engagement_score", "csat_score",
    "nps_last_survey", "days_since_last_login", "days_since_last_csm_touchpoint",
    "champion_turnover_flag_90d", "executive_sponsor_engaged", "qbr_attended_last_90d",
    "upsell_flag_90d", "downgrade_flag_90d", "revenue_movement_bucket", "age_bucket",
    "intervention_triggered_flag", "account_age_months", "avg_resolution_time_hrs",
]
MONTHLY_COLS = [
    "account_id", "panel_month_seq", "as_of_month", "segment", "region", "industry",
    "csm_owner", "churned_within_90d", "risk_score", "heuristic_risk_score",
    "engagement_score", "support_tickets_90d", "technical_issue_count_90d",
    "arr_run_rate_usd",
]


def main():
    conn = sqlite3.connect(DATA_DIR / "churn_data.db")
    monthly = pd.read_sql("SELECT * FROM account_monthly_metrics_enriched", conn)
    accounts = pd.read_sql("SELECT * FROM accounts", conn)
    scores = pd.read_sql("SELECT * FROM model_scores", conn)
    interventions = pd.read_sql("SELECT * FROM interventions", conn)
    baseline = pd.read_sql("SELECT * FROM baseline_benchmark", conn)
    conn.close()

    full = (
        monthly.merge(accounts, on="account_id")
        .merge(scores[["account_id", "as_of_month", "risk_score", "risk_band"]],
               on=["account_id", "as_of_month"], how="left")
        .merge(baseline[["account_id", "as_of_month", "heuristic_risk_score", "heuristic_risk_band"]],
               on=["account_id", "as_of_month"], how="left", suffixes=("", "_dup"))
    )
    # drop the duplicate heuristic columns that already existed on `monthly`
    full = full.loc[:, ~full.columns.str.endswith("_dup")]

    latest = full[full.panel_month_seq == 12][LATEST_COLS].copy()
    # drop as_of_month (redundant with panel_month_seq) to cut size further
    monthly_slim = full[[c for c in MONTHLY_COLS if c != "as_of_month"]].copy()

    iv = interventions.merge(
        accounts[["account_id", "segment", "region", "industry", "csm_owner"]],
        on="account_id", how="left",
    )

    def round_floats(df, nd=2):
        df = df.copy()
        for c in df.select_dtypes(include=["float64", "float32"]).columns:
            df[c] = df[c].round(nd)
        return df

    def columnar(df):
        """{columns: [...], data: [[row0 values...], [row1 values...]]} --
        no repeated keys, far smaller than record-per-row JSON for wide tables."""
        df = round_floats(df)
        df = df.where(pd.notna(df), None)
        return {"columns": list(df.columns), "data": df.values.tolist()}

    def records(df):
        return json.loads(round_floats(df).to_json(orient="records"))

    out = {
        "latest": columnar(latest),
        "monthly": columnar(monthly_slim),
        "interventions": records(iv),
        "feature_importance": records(pd.read_csv(DATA_DIR / "feature_importance.csv").head(12)),
        "model_metrics": json.load(open(DATA_DIR / "model_metrics.json")),
        "meta": {
            "as_of_month": str(full["as_of_month"].max()),
            "n_accounts": int(accounts.shape[0]),
        },
    }

    # gains chart precomputed on holdout only (see docstring -- a fixed
    # evaluation artifact, not filtered live; this is documented in the UI)
    holdout = full[full.panel_month_seq >= 10][
        ["account_id", "as_of_month", "churned_within_90d", "risk_score", "heuristic_risk_score"]
    ]

    def gains_curve(score_col):
        gg = holdout.sort_values(score_col, ascending=False).reset_index(drop=True)
        total_pos = gg["churned_within_90d"].sum()
        gg["cum_pos"] = gg["churned_within_90d"].cumsum()
        deciles = gg.iloc[[int(len(gg) * d / 10) - 1 for d in range(1, 11)]]
        return [
            {"pct_accounts": round((i + 1) / 10, 2),
             "pct_churners_captured": round(float(row["cum_pos"] / max(1, total_pos)), 4)}
            for i, (_, row) in enumerate(deciles.iterrows())
        ]

    out["gains_chart"] = {"model": gains_curve("risk_score"), "heuristic": gains_curve("heuristic_risk_score")}

    OUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, default=lambda o: None if (isinstance(o, float) and np.isnan(o)) else o)

    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"Wrote {OUT_PATH} ({size_kb:.0f} KB)")
    print(f"latest: {len(out['latest'])} rows, monthly: {len(out['monthly'])} rows, "
          f"interventions: {len(out['interventions'])} rows")


if __name__ == "__main__":
    main()
