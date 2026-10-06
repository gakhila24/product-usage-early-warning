import json
import sqlite3

import numpy as np
import pandas as pd


def conn(pipeline):
    return sqlite3.connect(pipeline / "churn_data.db")


def test_derived_fields(pipeline):
    df = pd.read_sql("select * from account_monthly_metrics_enriched", conn(pipeline))
    assert np.allclose(df.arr_run_rate_usd, (df.monthly_spend_usd * 12).round(2))
    assert set(df.revenue_movement_bucket) <= {"Churned", "Mixed", "Upsell", "Downgrade", "Flat"}
    assert (df[df.churned_within_90d == 1].revenue_movement_bucket == "Churned").all()
    assert (df[df.account_age_months < 0].age_bucket == "Pre-signup").all()
    both = df[(df.upsell_flag_90d == 1) & (df.downgrade_flag_90d == 1)]
    assert both.revenue_movement_bucket.isin(["Mixed", "Churned"]).all()


def test_model_scores_cover_every_row_and_bands_match_thresholds(pipeline):
    s = pd.read_sql("select * from model_scores", conn(pipeline))
    assert len(s) == 36000 and s.risk_score.between(0, 100).all()
    expected = pd.cut(s.risk_score / 100, [-0.01, 0.25, 0.50, 0.75, 1.01], labels=["Low", "Medium", "High", "Critical"]).astype(str)
    assert (expected == s.risk_band).mean() > 0.999
    latest = s[s.panel_month_seq == 12].risk_band.value_counts(normalize=True)
    assert latest["Low"] > 0.4 and 0.02 < latest["Critical"] < 0.2


def test_ranking_quality_gate(pipeline):
    m = json.load(open(pipeline / "model_metrics.json"))
    assert m["random_forest"]["auroc"] >= 0.75                          # the Evaluation page's release gate
    assert m["random_forest"]["auroc"] > m["heuristic_baseline"]["auroc"] + 0.05
    assert m["random_forest"]["precision_at_top_5pct"] > m["random_forest"]["precision_at_top_20pct"]


def test_feature_importance(pipeline):
    fi = pd.read_csv(pipeline / "feature_importance.csv")
    assert abs(fi.importance.sum() - 1.0) < 1e-6 and fi.importance.is_monotonic_decreasing
    assert fi.feature.iloc[0] in {"engagement_score", "seat_utilization_pct", "feature_abandonment_rate_90d", "support_friction_score", "usage_trend_90d_pct"}


def test_drift_report(pipeline):
    r = json.load(open(pipeline / "drift_report.json"))
    assert r["alertThreshold"] == 0.10 and len(r["signals"]) == 10
    assert all((s["psi"] >= 0.10) == s["alert"] for s in r["signals"])
    assert r["nFeaturesAlerting"] == sum(s["alert"] for s in r["signals"])
    assert r["detector_validation"]["accuracy"] >= 0.6                  # the drift gate


def test_psi_function_properties():
    import drift_monitor as d
    rng = np.random.default_rng(0)
    base = rng.normal(0, 1, 5000)
    assert d._psi(base, rng.normal(0, 1, 5000)) < 0.05                  # same distribution -> ~0
    assert d._psi(base, rng.normal(1.0, 1, 5000)) > 0.25                # large shift -> major
    assert d._psi(np.zeros(5), base) == 0.0                             # degenerate input is safe


def test_baseline_benchmark_table(pipeline):
    b = pd.read_sql("select * from baseline_benchmark", conn(pipeline))
    assert b.heuristic_risk_score.between(0, 100).all() and set(b.heuristic_risk_band) == {"Low", "Medium", "High", "Critical"}
