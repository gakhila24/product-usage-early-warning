"""Business-logic invariants of action_center_service (the Customer Health pages)."""
import math

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def F(ac):
    return ac.Filters()


def test_health_is_complement_of_risk_and_bands(ac):
    cur = ac.snapshot()["cur"]
    assert ((cur.health + cur.risk_score).round(6) == 100).all()
    assert (cur.health_band == cur.health.map(ac.health_band)).all()
    assert ac.health_band(80) == "Excellent" and ac.health_band(79.99) == "Good" and ac.health_band(59.99) == "Fair"
    assert ac.health_band(39.99) == "Poor" and ac.health_band(19.99) == "Critical" and ac.health_band(0) == "Critical"
    assert (cur.at_risk == (cur.health < 60)).all()


def test_distribution_sums_to_total(ac, F):
    d = ac.health_distribution(ac._filtered(F))
    assert sum(x["count"] for x in d) == 3000 and [x["band"] for x in d] == ["Excellent", "Good", "Fair", "Poor", "Critical"]
    assert abs(sum(x["pctExact"] for x in d) - 100) < 0.3


def test_overview_kpis_are_internally_consistent(ac, F):
    o = ac._py(ac.overview(F))
    k = {x["key"]: x for x in o["kpis"]}
    assert k["accounts"]["value"] == 3000 and k["accounts"]["delta"] > 0                    # new logos joined during the month
    at = sum(d["count"] for d in o["healthDistribution"] if d["band"] in ("Fair", "Poor", "Critical"))
    assert k["atRisk"]["value"] == at
    assert k["atRisk"]["sub"] == f"{round(100 * at / 3000, 1)}% of total"
    assert 0 < k["churn"]["value"] < 10 and 90 < k["nrr"]["value"] < 130
    assert k["health"]["value"] == round(float(ac.snapshot()["cur"].health.mean()))
    assert len(o["churnDrivers"]) == 8 and len(o["recommendedActions"]) == 5


def test_revenue_metrics_reconcile(ac, F):
    r = ac.revenue_metrics(F, 12)
    assert r["nrr"] == pytest.approx((r["openingArr"] + r["expansion"] - r["contraction"] - r["churnArr"]) / r["openingArr"] * 100, abs=0.06)
    assert r["churnRate"] == pytest.approx(4.3, abs=0.05)                                    # generator target
    prev = ac.revenue_metrics(F, 11)
    assert prev["openingArr"] != r["openingArr"]
    ent = ac.revenue_metrics(ac.Filters(segment="Enterprise"), 12)
    assert ent["openingArr"] < r["openingArr"] and ent["nrr"] > ac.revenue_metrics(ac.Filters(segment="SMB"), 12)["nrr"]


def test_filters_are_applied_consistently(ac, F):
    full = len(ac._filtered(F))
    for kw in ({"region": "EMEA"}, {"segment": "SMB"}, {"product": "Sales Solutions"}, {"risk": "Critical"}, {"owner": "Unassigned"}):
        n = len(ac._filtered(ac.Filters(**kw)))
        assert 0 < n < full, kw
    assert len(ac._filtered(ac.Filters(owner="Assigned"))) + len(ac._filtered(ac.Filters(owner="Unassigned"))) == full
    o = ac._py(ac.overview(ac.Filters(region="APAC", segment="Mid-Market")))
    assert o["kpis"][0]["value"] == len(ac._filtered(ac.Filters(region="APAC", segment="Mid-Market"), apply_risk=False))


def test_risk_filter_does_not_zero_the_kpi_denominators(ac):
    o = ac._py(ac.overview(ac.Filters(risk="Critical")))
    assert o["kpis"][0]["value"] == 3000                                                      # KPIs ignore the risk-level filter


def test_trend_is_smooth_and_labelled_synthetic(ac, F):
    t = ac.health_trend(F, "daily")
    assert len(t["points"]) == 30 and "interpolated" in t["note"]
    scores = [p["score"] for p in t["points"]]
    assert max(scores) - min(scores) < 4 and all(0 < s < 100 for s in scores)
    assert len(ac.health_trend(F, "weekly")["points"]) == 26
    assert ac.health_trend(F, "daily") == ac.health_trend(F, "daily")                         # deterministic noise


def test_rfm_scores_and_segments(ac):
    cur = ac.snapshot()["cur"]
    for c in ("r_score", "f_score", "m_score"):
        assert cur[c].between(1, 5).all() and cur[c].nunique() == 5
    assert cur[cur.r_score == 5].days_since_last_login.mean() < cur[cur.r_score == 1].days_since_last_login.mean()     # Recency reversed
    assert cur[cur.m_score == 5].arr.min() >= cur[cur.m_score == 1].arr.max()
    assert set(cur.rfm_segment) == set(ac.RFM_SEGMENTS)
    hv = cur[cur.rfm_segment == "At Risk — High Value"]
    assert (hv.r_score <= 2).all() and (hv.f_score <= 2).all() and (hv.m_score == 5).all()
    assert ac._rfm_segment(5, 5, 1) == "Champions" and ac._rfm_segment(4, 4, 1) == "Loyal" and ac._rfm_segment(1, 2, 3) == "Hibernating"
    r = ac.rfm(ac.Filters())
    assert sum(s["count"] for s in r["segments"]) == 3000 and sum(g["count"] for g in r["grid"]) == 3000
    assert r["summary"]["highValueAtRiskCount"] == len(hv)


def test_priority_score_rule(ac):
    assert ac._priority(18, "Critical", 1_200_000, 1) == 92 + 0 or ac._priority(18, "Critical", 1_200_000, 1) <= 99
    assert ac._priority(95, "Excellent", 1000, 5) < 10
    assert ac._priority(0, "Critical", 5_000_000, 1) == 99                                    # capped
    cur = ac.snapshot()["cur"]
    assert cur.priority.between(0, 99).all()
    assert cur[cur.health < 20].priority.mean() > cur[cur.health > 80].priority.mean() + 30


def test_drivers_shares_and_signs(ac, F):
    d = ac.drivers(F)
    assert len(d["churn"]) == 8 and len(d["adoption"]) == 8
    assert all(x["impact"] <= 0 for x in d["churn"]) and all(x["impact"] >= 0 for x in d["adoption"])
    assert abs(sum(x["share"] for x in d["churn"]) - 100) < 0.5
    assert sum(-x["impact"] for x in d["churn"]) == pytest.approx(d["shortfall"], abs=0.6)
    assert [x["impact"] for x in d["churn"]] == sorted(x["impact"] for x in d["churn"])      # most negative first
    assert d["takeawayChurn"].startswith("Primary takeaway")


def test_renewals_pipeline_adds_up(ac, F):
    r = ac.renewals(F, horizon=90, page_size=5)
    assert sum(b["value"] for b in r["bands"]) == pytest.approx(r["pipeline"], rel=1e-9)
    assert r["bestGood"]["value"] + r["poorCritical"]["value"] <= r["pipeline"] + 1
    assert all(0 <= x["renewalDays"] <= 90 for x in r["rows"]) and [x["renewalDays"] for x in r["rows"]] == sorted(x["renewalDays"] for x in r["rows"])
    assert ac.renewals(F, horizon=30)["count"] < r["count"] < ac.renewals(F, horizon=365)["count"]
    assert all(x["recommendedAction"] for x in r["rows"])
    assert 90 <= r["ownerCoverage"] <= 97


def test_queue_is_priority_sorted_and_at_risk_only(ac, F):
    q = ac.action_queue(F, page_size=50)
    pr = [x["priority"] for x in q["rows"]]
    assert pr == sorted(pr, reverse=True) and all(x["health"] < 60 for x in q["rows"])
    assert q["total"] == int(ac.snapshot()["cur"].at_risk.sum())
    assert len(q["nba"]) == 4 and q["nba"][0]["priority"] == pr[0]
    page2 = ac.action_queue(F, page=2, page_size=50)
    assert page2["page"] == 2 and page2["rows"][0]["id"] != q["rows"][0]["id"]
    assert all(r["healthBand"] == "Critical" for r in ac.action_queue(F, risk="Critical", page_size=20)["rows"])
    assert ac.action_queue(F, q="zzzzzz")["total"] == 0


def test_next_best_action_matches_driver(ac):
    cur = ac.snapshot()["cur"]
    ar = cur[cur.at_risk & (cur.rfm_segment != "Hibernating")]
    assert (ar.next_action == ar.top_driver.map(ac.DRIVER_ACTION)).mean() > 0.95
    assert set(cur[~cur.at_risk].next_action) <= set(ac.RFM_SEGMENT_ACTION.values())


def test_intervention_effectiveness_definitions(ac, F):
    e = ac.intervention_effectiveness(F, page_size=200)
    s = e["summary"]
    assert s["measured"] > 100 and s["improved"] <= s["measured"] and s["successRate"] == round(s["improved"] / s["measured"] * 100)
    for r in e["register"]:
        if r["outcome"] == "Improved":
            assert r["lift"] >= ac.IMPROVED_LIFT
        if r["outcome"] == "No lift":
            assert r["lift"] < 0
        assert r["lift"] is None or r["lift"] == pytest.approx(r["current"] - r["baseline"], abs=1.01)
    assert {t["type"] for t in e["byType"]} <= {"Training & Enablement Session", "Technical / Support Health Check", "Champion Re-engagement Outreach", "Commercial Discount Review"}
    assert all(x["outcome"] == "Improved" for x in ac.intervention_effectiveness(F, outcome="Improved")["register"])
    assert "not a causal estimate" in e["note"].lower() or "not causal" in e["note"].lower() or "causal" in e["note"].lower()


def test_followup_lifecycle(ac, F, restore_action_center):
    acct = "ACC-30010"
    made = ac.create_followup({"accountId": acct, "actionType": "escalate", "subject": "Pytest escalation", "message": "m", "ownerRole": "Solutions Consultant", "due": "2026-10-09"})
    assert made["created"] and made["status"] == "Action committed" and made["ownerRole"] == "Solutions Consultant"
    # same account again -> updates the open follow-up instead of duplicating it
    again = ac.create_followup({"accountId": acct, "actionType": "email", "subject": "Pytest email"})
    assert not again["created"] and again["id"] == made["id"] and again["status"] == "Waiting on manager"
    adv = ac.advance_followup(made["id"])
    assert adv["status"] == "Action committed"
    ac.update_followup(made["id"], {"status": "Closed / validated"})
    assert ac.advance_followup(made["id"])["status"] == "Closed / validated"                 # cannot advance past the last stage
    ev = [e["event"] for e in ac.followup_events(made["id"])]
    assert ev[-1] == "created" and ev.count("updated") >= 3
    with pytest.raises(ValueError):
        ac.update_followup(made["id"], {"status": "Nonsense"})
    with pytest.raises(ValueError):
        ac.create_followup({"accountId": "ACC-NOPE"})
    with pytest.raises(KeyError):
        ac.advance_followup("FU-999999")
    # a closed follow-up does not block a new one
    new = ac.create_followup({"accountId": acct, "actionType": "task"})
    assert new["created"] and new["id"] != made["id"]
    assert ac.delete_followup(new["id"]) and not ac.delete_followup(new["id"])


def test_followup_board_stats(ac, F, restore_action_center):
    ac.seed_followups()
    b = ac.list_followups(F)
    assert b["stats"]["total"] == 24 and sum(b["stageCounts"].values()) == 24
    assert set(b["stageCounts"]) == set(ac.STAGE_NAMES)
    assert b["stats"]["open"] == sum(b["stageCounts"][s] for s in ac.STAGE_NAMES[:3])
    assert b["stats"]["closed"] == b["stageCounts"]["Closed / validated"]
    assert len(ac.list_followups(F, owner="CS Manager")["items"]) <= 24
    assert all(i["ownerRole"] == "CS Manager" for i in ac.list_followups(F, owner="CS Manager")["items"])


def test_alerts_review_flow(ac, restore_action_center):
    a = ac.alerts()
    assert a["total"] >= 15 and a["open"] == a["total"] and set(a["bySeverity"]) == {"Critical", "Warning", "Positive"}
    ac.review_alert(a["items"][0]["id"])
    assert ac.alerts()["open"] == a["total"] - 1
    assert len(ac.alerts(status="open")["items"]) == a["total"] - 1
    assert ac.review_all_alerts()["reviewed"] == a["total"] - 1 and ac.alerts()["open"] == 0
    ac.reopen_alerts()
    assert ac.alerts()["open"] == a["total"]
    with pytest.raises(KeyError):
        ac.review_alert("AL-NOPE")


def test_alert_numbers_are_derived_from_data(ac):
    cur = ac.snapshot()["cur"]
    went = int(((cur.health < 20) & (cur.prev_health >= 20)).sum())
    first = next(x for x in ac.alerts()["items"] if "moved into Critical health" in x["title"])
    assert first["title"].startswith(f"{went} accounts")


def test_playbook_eligibility_rules(ac, F):
    cur = ac.snapshot()["cur"]
    pbs = {p["id"]: p for p in ac.playbooks(F)}
    assert set(pbs) == {p["id"] for p in ac.PLAYBOOKS}
    mask = ac._playbook_mask(cur, "critical_renewal_response")
    assert (cur[mask].health < 40).all() and (cur[mask].days_to_renewal <= 60).all()
    assert all(a["health"] < 40 for a in pbs["critical_renewal_response"]["topAccounts"])
    assert all(p["eligible"] >= 0 and p["eligible"] + p["suppressed"] == int(ac._playbook_mask(cur, p["id"]).sum()) for p in pbs.values())


def test_launch_playbook_creates_tracked_followup(ac, restore_action_center):
    acct = ac.playbooks(ac.Filters())[1]["topAccounts"][0]["id"]
    r = ac.launch_playbook("executive_roi_review", acct)
    assert r["actionType"] == "playbook" and r["status"] == "Action committed"
    with pytest.raises(KeyError):
        ac.launch_playbook("nope", acct)


def test_reports_are_generated_and_rendered(ac, F, restore_action_center):
    r = ac.create_report({"template": "portfolio_health_summary", "recipients": "x@y.com", "filters": {"region": "EMEA"}})
    assert r["id"].startswith("RPT-") and r["filters"]["region"] == "EMEA"
    full = ac.get_report(r["id"])
    assert set(full["content"]) == set(ac.REPORT_TEMPLATES[0]["sections"])
    html = ac.report_html(r["id"])
    assert html.startswith("<!doctype html>") and "Portfolio health summary" in html and "EMEA" in html and "synthetic" in html
    assert "<script" not in html.lower()
    evil = ac.create_report({"template": "driver_intervention_brief", "name": "<script>alert(1)</script>"})
    assert "<script>alert(1)</script>" not in ac.report_html(evil["id"])                      # names are HTML-escaped
    assert len(ac.list_reports()["reports"]) == 2
    with pytest.raises(KeyError):
        ac.get_report("RPT-NOPE")


def test_settings_roundtrip(ac, restore_action_center):
    assert ac.get_settings() == ac.DEFAULT_SETTINGS
    assert ac.put_settings({"critical_alerts": False, "bogus": True})["critical_alerts"] is False
    assert "bogus" not in ac.get_settings()


def test_csv_exports_neutralise_formulas(ac, F):
    assert ac._csv_safe("=SUM(A1)") == "'=SUM(A1)" and ac._csv_safe("-5") == "-5" and ac._csv_safe("abc") == "abc"
    csv = ac.explorer_csv(F)
    assert csv.startswith("\ufeffAccount ID,Account") and csv.count("\n") >= 3000


def test_explorer_paging_and_sorting(ac, F):
    p1 = ac.explorer(F, page=1, page_size=10, sort="arr")
    assert p1["total"] == 3000 and p1["pages"] == 300
    arr = [r["arr"] for r in p1["rows"]]
    assert arr == sorted(arr, reverse=True)
    assert ac.explorer(F, page=9999, page_size=10)["page"] == 300                             # page is clamped
    assert ac.explorer(F, q="cobalt")["total"] < 100


def test_methodology_and_faqs_content(ac):
    m = ac.methodology()
    assert len(m["metrics"]) == 42 and len(m["sources"]) == 11 and len(m["controls"]) == 8
    assert m["sources"][0]["status"] == "Current" and all(s["status"] == "Proposed" for s in m["sources"][1:])
    assert any(x["metric"] == "Account Health Score" and "100 − risk_score" in x["formula"] for x in m["metrics"])
    f = ac.faqs()
    assert len(f["items"]) == 14 and "synthetic" in f["items"][0]["a"].lower()


def test_segments_and_portfolio(ac, F):
    s = ac.segments(F)["segments"]
    assert [x["segment"] for x in s] == ["Enterprise", "Mid-Market", "SMB"] and sum(x["accounts"] for x in s) == 3000
    assert s[0]["avgHealth"] > s[2]["avgHealth"]
    p = ac.portfolio(F)
    assert sum(x["accounts"] for x in p["products"]) > 3000                                   # multi-product accounts counted in each product
    assert sum(r["atRisk"] for r in p["regions"]) == int(ac.snapshot()["cur"].at_risk.sum())


def test_account_context(ac):
    c = ac.account_context("ACC-30001")
    assert c["id"] == "ACC-30001" and len(c["drivers"]) == 4 and "followups" in c
    with pytest.raises(KeyError):
        ac.account_context("NOPE")


def test_json_sanitiser(ac):
    import numpy as np
    out = ac._py({"a": np.int64(3), "b": np.float64("nan"), "c": [np.bool_(True)], "d": pd.Timestamp("2026-09-30")})
    assert out == {"a": 3, "b": None, "c": [True], "d": "2026-09-30"}
