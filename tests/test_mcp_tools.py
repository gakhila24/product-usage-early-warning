import json
import sqlite3

import pytest

import mcp_tools as tools


def test_account_profile_and_unknown_id():
    p = tools.get_account_profile("ACC-30001")
    assert p["account_id"] == "ACC-30001" and p["company_name"]
    with pytest.raises(tools.ToolError):
        tools.get_account_profile("ACC-NOPE")


def test_history_is_chronological_and_complete():
    h = tools.get_account_history("ACC-30005", 12)
    assert [r["panel_month_seq"] for r in h] == list(range(1, 13))
    assert len(tools.get_account_history("ACC-30005", 3)) == 3


def test_summaries_have_expected_fields():
    assert {"arr_run_rate_usd", "revenue_movement_bucket"} <= set(tools.get_commercial_summary("ACC-30005"))
    assert {"csat_score", "support_friction_score"} <= set(tools.get_support_summary("ACC-30005"))
    assert {"num_active_stakeholders", "nps_last_survey"} <= set(tools.get_stakeholder_summary("ACC-30005"))
    assert "_warning" in tools.get_baseline_score("ACC-30005")


def test_list_at_risk_filters_and_ordering():
    r = tools.list_at_risk_accounts(band="Critical", limit=10)
    scores = [a["risk_score"] for a in r["accounts"]]
    assert r["total"] > 0 and scores == sorted(scores, reverse=True) and {a["risk_band"] for a in r["accounts"]} == {"Critical"}
    seg = tools.list_at_risk_accounts(segment="Enterprise", limit=5)
    assert {a["segment"] for a in seg["accounts"]} == {"Enterprise"}
    assert tools.list_at_risk_accounts(min_score=99.9, limit=5)["total"] <= tools.list_at_risk_accounts(limit=5)["total"]


def test_cohort_excludes_self():
    cohort = tools.get_cohort_accounts("ACC-30001")
    assert cohort and all(c["account_id"] != "ACC-30001" for c in cohort)


def test_log_intervention_is_the_only_write_and_is_audited(pipeline):
    before = sqlite3.connect(pipeline / "churn_data.db").execute("select count(*) from interventions").fetchone()[0]
    res = tools.log_intervention("ACC-30001", "Training & Enablement Session", "Pytest Owner")
    conn = sqlite3.connect(pipeline / "churn_data.db")
    try:
        assert res["status"] == "logged"
        assert conn.execute("select count(*) from interventions").fetchone()[0] == before + 1
        row = conn.execute("select intervention_status, intervention_outcome from interventions where intervention_owner='Pytest Owner'").fetchone()
        assert row == ("Scheduled", None)                                # NULL outcome until completed
        last = json.loads(open(tools.AUDIT_LOG_PATH).read().strip().splitlines()[-1])
        assert last["tool"] == "log_intervention" and last["caller"] == "csm_ui"
    finally:
        conn.execute("delete from interventions where intervention_owner='Pytest Owner'")
        conn.commit(); conn.close()
    with pytest.raises(tools.ToolError):
        tools.log_intervention("ACC-NOPE", "x", "y")
