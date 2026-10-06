"""HTTP contract of /api/action-center/*"""
import pytest

B = "/api/action-center"
GETS = ["/filters", "/overview", "/trend?grain=weekly", "/at-risk?page=2&page_size=5", "/portfolio", "/queue?risk=Poor", "/followups", "/interventions?outcome=Improved",
        "/interventions/export", "/health-scores", "/rfm?segment=Champions", "/drivers", "/renewals?horizon=180&sort=arr", "/segments", "/explorer?sort=arr&q=a",
        "/explorer/export", "/alerts?severity=Critical", "/playbooks", "/reports", "/methodology", "/faqs", "/settings", "/accounts/ACC-30001",
        "/overview?product=Sales%20Solutions&region=EMEA&segment=Enterprise&owner=Assigned"]


@pytest.mark.parametrize("path", GETS)
def test_gets_ok(client, path):
    r = client.get(B + path)
    assert r.status_code == 200, r.data[:300]


def test_csv_downloads(client):
    for p, name in (("/explorer/export", "account-records.csv"), ("/interventions/export", "intervention-effectiveness.csv")):
        r = client.get(B + p)
        assert r.mimetype == "text/csv" and name in r.headers["Content-Disposition"] and r.data.startswith(b"\xef\xbb\xbf")


def test_unknown_and_invalid_inputs(client):
    assert client.get(B + "/accounts/NOPE").status_code == 404
    assert client.patch(B + "/followups/FU-0", json={}).status_code == 404
    assert client.delete(B + "/followups/FU-0").status_code == 404
    assert client.post(B + "/alerts/AL-0/review").status_code == 404
    assert client.get(B + "/reports/RPT-0").status_code == 404
    assert client.post(B + "/followups", json={"accountId": "NOPE"}).status_code == 400
    assert client.post(B + "/playbooks/executive_roi_review/launch", json={}).status_code == 400
    assert client.post(B + "/playbooks/nope/launch", json={"accountId": "ACC-30001"}).status_code == 404
    assert client.get(B + "/overview?horizon=banana").status_code == 200                      # bad numeric input falls back to defaults
    assert client.get(B + "/at-risk?page=-5&page_size=99999").get_json()["pageSize"] == 200


def test_followup_http_flow(client, restore_action_center):
    r = client.post(B + "/followups", json={"accountId": "ACC-30010", "actionType": "request", "subject": "S", "message": "M"})
    assert r.status_code == 201
    fid = r.get_json()["id"]
    assert client.post(f"{B}/followups/{fid}/advance").get_json()["status"] == "Action committed"
    assert client.patch(f"{B}/followups/{fid}", json={"status": "bogus"}).status_code == 400
    assert client.patch(f"{B}/followups/{fid}", json={"note": "updated", "ownerRole": "CS Manager"}).get_json()["note"] == "updated"
    board = client.get(B + "/followups").get_json()
    assert any(i["id"] == fid for i in board["items"])
    assert client.get(f"{B}/followups/{fid}/events").get_json()["events"]
    assert client.delete(f"{B}/followups/{fid}").get_json() == {"deleted": fid}
    assert client.post(B + "/followups/reset").get_json()["seeded"] == 24


def test_alerts_and_settings_http(client, restore_action_center):
    open0 = client.get(B + "/alerts").get_json()["open"]
    assert client.post(B + "/alerts/review-all").get_json()["reviewed"] == open0
    assert client.get(B + "/alerts?status=open").get_json()["items"] == []
    client.post(B + "/alerts/reopen")
    assert client.put(B + "/settings", json={"include_adoption_drivers": False}).get_json()["include_adoption_drivers"] is False


def test_report_http_flow(client, restore_action_center):
    r = client.post(B + "/reports", json={"template": "renewal_review_90d", "sections": ["executive_kpis", "upcoming_renewals"], "filters": {"region": "NAMER"}})
    assert r.status_code == 201 and r.get_json()["sections"] == ["executive_kpis", "upcoming_renewals"]
    rid = r.get_json()["id"]
    d = client.get(f"{B}/reports/{rid}/download")
    assert d.status_code == 200 and d.mimetype == "text/html" and rid in d.headers["Content-Disposition"]
    assert any(x["id"] == rid for x in client.get(B + "/reports").get_json()["reports"])


def test_filters_change_results_over_http(client):
    a = client.get(B + "/overview").get_json()["kpis"][0]["value"]
    b = client.get(B + "/overview?region=LATAM").get_json()["kpis"][0]["value"]
    assert 0 < b < a
    c = client.get(B + "/queue?segment=Enterprise").get_json()["total"]
    assert c < client.get(B + "/queue").get_json()["total"]


def test_filter_options_shape(client):
    o = client.get(B + "/filters").get_json()
    assert o["products"][0] == "All Products" and o["regions"][0] == "Global" and o["segments"][0] == "All segments"
    assert o["asOf"] == "2026-09-30" and o["period"]["label"] == "Sep 1 – Sep 30, 2026" and len(o["horizons"]) == 3
