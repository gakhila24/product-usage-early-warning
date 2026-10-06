"""
Application / API Layer — Design Doc Section 3.5
===================================================
Environment note: the design doc specifies FastAPI. This sandbox has no
network access to install fastapi/uvicorn, so Flask (already installed) is
used instead -- same endpoint contract, same JSON shapes. Swapping frameworks
later doesn't change any of the business logic in mcp_tools.py or
explanation_agent.py; only this file's routing layer would change.

Run: python3 api.py
Then: curl http://127.0.0.1:5050/api/accounts?band=Critical&limit=5

2026-10 update #1 (reliability fix): app.run() now passes threaded=True.
Flask's dev server defaults to handling one request at a time; the React
UI fires several concurrent requests on load (summary, risk-distribution,
risk-trend, accounts, plays, recent-actions, drift, meta -- and, on the
Evaluation tab, model-performance + drift again). With threaded=False, if
any single one of those is slow, every other in-flight request queues up
behind it, which is the most likely cause of the Evaluation tab appearing
to hang indefinitely ("Not coming"). See dashboard_service.py's own
2026-10 note for the matching backend-side fix (reduced p95-latency sample
size), and frontend/src/lib/api.js's note for the matching client-side fix
(a request timeout).

2026-10 update #2: added chart-data routes under /api/dashboard/charts/*
backing the legacy static dashboard's charts, ported into the new React UI's
tabs (see dashboard_service.py's new chart functions).

2026-10 update #3: added a friendly "/" route so opening the API's URL
directly in a browser shows a helpful message instead of Flask's default
"Not Found" page.

2026-10 update #4 (this one): /api/dashboard/chat now uses graph_rag.py
instead of the flat Critical/High account-ID-list grounding it used before.
Previously, the chat endpoint only gave Claude a plain list of Critical/High
account IDs as context -- no narrative text, no relationships. Now it runs
the full GraphRAG pipeline (narrative-similarity seed accounts -> graph
traversal for CSM/cohort/intervention facts -> merged context), so questions
like "what is this account's CSM doing about similar accounts?" can actually
be answered with real relationship facts, not just a flat list. The response
shape is unchanged ({"answer": "..."}) so the existing ChurnChat.jsx frontend
needs no changes -- it still just reads `answer`. If ANTHROPIC_API_KEY isn't
set, this route now returns the retrieved context as a readable fallback
answer (a GraphRAG-assembled summary) instead of a hard 500 error -- a
genuine improvement, since the retrieval half is useful even without
generation.

2026-10 update #5: the Customer Health "Action Center" pages (follow-ups, RFM, renewals, alerts, drivers,
reports, ...) are served by action_center_routes.py (blueprint under /api/action-center) on top of
action_center_service.py. /api/dashboard/chat first tries the Action-Center "dashboard guide" intents
(top priorities, waiting on manager, explain RFM, ...) and otherwise runs GraphRAG as before.

CORS: the React dev server runs on a different origin/port (typically
:5173) than this API (:5050), so a minimal same-origin-bypassing header is
added by hand below rather than adding a new `flask-cors` dependency.
"""
import json
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, request

import mcp_tools as tools
from explanation_agent import explain_account
import dashboard_service as dash
import graph_rag
import action_center_service as action_center
from action_center_routes import bp as action_center_bp

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

app = Flask(__name__)
# Action Center pages (Customer Health dashboard tabs): /api/action-center/*
app.register_blueprint(action_center_bp)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
    return response


def error_response(e: Exception, code: int = 400):
    return jsonify({"error": str(e)}), code


# ---------------------------------------------------------------------------
# Original MCP-tool-shaped routes (unchanged contract)
# ---------------------------------------------------------------------------

@app.route("/api/accounts", methods=["GET"])
def api_list_accounts():
    try:
        result = tools.list_at_risk_accounts(
            segment=request.args.get("segment"),
            region=request.args.get("region"),
            industry=request.args.get("industry"),
            csm_owner=request.args.get("csm_owner"),
            band=request.args.get("band"),
            min_score=request.args.get("min_score", type=float),
            limit=request.args.get("limit", default=50, type=int),
            offset=request.args.get("offset", default=0, type=int),
        )
        return jsonify(result)
    except tools.ToolError as e:
        return error_response(e, 400)


@app.route("/api/accounts/<account_id>", methods=["GET"])
def api_account_profile(account_id):
    try:
        profile = tools.get_account_profile(account_id)
        score = tools.get_model_score(account_id)
        return jsonify({**profile, "current_score": score})
    except tools.ToolError as e:
        return error_response(e, 404)


@app.route("/api/accounts/<account_id>/evidence", methods=["GET"])
def api_account_evidence(account_id):
    try:
        return jsonify(explain_account(account_id))
    except tools.ToolError as e:
        return error_response(e, 404)


@app.route("/api/accounts/<account_id>/trend", methods=["GET"])
def api_account_trend(account_id):
    try:
        history = tools.get_account_history(account_id, n_months=12)
        return jsonify({"account_id": account_id, "history": history})
    except tools.ToolError as e:
        return error_response(e, 404)


@app.route("/api/interventions", methods=["GET"])
def api_list_interventions():
    conn = sqlite3.connect(DATA_DIR / "churn_data.db")
    conn.row_factory = sqlite3.Row
    where, params = [], []
    status = request.args.get("status")
    if status:
        where.append("intervention_status = ?"); params.append(status)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    cur = conn.execute(f"SELECT * FROM interventions {clause} LIMIT 200", params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({"interventions": rows})


@app.route("/api/interventions", methods=["POST"])
def api_log_intervention():
    body = request.get_json(force=True)
    try:
        result = tools.log_intervention(
            account_id=body["account_id"],
            intervention_type=body["intervention_type"],
            owner=body["owner"],
        )
        return jsonify(result), 201
    except (tools.ToolError, KeyError) as e:
        return error_response(e, 400)


@app.route("/api/metrics/model", methods=["GET"])
def api_model_metrics():
    with open(DATA_DIR / "model_metrics.json") as f:
        metrics = json.load(f)
    return jsonify(metrics)


@app.route("/api/cohort/<account_id>", methods=["GET"])
def api_cohort(account_id):
    try:
        return jsonify({"account_id": account_id, "cohort": tools.get_cohort_accounts(account_id)})
    except tools.ToolError as e:
        return error_response(e, 404)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/", methods=["GET"])
def index():
    """Friendly response for anyone who opens the API's URL directly in a
    browser, instead of Flask's default "Not Found" page. 127.0.0.1:5050 is
    the backend API, not the dashboard -- the dashboard runs separately via
    `npm run dev` in frontend/ (http://localhost:5173 by default)."""
    return jsonify({
        "service": "Churn Early-Warning API",
        "status": "running",
        "note": (
            "This is the backend API, not the dashboard. "
            "Open the dashboard at http://localhost:5173 instead "
            "(run `npm run dev` in the frontend/ folder)."
        ),
        "try_instead": [
            "/health",
            "/api/dashboard/summary",
            "/api/dashboard/accounts",
            "/api/action-center/overview",
        ],
    })


# ---------------------------------------------------------------------------
# Dashboard routes (back the React "Signal" UI in /frontend)
# ---------------------------------------------------------------------------

@app.route("/api/dashboard/summary", methods=["GET"])
def api_dashboard_summary():
    try:
        return jsonify(dash.get_summary())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/risk-distribution", methods=["GET"])
def api_dashboard_risk_distribution():
    try:
        return jsonify(dash.get_risk_distribution())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/risk-trend", methods=["GET"])
def api_dashboard_risk_trend():
    try:
        return jsonify(dash.get_risk_trend())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/accounts", methods=["GET"])
def api_dashboard_accounts():
    try:
        return jsonify(dash.get_accounts())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/accounts/<account_id>", methods=["GET"])
def api_dashboard_account_detail(account_id):
    try:
        return jsonify(dash.get_account_detail(account_id))
    except tools.ToolError as e:
        return error_response(e, 404)
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/plays", methods=["GET"])
def api_dashboard_plays():
    try:
        return jsonify(dash.get_plays())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/recent-actions", methods=["GET"])
def api_dashboard_recent_actions():
    try:
        return jsonify(dash.get_recent_actions())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/drift", methods=["GET"])
def api_dashboard_drift():
    try:
        return jsonify(dash.get_drift())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/meta", methods=["GET"])
def api_dashboard_meta():
    try:
        return jsonify(dash.get_meta())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/model-performance", methods=["GET"])
def api_dashboard_model_performance():
    try:
        return jsonify(dash.get_model_performance())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/chat", methods=["POST"])
def api_dashboard_chat():
    """Grounded Q&A over the live portfolio, using GraphRAG (see
    graph_rag.py): narrative-similarity retrieval + graph traversal +
    (optional) Claude generation.

    Honesty note: generation requires the `anthropic` package and an
    ANTHROPIC_API_KEY environment variable in *your* running environment --
    neither is available in the sandbox this project was built in, so the
    generation path has not been exercised end-to-end. Without a key, this
    route still returns a useful, real answer: a readable summary built
    directly from the retrieved narrative + graph context (not a canned
    string), so the chat widget remains useful even with no API key set.
    """
    body = request.get_json(force=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return error_response(ValueError("question is required"), 400)

    # Action-Center style questions ("top priorities", "waiting on manager", "explain RFM", ...) are answered
    # from live dashboard data first; everything else falls through to GraphRAG exactly as before.
    try:
        guide = action_center.guide_answer(question)
    except Exception:
        guide = None
    if guide:
        return jsonify({"answer": guide})

    try:
        result = graph_rag.generate_answer(question, k_seeds=body.get("k_seeds", 5))
    except FileNotFoundError as e:
        # build_graph.py / narratives.py haven't been run yet
        return error_response(e, 503)
    except Exception as e:
        return error_response(e, 500)

    if result.get("answer"):
        return jsonify({"answer": result["answer"]})

    # No ANTHROPIC_API_KEY / anthropic package -- fall back to a real,
    # computed summary of the retrieved context instead of failing outright.
    accounts = result.get("accounts", {})
    if not accounts:
        return jsonify({"answer": "I couldn't find any accounts relevant to that question in the current data."})

    lines = [f"Here's what I found for \"{question}\" (retrieved via narrative similarity + account graph traversal; set ANTHROPIC_API_KEY for a generated answer instead):"]
    for acct_id, info in accounts.items():
        ctx = info["graph_context"]
        sim_note = f" (similarity {info['similarity_to_question']})" if info.get("similarity_to_question") is not None else f" ({info['included_as']})"
        detail = f"- {acct_id}{sim_note}: risk band {ctx.get('risk_band') or 'unknown'}, CSM {ctx.get('csm_owner') or 'unknown'}"
        if ctx.get("cohort_peers"):
            detail += f", cohort peers: {', '.join(ctx['cohort_peers'][:3])}"
        if info.get("top_evidence"):
            top_signal = info["top_evidence"][0].get("signal")
            if top_signal:
                detail += f", top signal: {top_signal}"
        lines.append(detail)
    return jsonify({"answer": "\n".join(lines)})


# ---------------------------------------------------------------------------
# GraphRAG as its own endpoint (full context, not collapsed to a chat reply)
# ---------------------------------------------------------------------------

@app.route("/api/dashboard/graph-rag", methods=["POST"])
def api_dashboard_graph_rag():
    """Same GraphRAG pipeline as /api/dashboard/chat, but returns the full
    assembled context (narrative text, graph facts, evidence per account) in
    addition to the generated answer -- useful for debugging/inspecting what
    the chat widget is actually grounding on."""
    body = request.get_json(force=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return error_response(ValueError("question is required"), 400)
    try:
        result = graph_rag.generate_answer(question, k_seeds=body.get("k_seeds", 5))
        return jsonify(result)
    except FileNotFoundError as e:
        return error_response(e, 503)
    except Exception as e:
        return error_response(e, 500)


# ---------------------------------------------------------------------------
# Chart-data routes, legacy dashboard charts ported into the new UI
# ---------------------------------------------------------------------------

@app.route("/api/dashboard/charts/region-churn", methods=["GET"])
def api_chart_region_churn():
    try:
        return jsonify(dash.get_region_churn())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/charts/arr-by-band", methods=["GET"])
def api_chart_arr_by_band():
    try:
        return jsonify(dash.get_arr_by_band())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/charts/feature-importance", methods=["GET"])
def api_chart_feature_importance():
    try:
        return jsonify(dash.get_feature_importance())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/charts/risk-histogram", methods=["GET"])
def api_chart_risk_histogram():
    try:
        return jsonify(dash.get_risk_histogram())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/charts/gains", methods=["GET"])
def api_chart_gains():
    try:
        return jsonify(dash.get_gains_chart())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/charts/risk-heatmap", methods=["GET"])
def api_chart_risk_heatmap():
    try:
        return jsonify(dash.get_risk_heatmap())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/charts/boxplots", methods=["GET"])
def api_chart_boxplots():
    try:
        return jsonify(dash.get_boxplot_stats())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/charts/intervention-funnel", methods=["GET"])
def api_chart_intervention_funnel():
    try:
        return jsonify(dash.get_intervention_funnel())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/charts/csm-leaderboard", methods=["GET"])
def api_chart_csm_leaderboard():
    try:
        return jsonify(dash.get_csm_leaderboard())
    except Exception as e:
        return error_response(e, 500)


@app.route("/api/dashboard/charts/win-rate-by-type", methods=["GET"])
def api_chart_win_rate_by_type():
    try:
        return jsonify(dash.get_win_rate_by_type())
    except Exception as e:
        return error_response(e, 500)


if __name__ == "__main__":
    # threaded=True -- see the 2026-10 update #1 note above. Without this,
    # the Flask dev server handles one request at a time, and a single slow
    # endpoint blocks every other dashboard call behind it.
    try:                                   # build the Action Center snapshot once, up front (first page load is then instant)
        action_center.ensure_tables()
        action_center.snapshot()
        action_center.seed_followups_if_empty()
        action_center.alerts()
    except Exception as exc:               # pragma: no cover - API still starts; pages surface the error
        print(f"[warn] Action Center warm-up skipped: {exc}")
    app.run(host="127.0.0.1", port=5050, debug=False, threaded=True)
