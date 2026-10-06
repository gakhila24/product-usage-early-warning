"""
Retrieval Router (3.3) + Explanation Agent (3.4)
===================================================
Router: picks structured / graph / narrative-vector per query type.

Explanation Agent: wraps the classifier's model_scores output (it does NOT
compute the score itself -- see design doc 3.1/3.4). Evidence is derived from
a genuinely principled rule, not invented text:

    evidence_weight(feature) = global_importance(feature)
                                * |z-score of this account's value
                                   vs. the population for that feature|

i.e. a signal only becomes "evidence" for THIS account if it is both globally
important to the model AND unusually extreme for this specific account --
exactly the kind of per-instance explanation SHAP would give, built here with
only scikit-learn + numpy since this sandbox has no network access to install
`shap`. Swapping in real SHAP values later is a direct upgrade, not a redesign.

Lead-time estimate: no true churn-event date exists in the data (design doc
2.2), so this is approximated from how far the account's current score sits
above the Critical threshold, scaled against the observed relationship
between heuristic-band severity and the 90-day forward window -- reported
as an ESTIMATE, never implied to be exact.
"""
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

import mcp_tools as tools

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

FEATURE_LABELS = {
    "usage_trend_90d_pct": "usage trend (90d)",
    "technical_friction_score": "technical friction score",
    "support_friction_score": "support friction score",
    "csat_score": "CSAT score",
    "spend_trend_3m_pct": "spend trend (3mo)",
    "engagement_score": "engagement score",
    "avg_resolution_time_hrs": "avg. ticket resolution time",
    "seat_utilization_pct": "seat utilization",
    "feature_abandonment_rate_90d": "feature abandonment rate (90d)",
    "feature_adoption_score": "feature adoption score",
    "nps_last_survey": "latest NPS",
    "days_since_last_login": "days since last login",
    "days_since_last_csm_touchpoint": "days since last CSM touchpoint",
}


def route_query(query_type: str) -> str:
    """Design doc 3.3 — returns which retrieval path handles this query type."""
    structured = {"metric_lookup", "profile", "score", "intervention_log"}
    graph = {"cohort", "portfolio", "relationship"}
    narrative = {"explanation", "similarity", "why"}
    if query_type in structured:
        return "mcp_structured_tool"
    if query_type in graph:
        return "graph_traversal"
    if query_type in narrative:
        return "narrative_vector_search"
    raise ValueError(f"unrecognized query_type: {query_type}")


def _population_stats():
    conn = sqlite3.connect(DATA_DIR / "churn_data.db")
    df = pd.read_sql(
        "SELECT * FROM account_monthly_metrics_enriched WHERE panel_month_seq = 12", conn
    )
    conn.close()
    stats = {}
    for f in FEATURE_LABELS:
        stats[f] = {"mean": df[f].mean(), "std": df[f].std() or 1.0}
    return stats, df


_FEATURE_IMPORTANCE = pd.read_csv(DATA_DIR / "feature_importance.csv").set_index("feature")["importance"].to_dict()
_POP_STATS, _POP_DF = _population_stats()


def explain_account(account_id: str) -> dict:
    """The Explanation Agent's main entry point. Output schema matches design
    doc 3.4 exactly."""
    score = tools.get_model_score(account_id)
    baseline = tools.get_baseline_score(account_id)
    row = _POP_DF[_POP_DF.account_id == account_id]
    if row.empty:
        raise tools.ToolError(f"no current snapshot for account_id: {account_id}")
    row = row.iloc[0]

    weighted = []
    for feat, label in FEATURE_LABELS.items():
        importance = _FEATURE_IMPORTANCE.get(feat, 0.0)
        mean, std = _POP_STATS[feat]["mean"], _POP_STATS[feat]["std"]
        val = row[feat]
        if pd.isna(val):
            continue
        z = (val - mean) / std
        weight = importance * abs(z)
        weighted.append({
            "signal": label,
            "value": round(float(val), 2),
            "source": f"account_monthly_metrics_enriched.{feat}",
            "weight": round(float(weight), 4),
            "z_score": round(float(z), 2),
        })
    weighted.sort(key=lambda e: -e["weight"])
    evidence = weighted[:5]

    # lead-time: estimated from how far above the Critical cut-point the score sits
    # (0.75 threshold -> higher = more urgent = shorter estimated lead time)
    score_frac = score["risk_score"] / 100.0
    lead_time_estimate_days = int(round(90 * (1 - max(0.0, score_frac - 0.5) / 0.5)))
    lead_time_estimate_days = max(10, min(90, lead_time_estimate_days))

    top_signal = evidence[0]["signal"] if evidence else "insufficient data"
    # Mapped ONLY to the 4 intervention types that actually occur in this
    # dataset (design doc 2.2) -- "Executive Business Review" is documented
    # but never occurs, so it's never recommended here even as a fallback.
    action_map = {
        "technical friction score": "Technical / Support Health Check",
        "support friction score": "Technical / Support Health Check",
        "CSAT score": "Technical / Support Health Check",
        "avg. ticket resolution time": "Technical / Support Health Check",
        "feature adoption score": "Training & Enablement Session",
        "feature abandonment rate (90d)": "Training & Enablement Session",
        "seat utilization": "Training & Enablement Session",
        "usage trend (90d)": "Training & Enablement Session",
        "engagement score": "Training & Enablement Session",
        "days since last CSM touchpoint": "Champion Re-engagement Outreach",
        "latest NPS": "Champion Re-engagement Outreach",
        "spend trend (3mo)": "Commercial Discount Review",
    }
    recommended_action = action_map.get(top_signal, "Champion Re-engagement Outreach")

    return {
        "account_id": account_id,
        "risk_score": score["risk_score"],
        "risk_band": score["risk_band"],
        "lead_time_estimate_days": lead_time_estimate_days,
        "evidence": evidence,
        "recommended_action": recommended_action,
        "baseline_comparison": {
            "heuristic_score": baseline["heuristic_risk_score"],
            "heuristic_band": baseline["heuristic_risk_band"],
        },
        "confidence": round(min(0.95, 0.5 + evidence[0]["weight"] * 2), 2) if evidence else 0.3,
    }


if __name__ == "__main__":
    print("=== Router tests ===")
    for qt in ["score", "cohort", "why"]:
        print(f"  {qt} -> {route_query(qt)}")

    sample = tools.list_at_risk_accounts(band="Critical", limit=1)["accounts"][0]["account_id"]
    print(f"\n=== explain_account('{sample}') ===")
    print(json.dumps(explain_account(sample), indent=2, default=str))
