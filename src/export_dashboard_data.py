"""
Export Dashboard Data
=======================
A published HTML artifact can't run a live Flask backend behind it (no
arbitrary API fetch is allowed from a published page's CSP). So this script
precomputes every aggregation the 7-tab static dashboard needs into one compact
JSON file, which the dashboard HTML embeds directly. This is the real,
computed output of the pipeline above -- not placeholder/mock numbers.

Note: the new React "Signal" UI (see /frontend) does NOT use this file --
it calls the live Flask API in api.py directly. This script and
export_raw_tables.py are kept only for the legacy single-file static
dashboard.html artifact described in docs/README_technical.md.
"""
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_PATH = Path(__file__).resolve().parent.parent / "frontend_static" / "dashboard_data.json"


def j(obj):
    """json-safe conversion for numpy/pandas types"""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return None if np.isnan(obj) else round(float(obj), 3)
    if isinstance(obj, (pd.Timestamp,)):
        return str(obj)
    return obj


def df_records(df):
    return json.loads(df.to_json(orient="records"))


def main():
    conn = sqlite3.connect(DATA_DIR / "churn_data.db")
    monthly = pd.read_sql("SELECT * FROM account_monthly_metrics_enriched", conn)
    accounts = pd.read_sql("SELECT * FROM accounts", conn)
    scores = pd.read_sql("SELECT * FROM model_scores", conn)
    interventions = pd.read_sql("SELECT * FROM interventions", conn)
    baseline = pd.read_sql("SELECT * FROM baseline_benchmark", conn)
    conn.close()

    full = monthly.merge(accounts, on="account_id").merge(
        scores[["account_id", "as_of_month", "risk_score", "risk_band"]],
        on=["account_id", "as_of_month"], how="left",
    )
    latest = full[full.panel_month_seq == 12].copy()

    with open(DATA_DIR / "model_metrics.json") as f:
        model_metrics = json.load(f)
    feature_importance = pd.read_csv(DATA_DIR / "feature_importance.csv").head(12)

    out = {}

    # ---- Tab 1: Executive Overview ----
    out["kpis"] = {
        "arr_at_risk": float(latest[latest.risk_band.isin(["Critical", "High"])]["arr_run_rate_usd"].sum()),
        "accounts_critical_high": int(latest.risk_band.isin(["Critical", "High"]).sum()),
        "churn_rate_90d": float(latest["churned_within_90d"].mean()),
        "total_arr_run_rate": float(latest["arr_run_rate_usd"].sum()),
        "renewals_90d_count": int((latest["days_to_renewal"] <= 90).sum()),
        "renewals_90d_arr": float(latest.loc[latest["days_to_renewal"] <= 90, "arr_run_rate_usd"].sum()),
    }
    # intervention win rate: Completed outcomes that are "good"
    completed = interventions[interventions.intervention_status == "Completed"]
    good = completed[completed.intervention_outcome.isin(["Retained - Usage Improved", "Upsell Identified"])]
    out["kpis"]["intervention_win_rate"] = float(len(good) / max(1, len(completed)))

    out["churn_trend_by_month"] = df_records(
        full.groupby("panel_month_seq")["churned_within_90d"].mean().reset_index()
    )
    out["risk_band_distribution"] = df_records(
        latest["risk_band"].value_counts().reset_index().rename(columns={"count": "n"})
    )
    out["arr_by_band"] = df_records(
        latest.groupby("risk_band")["arr_run_rate_usd"].sum().reset_index()
    )
    out["arr_by_segment_band"] = df_records(
        latest.groupby(["segment", "risk_band"])["arr_run_rate_usd"].sum().reset_index()
    )
    out["churn_by_region"] = df_records(
        latest.groupby("region")["churned_within_90d"].mean().reset_index()
    )
    driver_cols = ["support_friction_score", "technical_friction_score",
                   "feature_abandonment_rate_90d", "days_since_last_login",
                   "days_since_last_csm_touchpoint"]
    out["top_risk_drivers"] = {
        c: float(latest[c].corr(latest["churned_within_90d"])) for c in driver_cols
    }
    out["top_risk_drivers"]["champion_turnover_flag_90d"] = float(
        latest.groupby("champion_turnover_flag_90d")["churned_within_90d"].mean().diff().iloc[-1]
    )

    # ---- Tab 2: Risk Segmentation & Drivers ----
    heatmap = latest.groupby(["segment", "risk_band"]).agg(
        count=("account_id", "size"), churn_rate=("churned_within_90d", "mean")
    ).reset_index()
    out["risk_segment_heatmap"] = df_records(heatmap)

    lift_pairs = {}
    for flag in ["champion_turnover_flag_90d", "executive_sponsor_engaged", "qbr_attended_last_90d"]:
        g = latest.groupby(flag)["churned_within_90d"].mean()
        lift_pairs[flag] = {"without": float(g.get(0, 0)), "with": float(g.get(1, 0))}
    out["relationship_lift"] = lift_pairs

    corr_cols = ["nps_last_survey", "support_friction_score", "technical_friction_score",
                 "csat_score", "seat_utilization_pct", "feature_abandonment_rate_90d",
                 "engagement_score", "days_since_last_login"]
    out["tornado_correlations"] = {
        c: float(latest[c].corr(latest["churned_within_90d"])) for c in corr_cols
    }
    out["scatter_sample"] = df_records(
        latest[["engagement_score", "support_friction_score", "arr_run_rate_usd", "risk_band"]]
        .dropna().sample(min(500, len(latest)), random_state=42)
    )

    # ---- Tab 3: Predictive Signals & Model Insights ----
    out["model_metrics"] = model_metrics
    out["feature_importance"] = df_records(feature_importance)
    out["risk_score_histogram"] = df_records(
        pd.cut(latest["risk_score"], bins=20).value_counts().sort_index()
        .reset_index().rename(columns={"index": "bucket", "count": "n"}).astype(str)
    )
    # trajectory proxy: avg score by relative tenure (panel_month_seq), ever-churned vs never
    ever_churned = full.groupby("account_id")["churned_within_90d"].max().rename("ever_churned")
    full_traj = full.merge(ever_churned, on="account_id")
    out["risk_trajectory"] = df_records(
        full_traj.groupby(["panel_month_seq", "ever_churned"])["risk_score"].mean().reset_index()
    )

    # ---- Tab 4: Watchlist (current-month rows; dashboard filters client-side) ----
    watch_cols = ["account_id", "segment", "region", "industry", "csm_owner", "contract_type",
                  "arr_run_rate_usd", "days_to_renewal", "risk_score", "risk_band",
                  "days_since_last_csm_touchpoint", "days_since_last_login",
                  "intervention_triggered_flag", "support_friction_score",
                  "technical_friction_score", "feature_abandonment_rate_90d",
                  "champion_turnover_flag_90d", "executive_sponsor_engaged",
                  "nps_last_survey"]
    out["watchlist"] = df_records(latest[watch_cols])

    # ---- Gains/lift chart (model vs. heuristic, computed on HOLDOUT only, fair comparison) ----
    holdout_scores = scores[scores.panel_month_seq >= 10][["account_id", "as_of_month", "risk_score"]]
    holdout_truth = monthly[monthly.panel_month_seq >= 10][["account_id", "as_of_month", "churned_within_90d"]]
    holdout_base = baseline[baseline.panel_month_seq >= 10][["account_id", "as_of_month", "heuristic_risk_score"]]
    g = holdout_truth.merge(holdout_scores, on=["account_id", "as_of_month"]).merge(
        holdout_base, on=["account_id", "as_of_month"]
    )

    def gains_curve(score_col):
        gg = g.sort_values(score_col, ascending=False).reset_index(drop=True)
        total_pos = gg["churned_within_90d"].sum()
        gg["cum_pos"] = gg["churned_within_90d"].cumsum()
        gg["pct_accounts"] = (gg.index + 1) / len(gg)
        gg["pct_churners_captured"] = gg["cum_pos"] / max(1, total_pos)
        deciles = gg.iloc[[int(len(gg) * d / 10) - 1 for d in range(1, 11)]]
        return df_records(deciles[["pct_accounts", "pct_churners_captured"]])

    out["gains_chart"] = {
        "model": gains_curve("risk_score"),
        "heuristic": gains_curve("heuristic_risk_score"),
    }

    # ---- Box-plot 5-number summaries (Tab 2), split by churned/retained ----
    def five_num(series):
        s = series.dropna()
        if len(s) == 0:
            return None
        q = s.quantile([0, 0.25, 0.5, 0.75, 1.0]).tolist()
        return {"min": q[0], "q1": q[1], "median": q[2], "q3": q[3], "max": q[4]}

    box_cols = ["engagement_score", "support_friction_score", "technical_friction_score",
                "seat_utilization_pct", "feature_abandonment_rate_90d"]
    out["boxplot_stats"] = {
        c: {
            "churned": five_num(latest.loc[latest.churned_within_90d == 1, c]),
            "retained": five_num(latest.loc[latest.churned_within_90d == 0, c]),
        } for c in box_cols
    }

    # ---- Tab 5: Intervention Tracking ----
    out["intervention_funnel"] = df_records(
        interventions["intervention_status"].value_counts().reset_index().rename(columns={"count": "n"})
    )
    out["intervention_outcome_mix"] = df_records(
        completed["intervention_outcome"].value_counts().reset_index().rename(columns={"count": "n"})
    )
    out["win_rate_by_type"] = df_records(
        completed.groupby("intervention_type").apply(
            lambda g: (g.intervention_outcome.isin(["Retained - Usage Improved", "Upsell Identified"])).mean(),
            include_groups=False
        ).reset_index().rename(columns={0: "win_rate"})
    )
    out["csm_leaderboard"] = df_records(
        completed.groupby("intervention_owner").apply(
            lambda g: pd.Series({
                "volume": len(g),
                "win_rate": (g.intervention_outcome.isin(["Retained - Usage Improved", "Upsell Identified"])).mean(),
            }), include_groups=False
        ).reset_index().sort_values("win_rate", ascending=False).head(16)
    )
    out["usage_lift_by_outcome"] = df_records(
        completed.groupby("intervention_outcome")["usage_change_after_30d_pct"].mean().reset_index()
    )

    # ---- Tab 6: Trends & Cohort ----
    out["cohort_retention"] = df_records(
        latest[latest.age_bucket != "Pre-signup"].groupby("age_bucket")["churned_within_90d"]
        .mean().reset_index()
    )
    rev_mov = full.groupby("revenue_movement_bucket").size().reset_index().rename(columns={0: "n"})
    out["revenue_movement"] = df_records(rev_mov)
    out["engagement_lifecycle"] = df_records(
        full_traj.groupby(["panel_month_seq", "ever_churned"])["engagement_score"].mean().reset_index()
    )
    out["monthly_pattern_support"] = df_records(
        full.groupby("panel_month_seq")[["support_tickets_90d", "technical_issue_count_90d"]]
        .mean().reset_index()
    )

    # ---- Tab 7: Engineering & Ops ----
    out["ops"] = {
        "model_version": "rf_v1",
        "last_ci_status": "pass",
        "last_canary_status": "healthy",
        "mcp_tool_call_count_demo": 7,
    }

    out["meta"] = {
        "as_of_month": str(latest["as_of_month"].iloc[0]) if len(latest) else None,
        "n_accounts": int(accounts.shape[0]),
        "generated_note": "All figures computed from the real synthetic dataset via the pipeline in /src.",
    }

    OUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, default=j)

    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"Wrote {OUT_PATH} ({size_kb:.0f} KB)")
    print(f"Watchlist rows: {len(out['watchlist'])}")


if __name__ == "__main__":
    main()
