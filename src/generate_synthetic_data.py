"""
Synthetic Data Generator
=========================
Builds the complete, fully synthetic source dataset that the rest of the
pipeline (derive_fields -> train_model -> drift_monitor -> build_graph ->
narratives -> action-center seed) reads.  NOTHING here is real customer data.

Outputs (all under ../data):
  churn_data.db  -- SQLite database with the tables below
  model_train.csv / model_holdout.csv / baseline_benchmark.csv

SQLite tables written here
  accounts                  one row per monitored account (3,000)
  account_monthly_metrics   12 monthly snapshots per account (panel_month_seq 1..12)
  account_spend_history     monthly spend for month_index -10..12 (used for NRR / TTM maths)
  account_products          account <-> product holdings (multi-product accounts exist)
  interventions             logged CSM interventions (+ outcomes for completed ones)
  baseline_benchmark        the "legacy heuristic" risk score (comparison baseline)
  churn_events              former customers that churned in the trailing window

Design (so the data is realistic enough to train and evaluate a model on):
  * Every account has a latent "distress" level d(t) in [0,1].  ~20% of accounts
    are decliners whose distress ramps up from a random onset month; a few recover.
  * Every observable feature is a noisy function of d(t) (+ a little feature-
    specific time drift so the drift monitor has something real to find).
  * churned_within_90d is Bernoulli with a logit that depends on d(t) and a few
    flags; a logged intervention lowers the odds (simulated effect, ~-60% odds).
  * Same seed => byte-identical data.   python generate_synthetic_data.py [--seed N]
"""
import argparse
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "churn_data.db"

N_ACCOUNTS = 3000
N_MONTHS = 12
SPEND_MONTHS = list(range(-10, 13))          # month_index -10 .. 12 (23 points)
# month 12 = Sep 2026 (data-through 2026-09-30)
MONTH_ENDS = pd.date_range("2025-10-31", periods=12, freq="ME")
HIST_MONTH_ENDS = pd.date_range(end=MONTH_ENDS[-1], periods=len(SPEND_MONTHS), freq="ME")

SEGMENTS = ["Enterprise", "Mid-Market", "SMB"]
REGIONS = ["NAMER", "EMEA", "APAC", "LATAM"]
INDUSTRIES = ["Technology", "Financial Services", "Healthcare", "Manufacturing",
              "Retail & E-commerce", "Professional Services", "Media & Entertainment",
              "Education", "Energy & Utilities", "Telecommunications"]
CONTRACTS = ["Monthly", "Annual", "Multi-Year"]
PRODUCTS = ["Talent Solutions", "Sales Solutions", "Marketing Solutions", "Learning Solutions"]
INTERVENTION_TYPES = [
    "Training & Enablement Session", "Technical / Support Health Check",
    "Champion Re-engagement Outreach", "Commercial Discount Review",
]
CSM_OWNERS = [
    "Priya Raman", "Marcus Webb", "Elena Petrova", "Daniel Okafor", "Sofia Lindqvist",
    "Hiro Tanaka", "Amara Nwosu", "Lucas Ferreira", "Grace Holloway", "Mateo Alvarez",
    "Ingrid Solberg", "Rahul Menon", "Chloe Dubois", "Tobias Krause", "Yuki Matsuda",
    "Fatima Al-Sayed", "Owen Mitchell", "Nadia Kowalski", "Samuel Adeyemi", "Leila Haddad",
    "Victor Moreau", "Hannah Brooks", "Arjun Nair", "Camila Ortega",
]
AE_OWNERS = ["Jordan Blake", "Mei Lin Zhao", "Carlos Mendes", "Aisha Rahman", "Peter Novak",
             "Isabelle Roy", "Kwame Boateng", "Anna Fischer", "Diego Salazar", "Hana Sato",
             "Noah Bennett", "Zara Qureshi"]
SC_OWNERS = ["Ravi Shankar", "Julia Kemp", "Andre Silva", "Mina Park", "Oscar Lindgren",
             "Tara Singh", "Felix Baumann", "Layla Mansour", "Ethan Cole", "Sana Iqbal",
             "Marta Kowal", "Joel Adeyemi"]

NAME_PREFIX = ["Northwind", "Harborview", "Bluepeak", "Ironbridge", "Silverline", "Redwood", "Clearwater",
               "Summit", "Evergreen", "Lakeshore", "Stonegate", "Brightwave", "Cedarpoint", "Goldfield",
               "Highland", "Kingsley", "Meridian", "Oakridge", "Pinnacle", "Quartzite", "Riverbend",
               "Skyline", "Trident", "Union", "Vertex", "Westbrook", "Yellowstone", "Zephyr", "Alder",
               "Beacon", "Crescent", "Dunmore", "Elmwood", "Fairmont", "Granite", "Hawthorne", "Ivory",
               "Juniper", "Kestrel", "Lumen", "Marlow", "Nimbus", "Orchard", "Prairie", "Quill", "Rosewood",
               "Sterling", "Thornfield", "Upland", "Valiant", "Windmere", "Xenon", "Yarrow", "Zenith",
               "Aurora", "Basalt", "Coral", "Delta", "Ember", "Fjord", "Glacier", "Horizon", "Indigo",
               "Jasper", "Keystone", "Lattice", "Monarch", "Nova", "Onyx", "Polaris", "Quantum", "Raven",
               "Sapphire", "Tundra", "Umber", "Vanguard", "Willow", "Apex", "Birch", "Cobalt"]
NAME_SUFFIX = ["Systems", "Analytics", "Logistics", "Partners", "Labs", "Industries", "Group", "Networks",
               "Dynamics", "Holdings", "Solutions", "Technologies", "Health", "Capital", "Media", "Energy",
               "Foods", "Robotics", "Cloud", "Consulting", "Learning", "Retail", "Motors", "Financial",
               "Software", "Materials", "Telecom", "Pharma", "Ventures", "Works", "Interactive", "Global",
               "Supply", "Education", "Utilities", "Security", "Devices", "Studios", "Brands", "Services"]

CHURN_DRIVERS = ["Low Product Adoption", "Low Perceived Value / ROI", "Pricing / Cost Concerns",
                 "Competing Solution", "Support Experience", "Onboarding Experience",
                 "Integration Gaps", "Contract / Commercial Terms"]
CHURN_DRIVER_P = np.array([0.25, 0.19, 0.15, 0.12, 0.10, 0.08, 0.07, 0.04])


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def build_company_names(rng, n):
    combos = [f"{p} {s}" for p in NAME_PREFIX for s in NAME_SUFFIX]
    rng.shuffle(combos)
    return combos[:n]


def make_accounts(rng):
    n = N_ACCOUNTS
    ids = [f"ACC-{30001 + i}" for i in range(n)]
    seg = rng.choice(SEGMENTS, size=n, p=[0.157, 0.368, 0.475])
    region = rng.choice(REGIONS, size=n, p=[0.40, 0.28, 0.22, 0.10])
    industry = rng.choice(INDUSTRIES, size=n)
    contract = np.empty(n, dtype=object)
    for s, p in {"Enterprise": [0.04, 0.46, 0.50], "Mid-Market": [0.14, 0.62, 0.24], "SMB": [0.34, 0.58, 0.08]}.items():
        m = seg == s
        contract[m] = rng.choice(CONTRACTS, size=m.sum(), p=p)
    product = rng.choice(PRODUCTS, size=n, p=[0.344, 0.256, 0.211, 0.189])

    csm = rng.choice(CSM_OWNERS, size=n)
    csm = np.where(rng.random(n) < 0.06, "Unassigned", csm)      # owner coverage ~94%
    ae = rng.choice(AE_OWNERS, size=n)
    sc = rng.choice(SC_OWNERS, size=n)

    # tenure at month 12 (months). ~13% joined within the last 12 months.
    age12 = np.where(rng.random(n) < 0.13, rng.integers(1, 13, n), rng.integers(13, 121, n))

    emp = np.empty(n, dtype=int)
    for s, (lo, hi) in {"Enterprise": (2000, 60000), "Mid-Market": (200, 2000), "SMB": (8, 200)}.items():
        m = seg == s
        emp[m] = np.exp(rng.uniform(np.log(lo), np.log(hi), m.sum())).astype(int)

    accounts = pd.DataFrame({
        "account_id": ids,
        "company_name": build_company_names(rng, n),
        "segment": seg, "region": region, "industry": industry,
        "csm_owner": csm, "account_executive": ae, "solutions_consultant": sc,
        "contract_type": contract, "primary_product": product,
        "company_size_employees": emp,
        "tenure_months_at_snapshot": age12,
    })

    # product holdings (primary + 0..2 additional products ~ 26% multi-product)
    rows = []
    for aid, prim in zip(ids, product):
        rows.append((aid, prim, 1))
        if rng.random() < 0.26:
            others = [p for p in PRODUCTS if p != prim]
            k = 1 if rng.random() < 0.8 else 2
            for p in rng.choice(others, size=k, replace=False):
                rows.append((aid, p, 0))
    products = pd.DataFrame(rows, columns=["account_id", "product", "is_primary"])
    return accounts, products


def make_monthly(rng, accounts, tune):
    n = len(accounts)
    seg = accounts.segment.to_numpy()
    contract = accounts.contract_type.to_numpy()
    age12 = accounts.tenure_months_at_snapshot.to_numpy()
    seg_idx = pd.Series(seg).map({"Enterprise": 0, "Mid-Market": 1, "SMB": 2}).to_numpy()

    # ---------------- latent distress path d[i, t] (t = 1..12) ----------------
    d0 = rng.beta(1.2, 7.6, n)
    d0 += np.select([seg == "SMB", seg == "Enterprise"], [0.04, -0.03], 0.0)
    d0 += np.select([contract == "Monthly", contract == "Multi-Year"], [0.05, -0.04], 0.0)
    decliner = rng.random(n) < tune["decliner_share"]
    recoverer = (~decliner) & (rng.random(n) < 0.07)
    onset = rng.integers(2, 11, n)
    slope = np.where(decliner, rng.uniform(0.022, 0.075, n),
                     np.where(recoverer, -rng.uniform(0.02, 0.05, n), rng.normal(0.0, 0.005, n)))
    t = np.arange(1, N_MONTHS + 1)[None, :]
    walk = np.cumsum(rng.normal(0, 0.012, (n, N_MONTHS)), axis=1)
    d = d0[:, None] + slope[:, None] * np.maximum(0, t - onset[:, None]) + 0.0025 * (t - 1) + walk
    d = np.clip(d, 0.01, 0.99)

    # ---------------- interventions: decided from (pre-intervention) distress, then they CHANGE d ----------------
    d_obs = np.clip(d + rng.normal(0, 0.10, (n, N_MONTHS)), 0, 1)
    interv = (rng.random((n, N_MONTHS)) < sigmoid(tune["flag_intercept"] + 4.0 * d_obs)).astype(int)
    for i in np.where(interv.sum(axis=1) > 3)[0]:                     # cap: <= 3 logged interventions / account
        keep = np.where(interv[i] == 1)[0][:3]
        interv[i] = 0
        interv[i, keep] = 1
    interv_records, d = apply_interventions(rng, d, interv, accounts)

    dr = ((t - 1) / (N_MONTHS - 1)) * np.ones((n, 1))          # 0..1 time-drift ramp
    R = lambda *shape: rng.normal(0, 1, shape if shape else (n, N_MONTHS))
    shp = (n, N_MONTHS)

    # ---------------- spend path, month -10 .. 12 (23 points) ----------------
    base_seats = np.select(
        [seg == "Enterprise", seg == "Mid-Market"],
        [np.exp(rng.uniform(np.log(250), np.log(3200), n)), np.exp(rng.uniform(np.log(40), np.log(320), n))],
        np.exp(rng.uniform(np.log(4), np.log(55), n)))
    prod_price = accounts.primary_product.map({"Talent Solutions": 82, "Sales Solutions": 74,
                                               "Marketing Solutions": 66, "Learning Solutions": 48}).to_numpy()
    price = np.round(prod_price * rng.uniform(0.85, 1.25, n), 2)
    base_disc = np.select([seg == "Enterprise", seg == "Mid-Market"], [rng.uniform(14, 32, n), rng.uniform(6, 18, n)],
                          rng.uniform(0, 9, n))
    spend0 = base_seats * price * (1 - base_disc / 100.0)             # monthly spend at month -10
    # d for the 11 pre-panel months: back-cast with the month-1 level
    d_full = np.concatenate([np.repeat(d[:, :1], len(SPEND_MONTHS) - N_MONTHS, axis=1), d], axis=1)
    g = tune["growth_base"] - tune["growth_slope"] * (d_full - 0.18) + rng.normal(0, 0.012, d_full.shape)
    g[:, 0] = 0
    spend_hist = spend0[:, None] * np.exp(np.cumsum(g, axis=1))        # (n, 23)
    spend = spend_hist[:, -N_MONTHS:]                                  # months 1..12
    spend_3m_ago = spend_hist[:, -N_MONTHS - 3:-3]
    spend_trend = (spend / spend_3m_ago - 1) * 100

    discount = np.clip(base_disc[:, None] + rng.normal(0, 1.2, shp) + 4 * np.clip(d - 0.5, 0, None), 0, 40)
    seats_lic = np.maximum(1, np.round(spend / (price[:, None] * (1 - discount / 100.0))))

    # ---------------- usage / adoption ----------------
    util = np.clip(92 * (1 - 0.66 * d) + 6 * R(), 4, 100)
    seats_active = np.maximum(0, np.round(seats_lic * util / 100.0))
    active_days = np.clip(np.round(26 * (1 - 0.82 * d) + 3 * R()), 0, 30)
    sessions = np.maximum(0.2, (seats_active ** 0.72) * 0.85 * (1 - 0.72 * d) * np.exp(rng.normal(0, 0.18, shp)))
    avg_session = np.clip(23 * (1 - 0.5 * d) + 4 * R(), 3, 60)
    distinct_feat = np.clip(np.round(24 * (1 - 0.66 * d) + 3 * R()), 1, 30)
    adoption = np.clip(86 * (1 - 0.72 * d) + 7 * R(), 2, 100)
    abandon = np.clip(0.05 + 0.62 * d + 0.06 * R(), 0, 0.98)
    login_scale = 0.4 + (30 - active_days) / (active_days + 2) * 2.0 + 8 * dr * d
    last_login = np.minimum(90, np.round(rng.exponential(1.0, shp) * login_scale))
    usage_trend = np.clip(12 - 86 * d - tune["usage_drift"] * dr + 10 * R(), -95, 60)
    usage_trend = np.where((t == 1) & (rng.random(shp) < 0.30), np.nan, usage_trend)   # no trailing window yet
    engagement = np.clip(88 * (1 - 0.8 * d) + 6 * R(), 1, 100)

    # ---------------- support / technical ----------------
    size_f = np.select([seg_idx == 0, seg_idx == 1], [2.0, 1.2], 0.7)[:, None]
    tickets = rng.poisson(np.clip((1.5 + 13 * d + tune["support_drift"] * 0.05 * dr * 10) * size_f, 0.1, None))
    escal = rng.binomial(tickets, np.clip(0.04 + 0.25 * d, 0, 0.9))
    hp = rng.binomial(tickets, np.clip(0.08 + 0.35 * d, 0, 0.95))
    resolution = np.clip(np.exp(np.log(8 + 42 * d) + 0.4 * R()), 1, 240)
    csat = np.clip(4.7 - 2.4 * d + 0.35 * R(), 1, 5)
    support_fr = np.clip(10 + 55 * d + 3 * escal + tune["support_drift"] * dr + 6 * R(), 0, 100)
    tech_issues = rng.poisson(np.clip(1 + 8 * d + 1.5 * dr * tune["tech_drift"], 0.1, None))
    login_fail = rng.poisson(np.clip(0.8 + 6 * d, 0.1, None))
    tech_fr = np.clip(8 + 50 * d + 2 * tech_issues + tune["tech_drift"] * 4 * dr + 6 * R(), 0, 100)

    # ---------------- relationship ----------------
    seg_base = np.select([seg_idx == 0, seg_idx == 1], [8.0, 5.0], 2.5)[:, None]
    stakeholders = np.clip(np.round(1 + (1 - d) * seg_base + 0.8 * R()), 1, 15)
    csm_days = np.clip(np.round(rng.exponential(1.0, shp) * (12 + 80 * d)), 0, 365)
    nps = np.clip(np.round(55 - 120 * d - tune["nps_drift"] * dr + 15 * R()), -100, 100).astype(float)
    nps = np.where(rng.random(shp) < 0.12, np.nan, nps)

    def flag(p):
        return (rng.random(shp) < np.clip(p, 0, 1)).astype(int)

    exec_sponsor = flag(0.82 - 0.65 * d)
    qbr = flag((0.72 - 0.62 * d) * np.select([seg_idx == 0, seg_idx == 1], [1.0, 0.8], 0.45)[:, None])
    champion = flag(0.01 + 0.18 * d)
    layoff = flag(0.02 + 0.05 * d)
    funding = flag(np.full(shp, 0.03))
    leadership = flag(0.03 + 0.06 * d)
    price_change = flag(np.full(shp, 0.08))
    overdue = flag(0.008 + 0.14 * d ** 1.5)
    contract_auto = np.select([contract == "Monthly", contract == "Annual"], [0.88, 0.72], 0.52)[:, None]
    auto_renew = flag(np.broadcast_to(contract_auto, shp))
    pay_fail = rng.poisson(0.08 + 1.2 * d ** 2)

    upsell = ((spend_trend > 8) & (rng.random(shp) < 0.85)) | (rng.random(shp) < 0.01)
    downgrade = ((spend_trend < -6) & (rng.random(shp) < 0.85)) | (rng.random(shp) < 0.01)

    # ---------------- renewal & tenure ----------------
    r12 = rng.integers(1, 366, n)
    days_to_renewal = ((r12[:, None] - 1 + 30 * (N_MONTHS - t)) % 365) + 1
    age = age12[:, None] - (N_MONTHS - t)                       # negative => pre-signup placeholder

    # ---------------- extra driver signals (NOT model features) ----------------
    integ_depth = np.clip(70 * (1 - 0.7 * d) + 9 * R(), 0, 100)
    role_cov = np.clip(78 * (1 - 0.75 * d) + 9 * R(), 0, 100)
    train_pct = np.clip(66 * (1 - 0.6 * d) + 14 * R(), 0, 100)
    admin_eng = np.clip(74 * (1 - 0.7 * d) + 10 * R(), 0, 100)
    onboard_pct = np.clip(88 - 45 * d - 18 * (age < 6) + 9 * R(), 0, 100)
    comp_mentions = rng.poisson(np.clip(0.1 + 2.2 * d ** 1.5, 0.02, None))
    roi_score = np.clip(80 * (1 - 0.8 * d) + 9 * R(), 0, 100)

    # ---------------- churn label & intervention flag ----------------
    logit = (tune["churn_intercept"] + 9.0 * d + 0.7 * champion + 0.5 * overdue + 0.35 * layoff
             + 0.3 * (1 - exec_sponsor) - 0.4 * funding - 0.15 * qbr + 0.25 * (t >= 10)
             - 0.9 * interv + rng.normal(0, 0.9, shp))
    churned = (rng.random(shp) < sigmoid(logit)).astype(int)

    # ---------------- assemble long-format frame ----------------
    ids = np.repeat(accounts.account_id.to_numpy(), N_MONTHS)
    seq = np.tile(np.arange(1, N_MONTHS + 1), n)
    flat = lambda a: np.asarray(a).reshape(-1)
    df = pd.DataFrame({
        "account_id": ids,
        "as_of_month": np.tile(MONTH_ENDS.strftime("%Y-%m-%d").to_numpy(), n),
        "panel_month_seq": seq,
        "company_size_employees": np.repeat(accounts.company_size_employees.to_numpy(), N_MONTHS),
        "account_age_months": flat(age),
        "days_to_renewal": flat(days_to_renewal),
        "seats_licensed": flat(seats_lic).astype(int),
        "price_per_seat_usd": np.repeat(price, N_MONTHS),
        "seats_active": flat(seats_active).astype(int),
        "seat_utilization_pct": flat(np.round(util, 1)),
        "monthly_spend_usd": flat(np.round(spend, 2)),
        "spend_trend_3m_pct": flat(np.round(spend_trend, 2)),
        "discount_pct": flat(np.round(discount, 1)),
        "payment_failure_90d_count": flat(pay_fail),
        "sessions_per_week": flat(np.round(sessions, 1)),
        "avg_session_duration_min": flat(np.round(avg_session, 1)),
        "distinct_features_used": flat(distinct_feat).astype(int),
        "feature_adoption_score": flat(np.round(adoption, 1)),
        "feature_abandonment_rate_90d": flat(np.round(abandon, 3)),
        "days_since_last_login": flat(last_login).astype(int),
        "usage_trend_90d_pct": flat(np.round(usage_trend, 1)),
        "engagement_score": flat(np.round(engagement, 1)),
        "support_tickets_90d": flat(tickets),
        "escalations_90d": flat(escal),
        "high_priority_tickets_90d": flat(hp),
        "avg_resolution_time_hrs": flat(np.round(resolution, 1)),
        "csat_score": flat(np.round(csat, 2)),
        "support_friction_score": flat(np.round(support_fr, 1)),
        "technical_issue_count_90d": flat(tech_issues),
        "login_failures_90d": flat(login_fail),
        "technical_friction_score": flat(np.round(tech_fr, 1)),
        "num_active_stakeholders": flat(stakeholders).astype(int),
        "days_since_last_csm_touchpoint": flat(csm_days).astype(int),
        "nps_last_survey": flat(nps),
        "auto_renew": flat(auto_renew), "price_change_flag_90d": flat(price_change),
        "upsell_flag_90d": flat(upsell).astype(int), "downgrade_flag_90d": flat(downgrade).astype(int),
        "invoice_overdue_flag": flat(overdue), "executive_sponsor_engaged": flat(exec_sponsor),
        "qbr_attended_last_90d": flat(qbr), "champion_turnover_flag_90d": flat(champion),
        "company_layoff_flag_90d": flat(layoff), "company_funding_event_flag_90d": flat(funding),
        "leadership_change_flag_90d": flat(leadership), "intervention_triggered_flag": flat(interv),
        # extra (non-model) signals used by the Action Center driver / RFM analytics
        "active_days_30d": flat(active_days).astype(int),
        "integration_depth_score": flat(np.round(integ_depth, 1)),
        "role_coverage_pct": flat(np.round(role_cov, 1)),
        "training_completion_pct": flat(np.round(train_pct, 1)),
        "admin_engagement_score": flat(np.round(admin_eng, 1)),
        "onboarding_completion_pct": flat(np.round(onboard_pct, 1)),
        "competitor_mentions_90d": flat(comp_mentions),
        "roi_realized_score": flat(np.round(roi_score, 1)),
        "churned_within_90d": flat(churned),
    })
    # latent distress is kept ONLY for the legacy-heuristic noise below, never persisted
    return df, d, spend_hist, interv_records


def make_baseline(rng, df, d_flat):
    """Legacy heuristic: a crude weighted rule on a handful of raw columns + noise.
    Deliberately weaker than the trained model."""
    z = (0.35 * np.clip(df.days_since_last_login / 60, 0, 1)
         + 0.25 * (1 - (df.csat_score.fillna(3.5) - 1) / 4)
         + 0.20 * np.clip(df.support_tickets_90d / 20, 0, 1)
         + 0.20 * (df.invoice_overdue_flag))
    score = np.clip(100 * z * 1.25 + rng.normal(0, 9, len(df)) + 4, 0, 100).round(2)
    band = pd.cut(score, [-0.01, 25, 50, 75, 100.01], labels=["Low", "Medium", "High", "Critical"]).astype(str)
    return pd.DataFrame({
        "account_id": df.account_id.to_numpy(), "as_of_month": df.as_of_month.to_numpy(),
        "panel_month_seq": df.panel_month_seq.to_numpy(),
        "heuristic_risk_score": score, "heuristic_risk_band": band,
    })


def apply_interventions(rng, d, interv, accounts):
    """Create the intervention log and let completed interventions move the distress path.
    Wins lower d for the following months (ramped over ~2 months); failures nudge it up."""
    n = d.shape[0]
    csm = accounts.csm_owner.to_numpy()
    type_w = {"Training & Enablement Session": 0.66, "Technical / Support Health Check": 0.60,
              "Champion Re-engagement Outreach": 0.54, "Commercial Discount Review": 0.47}
    owner_skill = {c: rng.normal(0, 0.09) for c in CSM_OWNERS}
    d = d.copy()
    rows = []
    for i, p0 in zip(*np.where(interv == 1)):
        p = p0 + 1                                                    # panel_month_seq
        itype = rng.choice(INTERVENTION_TYPES, p=[0.34, 0.27, 0.26, 0.13])
        owner = csm[i]
        owner = rng.choice(CSM_OWNERS) if owner == "Unassigned" or rng.random() < 0.08 else owner
        month_end = MONTH_ENDS[p0]
        idate = month_end - pd.Timedelta(days=int(rng.integers(0, 27)))
        age_m = N_MONTHS - p
        if age_m >= 2:
            status = "Completed" if rng.random() < 0.93 else "In progress"
        elif age_m == 1:
            status = str(rng.choice(["Completed", "In progress"], p=[0.62, 0.38]))
        else:
            status = str(rng.choice(["In progress", "Scheduled"], p=[0.6, 0.4]))
        outcome = usage = days_sig = None
        if status == "Completed":
            p_win = float(np.clip(type_w[itype] + owner_skill.get(owner, 0) + 0.10 * (d[i, p0] - 0.4), 0.05, 0.95))
            u = rng.random()
            if u < p_win * 0.84:
                outcome, usage, delta = "Retained - Usage Improved", round(float(rng.uniform(6, 38)), 1), -rng.uniform(0.10, 0.24)
            elif u < p_win:
                outcome, usage, delta = "Upsell Identified", round(float(rng.uniform(10, 45)), 1), -rng.uniform(0.08, 0.18)
            elif u < p_win + (1 - p_win) * 0.72:
                outcome, usage, delta = "Retained - No Change", round(float(rng.uniform(-6, 5)), 1), rng.normal(0, 0.012)
            else:
                outcome, usage, delta = "Churned", round(float(rng.uniform(-35, -4)), 1), rng.uniform(0.04, 0.10)
            if outcome in ("Retained - Usage Improved", "Upsell Identified"):
                days_sig = int(rng.integers(7, 46))
            for k in range(p, N_MONTHS):                               # months p+1 .. 12 (0-based p ..)
                ramp = min(1.0, (k - p + 1) / 2.0)
                d[i, k] = np.clip(d[i, k] + delta * ramp, 0.01, 0.99)
        rows.append((accounts.account_id.iloc[i], month_end.strftime("%Y-%m-%d"), itype, owner,
                     idate.strftime("%Y-%m-%d"), status, outcome, usage, days_sig))
    return rows, d


def make_churn_events(rng, accounts, spend_hist, target_ttm=0.043):
    """Former customers that churned during months -10..12 (23 months).  ARR lost is
    scaled so the TTM logo-churn *ARR* rate for the latest window is `target_ttm`."""
    n_per_month = rng.poisson(10.5, len(SPEND_MONTHS))
    seg_p = [0.12, 0.34, 0.54]
    rows = []
    k = 0
    for mi, cnt in enumerate(n_per_month):
        month_end = HIST_MONTH_ENDS[mi]
        for _ in range(cnt):
            seg = rng.choice(SEGMENTS, p=seg_p)
            lo, hi = {"Enterprise": (150_000, 1_400_000), "Mid-Market": (28_000, 220_000), "SMB": (4_000, 38_000)}[seg]
            arr = float(np.exp(rng.uniform(np.log(lo), np.log(hi))))
            region = rng.choice(REGIONS, p=[0.38, 0.28, 0.24, 0.10])
            product = rng.choice(PRODUCTS, p=[0.30, 0.26, 0.26, 0.18])
            drv = rng.choice(CHURN_DRIVERS, p=CHURN_DRIVER_P)
            day = int(rng.integers(1, month_end.days_in_month + 1))
            k += 1
            rows.append((f"ACC-2{k:04d}", f"{rng.choice(NAME_PREFIX)} {rng.choice(NAME_SUFFIX)} (former)", seg, region,
                         product, month_end.replace(day=day).strftime("%Y-%m-%d"), arr, drv, mi - 10))
    ev = pd.DataFrame(rows, columns=["account_id", "company_name", "segment", "region", "primary_product",
                                     "churn_date", "arr_lost", "primary_driver", "month_index"])
    # scale ARR lost so the TTM logo-churn ARR rate of the latest window (month_index 1..12, opening = index 0)
    # equals `target_ttm`.  Opening cohort = accounts already live 12 months ago (tenure >= 13 at month 12).
    window = ev[(ev.month_index >= 1) & (ev.month_index <= 12)]
    existing = (accounts.tenure_months_at_snapshot.to_numpy() >= 13)
    opening_monitored = spend_hist[existing, SPEND_MONTHS.index(0)].sum() * 12
    # churned ARR is part of the opening ARR too:  rate = c*A / (O + c*A)  => c*A = target*O/(1-target)
    want = target_ttm * opening_monitored / (1 - target_ttm)
    scale = want / window.arr_lost.sum()
    ev["arr_lost"] = (ev.arr_lost * scale).round(2)
    return ev.drop(columns=["month_index"])


def tune_params(seed):
    return dict(decliner_share=0.17, growth_base=0.0092, growth_slope=0.052, usage_drift=3.5,
                support_drift=3.4, tech_drift=0.9, nps_drift=3.0,
                flag_intercept=-4.5, churn_intercept=-6.1)


def main(seed: int = 42, verbose: bool = True):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    tune = tune_params(seed)
    accounts, products = make_accounts(rng)
    monthly, d, spend_hist, interv_rows = make_monthly(rng, accounts, tune)
    baseline = make_baseline(rng, monthly, d.reshape(-1))
    interventions = pd.DataFrame(interv_rows, columns=[
        "account_id", "as_of_month", "intervention_type", "intervention_owner", "intervention_date",
        "intervention_status", "intervention_outcome", "usage_change_after_30d_pct", "days_to_first_signal"])
    churn_events = make_churn_events(rng, accounts, spend_hist)

    hist_rows = []
    ids = accounts.account_id.to_numpy()
    for j, mi in enumerate(SPEND_MONTHS):
        hist_rows.append(pd.DataFrame({
            "account_id": ids, "month_index": mi,
            "as_of_month": HIST_MONTH_ENDS[j].strftime("%Y-%m-%d"),
            "monthly_spend_usd": np.round(spend_hist[:, j], 2)}))
    spend_history = pd.concat(hist_rows, ignore_index=True)

    # --------- persist ---------
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    accounts.to_sql("accounts", conn, index=False)
    monthly.to_sql("account_monthly_metrics", conn, index=False)
    spend_history.to_sql("account_spend_history", conn, index=False)
    products.to_sql("account_products", conn, index=False)
    interventions.to_sql("interventions", conn, index=False)
    baseline.to_sql("baseline_benchmark", conn, index=False)
    churn_events.to_sql("churn_events", conn, index=False)
    for stmt in (
        "CREATE INDEX idx_amm_account ON account_monthly_metrics(account_id, panel_month_seq)",
        "CREATE INDEX idx_bb_account ON baseline_benchmark(account_id, panel_month_seq)",
        "CREATE INDEX idx_iv_account ON interventions(account_id)",
        "CREATE INDEX idx_ash ON account_spend_history(account_id, month_index)",
    ):
        conn.execute(stmt)
    conn.commit()
    conn.close()

    # --------- CSVs the trainer reads ---------
    full = monthly.merge(accounts[["account_id", "segment", "industry", "region", "contract_type"]], on="account_id")
    full[full.panel_month_seq <= 9].to_csv(DATA_DIR / "model_train.csv", index=False)
    full[full.panel_month_seq >= 10].to_csv(DATA_DIR / "model_holdout.csv", index=False)
    baseline.to_csv(DATA_DIR / "baseline_benchmark.csv", index=False)

    if verbose:
        tr, ho = full[full.panel_month_seq <= 9], full[full.panel_month_seq >= 10]
        print("=== Synthetic dataset written ===")
        print(f"accounts={len(accounts):,}  monthly rows={len(monthly):,}  interventions={len(interventions):,}  "
              f"churn_events={len(churn_events):,}")
        print(f"churn rate  train (m1-9)={tr.churned_within_90d.mean():.4f}   holdout (m10-12)={ho.churned_within_90d.mean():.4f}")
        print(f"intervention flag rate={monthly.intervention_triggered_flag.mean():.4f}")
        print(f"-> {DB_PATH}")
    return DB_PATH


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    main(ap.parse_args().seed)
