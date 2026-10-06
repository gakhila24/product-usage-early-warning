import pytest

import explanation_agent as ea
import graph_rag as gr
import mcp_tools as tools


def test_router():
    assert ea.route_query("score") == "mcp_structured_tool"
    assert ea.route_query("cohort") == "graph_traversal"
    assert ea.route_query("why") == "narrative_vector_search"
    with pytest.raises(ValueError):
        ea.route_query("banana")


def test_explain_account_schema_and_ranking():
    acct = tools.list_at_risk_accounts(band="Critical", limit=1)["accounts"][0]["account_id"]
    e = ea.explain_account(acct)
    assert set(e) >= {"account_id", "risk_score", "risk_band", "lead_time_estimate_days", "evidence", "recommended_action", "baseline_comparison", "confidence"}
    w = [x["weight"] for x in e["evidence"]]
    assert len(w) == 5 and w == sorted(w, reverse=True)
    assert 10 <= e["lead_time_estimate_days"] <= 90 and 0 < e["confidence"] <= 0.95
    assert e["recommended_action"] in {"Technical / Support Health Check", "Training & Enablement Session", "Champion Re-engagement Outreach", "Commercial Discount Review"}


def test_critical_accounts_have_shorter_lead_time_than_low():
    crit = tools.list_at_risk_accounts(band="Critical", limit=1)["accounts"][0]["account_id"]
    low = tools.list_at_risk_accounts(band="Low", limit=1)["accounts"][0]["account_id"]
    assert ea.explain_account(crit)["lead_time_estimate_days"] <= ea.explain_account(low)["lead_time_estimate_days"]


def test_graph_expansion_has_csm_cohort_and_band():
    ctx = gr.expand_graph_context("ACC-30001")
    assert ctx["csm_owner"] and ctx["risk_band"] in {"Low", "Medium", "High", "Critical"}
    assert isinstance(ctx["cohort_peers"], list) and len(ctx["portfolio_peers_sample"]) <= 10
    with pytest.raises(tools.ToolError):
        gr.expand_graph_context("ACC-NOPE")


def test_seed_retrieval_uses_narrative_vocabulary():
    seeds = gr.seed_accounts_from_query("Which accounts are at Critical risk?")
    assert seeds and all(0 < s["similarity"] <= 1 for s in seeds)
    assert len(gr.seed_accounts_from_query("Critical risk", k=3)) <= 3
    assert gr.seed_accounts_from_query("zzzqqq nonsense") == []


def test_context_is_bounded_and_grounded():
    ctx = gr.assemble_context("Enterprise accounts with payment risk", k_seeds=3)
    seeds = [a for a in ctx["accounts"].values() if a["included_as"] == "narrative-similarity seed"]
    assert 0 < len(seeds) <= 3
    assert len(ctx["accounts"]) <= 3 * (1 + gr.MAX_COHORT_PEERS_PER_SEED)
    assert all(a["narrative"] for a in seeds)


def test_generate_answer_degrades_gracefully_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = gr.generate_answer("Which accounts are similar to ACC-30005?")
    assert out["answer"] is None and out["accounts"] and "ANTHROPIC_API_KEY" in out["_note"]


def test_graph_has_all_node_types():
    g = gr._load_graph()
    types = {d.get("type") for _, d in g.nodes(data=True)}
    assert {"Account", "CSM", "MonthlySnapshot", "Intervention", "RiskBand"} <= types
    rels = {d.get("rel") for _, _, d in g.edges(data=True)}
    assert {"OWNED_BY", "HAS_SNAPSHOT", "RECEIVED", "SCORED_AS", "SAME_COHORT_AS"} <= rels


def test_narratives_never_invent_facts():
    import pandas as pd
    n = pd.read_csv(gr.NARRATIVES_CSV)
    assert len(n) == 3000 and n.narrative.str.contains("risk band").all() and n.narrative.str.endswith(".").all()
