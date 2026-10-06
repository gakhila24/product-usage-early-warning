import hashlib
import sqlite3

import numpy as np
import pandas as pd
import pytest


def db(pipeline):
    return sqlite3.connect(pipeline / "churn_data.db")


def test_expected_tables_and_sizes(pipeline):
    conn = db(pipeline)
    n = lambda t: conn.execute(f"select count(*) from {t}").fetchone()[0]
    assert n("accounts") == 3000
    assert n("account_monthly_metrics") == 3000 * 12
    assert n("account_monthly_metrics_enriched") == 3000 * 12
    assert n("model_scores") == 3000 * 12
    assert n("baseline_benchmark") == 3000 * 12
    assert n("account_spend_history") == 3000 * 23
    assert n("interventions") > 500 and n("churn_events") > 100
    conn.close()


def test_account_attributes(pipeline):
    a = pd.read_sql("select * from accounts", db(pipeline))
    assert a.account_id.is_unique and a.company_name.is_unique
    assert set(a.segment) == {"Enterprise", "Mid-Market", "SMB"}
    assert set(a.region) == {"NAMER", "EMEA", "APAC", "LATAM"}
    assert set(a.contract_type) == {"Monthly", "Annual", "Multi-Year"}
    assert 0.03 < (a.csm_owner == "Unassigned").mean() < 0.10          # ~94% owner coverage
    assert a.account_id.iloc[0] == "ACC-30001"


def test_monthly_panel_integrity(pipeline):
    m = pd.read_sql("select * from account_monthly_metrics", db(pipeline))
    assert m.groupby("account_id").panel_month_seq.nunique().eq(12).all()
    assert m.as_of_month.nunique() == 12 and m.as_of_month.max() == "2026-09-30"
    assert m.csat_score.between(1, 5).all()
    assert m.seat_utilization_pct.between(0, 100).all()
    assert m.days_to_renewal.between(1, 365).all()
    assert m.days_since_last_login.between(0, 90).all()
    assert set(m.churned_within_90d.unique()) == {0, 1}
    for flag in ("auto_renew", "invoice_overdue_flag", "executive_sponsor_engaged", "intervention_triggered_flag"):
        assert set(m[flag].unique()) <= {0, 1}
    assert (m.account_age_months < 0).any()                              # pre-signup placeholder rows exist (see derive_fields)
    assert m.nps_last_survey.isna().mean() > 0.05                        # genuine missing values, not zero-filled


def test_label_rates_make_a_learnable_problem(pipeline):
    m = pd.read_sql("select panel_month_seq, churned_within_90d y from account_monthly_metrics", db(pipeline))
    train, hold = m[m.panel_month_seq <= 9].y.mean(), m[m.panel_month_seq >= 10].y.mean()
    assert 0.01 < train < 0.06 and 0.02 < hold < 0.12 and hold > train


def test_intervention_log_is_consistent(pipeline):
    iv = pd.read_sql("select * from interventions", db(pipeline))
    assert set(iv.intervention_status) == {"Completed", "In progress", "Scheduled"}
    done = iv[iv.intervention_status == "Completed"]
    assert done.intervention_outcome.notna().all() and done.usage_change_after_30d_pct.notna().all()
    open_ = iv[iv.intervention_status != "Completed"]
    assert open_.intervention_outcome.isna().all()                       # no outcome until completed
    assert set(done.intervention_outcome) <= {"Retained - Usage Improved", "Upsell Identified", "Retained - No Change", "Churned"}
    assert iv.groupby("account_id").size().max() <= 3


def test_improving_interventions_actually_lower_risk(pipeline):
    """The simulated effect that makes the Effectiveness page meaningful: wins reduce later risk."""
    conn = db(pipeline)
    iv = pd.read_sql("select * from interventions where intervention_status='Completed'", conn)
    sc = pd.read_sql("select account_id, panel_month_seq p, risk_score from model_scores", conn).set_index(["account_id", "p"]).risk_score
    iv["p"] = pd.to_datetime(iv.as_of_month).dt.month.map(lambda x: ((x - 10) % 12) + 1)
    iv = iv[iv.p <= 10]
    iv["drop"] = [sc[(a, p)] - sc[(a, 12)] for a, p in zip(iv.account_id, iv.p)]
    win = iv[iv.intervention_outcome == "Retained - Usage Improved"]["drop"].mean()
    lose = iv[iv.intervention_outcome == "Churned"]["drop"].mean()
    assert win > 3 and win > lose + 8


def test_churn_events_and_spend_history(pipeline):
    conn = db(pipeline)
    ev = pd.read_sql("select * from churn_events", conn)
    assert (ev.arr_lost > 0).all() and ev.churn_date.min() >= "2024-10-01"
    sh = pd.read_sql("select * from account_spend_history", conn)
    assert sh.month_index.min() == -10 and sh.month_index.max() == 12 and (sh.monthly_spend_usd > 0).all()


def test_generator_is_deterministic(tmp_path, monkeypatch):
    import generate_synthetic_data as g
    digests = []
    for _ in range(2):
        monkeypatch.setattr(g, "DATA_DIR", tmp_path)
        monkeypatch.setattr(g, "DB_PATH", tmp_path / "churn_data.db")
        g.main(seed=7, verbose=False)
        digests.append(hashlib.sha256((tmp_path / "model_holdout.csv").read_bytes()).hexdigest())
    assert digests[0] == digests[1]
