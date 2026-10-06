"""The original /api/* routes (dashboard_service.py + api.py), via the Flask test client."""
import pytest

GETS = [
    "/", "/health", "/api/dashboard/summary", "/api/dashboard/risk-distribution", "/api/dashboard/risk-trend", "/api/dashboard/accounts",
    "/api/dashboard/plays", "/api/dashboard/recent-actions", "/api/dashboard/drift", "/api/dashboard/meta", "/api/dashboard/model-performance",
    "/api/dashboard/charts/region-churn", "/api/dashboard/charts/arr-by-band", "/api/dashboard/charts/feature-importance",
    "/api/dashboard/charts/risk-histogram", "/api/dashboard/charts/gains", "/api/dashboard/charts/risk-heatmap", "/api/dashboard/charts/boxplots",
    "/api/dashboard/charts/intervention-funnel", "/api/dashboard/charts/csm-leaderboard", "/api/dashboard/charts/win-rate-by-type",
    "/api/accounts?band=Critical&limit=3", "/api/accounts/ACC-30001", "/api/accounts/ACC-30001/evidence", "/api/accounts/ACC-30001/trend",
    "/api/cohort/ACC-30001", "/api/interventions", "/api/metrics/model",
]


@pytest.mark.parametrize("path", GETS)
def test_get_routes_ok(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.data[:200]
    assert r.is_json


def test_unknown_accounts_are_404(client):
    for p in ("/api/accounts/NOPE", "/api/accounts/NOPE/evidence", "/api/dashboard/accounts/NOPE", "/api/cohort/NOPE"):
        assert client.get(p).status_code == 404


def test_cors_headers_allow_ui_methods(client):
    h = client.get("/health").headers
    assert h["Access-Control-Allow-Origin"] == "*" and "PATCH" in h["Access-Control-Allow-Methods"]


def test_accounts_payload_matches_ui_contract(client):
    rows = client.get("/api/dashboard/accounts").get_json()
    assert len(rows) == 3000
    a = rows[0]
    for k in ("id", "name", "industry", "plan", "region", "csmOwner", "score", "band", "arr", "usage", "wow", "signal", "renewalDays", "renewal",
              "urgency", "paymentRisk", "firmographicRisk", "csat", "nps", "seatUtilizationPct", "monthlySpend", "supportTickets90d", "daysSinceCsmTouchpoint"):
        assert k in a
    assert a["name"] != a["id"]                                          # company names, not raw ids
    assert all(r["renewal"] for r in rows)                               # regression: "%-d" strftime silently blanked this on Windows
    assert {r["band"] for r in rows} == {"Critical", "High", "Medium", "Low"}


def test_account_detail_contract(client):
    d = client.get("/api/dashboard/accounts/ACC-30001").get_json()
    for k in ("name", "id", "band", "score", "signals", "usage90d", "attribution", "play", "interventionHistory", "renewal", "last30"):
        assert k in d
    assert len(d["usage90d"]) == 6 and all(0 <= s["pct"] <= 100 for s in d["signals"])


def test_summary_distribution_consistency(client):
    dist = client.get("/api/dashboard/risk-distribution").get_json()
    assert sum(d["count"] for d in dist) == 3000
    summ = {s["key"]: s for s in client.get("/api/dashboard/summary").get_json()}
    assert summ["highRisk"]["value"] == next(d["count"] for d in dist if d["band"] == "Critical")


def test_model_performance_gate(client):
    p = client.get("/api/dashboard/model-performance").get_json()
    assert p["gate"] == "passed" and p["attributionCoverage"] == 1.0 and p["p95LatencyMs"] < 500
    pe = p["playEffectiveness"]
    assert pe["churn_rate_with_play"] is not None and pe["churn_rate_with_play"] < pe["churn_rate_without_play"]


def test_gains_chart_model_beats_random(client):
    g = client.get("/api/dashboard/charts/gains").get_json()
    assert len(g["model"]) == 10 and g["model"][0]["pctChurnersCaptured"] > 0.1                 # top decile beats random (0.1)
    assert g["model"][-1]["pctChurnersCaptured"] == pytest.approx(1.0, abs=0.01)


def test_log_intervention_route_roundtrip(client, pipeline):
    import sqlite3
    r = client.post("/api/interventions", json={"account_id": "ACC-30002", "intervention_type": "Commercial Discount Review", "owner": "Pytest API"})
    assert r.status_code == 201
    try:
        rows = client.get("/api/interventions?status=Scheduled").get_json()["interventions"]
        assert any(x["intervention_owner"] == "Pytest API" for x in rows)
    finally:
        c = sqlite3.connect(pipeline / "churn_data.db"); c.execute("delete from interventions where intervention_owner='Pytest API'"); c.commit(); c.close()
    assert client.post("/api/interventions", json={"account_id": "ACC-NOPE", "intervention_type": "x", "owner": "y"}).status_code == 400
    assert client.post("/api/interventions", json={"account_id": "ACC-30002"}).status_code == 400


def test_chat_requires_question_and_falls_back_to_graph_rag(client):
    assert client.post("/api/dashboard/chat", json={}).status_code == 400
    r = client.post("/api/dashboard/chat", json={"question": "Which accounts are at Critical risk?"})
    assert r.status_code == 200 and "ACC-" in r.get_json()["answer"]
    full = client.post("/api/dashboard/graph-rag", json={"question": "Critical accounts", "k_seeds": 2}).get_json()
    assert "accounts" in full and full["answer"] is None


@pytest.mark.parametrize("q,needle", [("Top priorities", "priorit"), ("Waiting on manager", "manager"), ("Effective interventions", "interventions"), ("Explain RFM", "Recency"),
                                      ("upcoming renewals", "renewals"), ("open alerts", "alerts")])
def test_dashboard_guide_intents(client, q, needle):
    a = client.post("/api/dashboard/chat", json={"question": q}).get_json()["answer"]
    assert needle.lower() in a.lower()
