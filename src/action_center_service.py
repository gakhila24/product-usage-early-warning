"""
Action Center Service  --  backs the "Customer Health / Action Center" pages of the Signal UI
================================================================================================
Everything here is computed from the SAME tables the churn model already reads
(accounts, account_monthly_metrics_enriched, model_scores, interventions, ...), plus the
synthetic revenue tables written by generate_synthetic_data.py.  Nothing is hard-coded to a
number: KPIs, distributions, RFM, drivers, renewals, alerts, effectiveness ... are all derived.

Definitions (also surfaced on the "Source & Methodology" page)
  Health score      = 100 - churn-model risk_score (0-100, higher = healthier)
  Health bands      = Excellent 80-100 | Good 60-79 | Fair 40-59 | Poor 20-39 | Critical 0-19
  At risk           = health < 60   (Fair + Poor + Critical)
  RFM               = Recency (days since last qualifying activity), Frequency (active days in the
                      trailing 30), Monetary (account ARR); each 1-5 quintile, Recency reversed
  Driver indices    = composites of standardised signals (see CHURN_DRIVERS / ADOPTION_DRIVERS)
  Priority score    = rule-based: health gap + risk-band boost + ARR weight + low-recency boost
  NRR / churn (TTM) = from account_spend_history + churn_events (cohort = accounts live 12 months ago)

Write paths (all in ac_* tables, never in the model tables):
  ac_followups / ac_followup_events  -> Follow-Up Monitoring board
  ac_alerts                          -> Alerts feed (mark reviewed)
  ac_reports                         -> generated reports
  ac_settings                        -> display / alert preferences

All "dates" are relative to the data-through date (max as_of_month in model_scores), so the
dashboard stays internally consistent no matter when it is opened.
"""
import csv
import html
import io
import json
import math
import sqlite3
import threading
import uuid
import zlib
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "churn_data.db"
CONTENT_DIR = Path(__file__).resolve().parent / "ac_content"

HEALTH_BANDS = [("Excellent", 80, 100, "#167d8d"), ("Good", 60, 79, "#73b6bc"), ("Fair", 40, 59, "#e4bf83"),
                ("Poor", 20, 39, "#dd929c"), ("Critical", 0, 19, "#c5525f")]
RISK_LEVELS = ["Critical", "Poor", "Fair", "Good", "Excellent"]
BAND_COLOR = {b[0]: b[3] for b in HEALTH_BANDS}
AT_RISK_THRESHOLD = 60
IMPROVED_LIFT = 3.0      # health points of pre/post lift that count as "Improved"; 0..3 = "Watch"; <0 = "No lift"
ALL_PRODUCTS, GLOBAL_REGION, ALL_SEGMENTS, ALL_RISK, ALL_OWNERS = (
    "All Products", "Global", "All segments", "All risk levels", "All accounts")

STAGES = [
    {"name": "Needs outreach", "hint": "Draft or send initial follow-up", "color": "#c5525f"},
    {"name": "Waiting on manager", "hint": "Decision or guidance pending", "color": "#d49a3a"},
    {"name": "Action committed", "hint": "Owner and next step confirmed", "color": "#167d8d"},
    {"name": "Monitoring impact", "hint": "Intervention delivered", "color": "#6f6fc3"},
    {"name": "Closed / validated", "hint": "Outcome window completed", "color": "#2c9a78"},
]
STAGE_NAMES = [s["name"] for s in STAGES]
OWNER_ROLES = ["CS Manager", "Account Executive", "Solutions Consultant"]

# --------------------------------------------------------------------------- driver taxonomy
# (column, direction)  direction=+1 -> higher value is WORSE (adverse) ; -1 -> lower value is worse
CHURN_DRIVERS = {
    "Low Product Adoption": [("feature_adoption_score", -1), ("seat_utilization_pct", -1), ("usage_trend_90d_pct", -1),
                             ("feature_abandonment_rate_90d", 1), ("role_coverage_pct", -1)],
    "Low Perceived Value / ROI": [("roi_realized_score", -1), ("nps_last_survey", -1),
                                  ("executive_sponsor_engaged", -1), ("qbr_attended_last_90d", -1)],
    "Pricing / Cost Concerns": [("spend_trend_3m_pct", -1), ("discount_pct", 1), ("price_change_flag_90d", 1),
                                ("downgrade_flag_90d", 1)],
    "Competing Solution": [("competitor_mentions_90d", 1), ("days_since_last_login", 1), ("sessions_per_week", -1)],
    "Support Experience": [("support_friction_score", 1), ("csat_score", -1), ("avg_resolution_time_hrs", 1),
                           ("escalations_90d", 1)],
    "Onboarding Experience": [("onboarding_completion_pct", -1), ("training_completion_pct", -1),
                              ("num_active_stakeholders", -1)],
    "Integration Gaps": [("technical_friction_score", 1), ("integration_depth_score", -1),
                         ("technical_issue_count_90d", 1), ("login_failures_90d", 1)],
    "Contract / Commercial Terms": [("auto_renew", -1), ("invoice_overdue_flag", 1), ("payment_failure_90d_count", 1)],
}
ADOPTION_DRIVERS = {
    "Executive Sponsorship": [("executive_sponsor_engaged", 1), ("qbr_attended_last_90d", 1)],
    "Role-Based Workflows": [("role_coverage_pct", 1), ("feature_adoption_score", 1)],
    "Integration Depth": [("integration_depth_score", 1)],
    "Multi-User Activation": [("seat_utilization_pct", 1), ("num_active_stakeholders", 1)],
    "Demonstrated ROI": [("roi_realized_score", 1), ("nps_last_survey", 1)],
    "Onboarding Completion": [("onboarding_completion_pct", 1)],
    "Admin Engagement": [("admin_engagement_score", 1)],
    "Training Participation": [("training_completion_pct", 1)],
}
DRIVER_ACTION = {
    "Low Product Adoption": "Role-based activation sprint",
    "Low Perceived Value / ROI": "ROI review before renewal",
    "Pricing / Cost Concerns": "Right-size and optimize",
    "Competing Solution": "Competitive displacement review",
    "Support Experience": "Critical issue recovery",
    "Onboarding Experience": "Re-onboarding sprint",
    "Integration Gaps": "Integration recovery plan",
    "Contract / Commercial Terms": "Commercial terms review",
}
DRIVER_RENEWAL_ACTION = {
    "Low Product Adoption": "Activation workshop", "Low Perceived Value / ROI": "Executive value review",
    "Pricing / Cost Concerns": "Right-size and optimize", "Competing Solution": "Competitive displacement review",
    "Support Experience": "Critical issue recovery", "Onboarding Experience": "Re-onboarding sprint",
    "Integration Gaps": "Integration recovery", "Contract / Commercial Terms": "Commercial terms review",
}
DRIVER_ROLE = {
    "Low Product Adoption": "CS Manager", "Support Experience": "CS Manager",
    "Low Perceived Value / ROI": "Account Executive", "Pricing / Cost Concerns": "Account Executive",
    "Contract / Commercial Terms": "Account Executive", "Competing Solution": "Account Executive",
    "Onboarding Experience": "Solutions Consultant", "Integration Gaps": "Solutions Consultant",
}
RFM_SEGMENT_ACTION = {
    "Champions": "Protect and expand adoption", "Loyal": "Build champion and cross-sell",
    "Potential Loyalists": "Deepen high-value workflows", "At Risk — High Value": "Executive reactivation + adoption reset",
    "Hibernating": "Low-cost win-back sequence", "Needs Attention": "Re-engage inactive roles",
}
RFM_SEGMENTS = ["Champions", "Loyal", "Potential Loyalists", "Needs Attention", "At Risk — High Value", "Hibernating"]

PLAYBOOKS = [
    {"id": "role_activation_sprint", "category": "Adoption", "title": "Role-based activation sprint",
     "description": "Map priority roles to workflows, activate key features and measure 30-day breadth.",
     "trigger": "Top driver is Low Product Adoption and health < 70", "icon": "zap", "color": "violet"},
    {"id": "executive_roi_review", "category": "Value", "title": "Executive ROI review",
     "description": "Translate usage and outcomes into an executive-ready value narrative before renewal.",
     "trigger": "Top driver is Low Perceived Value / ROI and health < 70", "icon": "target", "color": "blue"},
    {"id": "critical_renewal_response", "category": "Retention", "title": "Critical renewal response",
     "description": "Align owner, support and commercial action for high-risk renewals inside 60 days.",
     "trigger": "Health < 40 and renewal within 60 days", "icon": "calendar-clock", "color": "orange"},
    {"id": "reonboarding_pathway", "category": "Onboarding", "title": "Re-onboarding pathway",
     "description": "Reset success criteria, admin setup and role-specific enablement for stalled accounts.",
     "trigger": "Top driver is Onboarding Experience and health < 70", "icon": "refresh-cw", "color": "green"},
    {"id": "critical_issue_recovery", "category": "Support", "title": "Critical issue recovery",
     "description": "Resolve open critical tickets, restore confidence and communicate the prevention plan.",
     "trigger": ">= 2 high-priority tickets, support friction >= 60, health < 70", "icon": "life-buoy", "color": "blue"},
    {"id": "champion_amplification", "category": "Expansion", "title": "Champion amplification",
     "description": "Use executive sponsorship and successful use cases to extend adoption across teams.",
     "trigger": "Champions/Loyal RFM, health >= 75, executive sponsor engaged, seat utilization >= 80%", "icon": "users", "color": "violet"},
]
REPORT_TEMPLATES = [
    {"id": "portfolio_health_summary", "category": "Executive", "title": "Portfolio health summary",
     "description": "KPIs, health distribution, trend, risk exposure and priority actions.",
     "sections": ["executive_kpis", "health_trend", "rfm_summary", "drivers", "action_queue"]},
    {"id": "renewal_review_90d", "category": "Retention", "title": "90-day renewal review",
     "description": "Renewal pipeline segmented by health, top drivers and owner coverage.",
     "sections": ["executive_kpis", "upcoming_renewals", "drivers", "recommended_playbooks"]},
    {"id": "driver_intervention_brief", "category": "Adoption", "title": "Driver intervention brief",
     "description": "Side-by-side churn and adoption drivers with recommended playbooks.",
     "sections": ["drivers", "recommended_playbooks", "action_queue"]},
]
REPORT_SECTIONS = {
    "executive_kpis": "Executive KPIs", "rfm_summary": "RFM summary", "health_trend": "Health trend",
    "drivers": "Churn + adoption drivers", "action_queue": "Account action queue",
    "upcoming_renewals": "Upcoming renewals", "recommended_playbooks": "Recommended playbooks",
}
DEFAULT_SETTINGS = {"weekly_refresh": True, "critical_alerts": True, "renewal_reminders": True,
                    "include_adoption_drivers": True}


# =========================================================================== helpers
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _py(o):
    """Recursively convert numpy / pandas scalars (and NaN) to JSON-safe python values."""
    if isinstance(o, dict):
        return {str(k): _py(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_py(v) for v in o]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (isinstance(o, float) and math.isnan(o)) or (isinstance(o, np.floating) and np.isnan(o)) else float(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.strftime("%Y-%m-%d")
    return o


def _fmt_date(d) -> str:
    d = pd.Timestamp(d)
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def _fmt_short(d) -> str:
    d = pd.Timestamp(d)
    return f"{d.strftime('%b')} {d.day:02d}"


def money(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "$0"
    sign, v = ("-" if v < 0 else ""), abs(float(v))
    if v >= 1_000_000:
        return f"{sign}${v / 1_000_000:.1f}M" if v < 100_000_000 else f"{sign}${v / 1_000_000:.0f}M"
    if v >= 1_000:
        return f"{sign}${v / 1_000:.0f}K"
    return f"{sign}${v:.0f}"


def health_band(h: float) -> str:
    if h >= 80:
        return "Excellent"
    if h >= 60:
        return "Good"
    if h >= 40:
        return "Fair"
    if h >= 20:
        return "Poor"
    return "Critical"


def _pct(n, d, digits=1):
    return round(100.0 * n / d, digits) if d else 0.0


def _delta(cur, prev, digits=1):
    return round(float(cur) - float(prev), digits)


# =========================================================================== write-side schema
def ensure_tables():
    conn = _conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS ac_followups (
        id TEXT PRIMARY KEY, account_id TEXT NOT NULL, status TEXT NOT NULL, action TEXT NOT NULL,
        action_type TEXT DEFAULT 'task', owner_role TEXT, owner_name TEXT, due_date TEXT, note TEXT,
        subject TEXT, created_at TEXT, updated_at TEXT, source TEXT DEFAULT 'seed');
    CREATE TABLE IF NOT EXISTS ac_followup_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, followup_id TEXT, ts TEXT, event TEXT, detail TEXT);
    CREATE TABLE IF NOT EXISTS ac_alerts (
        id TEXT PRIMARY KEY, severity TEXT, category TEXT, title TEXT, detail TEXT,
        age_hours INTEGER, status TEXT DEFAULT 'open', account_id TEXT, reviewed_at TEXT);
    CREATE TABLE IF NOT EXISTS ac_reports (
        id TEXT PRIMARY KEY, name TEXT, template TEXT, recipients TEXT, sections TEXT, filters TEXT,
        content TEXT, created_at TEXT, status TEXT DEFAULT 'Generated');
    CREATE TABLE IF NOT EXISTS ac_settings (key TEXT PRIMARY KEY, value TEXT);
    """)
    conn.commit()
    conn.close()


# =========================================================================== snapshot cache
_SNAP = {"key": None, "data": None}
_SNAP_LOCK = threading.Lock()


def invalidate_cache():
    _SNAP["key"] = None


def _zs(df, col):
    s = df[col].astype(float)
    sd = s.std()
    sd = sd if sd and not math.isnan(sd) else 1.0
    return ((s - s.mean()) / sd).fillna(0.0)


def _index(df, signals):
    return sum(sign * _zs(df, c) for c, sign in signals) / len(signals)


def _quint(series):
    pct = series.rank(method="average", pct=True)
    return np.minimum(5, np.ceil(pct * 5)).astype(int)


def _rfm_segment(r, f, m):
    if r <= 2 and f <= 2:
        return "At Risk — High Value" if m == 5 else "Hibernating"
    if r == 5 and f == 5:
        return "Champions"
    if r >= 4 and f >= 4:
        return "Loyal"
    if r >= 3 and f >= 3:
        return "Potential Loyalists"
    return "Needs Attention"


def _build_snapshot():
    ensure_tables()
    conn = _conn()
    cur = pd.read_sql("""
        SELECT m.*, a.company_name, a.segment, a.region, a.industry, a.csm_owner, a.account_executive,
               a.solutions_consultant, a.contract_type, a.primary_product, s.risk_score, s.risk_band, s.model_version
        FROM account_monthly_metrics_enriched m
        JOIN accounts a ON a.account_id = m.account_id
        JOIN model_scores s ON s.account_id = m.account_id AND s.panel_month_seq = m.panel_month_seq
        WHERE m.panel_month_seq = 12""", conn)
    hist = pd.read_sql("""
        SELECT m.account_id, m.panel_month_seq, m.as_of_month, m.account_age_months, m.monthly_spend_usd,
               m.arr_run_rate_usd, m.feature_adoption_score, m.distinct_features_used, m.days_to_renewal,
               s.risk_score
        FROM account_monthly_metrics_enriched m
        JOIN model_scores s ON s.account_id = m.account_id AND s.panel_month_seq = m.panel_month_seq""", conn)
    holdings = pd.read_sql("SELECT account_id, product, is_primary FROM account_products", conn)
    spend = pd.read_sql("SELECT account_id, month_index, monthly_spend_usd FROM account_spend_history", conn)
    events = pd.read_sql("SELECT * FROM churn_events", conn)
    accounts = pd.read_sql("SELECT account_id, tenure_months_at_snapshot, segment, region, primary_product, csm_owner FROM accounts", conn)
    conn.close()

    hist["health"] = (100 - hist.risk_score).clip(0, 100)
    prev_health = hist[hist.panel_month_seq == 11].set_index("account_id").health
    as_of = pd.Timestamp(cur.as_of_month.iloc[0])

    cur["health"] = (100 - cur.risk_score).clip(0, 100)
    cur["health_int"] = cur.health.round().astype(int)
    cur["health_band"] = cur.health.map(health_band)
    cur["prev_health"] = cur.account_id.map(prev_health)
    cur["health_change"] = (cur.health - cur.prev_health).fillna(0.0).round(1)
    cur["at_risk"] = cur.health < AT_RISK_THRESHOLD
    cur["arr"] = cur.arr_run_rate_usd.astype(float)
    cur["payment_risk"] = cur.invoice_overdue_flag.astype(bool) | (cur.payment_failure_90d_count > 0)

    # ---- RFM (portfolio cohort quintiles) ----
    cur["r_score"] = 6 - _quint(cur.days_since_last_login)
    cur["f_score"] = _quint(cur.active_days_30d)
    cur["m_score"] = _quint(cur.arr)
    cur["rfm_segment"] = [_rfm_segment(r, f, m) for r, f, m in zip(cur.r_score, cur.f_score, cur.m_score)]
    cur["rfm_score"] = ((cur.r_score + cur.f_score + cur.m_score) / 15 * 100).round().astype(int)

    # ---- driver indices & association weights ----
    adv, fav = {}, {}
    for k, sig in CHURN_DRIVERS.items():
        cur[f"adv::{k}"] = _index(cur, sig)
        w = cur[f"adv::{k}"].corr(cur.risk_score)
        adv[k] = max(0.0, 0.0 if pd.isna(w) else float(w))
    for k, sig in ADOPTION_DRIVERS.items():
        cur[f"fav::{k}"] = _index(cur, sig)
        w = cur[f"fav::{k}"].corr(cur.health)
        fav[k] = max(0.0, 0.0 if pd.isna(w) else float(w))
    mat = np.column_stack([adv[k] * cur[f"adv::{k}"].clip(lower=0).to_numpy() for k in CHURN_DRIVERS])
    names = np.array(list(CHURN_DRIVERS))
    top_idx = mat.argmax(axis=1)
    cur["top_driver"] = np.where(mat.max(axis=1) < 0.04, "No dominant driver", names[top_idx])

    # ---- recommended action, owner, priority ----
    cur["priority"] = [_priority(h, band, a, r) for h, band, a, r in
                       zip(cur.health, cur.health_band, cur.arr, cur.r_score)]
    # at-risk accounts get the driver-specific play; low-value hibernating accounts get the cheap win-back sequence
    cur["next_action"] = [
        (RFM_SEGMENT_ACTION["Hibernating"] if (seg == "Hibernating" and m <= 2) else
         DRIVER_ACTION.get(drv, RFM_SEGMENT_ACTION[seg])) if ar else RFM_SEGMENT_ACTION[seg]
        for seg, ar, drv, m in zip(cur.rfm_segment, cur.at_risk, cur.top_driver, cur.m_score)]
    cur["renewal_action"] = cur.top_driver.map(DRIVER_RENEWAL_ACTION).fillna("Renewal health check")
    cur["owner_role"] = cur.top_driver.map(DRIVER_ROLE).fillna("CS Manager")
    cur["owner_name"] = np.select(
        [cur.owner_role == "Account Executive", cur.owner_role == "Solutions Consultant"],
        [cur.account_executive, cur.solutions_consultant],
        cur.csm_owner.where(cur.csm_owner != "Unassigned", "Unassigned"))
    cur["renewal_date"] = [as_of + timedelta(days=int(d)) for d in cur.days_to_renewal]

    spend_piv = spend.pivot(index="account_id", columns="month_index", values="monthly_spend_usd")
    cur_idx = cur.set_index("account_id", drop=False)
    cur_idx.index.name = None
    snap = dict(cur=cur_idx, hist=hist, holdings=holdings, spend=spend_piv,
                events=events.assign(churn_date=pd.to_datetime(events.churn_date)), accounts=accounts.set_index("account_id"),
                as_of=as_of, adv_w=adv, fav_w=fav)
    return snap


def _priority(health, band, arr, r_score):
    boost = {"Critical": 28, "Poor": 18, "Fair": 8}.get(band, 0)
    return int(min(99, round((100 - health) * 0.55 + boost + min(1.0, arr / 1_200_000) * 16 + (8 if r_score <= 2 else 0))))


def snapshot():
    key = (DATA_DIR / "model_metrics.json").stat().st_mtime_ns     # changes whenever the model is retrained
    if _SNAP["key"] != key or _SNAP["data"] is None:
        with _SNAP_LOCK:                                   # the UI fires many requests at once on first load
            if _SNAP["key"] != key or _SNAP["data"] is None:
                _SNAP["data"] = _build_snapshot()
                _SNAP["key"] = key
    return _SNAP["data"]


# =========================================================================== filters
class Filters:
    def __init__(self, product=ALL_PRODUCTS, region=GLOBAL_REGION, segment=ALL_SEGMENTS, risk=ALL_RISK,
                 horizon=90, owner=ALL_OWNERS):
        self.product, self.region, self.segment = product or ALL_PRODUCTS, region or GLOBAL_REGION, segment or ALL_SEGMENTS
        self.risk, self.owner = risk or ALL_RISK, owner or ALL_OWNERS
        try:
            self.horizon = int(horizon or 90)
        except (TypeError, ValueError):
            self.horizon = 90

    @classmethod
    def from_args(cls, args):
        g = lambda k, d=None: (args.get(k) if hasattr(args, "get") else None) or d
        return cls(g("product"), g("region"), g("segment"), g("risk"), g("horizon", 90), g("owner"))

    def as_dict(self):
        return {"product": self.product, "region": self.region, "segment": self.segment, "risk": self.risk,
                "horizon": self.horizon, "owner": self.owner}

    def describe(self):
        parts = [self.product, self.region, self.segment]
        if self.risk != ALL_RISK:
            parts.append(f"Risk: {self.risk}")
        if self.owner != ALL_OWNERS:
            parts.append(f"Owner: {self.owner}")
        return " · ".join(parts)


def _filtered(f: Filters, apply_risk=True, apply_product=True) -> pd.DataFrame:
    s = snapshot()
    df = s["cur"]
    if f.region != GLOBAL_REGION:
        df = df[df.region == f.region]
    if f.segment != ALL_SEGMENTS:
        df = df[df.segment == f.segment]
    if apply_product and f.product != ALL_PRODUCTS:
        ids = set(s["holdings"].loc[s["holdings"]["product"] == f.product, "account_id"])
        df = df[df.account_id.isin(ids)]
    if f.owner == "Assigned":
        df = df[df.csm_owner != "Unassigned"]
    elif f.owner == "Unassigned":
        df = df[df.csm_owner == "Unassigned"]
    if apply_risk and f.risk != ALL_RISK:
        if f.risk == "At risk":
            df = df[df.at_risk]
        else:
            df = df[df.health_band == f.risk]
    return df


# =========================================================================== follow-up lookups
def _open_followups() -> dict:
    ensure_tables()
    conn = _conn()
    rows = conn.execute("SELECT * FROM ac_followups ORDER BY updated_at DESC").fetchall()
    conn.close()
    out = {}
    for r in rows:
        if r["account_id"] not in out and r["status"] != "Closed / validated":
            out[r["account_id"]] = dict(r)
    return out


def _fu_public(r: dict) -> dict:
    return {"id": r["id"], "accountId": r["account_id"], "status": r["status"], "action": r["action"],
            "actionType": r["action_type"], "ownerRole": r["owner_role"], "ownerName": r["owner_name"],
            "due": r["due_date"], "dueLabel": _fmt_short(r["due_date"]) if r["due_date"] else None,
            "note": r["note"], "createdAt": r["created_at"], "updatedAt": r["updated_at"]}


def _why(r) -> str:
    bits = [f"{r.health_band} health", f"{money(r.arr)} value"]
    if r.days_to_renewal <= 90:
        bits.append(f"renews in {int(r.days_to_renewal)} days")
    if r.top_driver != "No dominant driver":
        bits.append(f"leading driver: {r.top_driver}")
    return ", ".join(bits) + "."


def _row(r, fu=None) -> dict:
    return {
        "id": r.account_id, "name": r.company_name, "product": r.primary_product, "region": r.region,
        "segment": r.segment, "industry": r.industry, "plan": r.contract_type,
        "health": int(r.health_int), "healthBand": r.health_band, "healthChange": float(r.health_change),
        "modelRiskBand": r.risk_band, "riskScore": round(float(r.risk_score), 1),
        "topDriver": r.top_driver, "renewal": _fmt_date(r.renewal_date), "renewalDays": int(r.days_to_renewal),
        "arr": float(r.arr), "amount": money(r.arr), "owner": r.csm_owner,
        "ownerRole": r.owner_role, "ownerName": r.owner_name,
        "rfm": {"r": int(r.r_score), "f": int(r.f_score), "m": int(r.m_score), "recencyDays": int(r.days_since_last_login),
                "activeDays": int(r.active_days_30d), "segment": r.rfm_segment, "score": int(r.rfm_score)},
        "nextBestAction": r.next_action, "renewalAction": r.renewal_action, "why": _why(r), "priority": int(r.priority),
        "paymentRisk": bool(r.payment_risk), "followup": _fu_public(fu) if fu else None,
    }


def _page(df: pd.DataFrame, page: int, page_size: int):
    page, page_size = max(1, int(page or 1)), max(1, min(int(page_size or 10), 200))
    total = len(df)
    pages = max(1, math.ceil(total / page_size))
    page = min(page, pages)
    return df.iloc[(page - 1) * page_size: page * page_size], {"page": page, "pageSize": page_size, "total": total, "pages": pages}


def _search(df: pd.DataFrame, q: str) -> pd.DataFrame:
    q = (q or "").strip().lower()
    if not q:
        return df
    hay = (df.company_name + " " + df.account_id + " " + df.primary_product + " " + df.top_driver + " " +
           df.next_action + " " + df.rfm_segment + " " + df.csm_owner).str.lower()
    return df[hay.str.contains(q, regex=False)]


# =========================================================================== revenue metrics
def revenue_metrics(f: Filters, month=12) -> dict:
    """TTM churn (ARR) and NRR for the 12-month window ending `month` (12 = latest, 11 = previous month)."""
    s = snapshot()
    acc = s["accounts"]
    if f.region != GLOBAL_REGION:
        acc = acc[acc.region == f.region]
    if f.segment != ALL_SEGMENTS:
        acc = acc[acc.segment == f.segment]
    if f.product != ALL_PRODUCTS:
        acc = acc[acc.primary_product == f.product]
    if f.owner == "Assigned":
        acc = acc[acc.csm_owner != "Unassigned"]
    elif f.owner == "Unassigned":
        acc = acc[acc.csm_owner == "Unassigned"]
    cohort = acc[acc.tenure_months_at_snapshot >= 13 + (12 - month)].index
    piv = s["spend"]
    opening = piv.loc[cohort, month - 12].to_numpy() * 12
    now = piv.loc[cohort, month].to_numpy() * 12
    expansion = float(np.clip(now - opening, 0, None).sum())
    contraction = float(np.clip(opening - now, 0, None).sum())
    ev = s["events"]
    end = s["as_of"] - pd.DateOffset(months=12 - month) + pd.offsets.MonthEnd(0)
    start = end - pd.DateOffset(months=12)
    ev = ev[(ev.churn_date > start) & (ev.churn_date <= end)]
    if f.region != GLOBAL_REGION:
        ev = ev[ev.region == f.region]
    if f.segment != ALL_SEGMENTS:
        ev = ev[ev.segment == f.segment]
    if f.product != ALL_PRODUCTS:
        ev = ev[ev.primary_product == f.product]
    churn = float(ev.arr_lost.sum())
    opening_total = float(opening.sum()) + churn
    if opening_total <= 0:
        return {"openingArr": 0, "expansion": 0, "contraction": 0, "churnArr": 0, "nrr": None, "churnRate": None, "churnedLogos": 0}
    return {"openingArr": opening_total, "expansion": expansion, "contraction": contraction, "churnArr": churn,
            "nrr": round((opening_total + expansion - contraction - churn) / opening_total * 100, 1),
            "churnRate": round(churn / opening_total * 100, 2), "churnedLogos": int(len(ev))}


# =========================================================================== filters / meta
def filter_options() -> dict:
    s = snapshot()
    cur = s["cur"]
    as_of = s["as_of"]
    start = as_of.replace(day=1)
    prev_end = start - timedelta(days=1)
    mtime = datetime.fromtimestamp((DATA_DIR / "model_metrics.json").stat().st_mtime)
    delta = datetime.now() - mtime
    last = "just now" if delta.total_seconds() < 90 else (f"{int(delta.total_seconds() // 3600)}h ago" if delta.total_seconds() < 86400 * 2 else f"{delta.days}d ago")
    return {
        "products": [ALL_PRODUCTS] + sorted(s["holdings"]["product"].unique().tolist()),
        "regions": [GLOBAL_REGION] + sorted(cur.region.unique().tolist()),
        "segments": [ALL_SEGMENTS, "Enterprise", "Mid-Market", "SMB"],
        "risks": [ALL_RISK] + RISK_LEVELS,
        "horizons": [{"value": 90, "label": "Next 90 days"}, {"value": 180, "label": "Next 180 days"}, {"value": 365, "label": "Next 365 days"}],
        "owners": [ALL_OWNERS, "Assigned", "Unassigned"],
        "asOf": as_of.strftime("%Y-%m-%d"), "asOfLabel": _fmt_date(as_of),
        "period": {"label": f"{_fmt_short(start)} – {_fmt_short(as_of)}, {as_of.year}".replace(" 0", " "),
                   "compareLabel": f"{_fmt_short(prev_end.replace(day=1))} – {_fmt_short(prev_end)}".replace(" 0", " ")},
        "lastUpdated": last, "modelVersion": str(cur.model_version.iloc[0]),
    }


# =========================================================================== overview
def _kpi(key, label, value, unit, delta, delta_label, good_when="up", sub=None, fmt=None):
    tone = "neutral"
    if delta:
        tone = ("positive" if delta > 0 else "negative") if good_when == "up" else ("negative" if delta > 0 else "positive")
    return {"key": key, "label": label, "value": value, "unit": unit, "delta": delta, "deltaLabel": delta_label,
            "tone": tone, "sub": sub}


def overview(f: Filters) -> dict:
    s = snapshot()
    df = _filtered(f)
    base = _filtered(f, apply_risk=False)           # KPI maths ignore the risk-level filter (it would zero the denominator)
    hist = s["hist"]
    ids = set(base.account_id)
    h = hist[hist.account_id.isin(ids)]
    h12, h11 = h[h.panel_month_seq == 12], h[h.panel_month_seq == 11]
    e12, e11 = h12[h12.account_age_months >= 1], h11[h11.account_age_months >= 1]
    n12, n11 = len(e12), len(e11)
    avg12, avg11 = e12.health.mean(), e11.health.mean()
    ar12, ar11 = int((e12.health < AT_RISK_THRESHOLD).sum()), int((e11.health < AT_RISK_THRESHOLD).sum())
    share12, share11 = _pct(ar12, n12), _pct(ar11, n11)
    rev12, rev11 = revenue_metrics(f, 12), revenue_metrics(f, 11)
    cmp = filter_options()["period"]["compareLabel"]
    kpis = [
        _kpi("accounts", "Total Accounts", n12, "", _pct(n12 - n11, n11), f"vs {cmp}"),
        _kpi("health", "Avg. Health Score", round(float(avg12)) if n12 else 0, "/100", round(float(avg12 - avg11), 1), f"pts vs {cmp}"),
        _kpi("atRisk", "At-Risk Accounts", ar12, "", _delta(share12, share11), f"pp vs {cmp}", good_when="down", sub=f"{share12}% of total"),
        _kpi("churn", "Churn Rate (TTM)", rev12["churnRate"], "%", _delta(rev12["churnRate"] or 0, rev11["churnRate"] or 0, 2), f"pp vs {cmp}", good_when="down"),
        _kpi("nrr", "Net Revenue Retention", rev12["nrr"], "%", _delta(rev12["nrr"] or 0, rev11["nrr"] or 0), f"pp vs {cmp}"),
    ]
    rfm = {"recencyDays": round(float(base.days_since_last_login.mean()), 1) if len(base) else 0,
           "activeDays": round(float(base.active_days_30d.mean()), 1) if len(base) else 0,
           "arr": float(base.arr.sum()), "arrLabel": money(base.arr.sum())}
    dist = health_distribution(base)
    drivers_ = drivers(f)
    return {
        "filters": f.as_dict(), "kpis": kpis, "rfm": rfm, "healthDistribution": dist,
        "churnDrivers": drivers_["churn"][:8], "recommendedActions": recommended_actions(base),
        "renewalsPreview": renewals(f, horizon=90, page_size=3, preview=True),
        "about": about_model(), "asOf": filter_options()["asOf"],
    }


def health_distribution(df: pd.DataFrame) -> list:
    total = len(df)
    out = []
    for name, lo, hi, color in HEALTH_BANDS:
        n = int((df.health_band == name).sum())
        out.append({"band": name, "range": f"{lo}–{hi}", "count": n, "pct": _pct(n, total, 0), "pctExact": _pct(n, total, 1), "color": color})
    return out


_ABOUT = {}


def about_model() -> dict:
    s = snapshot()
    if _ABOUT.get("key") == _SNAP["key"]:
        return _ABOUT["val"]
    metrics = json.load(open(DATA_DIR / "model_metrics.json"))
    auroc = metrics.get("random_forest", {}).get("auroc", 0)
    conf = "High" if auroc >= 0.85 else "Medium" if auroc >= 0.75 else "Low"
    sources = json.load(open(CONTENT_DIR / "sources.json", encoding="utf8"))
    from train_model import NUMERIC, BOOL_AS_INT
    val = {"dataSources": max(0, len(sources) - 1), "signals": len(NUMERIC) + len(BOOL_AS_INT) + 8, "modelSignals": len(NUMERIC) + len(BOOL_AS_INT),
           "refresh": "Weekly", "nextRefresh": _fmt_date(s["as_of"] + timedelta(days=7)), "confidence": conf,
           "auroc": round(float(auroc), 3), "version": "Methodology v2.4", "modelVersion": str(s["cur"].model_version.iloc[0])}
    _ABOUT.update(key=_SNAP["key"], val=val)
    return val


def recommended_actions(df: pd.DataFrame) -> list:
    risk = df[df.at_risk]
    actions = [
        ("reach_out", "Reach out to at-risk accounts", "High risk & declining score",
         int(((df.health < 40) | (df.at_risk & (df.health_change <= -3))).sum()), "check"),
        ("adoption", "Drive product adoption", "Low usage of key features",
         int(((df.top_driver == "Low Product Adoption") & (df.health < 70)).sum()), "trending"),
        ("roi", "Discuss ROI and value", "Low perceived value signals",
         int(((df.top_driver == "Low Perceived Value / ROI") & (df.health < 70)).sum()), "diamond"),
        ("renewals", "Review upcoming renewals", "Renewal within 60 days",
         int(((df.days_to_renewal <= 60) & df.at_risk).sum()), "calendar"),
        ("support", "Address support issues", "Open critical tickets",
         int(((df.high_priority_tickets_90d >= 2) & (df.support_friction_score >= 60) & (df.health < 70)).sum()), "alert"),
    ]
    return [{"id": a, "title": t, "subtitle": sub, "count": c, "icon": ic} for a, t, sub, c, ic in actions]


# =========================================================================== trend
def health_trend(f: Filters, grain="daily") -> dict:
    s = snapshot()
    base = _filtered(f, apply_risk=False)
    h = s["hist"]
    h = h[h.account_id.isin(set(base.account_id)) & (h.account_age_months >= 1)]
    monthly = h.groupby("as_of_month").health.mean().sort_index()
    pts = [(pd.Timestamp(k), float(v)) for k, v in monthly.items()]
    if not pts:
        return {"grain": grain, "points": [], "note": ""}
    # interpolate month-end snapshots to a daily series (+ small deterministic noise), then 30-day MA
    start = pts[0][0] - pd.Timedelta(days=30)
    days = pd.date_range(start, pts[-1][0], freq="D")
    x = np.array([(d - start).days for d in days], dtype=float)
    xp = np.array([(d - start).days for d, _ in pts], dtype=float)
    yp = np.array([v for _, v in pts])
    seed = zlib.crc32(f"{f.product}|{f.region}|{f.segment}|{f.owner}".encode()) % (2 ** 32)
    rng = np.random.default_rng(seed)
    y = np.interp(x, xp, yp, left=yp[0]) + rng.normal(0, 0.18, len(x))
    daily = pd.Series(y, index=days)
    ma = daily.rolling(30, min_periods=7).mean()
    if grain == "weekly":
        wk = daily.resample("W-SUN").mean()
        wma = ma.resample("W-SUN").last()
        rows = [{"label": d.strftime("%b ") + str(d.day), "date": d.strftime("%Y-%m-%d"), "score": round(float(v), 2),
                 "ma": None if pd.isna(wma.loc[d]) else round(float(wma.loc[d]), 2)} for d, v in wk.tail(26).items()]
    else:
        tail = daily.tail(30)
        rows = [{"label": d.strftime("%b ") + str(d.day), "date": d.strftime("%Y-%m-%d"), "score": round(float(v), 2),
                 "ma": None if pd.isna(ma.loc[d]) else round(float(ma.loc[d]), 2)} for d, v in tail.items()]
    return {"grain": grain, "points": rows,
            "monthly": [{"date": d.strftime("%Y-%m-%d"), "score": round(v, 2)} for d, v in pts],
            "note": "Daily / weekly points are interpolated between month-end score snapshots (synthetic); the 30-day moving average is computed on the daily series."}


# =========================================================================== account tables
def at_risk_accounts(f: Filters, page=1, page_size=6, q="", sort="health") -> dict:
    df = _search(_filtered(f), q)
    df = df[df.at_risk] if f.risk == ALL_RISK else df
    df = df.sort_values(["health", "arr"], ascending=[True, False]) if sort == "health" else df.sort_values("priority", ascending=False)
    fus = _open_followups()
    chunk, meta = _page(df, page, page_size)
    return {**meta, "rows": [_row(r, fus.get(r.account_id)) for r in chunk.itertuples()]}


def explorer(f: Filters, page=1, page_size=12, q="", sort="health") -> dict:
    df = _search(_filtered(f), q)
    key = {"health": ("health", True), "arr": ("arr", False), "renewal": ("days_to_renewal", True),
           "priority": ("priority", False), "name": ("company_name", True)}.get(sort, ("health", True))
    df = df.sort_values(key[0], ascending=key[1])
    chunk, meta = _page(df, page, page_size)
    return {**meta, "rows": [_row(r) for r in chunk.itertuples()]}


def explorer_csv(f: Filters, q="") -> str:
    df = _search(_filtered(f), q).sort_values("health")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Account ID", "Account", "Product", "Region", "Segment", "Health score", "Risk level", "Top driver",
                "Renewal date", "ARR (USD)", "Owner", "RFM segment", "Priority", "Next best action"])
    for r in df.itertuples():
        w.writerow([_csv_safe(x) for x in [r.account_id, r.company_name, r.primary_product, r.region, r.segment, r.health_int,
                                           r.health_band, r.top_driver, _fmt_date(r.renewal_date), round(r.arr, 2), r.csm_owner,
                                           r.rfm_segment, r.priority, r.next_action]])
    return "\ufeff" + buf.getvalue()


def _csv_safe(v):
    s = str(v)
    return "'" + s if s[:1] in "=+-@" and not s.replace(".", "", 1).lstrip("-").isdigit() else v


def account_context(account_id: str) -> dict:
    s = snapshot()
    cur = s["cur"]
    if account_id not in cur.index:
        raise KeyError(account_id)
    r = next(cur.loc[[account_id]].itertuples())
    conn = _conn()
    fus = [dict(x) for x in conn.execute("SELECT * FROM ac_followups WHERE account_id=? ORDER BY updated_at DESC", (account_id,))]
    conn.close()
    drv = sorted([{"driver": k, "adverse": round(float(cur.loc[account_id, f"adv::{k}"]), 2)} for k in CHURN_DRIVERS],
                 key=lambda d: -d["adverse"])[:4]
    return {**_row(r, next((x for x in fus if x["status"] != "Closed / validated"), None)),
            "followups": [_fu_public(x) for x in fus], "drivers": drv}


# =========================================================================== action queue
def action_queue(f: Filters, page=1, page_size=6, q="", risk=None) -> dict:
    base = _filtered(f)
    if risk and risk != ALL_RISK:
        base = base[base.health_band == risk]
    df = base[base.at_risk] if (f.risk == ALL_RISK and not risk) else base
    df = _search(df, q).sort_values("priority", ascending=False)
    fus = _open_followups()
    chunk, meta = _page(df, page, page_size)
    all_fu = list_followups(f)
    stats = {
        "queued": int(len(df)), "valueMonitored": float(df.arr.sum()), "valueLabel": money(df.arr.sum()),
        "highValueAtRisk": int((df.rfm_segment == "At Risk — High Value").sum()),
        "decisionsNeeded": all_fu["stats"]["waiting"], "dueThisWeek": all_fu["stats"]["dueIn7"],
        "interventionSuccess": intervention_effectiveness(f)["summary"]["successRate"],
    }
    top = base[base.at_risk].sort_values("priority", ascending=False).head(4)
    nba = [{"rank": i + 1, "account": r.company_name, "accountId": r.account_id, "action": r.next_action,
            "why": _why(r), "priority": int(r.priority)} for i, r in enumerate(top.itertuples())]
    return {**meta, "stats": stats, "nba": nba, "rows": [_row(r, fus.get(r.account_id)) for r in chunk.itertuples()]}


# =========================================================================== follow-ups
def _as_of():
    return snapshot()["as_of"]


def list_followups(f: Filters, owner=None, q="") -> dict:
    ensure_tables()
    snap = snapshot()
    cur = snap["cur"]
    seed_followups_if_empty()
    conn = _conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM ac_followups ORDER BY updated_at DESC")]
    conn.close()
    base_ids = set(_filtered(f, apply_risk=False).account_id)
    out = []
    ql = (q or "").strip().lower()
    for r in rows:
        if r["account_id"] not in cur.index or r["account_id"] not in base_ids:
            continue
        a = cur.loc[r["account_id"]]
        if owner and owner != "all" and r["owner_role"] != owner:
            continue
        item = _fu_public(r)
        item.update({"account": a.company_name, "product": a.primary_product, "healthBand": a.health_band,
                     "health": int(a.health_int), "amount": money(a.arr), "renewal": _fmt_date(a.renewal_date),
                     "priority": int(a.priority), "region": a.region})
        if ql and ql not in f"{item['account']} {item['action']} {item['ownerRole']} {item['ownerName']} {item['note']}".lower():
            continue
        out.append(item)
    asof = _as_of()
    due7 = [x for x in out if x["due"] and x["status"] != "Closed / validated" and pd.Timestamp(x["due"]) <= asof + timedelta(days=7)]
    stats = {"open": sum(1 for x in out if x["status"] in STAGE_NAMES[:3]), "dueIn7": len(due7),
             "closed": sum(1 for x in out if x["status"] == "Closed / validated"),
             "waiting": sum(1 for x in out if x["status"] == "Waiting on manager"), "total": len(out)}
    stage_counts = {n: sum(1 for x in out if x["status"] == n) for n in STAGE_NAMES}
    return {"stages": STAGES, "items": out, "stats": stats, "stageCounts": stage_counts, "owners": OWNER_ROLES}


def _log_event(conn, fid, event, detail=""):
    conn.execute("INSERT INTO ac_followup_events (followup_id, ts, event, detail) VALUES (?,?,?,?)",
                 (fid, datetime.utcnow().isoformat(timespec="seconds"), event, detail))


def seed_followups(reset=True, n=24) -> int:
    ensure_tables()
    snap = snapshot()
    cur = snap["cur"]
    asof = snap["as_of"]
    rng = np.random.default_rng(20261006)
    top = cur[cur.at_risk].sort_values("priority", ascending=False).head(n)
    plan = (["Needs outreach"] * 7 + ["Waiting on manager"] * 5 + ["Action committed"] * 5 + ["Monitoring impact"] * 4 + ["Closed / validated"] * 3)
    rng.shuffle(plan)
    # keep the very top priority accounts in the "act now" lanes (like the reference prototype)
    plan[:4] = ["Waiting on manager", "Action committed", "Needs outreach", "Waiting on manager"]
    notes = {
        "Needs outreach": "Initial manager follow-up has not yet been sent.",
        "Waiting on manager": "Manager decision requested; confirm owner, executive sponsor and target date.",
        "Action committed": "Owner and next step confirmed; evidence package is being prepared.",
        "Monitoring impact": "Intervention delivered; monitor adoption and health weekly.",
        "Closed / validated": "Health and the leading driver improved within the observation window.",
    }
    atypes = {"Needs outreach": "email", "Waiting on manager": "request", "Action committed": "playbook",
              "Monitoring impact": "playbook", "Closed / validated": "task"}
    conn = _conn()
    if reset:
        conn.execute("DELETE FROM ac_followups")
        conn.execute("DELETE FROM ac_followup_events")
    now = datetime.utcnow().isoformat(timespec="seconds")
    for i, (r, st) in enumerate(zip(top.itertuples(), plan)):
        fid = f"FU-{101 + i}"
        due = asof + timedelta(days=int(rng.integers(2, 15))) if st != "Closed / validated" else asof - timedelta(days=int(rng.integers(2, 12)))
        action = {"email": f"Follow up on {r.next_action.lower()}", "request": f"Approve {r.next_action.lower()}",
                  "playbook": f"Run {r.next_action.lower()}", "task": f"Validate {r.next_action.lower()} durability"}[atypes[st]]
        conn.execute("""INSERT OR REPLACE INTO ac_followups (id, account_id, status, action, action_type, owner_role, owner_name,
                        due_date, note, subject, created_at, updated_at, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (fid, r.Index, st, action, atypes[st], r.owner_role, r.owner_name, due.strftime("%Y-%m-%d"), notes[st],
                      f"Follow-up: {r.company_name} health and renewal risk", now, now, "seed"))
        _log_event(conn, fid, "created", f"Seeded in stage '{st}'")
    conn.commit()
    conn.close()
    return len(top)


def seed_followups_if_empty():
    ensure_tables()
    conn = _conn()
    n = conn.execute("SELECT COUNT(*) FROM ac_followups").fetchone()[0]
    conn.close()
    if n == 0:
        seed_followups()


ACTION_DEFS = {
    "email": {"label": "Send Follow-Up Email", "status": "Waiting on manager"},
    "request": {"label": "Request Next Action", "status": "Waiting on manager"},
    "playbook": {"label": "Assign Playbook", "status": "Action committed"},
    "escalate": {"label": "Escalate Risk", "status": "Action committed"},
    "task": {"label": "Create Task", "status": "Action committed"},
}


def create_followup(payload: dict) -> dict:
    ensure_tables()
    snap = snapshot()
    cur = snap["cur"]
    aid = payload.get("accountId")
    if aid not in cur.index:
        raise ValueError(f"unknown accountId: {aid}")
    atype = payload.get("actionType") if payload.get("actionType") in ACTION_DEFS else "task"
    a = cur.loc[aid]
    role = payload.get("ownerRole") if payload.get("ownerRole") in OWNER_ROLES else a.owner_role
    name = {"Account Executive": a.account_executive, "Solutions Consultant": a.solutions_consultant}.get(role, a.csm_owner)
    due = payload.get("due") or (snap["as_of"] + timedelta(days=7)).strftime("%Y-%m-%d")
    action = (payload.get("subject") or ACTION_DEFS[atype]["label"]).strip()[:200]
    note = (payload.get("message") or "").strip()[:1000] or f"{ACTION_DEFS[atype]['label']} created from the account action center."
    status = ACTION_DEFS[atype]["status"]
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn = _conn()
    existing = conn.execute("SELECT id FROM ac_followups WHERE account_id=? AND status!='Closed / validated' ORDER BY updated_at DESC LIMIT 1", (aid,)).fetchone()
    if existing:
        fid = existing["id"]
        conn.execute("""UPDATE ac_followups SET status=?, action=?, action_type=?, owner_role=?, owner_name=?, due_date=?, note=?,
                        subject=?, updated_at=? WHERE id=?""", (status, action, atype, role, name, due, note, action, now, fid))
        _log_event(conn, fid, "updated", f"{ACTION_DEFS[atype]['label']} · now '{status}'")
    else:
        n = conn.execute("SELECT COALESCE(MAX(CAST(SUBSTR(id,4) AS INTEGER)),100) FROM ac_followups").fetchone()[0]
        fid = f"FU-{n + 1}"
        conn.execute("""INSERT INTO ac_followups (id, account_id, status, action, action_type, owner_role, owner_name, due_date, note,
                        subject, created_at, updated_at, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (fid, aid, status, action, atype, role, name, due, note, action, now, now, "ui"))
        _log_event(conn, fid, "created", f"{ACTION_DEFS[atype]['label']} · stage '{status}'")
    conn.commit()
    row = dict(conn.execute("SELECT * FROM ac_followups WHERE id=?", (fid,)).fetchone())
    conn.close()
    return {**_fu_public(row), "account": a.company_name, "created": not existing}


def update_followup(fid: str, patch: dict) -> dict:
    ensure_tables()
    allowed = {"status": "status", "ownerRole": "owner_role", "ownerName": "owner_name", "due": "due_date", "note": "note", "action": "action"}
    sets, vals = [], []
    for k, col in allowed.items():
        if k in patch and patch[k] is not None:
            if k == "status" and patch[k] not in STAGE_NAMES:
                raise ValueError(f"invalid status: {patch[k]}")
            if k == "ownerRole" and patch[k] not in OWNER_ROLES:
                raise ValueError(f"invalid ownerRole: {patch[k]}")
            sets.append(f"{col}=?")
            vals.append(patch[k])
    conn = _conn()
    row = conn.execute("SELECT * FROM ac_followups WHERE id=?", (fid,)).fetchone()
    if row is None:
        conn.close()
        raise KeyError(fid)
    if sets:
        sets.append("updated_at=?")
        vals.extend([datetime.utcnow().isoformat(timespec="seconds"), fid])
        conn.execute(f"UPDATE ac_followups SET {', '.join(sets)} WHERE id=?", vals)
        _log_event(conn, fid, "updated", ", ".join(k for k in allowed if k in patch))
        conn.commit()
    row = dict(conn.execute("SELECT * FROM ac_followups WHERE id=?", (fid,)).fetchone())
    conn.close()
    return _fu_public(row)


def advance_followup(fid: str) -> dict:
    conn = _conn()
    row = conn.execute("SELECT status FROM ac_followups WHERE id=?", (fid,)).fetchone()
    conn.close()
    if row is None:
        raise KeyError(fid)
    i = STAGE_NAMES.index(row["status"])
    if i >= len(STAGE_NAMES) - 1:
        return update_followup(fid, {})
    return update_followup(fid, {"status": STAGE_NAMES[i + 1]})


def delete_followup(fid: str) -> bool:
    conn = _conn()
    n = conn.execute("DELETE FROM ac_followups WHERE id=?", (fid,)).rowcount
    conn.commit()
    conn.close()
    return bool(n)


def followup_events(fid: str) -> list:
    conn = _conn()
    rows = [dict(r) for r in conn.execute("SELECT ts, event, detail FROM ac_followup_events WHERE followup_id=? ORDER BY id DESC", (fid,))]
    conn.close()
    return rows


# =========================================================================== interventions
def intervention_effectiveness(f: Filters, outcome="all", page=1, page_size=10) -> dict:
    s = snapshot()
    cur = s["cur"]
    base = _filtered(f, apply_risk=False)
    conn = _conn()
    iv = pd.read_sql("SELECT * FROM interventions", conn)
    conn.close()
    hist = s["hist"]
    iv = iv[iv.account_id.isin(set(base.account_id))].copy()
    ym = pd.to_datetime(iv.as_of_month)
    asof = s["as_of"]
    iv["panel"] = 12 - ((asof.year - ym.dt.year) * 12 + (asof.month - ym.dt.month))
    iv = iv.sort_values("intervention_date").groupby("account_id").tail(1)      # latest intervention per account
    hx = hist.set_index(["account_id", "panel_month_seq"])
    score, ad = hx.risk_score, hx.feature_adoption_score
    rows = []
    for r in iv.itertuples():
        p = int(r.panel)
        if p < 1:
            continue
        base_h = 100 - float(score.get((r.account_id, p), np.nan))
        cur_h = 100 - float(score.get((r.account_id, 12), np.nan))
        lift = round(cur_h - base_h, 1) if not (math.isnan(base_h) or math.isnan(cur_h)) else float("nan")
        a0, a1 = ad.get((r.account_id, p), np.nan), ad.get((r.account_id, 12), np.nan)
        adoption_change = round(float(a1 - a0), 1) if not (pd.isna(a0) or pd.isna(a1)) else None
        if p >= 12 or r.intervention_status in ("Scheduled",) or pd.isna(lift):
            res = "Pending"
        elif lift >= IMPROVED_LIFT:
            res = "Improved"
        elif lift >= 0:
            res = "Watch"
        else:
            res = "No lift"
        a = cur.loc[r.account_id]
        decision = {"Improved": "Continue; confirm durability before closing", "Watch": "Confirm milestone and keep monitoring",
                    "No lift": "Escalate and re-scope the intervention", "Pending": "Wait for the first outcome window"}[res]
        rows.append({"accountId": r.account_id, "account": a.company_name, "type": r.intervention_type, "owner": r.intervention_owner,
                     "started": _fmt_short(r.intervention_date), "startedIso": r.intervention_date, "status": r.intervention_status,
                     "baseline": None if math.isnan(base_h) else round(base_h), "current": None if math.isnan(cur_h) else round(cur_h), "lift": None if math.isnan(lift) else lift, "adoptionChange": adoption_change,
                     "outcome": res, "loggedOutcome": r.intervention_outcome, "decision": decision, "arr": float(a.arr),
                     "daysToSignal": None if pd.isna(r.days_to_first_signal) else int(r.days_to_first_signal)})
    df = pd.DataFrame(rows)
    if df.empty:
        return {"summary": {"successRate": None, "improved": 0, "measured": 0, "avgLift": 0, "valueMonitored": 0, "medianDaysToSignal": None},
                "byType": [], "slope": [], "register": [], "total": 0}
    measured = df[df.outcome != "Pending"]
    improved = int((measured.outcome == "Improved").sum())
    active = df[df.status.isin(["In progress", "Scheduled"])]
    summary = {
        "successRate": round(improved / len(measured) * 100) if len(measured) else None, "improved": improved, "measured": int(len(measured)),
        "avgLift": round(float(measured.lift.mean()), 1) if len(measured) else 0,
        "valueMonitored": float(active.arr.sum()), "valueLabel": money(active.arr.sum()),
        "medianDaysToSignal": int(df.daysToSignal.dropna().median()) if df.daysToSignal.notna().any() else None,
        "activeWindows": int(len(active)),
    }
    by_type = []
    for t, g in measured.groupby("type"):
        by_type.append({"type": t, "n": int(len(g)), "avgLift": round(float(g.lift.mean()), 1),
                        "successRate": round(float((g.outcome == "Improved").mean()) * 100)})
    by_type.sort(key=lambda x: -x["avgLift"])
    slope_src = measured.sort_values("arr", ascending=False).head(8)
    slope = [{"account": r.account, "baseline": r.baseline, "current": r.current, "outcome": r.outcome} for r in slope_src.itertuples()]
    reg = df if outcome in ("all", "All outcomes", None) else df[df.outcome == outcome]
    reg = reg.sort_values("startedIso", ascending=False)
    chunk, meta = _page(reg, page, page_size)
    return {"summary": summary, "byType": by_type, "slope": slope, "register": chunk.to_dict(orient="records"), **meta,
            "note": "Observational pre/post health movement from model scores (baseline = intervention month, current = latest). Not a causal estimate."}


def intervention_csv(f: Filters) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Account", "Intervention", "Started", "Status", "Baseline health", "Current health", "Lift", "Adoption change", "Outcome", "Next decision"])
    for r in intervention_effectiveness(f, page=1, page_size=200).get("register", []):
        w.writerow([_csv_safe(x) for x in [r["account"], r["type"], r["started"], r["status"], r["baseline"], r["current"], r["lift"],
                                           r["adoptionChange"], r["outcome"], r["decision"]]])
    return "\ufeff" + out.getvalue()


# =========================================================================== health scores / portfolio / segments
def health_scores(f: Filters) -> dict:
    df = _filtered(f, apply_risk=False)
    dist = health_distribution(df)
    return {"distribution": dist, "total": int(len(df)), "average": round(float(df.health.mean()), 1) if len(df) else 0,
            "median": round(float(df.health.median()), 1) if len(df) else 0, "atRiskThreshold": AT_RISK_THRESHOLD,
            "model": about_model(),
            "bands": [{"band": n, "range": f"{lo}–{hi}", "color": c} for n, lo, hi, c in HEALTH_BANDS],
            "methodology": ["Health = 100 − churn-model risk score (Random Forest, class-balanced).",
                            "Bands: Excellent 80–100 · Good 60–79 · Fair 40–59 · Poor 20–39 · Critical 0–19.",
                            "At risk = health below 60 (Fair, Poor and Critical).",
                            "Scores refresh weekly; thresholds are versioned with the methodology (v2.4)."]}


def portfolio(f: Filters) -> dict:
    s = snapshot()
    base = _filtered(f, apply_risk=False, apply_product=False)
    hold = s["holdings"]
    rows = []
    for p in sorted(hold["product"].unique()):
        ids = set(hold.loc[hold["product"] == p, "account_id"])
        g = base[base.account_id.isin(ids)]
        pf = Filters(p, f.region, f.segment, f.risk, f.horizon, f.owner)
        rev = revenue_metrics(pf, 12)
        rows.append({"product": p, "accounts": int(len(g)), "avgScore": round(float(g.health.mean())) if len(g) else 0,
                     "atRiskPct": _pct(int(g.at_risk.sum()), len(g)), "nrr": rev["nrr"], "arr": float(g.arr.sum()), "arrLabel": money(g.arr.sum())})
    ar = base[base.at_risk]
    regions = [{"region": r, "atRisk": int((ar.region == r).sum()), "accounts": int((base.region == r).sum()),
                "pct": _pct(int((ar.region == r).sum()), int((base.region == r).sum()))} for r in sorted(base.region.unique())]
    regions.sort(key=lambda x: -x["atRisk"])
    rev = revenue_metrics(f, 12)
    return {"snapshot": {"accounts": int(len(base)), "avgHealth": round(float(base.health.mean())) if len(base) else 0, "nrr": rev["nrr"]},
            "products": rows, "regions": regions,
            "note": "Multi-product accounts are counted once in each product row, so product totals can exceed the unique account count."}


def segments(f: Filters) -> dict:
    base = _filtered(f, apply_risk=False)
    out = []
    for seg in ["Enterprise", "Mid-Market", "SMB"]:
        g = base[base.segment == seg]
        sf = Filters(f.product, f.region, seg, f.risk, f.horizon, f.owner)
        rev = revenue_metrics(sf, 12)
        out.append({"segment": seg, "accounts": int(len(g)), "avgHealth": round(float(g.health.mean())) if len(g) else 0,
                    "atRiskPct": _pct(int(g.at_risk.sum()), len(g)), "nrr": rev["nrr"], "arr": float(g.arr.sum()), "arrLabel": money(g.arr.sum())})
    return {"segments": out}


# =========================================================================== RFM
def rfm(f: Filters, segment="all", q="", page=1, page_size=10) -> dict:
    df = _filtered(f, apply_risk=False)
    hv = df[df.rfm_segment == "At Risk — High Value"]
    summary = {"avgRecency": round(float(df.days_since_last_login.mean()), 1) if len(df) else 0,
               "avgFrequency": round(float(df.active_days_30d.mean()), 1) if len(df) else 0,
               "monetary": float(df.arr.sum()), "monetaryLabel": money(df.arr.sum()),
               "highValueAtRisk": float(hv.arr.sum()), "highValueAtRiskLabel": money(hv.arr.sum()), "highValueAtRiskCount": int(len(hv))}
    grid = []
    for r in range(1, 6):
        for fr in range(1, 6):
            g = df[(df.r_score == r) & (df.f_score == fr)]
            if len(g):
                grid.append({"r": r, "f": fr, "count": int(len(g)), "arr": float(g.arr.sum()), "arrLabel": money(g.arr.sum()),
                             "avgHealth": round(float(g.health.mean())), "segment": g.rfm_segment.mode().iloc[0]})
    seg_rows = []
    for sname in RFM_SEGMENTS:
        g = df[df.rfm_segment == sname]
        seg_rows.append({"segment": sname, "count": int(len(g)), "arr": float(g.arr.sum()), "arrLabel": money(g.arr.sum()),
                         "avgHealth": round(float(g.health.mean())) if len(g) else 0, "action": RFM_SEGMENT_ACTION[sname]})
    tbl = df if segment in ("all", "All RFM segments", None) else df[df.rfm_segment == segment]
    tbl = _search(tbl, q).sort_values(["m_score", "arr"], ascending=[False, False])
    chunk, meta = _page(tbl, page, page_size)
    return {"summary": summary, "grid": grid, "segments": seg_rows, **meta,
            "rows": [_row(r) for r in chunk.itertuples()],
            "priorityNote": (f"Protect {money(hv.arr.sum())} across {len(hv)} high-value accounts with low Recency and Frequency scores." if len(hv) else "No high-value accounts currently show low Recency and Frequency."),
            "rules": [{"step": "1 · Establish grain", "text": "One row per governed CRM account and a single as-of date."},
                      {"step": "2 · Score each dimension", "text": "Assign cohort quintiles from 1–5; reverse Recency so 5 is best."},
                      {"step": "3 · Segment", "text": "Apply versioned R/F engagement rules, then use M to prioritize value."},
                      {"step": "4 · Validate", "text": "Monitor coverage, telemetry freshness, FX policy and Finance reconciliation."}],
            "segmentRules": [{"segment": "Champions", "rule": "R = 5 and F = 5"}, {"segment": "Loyal", "rule": "R ≥ 4 and F ≥ 4"},
                             {"segment": "Potential Loyalists", "rule": "R ≥ 3 and F ≥ 3"}, {"segment": "Needs Attention", "rule": "Mixed R/F scores"},
                             {"segment": "At Risk — High Value", "rule": "R ≤ 2 and F ≤ 2 and M = 5"}, {"segment": "Hibernating", "rule": "R ≤ 2 and F ≤ 2 and M < 5"}],
            "definitions": [{"k": "Recency", "v": f"Calendar days since the most recent qualifying account activity as of {_fmt_date(snapshot()['as_of'])}. Lower raw values receive higher scores.",
                             "src": "Primary: Product telemetry warehouse · Fallback: Customer Success platform"},
                            {"k": "Frequency", "v": "Distinct days with at least one qualifying product event in the trailing 30 days.", "src": "Primary: Product telemetry warehouse · identity resolved to CRM account ID"},
                            {"k": "Monetary", "v": "Finance-approved recurring revenue at the account level in reporting currency (synthetic ARR here).", "src": "Primary: Contract & billing system · Control: Finance revenue mart"}]}


# =========================================================================== drivers
def drivers(f: Filters) -> dict:
    s = snapshot()
    df = _filtered(f, apply_risk=False)
    risk, good = df[df.at_risk], df[df.health >= AT_RISK_THRESHOLD]
    shortfall = float((80 - risk.health).clip(lower=0).mean()) if len(risk) else 0.0
    uplift = float(good.health.mean() - risk.health.mean()) if len(risk) and len(good) else 0.0
    raw = {k: s["adv_w"][k] * float(risk[f"adv::{k}"].clip(lower=0).mean()) if len(risk) else 0.0 for k in CHURN_DRIVERS}
    tot = sum(raw.values()) or 1.0
    affected = risk.top_driver.value_counts().to_dict()
    churn = sorted([{"driver": k, "impact": -round(shortfall * v / tot, 1), "share": round(v / tot * 100, 1),
                     "accounts": int(affected.get(k, 0))} for k, v in raw.items()], key=lambda d: d["impact"])
    ahigh = good[good.health >= 70]
    rawf = {k: s["fav_w"][k] * float(ahigh[f"fav::{k}"].clip(lower=0).mean()) if len(ahigh) else 0.0 for k in ADOPTION_DRIVERS}
    totf = sum(rawf.values()) or 1.0
    adoption = sorted([{"driver": k, "impact": round(uplift * v / totf, 1), "share": round(v / totf * 100, 1)} for k, v in rawf.items()],
                      key=lambda d: -d["impact"])
    top = churn[:2]
    return {"churn": churn, "adoption": adoption, "shortfall": round(shortfall, 1), "uplift": round(uplift, 1),
            "takeawayChurn": (f"Primary takeaway: {top[0]['driver']} and {top[1]['driver']} are the two largest controllable sources of churn risk in this portfolio." if len(top) == 2 and len(risk) else "Not enough at-risk accounts for the current filters."),
            "takeawayAdoption": (f"Primary takeaway: {adoption[0]['driver']}, {adoption[1]['driver']} and {adoption[2]['driver']} are the highest-leverage adoption signals." if len(adoption) >= 3 and len(ahigh) else ""),
            "atRiskAccounts": int(len(risk)),
            "note": "Impacts are model associations on the 0–100 health scale, not causal estimates. Weights = correlation of each driver index with churn risk; see Source & Methodology."}


# =========================================================================== renewals
def renewals(f: Filters, horizon=None, page=1, page_size=10, preview=False, sort="days") -> dict:
    horizon = int(horizon or f.horizon or 90)
    df = _filtered(f, apply_risk=False)
    win = df[(df.days_to_renewal >= 0) & (df.days_to_renewal <= horizon)]
    total = float(win.arr.sum())
    bands = {"Excellent": 0.0, "Good": 0.0, "Fair": 0.0, "Poor / Critical": 0.0}
    for r in win.itertuples():
        bands["Poor / Critical" if r.health_band in ("Poor", "Critical") else r.health_band] += r.arr
    pc, bg = bands["Poor / Critical"], bands["Excellent"] + bands["Good"]
    cov = _pct(int((win.csm_owner != "Unassigned").sum()), len(win), 0)
    prev_win = None
    s = snapshot()
    ph = s["hist"]
    ph = ph[(ph.panel_month_seq == 11) & ph.account_id.isin(set(df.account_id)) & (ph.days_to_renewal >= 0) & (ph.days_to_renewal <= horizon)]
    prev_cov = _pct(int((s["cur"].loc[ph.account_id, "csm_owner"] != "Unassigned").sum()), len(ph), 0) if len(ph) else cov
    sorted_ = win.sort_values("days_to_renewal") if sort == "days" else win.sort_values("arr", ascending=False)
    if preview:
        sorted_ = win[win.at_risk].nlargest(page_size, "arr").sort_values("days_to_renewal")
        chunk, meta = sorted_, {"page": 1, "pageSize": page_size, "total": int(len(win)), "pages": 1}
    else:
        chunk, meta = _page(sorted_, page, page_size)
    fus = _open_followups()
    rows = []
    for r in chunk.itertuples():
        row = _row(r, fus.get(r.Index))
        row["recommendedAction"] = r.renewal_action
        rows.append(row)
    return {"horizon": horizon, "pipeline": total, "pipelineLabel": money(total), "count": int(len(win)),
            "poorCritical": {"value": pc, "label": money(pc), "pct": _pct(pc, total)},
            "bestGood": {"value": bg, "label": money(bg), "pct": _pct(bg, total)},
            "avgDays": round(float(win.days_to_renewal.mean())) if len(win) else 0,
            "ownerCoverage": cov, "ownerCoverageDelta": cov - prev_cov,
            "bands": [{"band": k, "value": v, "label": money(v), "pct": _pct(v, total)} for k, v in bands.items()],
            "rows": rows, **meta}


# =========================================================================== playbooks
def _playbook_mask(df: pd.DataFrame, pid: str):
    if pid == "role_activation_sprint":
        return (df.top_driver == "Low Product Adoption") & (df.health < 70)
    if pid == "executive_roi_review":
        return (df.top_driver == "Low Perceived Value / ROI") & (df.health < 70)
    if pid == "critical_renewal_response":
        return (df.health < 40) & (df.days_to_renewal <= 60)
    if pid == "reonboarding_pathway":
        return (df.top_driver == "Onboarding Experience") & (df.health < 70)
    if pid == "critical_issue_recovery":
        return (df.high_priority_tickets_90d >= 2) & (df.support_friction_score >= 60) & (df.health < 70)
    if pid == "champion_amplification":
        return (df.rfm_segment.isin(["Champions", "Loyal"])) & (df.health >= 75) & (df.executive_sponsor_engaged == 1) & (df.seat_utilization_pct >= 80)
    return pd.Series(False, index=df.index)


def playbooks(f: Filters) -> list:
    df = _filtered(f, apply_risk=False)
    fus = _open_followups()
    suppress = set(fus)
    out = []
    for p in PLAYBOOKS:
        m = _playbook_mask(df, p["id"])
        elig = df[m & ~df.account_id.isin(suppress)]
        out.append({**p, "eligible": int(len(elig)), "suppressed": int((m & df.account_id.isin(suppress)).sum()),
                    "eligibleArr": float(elig.arr.sum()), "eligibleArrLabel": money(elig.arr.sum()),
                    "topAccounts": [{"id": r.account_id, "name": r.company_name, "health": int(r.health_int), "amount": money(r.arr)}
                                    for r in elig.sort_values("priority", ascending=False).head(5).itertuples()]})
    return out


def launch_playbook(pid: str, account_id: str, due=None) -> dict:
    book = next((p for p in PLAYBOOKS if p["id"] == pid), None)
    if book is None:
        raise KeyError(pid)
    return create_followup({"accountId": account_id, "actionType": "playbook", "subject": f"{book['title']}",
                            "message": f"{book['description']} Trigger: {book['trigger']}.", "due": due})


# =========================================================================== alerts
def seed_alerts() -> int:
    ensure_tables()
    s = snapshot()
    cur, hist, asof = s["cur"], s["hist"], s["as_of"]
    rng = np.random.default_rng(7)
    alerts = []

    def add(sev, cat, title, detail, age, acct=None):
        alerts.append((f"AL-{len(alerts) + 1:03d}", sev, cat, title, detail, int(age), "open", acct, None))

    went_crit = cur[(cur.health < 20) & (cur.prev_health >= 20)]
    if len(went_crit):
        top = went_crit.top_driver.value_counts().index[0]
        add("Critical", "Health", f"{len(went_crit)} accounts moved into Critical health",
            f"Largest movement is associated with {top.lower()} and open support issues; {money(went_crit.arr.sum())} ARR affected.", 2)
    soon = cur[(cur.days_to_renewal <= 30) & (cur.health < 40)]
    if len(soon):
        add("Critical", "Renewals", f"{len(soon)} Poor/Critical accounts renew within 30 days",
            f"{money(soon.arr.sum())} of renewal value needs an owner-reviewed plan this month.", 3)
    for prod in sorted(cur.primary_product.unique()):
        g = cur[cur.primary_product == prod]
        h = hist[hist.account_id.isin(set(g.account_id))]
        a12, a11 = h[h.panel_month_seq == 12].distinct_features_used.mean(), h[h.panel_month_seq == 11].distinct_features_used.mean()
        chg = (a12 - a11) / a11 * 100 if a11 else 0
        if chg <= -1.0:
            mm = g[(g.segment == "Mid-Market") & (g.days_to_renewal <= 90) & g.at_risk]
            add("Warning", "Adoption", f"{prod} adoption declined {abs(chg):.1f}%",
                f"Feature breadth fell across {len(g)} accounts; {len(mm)} mid-market accounts have renewals inside 90 days.", 5 + int(rng.integers(0, 6)))
    for seg in ["Enterprise", "Mid-Market", "SMB"]:
        g = cur[cur.segment == seg]
        d = (g.health - g.prev_health).mean()
        if d <= -0.4:
            add("Warning", "Segment", f"{seg} average health fell {abs(d):.1f} pts month over month",
                f"{int(((g.health_change <= -3)).sum())} {seg} accounts lost 3+ points.", 8 + int(rng.integers(0, 6)))
    for reg in sorted(cur.region.unique()):
        g = cur[cur.region == reg]
        pr = hist[(hist.panel_month_seq == 11) & hist.account_id.isin(set(g.account_id))]
        d = _pct(int(g.at_risk.sum()), len(g)) - _pct(int((pr.health < 60).sum()), len(pr))
        if d >= 0.8:
            add("Warning", "Region", f"{reg} at-risk share up {d:.1f}pp",
                f"{int(g.at_risk.sum())} of {len(g)} {reg} accounts are now below the risk threshold.", 12 + int(rng.integers(0, 10)))
    ch = cur[(cur.champion_turnover_flag_90d == 1) & cur.at_risk]
    if len(ch):
        add("Warning", "Relationship", f"{len(ch)} at-risk accounts flagged champion turnover",
            f"{int((ch.segment == 'Enterprise').sum())} are Enterprise; re-establish an executive sponsor.", 14)
    pay = cur[(cur.invoice_overdue_flag == 1) & (cur.payment_failure_90d_count > 0)]
    if len(pay):
        add("Warning", "Commercial", f"{len(pay)} accounts have an overdue invoice and failed payments",
            f"{money(pay.arr.sum())} ARR exposed; coordinate with Finance before outreach.", 20)
    hp = cur[(cur.high_priority_tickets_90d >= 3) & (cur.health < 70)]
    if len(hp):
        add("Warning", "Support", f"{len(hp)} accounts have 3+ high-priority tickets in 90 days",
            "Escalate to Support Operations and confirm a prevention plan.", 26)
    nosp = cur[(cur.arr >= cur.arr.quantile(0.9)) & (cur.executive_sponsor_engaged == 0) & cur.at_risk]
    if len(nosp):
        add("Warning", "Relationship", f"{len(nosp)} high-value at-risk accounts have no engaged executive sponsor",
            f"{money(nosp.arr.sum())} ARR; assign an executive owner.", 30)
    conn = _conn()
    iv = pd.read_sql("SELECT * FROM interventions WHERE intervention_status='Completed' AND intervention_outcome IN ('Retained - Usage Improved','Upsell Identified')", conn)
    conn.close()
    imp = iv[iv.account_id.isin(set(cur.index))]
    if len(imp):
        sc = hist.set_index(["account_id", "panel_month_seq"]).health
        lifts = []
        for r in imp.itertuples():
            ym = pd.Timestamp(r.as_of_month)
            p = 12 - ((asof.year - ym.year) * 12 + (asof.month - ym.month))
            if 1 <= p <= 11:
                lifts.append(sc.get((r.account_id, 12), np.nan) - sc.get((r.account_id, p), np.nan))
        lifts = [x for x in lifts if not pd.isna(x)]
        if lifts:
            add("Positive", "Interventions", f"{len([x for x in lifts if x >= 5])} accounts improved after interventions",
                f"Average health score increased by {np.mean([x for x in lifts if x >= 5]):.0f} points between the intervention month and now.", 26)
    # account-level movers
    drops = cur[cur.health_change <= -10].nlargest(6, "arr")
    for r in drops.itertuples():
        if r.health_change <= -10:
            add("Critical" if r.health < 40 else "Warning", "Account", f"{r.company_name} health dropped {abs(r.health_change):.0f} points to {r.health_int}",
                f"{r.health_band} · leading driver: {r.top_driver}; renewal {_fmt_date(r.renewal_date)} ({money(r.arr)}).", 6 + int(rng.integers(0, 70)), r.Index)
    ups = cur[cur.health_change >= 8].nlargest(3, "arr")
    for r in ups.itertuples():
        if r.health_change >= 8:
            add("Positive", "Account", f"{r.company_name} health improved {r.health_change:.0f} points to {r.health_int}",
                f"Now {r.health_band}; consider moving to the Monitoring stage.", 30 + int(rng.integers(0, 60)), r.Index)
    conn = _conn()
    conn.execute("DELETE FROM ac_alerts")
    conn.executemany("INSERT INTO ac_alerts (id, severity, category, title, detail, age_hours, status, account_id, reviewed_at) VALUES (?,?,?,?,?,?,?,?,?)", alerts)
    conn.commit()
    conn.close()
    return len(alerts)


def _age_label(h):
    return f"{h}h ago" if h < 24 else f"{h // 24}d ago"


def alerts(status="all", severity="all") -> dict:
    ensure_tables()
    conn = _conn()
    n = conn.execute("SELECT COUNT(*) FROM ac_alerts").fetchone()[0]
    conn.close()
    if n == 0:
        seed_alerts()
    conn = _conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM ac_alerts ORDER BY age_hours ASC, id")]
    conn.close()
    items = [{"id": r["id"], "severity": r["severity"], "category": r["category"], "title": r["title"], "detail": r["detail"],
              "age": _age_label(r["age_hours"]), "ageHours": r["age_hours"], "status": r["status"], "accountId": r["account_id"]} for r in rows]
    open_n = sum(1 for x in items if x["status"] == "open")
    view = [x for x in items if (status == "all" or x["status"] == status) and (severity == "all" or x["severity"] == severity)]
    return {"items": view, "open": open_n, "total": len(items),
            "bySeverity": {sv: sum(1 for x in items if x["severity"] == sv and x["status"] == "open") for sv in ["Critical", "Warning", "Positive"]}}


def review_alert(aid: str) -> dict:
    conn = _conn()
    n = conn.execute("UPDATE ac_alerts SET status='reviewed', reviewed_at=? WHERE id=?", (datetime.utcnow().isoformat(timespec="seconds"), aid)).rowcount
    conn.commit()
    conn.close()
    if not n:
        raise KeyError(aid)
    return {"id": aid, "status": "reviewed"}


def review_all_alerts() -> dict:
    conn = _conn()
    n = conn.execute("UPDATE ac_alerts SET status='reviewed', reviewed_at=? WHERE status='open'", (datetime.utcnow().isoformat(timespec="seconds"),)).rowcount
    conn.commit()
    conn.close()
    return {"reviewed": n}


def reopen_alerts() -> dict:
    conn = _conn()
    conn.execute("UPDATE ac_alerts SET status='open', reviewed_at=NULL")
    conn.commit()
    conn.close()
    return {"status": "open"}


# =========================================================================== reports
def _section_content(sec: str, f: Filters) -> dict:
    if sec == "executive_kpis":
        return {"kpis": overview(f)["kpis"], "distribution": health_distribution(_filtered(f, apply_risk=False))}
    if sec == "rfm_summary":
        r = rfm(f)
        return {"summary": r["summary"], "segments": r["segments"], "note": r["priorityNote"]}
    if sec == "health_trend":
        t = health_trend(f, "weekly")
        return {"points": t["points"][-12:], "note": t["note"]}
    if sec == "drivers":
        d = drivers(f)
        return {"churn": d["churn"], "adoption": d["adoption"], "takeaway": d["takeawayChurn"]}
    if sec == "action_queue":
        return {"rows": action_queue(f, page=1, page_size=10)["rows"]}
    if sec == "upcoming_renewals":
        r = renewals(f, horizon=f.horizon, page_size=10)
        return {k: r[k] for k in ("horizon", "pipelineLabel", "count", "poorCritical", "bestGood", "avgDays", "ownerCoverage", "bands", "rows")}
    if sec == "recommended_playbooks":
        return {"playbooks": [{k: p[k] for k in ("title", "category", "eligible", "eligibleArrLabel", "trigger")} for p in playbooks(f)]}
    return {}


def create_report(payload: dict) -> dict:
    ensure_tables()
    tpl = next((t for t in REPORT_TEMPLATES if t["id"] == payload.get("template")), REPORT_TEMPLATES[0])
    sections = [s for s in (payload.get("sections") or tpl["sections"]) if s in REPORT_SECTIONS] or tpl["sections"]
    f = Filters(**{k: (payload.get("filters") or {}).get(k) for k in ("product", "region", "segment", "risk", "horizon", "owner")})
    content = {sec: _section_content(sec, f) for sec in sections}
    rid = f"RPT-{uuid.uuid4().hex[:8].upper()}"
    name = (payload.get("name") or tpl["title"]).strip()[:120]
    recipients = (payload.get("recipients") or "").strip()[:300]
    conn = _conn()
    conn.execute("INSERT INTO ac_reports (id, name, template, recipients, sections, filters, content, created_at, status) VALUES (?,?,?,?,?,?,?,?,?)",
                 (rid, name, tpl["id"], recipients, json.dumps(sections), json.dumps(f.as_dict()), json.dumps(_py(content)),
                  datetime.utcnow().isoformat(timespec="seconds"), "Generated"))
    conn.commit()
    conn.close()
    return get_report(rid, with_content=False)


def list_reports() -> dict:
    ensure_tables()
    conn = _conn()
    rows = [dict(r) for r in conn.execute("SELECT id, name, template, recipients, sections, filters, created_at, status FROM ac_reports ORDER BY created_at DESC")]
    conn.close()
    return {"templates": [{**t, "sectionLabels": [REPORT_SECTIONS[x] for x in t["sections"]]} for t in REPORT_TEMPLATES],
            "sections": [{"id": k, "label": v} for k, v in REPORT_SECTIONS.items()],
            "reports": [{**r, "sections": json.loads(r["sections"]), "filters": json.loads(r["filters"])} for r in rows]}


def get_report(rid: str, with_content=True) -> dict:
    conn = _conn()
    r = conn.execute("SELECT * FROM ac_reports WHERE id=?", (rid,)).fetchone()
    conn.close()
    if r is None:
        raise KeyError(rid)
    r = dict(r)
    out = {"id": r["id"], "name": r["name"], "template": r["template"], "recipients": r["recipients"], "createdAt": r["created_at"],
           "status": r["status"], "sections": json.loads(r["sections"]), "filters": json.loads(r["filters"])}
    if with_content:
        out["content"] = json.loads(r["content"])
    return out


def report_html(rid: str) -> str:
    r = get_report(rid)
    esc = html.escape
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(r['name'])}</title>"
             "<style>body{font-family:Segoe UI,Arial,sans-serif;color:#243b46;max-width:960px;margin:32px auto;padding:0 20px}"
             "h1{font-size:24px}h2{font-size:16px;margin-top:28px;border-bottom:1px solid #e0e7e9;padding-bottom:6px;color:#105e6b}"
             "table{border-collapse:collapse;width:100%;font-size:12px;margin-top:8px}th,td{border-bottom:1px solid #e0e7e9;padding:6px 8px;text-align:left}"
             "th{background:#f4f7f7;color:#647780}.k{display:inline-block;margin:6px 14px 6px 0}.k b{display:block;font-size:20px}"
             ".note{color:#647780;font-size:11px;margin-top:10px}</style></head><body>"]
    flt = r["filters"]
    parts.append(f"<h1>{esc(r['name'])}</h1><p class='note'>Generated {esc(r['createdAt'])} UTC · Filters: "
                 f"{esc(' · '.join(str(v) for k, v in flt.items() if k != 'horizon'))} · Recipients: {esc(r['recipients'] or '—')} · "
                 "All values are synthetic.</p>")

    def table(headers, rows):
        return "<table><tr>" + "".join(f"<th>{esc(h)}</th>" for h in headers) + "</tr>" + "".join(
            "<tr>" + "".join(f"<td>{esc(str(c))}</td>" for c in row) + "</tr>" for row in rows) + "</table>"

    for sec in r["sections"]:
        c = r["content"].get(sec, {})
        parts.append(f"<h2>{esc(REPORT_SECTIONS[sec])}</h2>")
        if sec == "executive_kpis":
            parts.extend(f"<span class='k'><b>{esc(str(k['value']))}{esc(k['unit'] or '')}</b>{esc(k['label'])}</span>" for k in c.get("kpis", []))
            parts.append(table(["Band", "Range", "Accounts", "Share"], [[d["band"], d["range"], d["count"], f"{d['pctExact']}%"] for d in c.get("distribution", [])]))
        elif sec == "rfm_summary":
            s = c.get("summary", {})
            parts.append(f"<p>Avg recency {s.get('avgRecency')} days · avg frequency {s.get('avgFrequency')} active days · monetary {esc(str(s.get('monetaryLabel')))} · "
                         f"high-value at risk {esc(str(s.get('highValueAtRiskLabel')))} ({s.get('highValueAtRiskCount')} accounts)</p>")
            parts.append(table(["Segment", "Accounts", "ARR", "Avg health", "Action"], [[x["segment"], x["count"], x["arrLabel"], x["avgHealth"], x["action"]] for x in c.get("segments", [])]))
        elif sec == "health_trend":
            parts.append(table(["Week", "Health", "30-day MA"], [[p["label"], p["score"], p["ma"]] for p in c.get("points", [])]))
            parts.append(f"<p class='note'>{esc(c.get('note', ''))}</p>")
        elif sec == "drivers":
            parts.append(table(["Churn driver", "Impact (pts)", "Accounts"], [[d["driver"], d["impact"], d["accounts"]] for d in c.get("churn", [])]))
            parts.append(table(["Adoption driver", "Impact (pts)"], [[d["driver"], f"+{d['impact']}"] for d in c.get("adoption", [])]))
            parts.append(f"<p class='note'>{esc(c.get('takeaway', ''))}</p>")
        elif sec == "action_queue":
            parts.append(table(["Account", "Health", "Risk level", "RFM segment", "Renewal", "Amount", "Next best action"],
                               [[x["name"], x["health"], x["healthBand"], x["rfm"]["segment"], x["renewal"], x["amount"], x["nextBestAction"]] for x in c.get("rows", [])]))
        elif sec == "upcoming_renewals":
            parts.append(f"<p>{esc(str(c.get('pipelineLabel')))} pipeline · {c.get('count')} renewals · avg {c.get('avgDays')} days · owner coverage {c.get('ownerCoverage')}%</p>")
            parts.append(table(["Account", "Renewal", "Days", "Health", "Top driver", "Amount", "Action"],
                               [[x["name"], x["renewal"], x["renewalDays"], f"{x['health']} · {x['healthBand']}", x["topDriver"], x["amount"], x["recommendedAction"]] for x in c.get("rows", [])]))
        elif sec == "recommended_playbooks":
            parts.append(table(["Playbook", "Category", "Eligible accounts", "Eligible ARR", "Trigger"],
                               [[x["title"], x["category"], x["eligible"], x["eligibleArrLabel"], x["trigger"]] for x in c.get("playbooks", [])]))
    parts.append("</body></html>")
    return "".join(parts)


# =========================================================================== static content / settings
def methodology() -> dict:
    j = lambda n: json.load(open(CONTENT_DIR / n, encoding="utf8"))
    return {"sources": j("sources.json"), "metrics": j("metrics.json"), "controls": j("controls.json"),
            "stats": {"version": "v2.4", "refresh": "Weekly", "signals": about_model()["signals"], "dataStatus": "Synthetic"},
            "disclosure": ("This build does not connect to production systems. All displayed values and account names are synthetic, generated by "
                           "generate_synthetic_data.py and stored in a local SQLite database. The production systems listed below are a proposed "
                           "source-of-truth design and must be validated with Data Engineering, Finance, Customer Success Operations, Support and "
                           "Privacy before launch.")}


def faqs() -> dict:
    return {"items": json.load(open(CONTENT_DIR / "faqs.json", encoding="utf8")),
            "quick": [{"k": "0–100", "v": "Higher indicates healthier renewal signals."}, {"k": "60", "v": "Scores below 60 are considered at risk."},
                      {"k": "Weekly", "v": "Proposed model refresh cadence."}, {"k": "Validate", "v": "Model output supports—not replaces—owner judgment."}]}


def get_settings() -> dict:
    ensure_tables()
    conn = _conn()
    rows = {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT key, value FROM ac_settings")}
    conn.close()
    return {**DEFAULT_SETTINGS, **rows}


def put_settings(patch: dict) -> dict:
    conn = _conn()
    for k, v in patch.items():
        if k in DEFAULT_SETTINGS:
            conn.execute("INSERT OR REPLACE INTO ac_settings (key, value) VALUES (?, ?)", (k, json.dumps(bool(v))))
    conn.commit()
    conn.close()
    return get_settings()


# =========================================================================== chat "dashboard guide"
def guide_answer(question: str):
    """Answers the Action-Center style questions from live data. Returns None for anything else so the
    GraphRAG pipeline (graph_rag.py) keeps handling account/narrative questions unchanged."""
    q = (question or "").lower()
    f = Filters()
    if "top priorit" in q or "highest priorit" in q:
        rows = action_queue(f, page_size=5)["rows"]
        lines = [f"- {r['name']} ({r['id']}): health {r['health']} ({r['healthBand']}), {r['amount']}, renews {r['renewal']} — {r['nextBestAction']}" for r in rows]
        return "Top account priorities right now (rule-based priority score):\n" + "\n".join(lines)
    if "waiting on manager" in q:
        fu = [x for x in list_followups(f)["items"] if x["status"] == "Waiting on manager"]
        if not fu:
            return "No follow-ups are currently waiting on a manager decision."
        return f"{len(fu)} follow-ups are waiting on a manager decision:\n" + "\n".join(f"- {x['account']} — {x['action']} (owner: {x['ownerRole']}, due {x['dueLabel']})" for x in fu[:8])
    if "effective intervention" in q or "intervention result" in q or "interventions work" in q:
        e = intervention_effectiveness(f)
        sm = e["summary"]
        best = e["byType"][0] if e["byType"] else None
        return (f"{sm['improved']} of {sm['measured']} measured interventions improved health ({sm['successRate']}% success), average lift {sm['avgLift']:+.1f} points. "
                + (f"Strongest type: {best['type']} ({best['avgLift']:+.1f} pts, {best['successRate']}% improved). " if best else "")
                + "These are observational pre/post results, not causal estimates.")
    if "explain rfm" in q or "what is rfm" in q or "how is rfm" in q:
        r = rfm(f)["summary"]
        return ("RFM scores each account 1–5 on Recency (days since qualifying activity, reversed so 5 = most recent), Frequency (active days in the trailing 30) and "
                f"Monetary value (ARR). Portfolio average recency is {r['avgRecency']} days and frequency {r['avgFrequency']} active days; "
                f"{r['highValueAtRiskLabel']} sits in {r['highValueAtRiskCount']} high-value accounts with low Recency and Frequency.")
    if "upcoming renewal" in q or "renewal pipeline" in q:
        r = renewals(f, horizon=90, page_size=3)
        return (f"{r['count']} renewals worth {r['pipelineLabel']} fall in the next 90 days; {r['poorCritical']['label']} ({r['poorCritical']['pct']}%) belongs to Poor/Critical accounts. "
                "Largest: " + "; ".join(f"{x['name']} {x['renewal']} ({x['amount']})" for x in r["rows"]))
    if "open alerts" in q or "alert summary" in q:
        a = alerts("open")
        return f"{a['open']} open alerts ({a['bySeverity']['Critical']} critical, {a['bySeverity']['Warning']} warning). Latest: " + "; ".join(x["title"] for x in a["items"][:3])
    return None
