"""
Dashboard Aggregation Service — backs the React "Signal" UI (/frontend) via
the Flask API in api.py.

2026-10 update (this revision):
  1. Fixed a real reliability bug: get_model_performance() measured p95
     latency by calling tools.get_model_score() 200 times in a row, each of
     which opens its own new sqlite3 connection (see mcp_tools.py's _conn()).
     200 sequential connection opens is slow enough on some machines/disks
     to make this one endpoint take many seconds -- and because Flask's dev
     server defaults to handling one request at a time, every other
     in-flight dashboard request queues up behind it. That's the most
     likely cause of the Evaluation tab appearing to hang forever ("Not
     coming"). Fixed two ways: the sample size dropped from 200 to 40
     (still a real, representative timing, just fewer round trips), and
     api.py now runs the Flask dev server with threaded=True so concurrent
     requests no longer serialize behind one slow one. See api.py's own
     2026-10 note for the matching client-side fix (a request timeout).
  2. Added the chart-data functions needed to bring the legacy 7-tab static
     dashboard's charts (export_dashboard_data.py) into the new React UI's
     tabs: get_region_churn, get_arr_by_band, get_feature_importance,
     get_risk_histogram, get_gains_chart, get_risk_heatmap,
     get_boxplot_stats, get_intervention_funnel, get_csm_leaderboard,
     get_win_rate_by_type. Every one of these is computed from the same
     real tables the rest of this file already reads -- nothing here is
     ported from the old dashboard's embedded JSON, it's recomputed fresh.

Why this file exists at all: mcp_tools.py exposes account-level, cohort-
level, and intervention-level reads (the MCP tool catalog from design doc
3.2). The React dashboard additionally needs portfolio-level aggregates
shaped for specific chart components. Those aggregates don't belong in the
MCP tool catalog (they're view-shaping, not reusable structured/graph/
narrative retrieval), so they live here instead, and api.py's
/api/dashboard/* routes call straight into this module.

Field-naming honesty notes (read before trusting a field 1:1 against your
data dictionary):
  - "plan" in the UI is mapped from `contract_type` -- there is no separate
    subscription-plan field in this dataset, and `contract_type` (e.g.
    Monthly/Annual/Multi-Year) is the closest real analogue.
  - "name" in the UI is mapped from `account_id` -- there is no company
    display-name field in this dataset.
  - "usage" (labeled "Usage trend (30d)" in AccountsTable.jsx) is mapped from
    `usage_trend_90d_pct` -- this dataset only tracks a 90-day usage trend,
    not a 30-day one. The UI's column header is left as-is (a frontend copy
    fix, not a backend concern) but is inaccurate until that label is edited.
  - "wow" (week-over-week delta in the UI's copy) is actually a month-over-
    month delta here (this month's risk_score minus last month's, panel
    month 12 vs 11) -- there is no weekly scoring cadence in this dataset.
  - "csat" is passed through on whatever scale `csat_score` is natively
    recorded on. Views.jsx hardcodes a "/ 5" suffix when displaying it --
    verify that assumption against your real data dictionary once loaded;
    if your CSAT is on a different scale, edit that suffix in Views.jsx.
  - "firmographicRisk" is a composite not present in the original pipeline:
    True when company_layoff_flag_90d OR leadership_change_flag_90d is set.
    This is a reasonable proxy for "something risky happened at the company
    level," added specifically to back the UI's "Firmographic risk" badge,
    not a field that exists natively in account_monthly_metrics.
  - "paymentRisk" is a composite: True when invoice_overdue_flag is set OR
    payment_failure_90d_count > 0.
  - Risk-segment heatmap groups by `segment` (the account's commercial
    segment, e.g. SMB/Mid-Market/Enterprise) x `risk_band` -- not by
    `industry`. If your heatmap looks wrong, confirm `segment` is populated
    the way you expect in the `accounts` table.
"""
import math
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import mcp_tools as tools
from explanation_agent import (
    FEATURE_LABELS, _FEATURE_IMPORTANCE, _POP_STATS, _POP_DF, explain_account,
)
from drift_monitor import compute_drift_report, validate_drift_detector

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "churn_data.db"

RISK_COLORS = {"Critical": "#c5525f", "High": "#dd929c", "Medium": "#e4bf83", "Low": "#167d8d"}

PLAY_STEPS = {
    "Technical / Support Health Check": [
        "Review the last 5 support tickets for a pattern",
        "Loop in a technical specialist for a health check",
        "Offer a proactive office-hours session",
        "Confirm resolution with the account's admin",
    ],
    "Training & Enablement Session": [
        "Pull the 90-day usage trend for the account",
        "Schedule a 20-minute check-in with the primary user",
        "Share a tailored adoption tip based on unused features",
        "Log the outcome within 7 days",
    ],
    "Champion Re-engagement Outreach": [
        "Identify the current primary stakeholder",
        "Send a warm re-introduction with a short account recap",
        "Offer a tailored onboarding refresher",
        "Confirm an executive sponsor is engaged",
    ],
    "Commercial Discount Review": [
        "Pull the account's spend trend and discount history",
        "Loop in revenue/deal desk on renewal terms",
        "Propose a commercial adjustment ahead of renewal",
        "Document the outcome against the next renewal date",
    ],
}
PLAY_META = {
    "Technical / Support Health Check": {"id": "technical_support_health_check", "icon": "life-buoy", "color": "blue", "category": "Support", "trigger": "technical friction score", "band": "High risk"},
    "Training & Enablement Session": {"id": "training_enablement_session", "icon": "zap", "color": "violet", "category": "Engagement", "trigger": "usage trend (90d)", "band": "High risk"},
    "Champion Re-engagement Outreach": {"id": "champion_reengagement_outreach", "icon": "user-round", "color": "orange", "category": "Relationship", "trigger": "days since last CSM touchpoint", "band": "High risk"},
    "Commercial Discount Review": {"id": "commercial_discount_review", "icon": "dollar", "color": "green", "category": "Commercial", "trigger": "spend trend (3mo)", "band": "Medium risk"},
}
PLAY_ID_TO_TITLE = {v["id"]: k for k, v in PLAY_META.items()}


def _conn():
    return sqlite3.connect(DB_PATH)


def _fmt_date(d) -> str:
    """Portable replacement for strftime("%b %-d, %Y") -- the "%-d" flag is not supported on Windows,
    where it raised ValueError (silently swallowed -> renewal dates showed as empty)."""
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def _latest_df() -> pd.DataFrame:
    conn = _conn()
    df = pd.read_sql(
        """
        SELECT m.*, a.segment, a.region, a.industry, a.csm_owner, a.contract_type, a.company_name,
               s.risk_score, s.risk_band
        FROM account_monthly_metrics_enriched m
        JOIN accounts a ON a.account_id = m.account_id
        JOIN model_scores s ON s.account_id = m.account_id AND s.as_of_month = m.as_of_month
        WHERE m.panel_month_seq = 12
        """,
        conn,
    )
    conn.close()
    return df


def _money_compact(value: float) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "$0"
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000:
        return f"{sign}${value/1_000_000:.1f}M"
    if value >= 1_000:
        return f"{sign}${value/1_000:.0f}K"
    return f"{sign}${value:.0f}"


def _vectorized_top_signal(df: pd.DataFrame) -> pd.Series:
    """Batched version of explain_account()'s evidence-ranking formula,
    computed across the whole dataframe at once (instead of one SQL round
    trip per account) so the accounts list endpoint stays fast. Returns the
    single top-signal label per row; the full ranked evidence list is only
    computed per-account, on demand, in get_account_detail()."""
    best_weight = pd.Series(-np.inf, index=df.index)
    best_label = pd.Series("insufficient data", index=df.index)
    for feat, label in FEATURE_LABELS.items():
        if feat not in df.columns:
            continue
        importance = _FEATURE_IMPORTANCE.get(feat, 0.0)
        mean, std = _POP_STATS[feat]["mean"], _POP_STATS[feat]["std"]
        z = (df[feat] - mean) / (std or 1.0)
        weight = importance * z.abs()
        better = weight.fillna(-np.inf) > best_weight
        best_weight = weight.where(better, best_weight)
        best_label = best_label.where(~better, label)
    return best_label


def get_summary() -> list[dict]:
    df = _latest_df()
    critical = int((df.risk_band == "Critical").sum())
    crit_high_arr = float(df.loc[df.risk_band.isin(["Critical", "High"]), "arr_run_rate_usd"].sum())
    payment_risk = df["invoice_overdue_flag"].astype(bool) | (df["payment_failure_90d_count"] > 0)
    return [
        {"key": "highRisk", "value": critical, "delta": f"{critical} in the Critical band"},
        {"key": "revenue", "value": _money_compact(crit_high_arr), "delta": "Critical + High bands"},
        {"key": "paymentRisk", "value": int(payment_risk.sum()), "delta": "Overdue invoice or failed payment, 90d"},
    ]


def get_risk_distribution() -> list[dict]:
    df = _latest_df()
    total = max(1, len(df))
    out = []
    for band in ("Critical", "High", "Medium", "Low"):
        count = int((df.risk_band == band).sum())
        out.append({"band": band, "count": count, "pct": round(count / total * 100), "color": RISK_COLORS[band]})
    return out


def get_risk_trend() -> list[dict]:
    conn = _conn()
    df = pd.read_sql(
        """
        SELECT s.panel_month_seq, s.as_of_month, s.risk_band
        FROM model_scores s
        WHERE s.panel_month_seq BETWEEN 1 AND 12
        """,
        conn,
    )
    conn.close()
    grouped = df.groupby(["panel_month_seq", "as_of_month"]).apply(
        lambda g: int(g.risk_band.isin(["Critical", "High"]).sum()), include_groups=False
    ).reset_index(name="value").sort_values("panel_month_seq")
    return [{"date": str(row.as_of_month), "value": int(row.value)} for row in grouped.itertuples()]


def get_accounts() -> list[dict]:
    df = _latest_df()
    conn = _conn()
    prev = pd.read_sql(
        "SELECT account_id, risk_score FROM model_scores WHERE panel_month_seq = 11", conn
    ).set_index("account_id")["risk_score"]
    conn.close()

    df["top_signal"] = _vectorized_top_signal(df)
    df["wow"] = (df["risk_score"] - df["account_id"].map(prev)).fillna(0).round(1)
    df["payment_risk"] = df["invoice_overdue_flag"].astype(bool) | (df["payment_failure_90d_count"] > 0)
    df["firmographic_risk"] = df["company_layoff_flag_90d"].astype(bool) | df["leadership_change_flag_90d"].astype(bool)

    out = []
    for row in df.itertuples():
        renewal_date = None
        try:
            base_date = datetime.strptime(str(row.as_of_month)[:10], "%Y-%m-%d")
            renewal_date = _fmt_date(base_date + timedelta(days=int(row.days_to_renewal)))
        except Exception:
            renewal_date = None
        days = row.days_to_renewal
        urgency = "This month" if days <= 30 else "This quarter" if days <= 90 else "Not urgent"
        out.append({
            "id": row.account_id,
            "name": getattr(row, "company_name", None) or row.account_id,
            "industry": row.industry,
            "plan": row.contract_type,
            "region": row.region,
            "csmOwner": row.csm_owner,
            "score": round(float(row.risk_score)),
            "band": row.risk_band,
            "arr": float(row.arr_run_rate_usd),
            "usage": round(float(row.usage_trend_90d_pct), 1) if pd.notna(row.usage_trend_90d_pct) else 0.0,
            "wow": float(row.wow),
            "signal": row.top_signal,
            "renewalDays": int(row.days_to_renewal),
            "renewal": renewal_date,
            "urgency": urgency,
            "paymentRisk": bool(row.payment_risk),
            "firmographicRisk": bool(row.firmographic_risk),
            "csat": float(row.csat_score) if pd.notna(row.csat_score) else None,
            "nps": int(row.nps_last_survey) if pd.notna(row.nps_last_survey) else None,
            "seatUtilizationPct": float(row.seat_utilization_pct) if pd.notna(row.seat_utilization_pct) else None,
            "monthlySpend": float(row.monthly_spend_usd),
            "supportTickets90d": int(row.support_tickets_90d),
            "daysSinceCsmTouchpoint": int(row.days_since_last_csm_touchpoint),
        })
    return out


def get_plays() -> list[dict]:
    return [
        {
            "id": meta["id"], "icon": meta["icon"], "color": meta["color"], "band": meta["band"],
            "category": meta["category"], "title": title, "trigger": meta["trigger"],
            "steps": PLAY_STEPS[title],
        }
        for title, meta in PLAY_META.items()
    ]


def get_recent_actions(limit: int = 20) -> list[dict]:
    conn = _conn()
    df = pd.read_sql(
        """
        SELECT i.*, a.csm_owner AS account_csm_owner, a.company_name AS company_name
        FROM interventions i
        JOIN accounts a ON a.account_id = i.account_id
        ORDER BY i.intervention_date DESC
        LIMIT ?
        """,
        conn, params=(limit,),
    )
    conn.close()
    out = []
    for row in df.itertuples():
        note = f"{row.intervention_type} logged by {row.intervention_owner or row.account_csm_owner}."
        if pd.notna(row.intervention_outcome) and row.intervention_outcome:
            note += f" Outcome: {row.intervention_outcome}."
        out.append({
            "accountId": row.account_id,
            "account": row.company_name or row.account_id,
            "play": row.intervention_type,
            "status": row.intervention_status,
            "action": note,
            "date": row.intervention_date,
        })
    return out


def get_drift() -> dict:
    report = compute_drift_report()
    return {
        "nFeaturesAlerting": report["nFeaturesAlerting"],
        "alertThreshold": report["alertThreshold"],
        "asOfDate": report["asOfDate"],
        "signals": report["signals"],
    }


def get_meta() -> dict:
    conn = _conn()
    row = conn.execute(
        "SELECT as_of_month, model_version FROM model_scores WHERE panel_month_seq = 12 LIMIT 1"
    ).fetchone()
    conn.close()
    if row is None:
        return {"asOf": None, "modelVersion": None}
    return {"asOf": row[0], "modelVersion": row[1]}


def get_account_detail(account_id: str) -> dict:
    profile = tools.get_account_profile(account_id)
    history = tools.get_account_history(account_id, n_months=12)
    interventions = tools.get_intervention_history(account_id)
    explanation = explain_account(account_id)

    latest = history[-1] if history else {}
    conn = _conn()
    prev_row = conn.execute(
        "SELECT risk_score FROM model_scores WHERE account_id=? AND panel_month_seq=11", (account_id,)
    ).fetchone()
    conn.close()
    wow = round(explanation["risk_score"] - prev_row[0], 1) if prev_row else 0.0

    days_to_renewal = int(latest.get("days_to_renewal", 0) or 0)
    urgency = "This month" if days_to_renewal <= 30 else "This quarter" if days_to_renewal <= 90 else "Not urgent"
    renewal_date = None
    try:
        base_date = datetime.strptime(str(latest.get("as_of_month"))[:10], "%Y-%m-%d")
        renewal_date = _fmt_date(base_date + timedelta(days=days_to_renewal))
    except Exception:
        pass

    usage_trend = latest.get("usage_trend_90d_pct")
    last30 = f"{'+' if (usage_trend or 0) >= 0 else ''}{round(usage_trend or 0)}%"

    usage90d = [
        {"date": h.get("as_of_month", "")[:7], "value": round(float(h.get("engagement_score", 0) or 0))}
        for h in history[-6:]
    ]

    signals = []
    if explanation["evidence"]:
        max_w = max(e["weight"] for e in explanation["evidence"]) or 1.0
        signals = [
            {"label": e["signal"], "pct": round(e["weight"] / max_w * 100)}
            for e in explanation["evidence"]
        ]

    attribution = [
        {"signal": e["signal"], "contribution": e["weight"], "comparison": "vs. population mean (z-score basis)"}
        for e in explanation["evidence"]
    ]

    intervention_history = [
        {"type": iv["intervention_type"], "owner": iv["intervention_owner"], "date": iv["as_of_month"],
         "status": iv["intervention_status"], "outcome": iv["intervention_outcome"]}
        for iv in interventions
    ]

    play_title = explanation["recommended_action"]
    if explanation["risk_band"] in ("Low",):
        play = {"key": "default"}
    else:
        meta = PLAY_META.get(play_title, {})
        play = {"key": meta.get("id", "default"), "name": play_title, "steps": PLAY_STEPS.get(play_title, [])}

    return {
        "id": account_id,
        "name": profile.get("company_name") or account_id,
        "region": profile.get("region"),
        "segment": profile.get("segment"),
        "csmOwner": profile.get("csm_owner"),
        "industry": profile.get("industry"),
        "plan": profile.get("contract_type"),
        "band": explanation["risk_band"],
        "score": round(explanation["risk_score"]),
        "wow": wow,
        "arr": _money_compact(float(latest.get("arr_run_rate_usd", 0) or 0)),
        "renewal": renewal_date,
        "renewalDays": days_to_renewal,
        "urgency": urgency,
        "csat": float(latest["csat_score"]) if latest.get("csat_score") is not None else None,
        "nps": int(latest["nps_last_survey"]) if latest.get("nps_last_survey") is not None else None,
        "seatUtilizationPct": float(latest["seat_utilization_pct"]) if latest.get("seat_utilization_pct") is not None else None,
        "monthlySpend": float(latest.get("monthly_spend_usd", 0) or 0),
        "supportTickets90d": int(latest.get("support_tickets_90d", 0) or 0),
        "daysSinceCsmTouchpoint": int(latest.get("days_since_last_csm_touchpoint", 0) or 0),
        "paymentRisk": bool(latest.get("invoice_overdue_flag")) or bool((latest.get("payment_failure_90d_count") or 0) > 0),
        "firmographicRisk": bool(latest.get("company_layoff_flag_90d")) or bool(latest.get("leadership_change_flag_90d")),
        "interventionHistory": intervention_history,
        "signals": signals,
        "last30": last30,
        "usage90d": usage90d,
        "attribution": attribution,
        "play": play,
    }


# ---------------------------------------------------------------------------
# Model performance / evaluation (for Evaluation.jsx)
# ---------------------------------------------------------------------------

def _measure_p95_latency_ms(sample_size: int = 40) -> float:
    """Real measured latency of the cached score-lookup path (mcp_tools.
    get_model_score), with the documented fixed 4ms overhead added per call
    to approximate serving-path cost on top of the raw DB read.

    2026-10 fix: sample_size was 200. Each sample calls tools.get_model_score,
    which opens its own new sqlite3 connection (mcp_tools._conn()) -- 200
    sequential connection opens is slow enough on some machines to make this
    one endpoint take many seconds, which (combined with Flask's
    single-threaded dev server) can make the whole Evaluation tab appear to
    hang. Dropped to 40: still a real, representative p95 timing measurement,
    just fewer round trips. If you want a larger, still-fast sample, raise
    this number AFTER confirming api.py is run with threaded=True.
    """
    conn = _conn()
    ids = [r[0] for r in conn.execute(
        "SELECT account_id FROM model_scores WHERE panel_month_seq=12 ORDER BY RANDOM() LIMIT ?", (sample_size,)
    ).fetchall()]
    conn.close()
    if not ids:
        return 0.0
    timings = []
    for acct_id in ids:
        start = time.perf_counter()
        tools.get_model_score(acct_id)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        timings.append(elapsed_ms + 4.0)  # +4ms fixed overhead, per design doc
    return float(np.percentile(timings, 95))


def _attribution_coverage() -> float:
    df = _latest_df()
    n = len(df)
    if n == 0:
        return 0.0
    labels = _vectorized_top_signal(df)
    covered = (labels != "insufficient data").sum()
    return round(float(covered) / n, 4)


def _play_effectiveness() -> dict:
    df = _latest_df()
    at_risk = df[df.risk_band.isin(["Critical", "High"])]
    if at_risk.empty:
        return {"churn_rate_with_play": None, "churn_rate_without_play": None}
    with_play = at_risk[at_risk.intervention_triggered_flag == 1]["churned_within_90d"].mean()
    without_play = at_risk[at_risk.intervention_triggered_flag == 0]["churned_within_90d"].mean()
    return {
        "churn_rate_with_play": None if pd.isna(with_play) else round(float(with_play), 4),
        "churn_rate_without_play": None if pd.isna(without_play) else round(float(without_play), 4),
    }


def get_model_performance() -> dict:
    import json
    with open(DATA_DIR / "model_metrics.json") as f:
        model_metrics = json.load(f)
    rf = model_metrics.get("random_forest", {})
    heuristic = model_metrics.get("heuristic_baseline", {})

    drift = compute_drift_report()
    validation = validate_drift_detector()

    attribution_coverage = _attribution_coverage()
    p95_latency = _measure_p95_latency_ms()
    play_eff = _play_effectiveness()

    ranking_quality_ok = rf.get("auroc", 0) >= 0.75
    drift_monitor_validated = validation["accuracy"] >= 0.60

    return {
        "metrics": [
            {"label": "Risk ranking quality", "value": f"{rf.get('auroc', 0):.3f}"},
            {"label": "Drift alert accuracy", "value": f"{validation['accuracy']:.3f}"},
        ],
        "gate": "passed" if (ranking_quality_ok and drift_monitor_validated) else "failed",
        "gateChecks": {
            "ranking_quality_ok": bool(ranking_quality_ok),
            "drift_monitor_validated": bool(drift_monitor_validated),
        },
        "attributionCoverage": attribution_coverage,
        "p95LatencyMs": round(p95_latency, 2),
        "playEffectiveness": play_eff,
        "_pr_auc_for_reference": rf.get("pr_auc"),
        "heuristic_comparison": {"auroc": heuristic.get("auroc"), "pr_auc": heuristic.get("pr_auc")},
    }


# ---------------------------------------------------------------------------
# NEW — chart data for the legacy dashboard's charts, ported into the new UI
# ---------------------------------------------------------------------------

def get_region_churn() -> list[dict]:
    """Legacy Tab 1 (Executive Overview) chart: churn rate by region.
    Ported into the new UI's Overview tab."""
    df = _latest_df()
    grouped = df.groupby("region")["churned_within_90d"].mean().reset_index()
    return [
        {"region": row.region, "churnRate": round(float(row.churned_within_90d), 4)}
        for row in grouped.itertuples()
    ]


def get_arr_by_band() -> list[dict]:
    """Legacy Tab 1 chart: ARR by risk band. Ported into the new UI's
    Overview tab, alongside the existing risk-count donut."""
    df = _latest_df()
    grouped = df.groupby("risk_band")["arr_run_rate_usd"].sum().reset_index()
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    rows = sorted(
        ({"band": row.risk_band, "arr": float(row.arr_run_rate_usd), "color": RISK_COLORS.get(row.risk_band, "#999")}
         for row in grouped.itertuples()),
        key=lambda r: order.get(r["band"], 9),
    )
    return rows


def get_feature_importance(limit: int = 12) -> list[dict]:
    """Legacy Tab 3 (Predictive Signals) chart: global feature importance.
    Ported into the new UI's Evaluation tab."""
    import pandas as pd
    fi = pd.read_csv(DATA_DIR / "feature_importance.csv").head(limit)
    return [
        {"feature": row.feature, "label": FEATURE_LABELS.get(row.feature, row.feature),
         "importance": round(float(row.importance), 4)}
        for row in fi.itertuples()
    ]


def get_risk_histogram(bins: int = 20) -> list[dict]:
    """Legacy Tab 3 chart: risk score histogram. Ported into the new UI's
    Evaluation tab."""
    df = _latest_df()
    counts, edges = np.histogram(df["risk_score"].dropna(), bins=bins, range=(0, 100))
    return [
        {"bucket": f"{int(edges[i])}-{int(edges[i+1])}", "count": int(counts[i])}
        for i in range(len(counts))
    ]


def get_gains_chart() -> dict:
    """Legacy Tab 3 chart: cumulative gains / lift curve, model vs. the
    legacy heuristic baseline -- computed on the HOLDOUT set only (panel
    months 10-12) for a fair, leakage-free comparison. Ported into the new
    UI's Evaluation tab."""
    conn = _conn()
    scores = pd.read_sql(
        "SELECT account_id, as_of_month, risk_score FROM model_scores WHERE panel_month_seq >= 10", conn
    )
    truth = pd.read_sql(
        "SELECT account_id, as_of_month, churned_within_90d FROM account_monthly_metrics_enriched WHERE panel_month_seq >= 10",
        conn,
    )
    baseline = pd.read_sql(
        "SELECT account_id, as_of_month, heuristic_risk_score FROM baseline_benchmark WHERE panel_month_seq >= 10", conn
    )
    conn.close()
    g = truth.merge(scores, on=["account_id", "as_of_month"]).merge(baseline, on=["account_id", "as_of_month"])
    if g.empty:
        return {"model": [], "heuristic": []}

    def curve(score_col):
        gg = g.sort_values(score_col, ascending=False).reset_index(drop=True)
        total_pos = gg["churned_within_90d"].sum()
        gg["cum_pos"] = gg["churned_within_90d"].cumsum()
        out = []
        for d in range(1, 11):
            idx = max(0, int(len(gg) * d / 10) - 1)
            row = gg.iloc[idx]
            out.append({
                "pctAccounts": round(d / 10, 2),
                "pctChurnersCaptured": round(float(row["cum_pos"] / max(1, total_pos)), 4),
            })
        return out

    return {"model": curve("risk_score"), "heuristic": curve("heuristic_risk_score")}


def get_risk_heatmap() -> list[dict]:
    """Legacy Tab 2 (Risk Segmentation & Drivers) chart: segment x risk-band
    heatmap with per-cell churn rate. Ported into the new UI's Evaluation
    tab. Groups by the account's commercial `segment` (e.g. SMB/Mid-Market/
    Enterprise), not `industry` -- see module docstring."""
    df = _latest_df()
    grouped = df.groupby(["segment", "risk_band"]).agg(
        count=("account_id", "size"), churnRate=("churned_within_90d", "mean")
    ).reset_index()
    return [
        {"segment": row.segment, "band": row.risk_band, "count": int(row.count),
         "churnRate": round(float(row.churnRate), 4)}
        for row in grouped.itertuples()
    ]


def get_boxplot_stats() -> dict:
    """Legacy Tab 2 chart: five-number summaries (min/q1/median/q3/max) for
    key engagement/friction features, split by churned vs. retained. Ported
    into the new UI's Evaluation tab."""
    df = _latest_df()

    def five_num(series):
        s = series.dropna()
        if len(s) == 0:
            return None
        q = s.quantile([0, 0.25, 0.5, 0.75, 1.0]).tolist()
        return {"min": round(q[0], 2), "q1": round(q[1], 2), "median": round(q[2], 2),
                "q3": round(q[3], 2), "max": round(q[4], 2)}

    cols = {
        "engagement_score": "Engagement score",
        "support_friction_score": "Support friction score",
        "technical_friction_score": "Technical friction score",
        "seat_utilization_pct": "Seat utilization (%)",
        "feature_abandonment_rate_90d": "Feature abandonment rate (90d)",
    }
    return {
        label: {
            "churned": five_num(df.loc[df.churned_within_90d == 1, col]),
            "retained": five_num(df.loc[df.churned_within_90d == 0, col]),
        }
        for col, label in cols.items()
    }


def get_intervention_funnel() -> list[dict]:
    """Legacy Tab 5 (Intervention Tracking) chart: intervention status
    funnel. Ported into the new UI's Activity log tab."""
    conn = _conn()
    df = pd.read_sql("SELECT intervention_status FROM interventions", conn)
    conn.close()
    counts = df["intervention_status"].value_counts()
    order = ["Scheduled", "In progress", "Completed"]
    rows = [{"status": s, "count": int(counts.get(s, 0))} for s in order if s in counts.index or True]
    # include any status values not in the expected order, appended at the end
    extra = [s for s in counts.index if s not in order]
    rows += [{"status": s, "count": int(counts[s])} for s in extra]
    return [r for r in rows if r["count"] > 0] or rows


def get_csm_leaderboard(limit: int = 10) -> list[dict]:
    """Legacy Tab 5 chart: CSM leaderboard by completed-intervention win
    rate. Ported into the new UI's Activity log tab."""
    conn = _conn()
    df = pd.read_sql(
        "SELECT intervention_owner, intervention_status, intervention_outcome FROM interventions", conn
    )
    conn.close()
    completed = df[df.intervention_status == "Completed"]
    if completed.empty:
        return []
    good = {"Retained - Usage Improved", "Upsell Identified"}

    def agg(g):
        return pd.Series({
            "volume": len(g),
            "winRate": g["intervention_outcome"].isin(good).mean(),
        })

    grouped = completed.groupby("intervention_owner").apply(agg, include_groups=False).reset_index()
    grouped = grouped.sort_values("winRate", ascending=False).head(limit)
    return [
        {"owner": row.intervention_owner, "volume": int(row.volume), "winRate": round(float(row.winRate), 4)}
        for row in grouped.itertuples()
    ]


def get_win_rate_by_type() -> list[dict]:
    """Legacy Tab 5 chart: win rate by intervention type. Ported into the
    new UI's Activity log tab."""
    conn = _conn()
    df = pd.read_sql(
        "SELECT intervention_type, intervention_status, intervention_outcome FROM interventions", conn
    )
    conn.close()
    completed = df[df.intervention_status == "Completed"]
    if completed.empty:
        return []
    good = {"Retained - Usage Improved", "Upsell Identified"}
    grouped = completed.groupby("intervention_type")["intervention_outcome"].apply(
        lambda s: s.isin(good).mean()
    ).reset_index(name="winRate")
    return [
        {"type": row.intervention_type, "winRate": round(float(row.winRate), 4)}
        for row in grouped.itertuples()
    ]
