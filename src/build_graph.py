"""
Property Graph — Design Doc Section 2.3
=========================================
Built with networkx (in-process — see design doc Section 8's open decision:
3,000 accounts / ~40k nodes is small enough that a dedicated graph database
like Neo4j isn't needed; this module demonstrates the traversal queries that
justify having a graph at all, not just a flat table).

Nodes: Account, CSM, MonthlySnapshot (latest month only, to keep this demo
       graph a manageable size -- the full 12-month chain is the same
       pattern, just more NEXT edges), Intervention, RiskBand
Edges: OWNED_BY, HAS_SNAPSHOT, RECEIVED, SCORED_AS, SAME_COHORT_AS

2026-10 fix: GraphML (the output format written below) cannot serialize
Python None or numpy scalar types (numpy.bool_, numpy.int64, etc.) as node/
edge attribute values -- it raises `TypeError: GraphML does not support type
<class 'NoneType'>` (or numpy.bool_, etc.) the moment it hits one. Several
real columns genuinely contain these: interventions that are still
"Scheduled"/"In progress" have NULL intervention_outcome and NULL
usage_change_after_30d_pct (see mcp_tools.py's log_intervention -- it writes
those as SQL NULL on purpose, since there's no outcome yet), and pandas'
read_sql can return numpy scalar dtypes for boolean/int flag columns
depending on the SQLite column affinity. `_safe_attrs()` below sanitizes
every attribute dict before it's added to the graph: None values are
dropped (the attribute is simply absent from that node, which is the
correct representation of "not yet known" -- not coerced to a fake 0/""
that could be misread as a real value), and numpy scalar types are cast to
their native Python equivalents, which GraphML's writer does support.
"""
import sqlite3
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "churn_data.db"


def _safe_attrs(d: dict) -> dict:
    """Drop None values and cast numpy scalar types to native Python types,
    so every attribute dict is safe to pass as GraphML node/edge data."""
    out = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, np.bool_):
            v = bool(v)
        elif isinstance(v, np.integer):
            v = int(v)
        elif isinstance(v, np.floating):
            v = float(v)  # NaN floats serialize fine in GraphML; only None fails
        elif isinstance(v, (np.str_, pd.Timestamp)):
            v = str(v)
        out[k] = v
    return out


def build_graph() -> nx.MultiDiGraph:
    conn = sqlite3.connect(DB_PATH)
    accounts = pd.read_sql("SELECT * FROM accounts", conn)
    latest = pd.read_sql(
        "SELECT * FROM account_monthly_metrics_enriched WHERE panel_month_seq = 12", conn
    )
    scores = pd.read_sql(
        "SELECT * FROM model_scores WHERE panel_month_seq = 12", conn
    )
    interventions = pd.read_sql("SELECT * FROM interventions", conn)
    conn.close()

    g = nx.MultiDiGraph()
    for _, a in accounts.iterrows():
        g.add_node(f"account:{a.account_id}", type="Account", **_safe_attrs(a.to_dict()))
        csm_node = f"csm:{a.csm_owner}"
        if csm_node not in g:
            g.add_node(csm_node, type="CSM", name=a.csm_owner)
        g.add_edge(f"account:{a.account_id}", csm_node, rel="OWNED_BY")

    for _, m in latest.iterrows():
        snap_node = f"snapshot:{m.account_id}:{m.as_of_month}"
        g.add_node(snap_node, type="MonthlySnapshot", **_safe_attrs(m.to_dict()))
        g.add_edge(f"account:{m.account_id}", snap_node, rel="HAS_SNAPSHOT")

    for _, s in scores.iterrows():
        snap_node = f"snapshot:{s.account_id}:{s.as_of_month}"
        band_node = f"band:{s.risk_band}"
        if band_node not in g:
            g.add_node(band_node, type="RiskBand", name=s.risk_band)
        if snap_node in g:
            g.add_edge(snap_node, band_node, rel="SCORED_AS")

    for _, iv in interventions.iterrows():
        iv_node = f"intervention:{iv.account_id}:{iv.as_of_month}"
        # intervention_outcome / usage_change_after_30d_pct are genuinely
        # NULL for interventions that haven't concluded yet -- _safe_attrs
        # drops those keys rather than inventing a placeholder value.
        g.add_node(iv_node, type="Intervention", **_safe_attrs(iv.to_dict()))
        g.add_edge(f"account:{iv.account_id}", iv_node, rel="RECEIVED")

    # SAME_COHORT_AS: same industry + segment (sampled, not full O(n^2), for demo size)
    cohort_groups = accounts.groupby(["industry", "segment"])["account_id"].apply(list)
    for (_, _), ids in cohort_groups.items():
        if len(ids) < 2:
            continue
        anchor = ids[0]
        for other in ids[1:6]:  # cap fan-out for a readable demo graph
            g.add_edge(f"account:{anchor}", f"account:{other}", rel="SAME_COHORT_AS")

    return g


def demo_queries(g: nx.MultiDiGraph):
    print("=== Graph size ===")
    print(f"Nodes: {g.number_of_nodes():,}  Edges: {g.number_of_edges():,}")

    print("\n=== Demo query: CSM portfolio risk ===")
    # "accounts in a given CSM's portfolio that are Critical-band"
    sample_csm = [n for n, d in g.nodes(data=True) if d.get("type") == "CSM"][0]
    portfolio = [
        u for u, v, d in g.in_edges(sample_csm, data=True) if d.get("rel") == "OWNED_BY"
    ]
    critical_in_portfolio = []
    for acct in portfolio:
        acct_id = acct.split(":", 1)[1]
        for _, snap, d in g.out_edges(acct, data=True):
            if d.get("rel") != "HAS_SNAPSHOT":
                continue
            for _, band, d2 in g.out_edges(snap, data=True):
                if d2.get("rel") == "SCORED_AS" and band == "band:Critical":
                    critical_in_portfolio.append(acct_id)
    print(f"{sample_csm}: {len(portfolio)} accounts in portfolio, "
          f"{len(critical_in_portfolio)} in Critical band")

    print("\n=== Demo query: cohort traversal ===")
    sample_acct = portfolio[0] if portfolio else None
    if sample_acct:
        cohort = [v for _, v, d in g.out_edges(sample_acct, data=True) if d.get("rel") == "SAME_COHORT_AS"]
        print(f"{sample_acct} same-cohort peers: {cohort}")


if __name__ == "__main__":
    graph = build_graph()
    demo_queries(graph)
    nx.write_graphml(graph, DATA_DIR / "account_graph.graphml")
    print(f"\nWrote account_graph.graphml to {DATA_DIR}")
