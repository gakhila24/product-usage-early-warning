"""
GraphRAG — Graph-Augmented Retrieval for Grounded Q&A
========================================================
Combines two pieces that already exist in this project but were never
wired together or used at query time:

  1. The narrative vector index (narratives.py -> narrative_index.pkl) --
     TF-IDF similarity search over real, per-account narrative text. This is
     the "RAG" half: it finds which accounts are semantically relevant to a
     free-text question.
  2. The account relationship graph (build_graph.py -> account_graph.graphml)
     -- real edges for OWNED_BY (account -> CSM), SAME_COHORT_AS (account ->
     same industry+segment peers), HAS_SNAPSHOT -> SCORED_AS (account ->
     risk band), and RECEIVED (account -> intervention). This is the "graph"
     half: it expands a seed account outward to the other accounts/facts an
     answer might need, which plain vector search over narratives alone
     would miss (e.g. "what's this account's CSM doing about similar
     accounts in their portfolio?" needs the OWNED_BY edge, not just text
     similarity).

Pipeline:
  question
    -> seed_accounts_from_query()   [vector search, narrative_index.pkl]
    -> expand_graph_context()       [graph traversal, account_graph.graphml]
    -> assemble_context()           [merges narrative text + graph facts +
                                      explanation-agent evidence per account]
    -> generate_answer()            [hands the assembled context to Claude;
                                      degrades gracefully to "context only,
                                      no generated answer" if no API key]

2026-10: wired into api.py's /api/dashboard/chat route (replacing the
previous flat Critical/High account-ID-list grounding) -- see api.py's own
note on that change. The retrieval + graph-expansion steps produce real,
useful, inspectable output on their own -- they do not require an LLM call
to be useful. generate_answer() always returns the full assembled context
(real, computed) even when it can't also return a generated narrative
answer, rather than failing outright when ANTHROPIC_API_KEY isn't set.

Fan-out is capped (K_SEEDS narrative seeds, a handful of cohort peers per
seed) specifically so context size stays bounded and inspectable -- this is
a documented scope cut, not an oversight. A production system would likely
rank/re-rank a larger candidate pool before truncating.
"""
import json
import os
import pickle
from pathlib import Path

import networkx as nx
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity

import mcp_tools as tools
from explanation_agent import explain_account

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GRAPH_PATH = DATA_DIR / "account_graph.graphml"
NARRATIVE_INDEX_PATH = DATA_DIR / "narrative_index.pkl"
NARRATIVES_CSV = DATA_DIR / "narratives.csv"

MAX_COHORT_PEERS_PER_SEED = 3
DEFAULT_K_SEEDS = 5

_graph_cache = None
_narrative_index_cache = None
_narrative_text_cache = None


def _load_graph() -> nx.MultiDiGraph:
    global _graph_cache
    if _graph_cache is None:
        if not GRAPH_PATH.exists():
            raise FileNotFoundError(f"{GRAPH_PATH} not found -- run build_graph.py first")
        _graph_cache = nx.read_graphml(GRAPH_PATH)
    return _graph_cache


def _load_narrative_index() -> dict:
    global _narrative_index_cache
    if _narrative_index_cache is None:
        if not NARRATIVE_INDEX_PATH.exists():
            raise FileNotFoundError(f"{NARRATIVE_INDEX_PATH} not found -- run narratives.py first")
        with open(NARRATIVE_INDEX_PATH, "rb") as f:
            _narrative_index_cache = pickle.load(f)
    return _narrative_index_cache


def _load_narrative_text() -> dict:
    global _narrative_text_cache
    if _narrative_text_cache is None:
        if not NARRATIVES_CSV.exists():
            raise FileNotFoundError(f"{NARRATIVES_CSV} not found -- run narratives.py first")
        df = pd.read_csv(NARRATIVES_CSV)
        _narrative_text_cache = dict(zip(df["account_id"], df["narrative"]))
    return _narrative_text_cache


def seed_accounts_from_query(question: str, k: int = DEFAULT_K_SEEDS) -> list[dict]:
    """Step 1 (RAG): vector search over real account narratives to find the
    accounts most semantically relevant to a free-text question."""
    index = _load_narrative_index()
    qvec = index["vectorizer"].transform([question])
    sims = cosine_similarity(qvec, index["matrix"]).flatten()
    order = sims.argsort()[::-1][:k]
    return [
        {"account_id": index["account_ids"][i], "similarity": round(float(sims[i]), 4)}
        for i in order if sims[i] > 0
    ]


def expand_graph_context(account_id: str) -> dict:
    """Step 2 (graph): traverse the real account relationship graph outward
    from a seed account -- CSM, cohort peers, current risk band, and
    intervention history. This is the half plain narrative-vector search
    alone cannot answer (e.g. "who else is this account's CSM managing?")."""
    g = _load_graph()
    node = f"account:{account_id}"
    if node not in g:
        raise tools.ToolError(f"unknown account_id: {account_id}")

    csm = None
    cohort_peers = []
    risk_band = None
    for _, target, data in g.out_edges(node, data=True):
        rel = data.get("rel")
        if rel == "OWNED_BY":
            csm = target.split(":", 1)[1]
        elif rel == "SAME_COHORT_AS":
            cohort_peers.append(target.split(":", 1)[1])
        elif rel == "HAS_SNAPSHOT":
            for _, band_node, d2 in g.out_edges(target, data=True):
                if d2.get("rel") == "SCORED_AS":
                    risk_band = band_node.split(":", 1)[1]

    portfolio_peers = []
    if csm:
        csm_node = f"csm:{csm}"
        portfolio_peers = [
            u.split(":", 1)[1] for u, v, d in g.in_edges(csm_node, data=True)
            if d.get("rel") == "OWNED_BY" and u != node
        ][:10]

    interventions = [
        dict(g.nodes[iv_node]) for _, iv_node, d in g.out_edges(node, data=True)
        if d.get("rel") == "RECEIVED"
    ]

    return {
        "account_id": account_id,
        "risk_band": risk_band,
        "csm_owner": csm,
        "cohort_peers": cohort_peers,
        "portfolio_peers_sample": portfolio_peers,
        "interventions": interventions,
    }


def assemble_context(question: str, k_seeds: int = DEFAULT_K_SEEDS) -> dict:
    """Steps 1+2 combined: seed via narrative similarity, expand each seed
    via graph traversal, and pull real narrative text + top explanation-
    agent evidence for every account in context. Cohort peers of each seed
    are pulled in at shallow depth (graph facts only, no narrative/evidence
    lookup) to keep the context bounded -- see MAX_COHORT_PEERS_PER_SEED."""
    seeds = seed_accounts_from_query(question, k=k_seeds)
    narrative_text = _load_narrative_text()

    accounts_in_context = {}
    for seed in seeds:
        acct_id = seed["account_id"]
        try:
            graph_ctx = expand_graph_context(acct_id)
        except tools.ToolError:
            continue
        try:
            evidence = explain_account(acct_id)["evidence"][:3]
        except tools.ToolError:
            evidence = []
        accounts_in_context[acct_id] = {
            "similarity_to_question": seed["similarity"],
            "narrative": narrative_text.get(acct_id, ""),
            "graph_context": graph_ctx,
            "top_evidence": evidence,
            "included_as": "narrative-similarity seed",
        }
        for peer in graph_ctx["cohort_peers"][:MAX_COHORT_PEERS_PER_SEED]:
            if peer in accounts_in_context:
                continue
            try:
                peer_graph_ctx = expand_graph_context(peer)
            except tools.ToolError:
                continue
            accounts_in_context[peer] = {
                "similarity_to_question": None,
                "narrative": narrative_text.get(peer, ""),
                "graph_context": peer_graph_ctx,
                "top_evidence": [],
                "included_as": f"cohort peer of {acct_id}",
            }

    return {"question": question, "accounts": accounts_in_context}


def generate_answer(question: str, k_seeds: int = DEFAULT_K_SEEDS) -> dict:
    """Step 3: hand the assembled, graph-expanded, narrative-grounded
    context to Claude for a natural-language answer.

    Honesty note: requires ANTHROPIC_API_KEY in your environment -- neither
    that key nor the anthropic package is available in the sandbox this
    module was built in, so the generation step has not been exercised
    end-to-end. The retrieval + graph-expansion steps above it have been
    tested against a synthetic fixture (see test_graph_rag_synthetic.py from
    the earlier delivery). If the key/package is missing, this function
    still returns the full assembled context with answer=None rather than
    failing -- the retrieval half is useful on its own."""
    context = assemble_context(question, k_seeds=k_seeds)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {**context, "answer": None,
                "_note": "ANTHROPIC_API_KEY not set -- returning retrieved context only, no generated answer."}
    try:
        import anthropic
    except ImportError:
        return {**context, "answer": None,
                "_note": "anthropic package not installed -- returning retrieved context only."}

    context_text = json.dumps(context["accounts"], indent=2, default=str)
    system_prompt = (
        "You are a churn-risk analyst assistant. Answer ONLY using the account "
        "evidence below, which was retrieved via narrative similarity search "
        "and graph traversal of real account relationships (CSM ownership, "
        "cohort membership, intervention history). Cite account IDs directly. "
        "If the evidence doesn't answer the question, say so rather than "
        "guessing. Be concise.\n\n" + context_text
    )
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-3-5-haiku-20241022", max_tokens=500,
        system=system_prompt, messages=[{"role": "user", "content": question}],
    )
    answer = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
    return {**context, "answer": answer}


if __name__ == "__main__":
    sample_q = "Which accounts are similar to ACC-30005 and what is their CSM doing about risk?"
    result = generate_answer(sample_q)
    print(json.dumps(result, indent=2, default=str))
