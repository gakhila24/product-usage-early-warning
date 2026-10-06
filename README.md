# Signal — Customer Health / Churn Early-Warning Dashboard

Your existing **Signal** console (Harbor teal theme, icon rail, GraphRAG chat, MCP-shaped tools, evaluation & drift) now carries
**every tab, detail and workflow of the Customer Health "Action Center v2" reference dashboard** — driven by a fully **synthetic**
dataset that flows through your real pipeline (train → score → explain → graph → narratives → API → UI).

> All data is synthetic and generated locally. Nothing here is customer data.

## Quick start (Windows)

1. Install **Python 3.10+** (tick *Add python.exe to PATH*) and **Node.js 18+ (LTS)**.
2. Double-click **`RUN_PROJECT.bat`**.
   First run: creates `.venv`, installs packages, builds the dataset + trains the models (~1 min), runs `npm install`, then opens
   **http://localhost:5173**. Later runs start in seconds.
3. Close the two console windows to stop.

Other scripts: `REBUILD_DATA.bat [seed]` (regenerate data/model — stop the API first) · `RUN_TESTS.bat` (132 backend tests).

### Manual start
```bash
python -m venv .venv && .venv\Scripts\activate        # (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python src/run_pipeline.py                              # data + models + graph + narratives + Action Center seed
python src/api.py                                       # API  -> http://127.0.0.1:5050
cd frontend && npm install && npm run dev               # UI   -> http://localhost:5173
```
Optional: `set ANTHROPIC_API_KEY=...` (and `pip install anthropic`) for *generated* chat answers. Without it the chat still answers from the
GraphRAG-retrieved context.

## What you get — 19 pages (hover the left rail to see labels)

| Group | Pages |
|---|---|
| Monitor | **Overview** (Customer health ⇄ Early-warning model) · **Portfolio** · **Accounts** (Action queue ⇄ Risk register) · **Follow-Up Monitoring** (5-stage board) · **Interventions** |
| Analyze | **Health Scores** · **RFM Analysis** · **Alerts** · **Renewals** · **Drivers** (churn + adoption) · **Segments** |
| Act | **Playbooks** (6 customer-health + 4 model-recommended) · **Reports** · **Activity log** |
| Model & data | **Evaluation** (your original page) · **Data Explorer** |
| Govern | **Source & Methodology** (42-metric dictionary) · **FAQs** · Settings |

Global filters (product, region, segment, risk level, renewal horizon, owner coverage) are applied **server-side** on every page —
numerators and denominators alike. Actions (follow-up email draft, request decision, assign playbook, escalate, create task) are
**persisted in SQLite**, move through the board, and feed the Interventions / Alerts / chat.
See `docs/PAGES_MAP.md` for page → endpoint → data-source mapping and `docs/CHANGES.md` for what changed in your files.

## How the numbers are produced (no hard-coded KPIs)

* `src/generate_synthetic_data.py` — seeded generator: 3,000 accounts × 12 monthly snapshots, spend history, interventions, churn events.
  A latent “distress” path drives every signal; completed interventions *change* later distress (so effectiveness is measurable).
* `train_model.py` (RandomForest + LogisticRegression, unchanged) → `model_scores`. **Health score = 100 − risk score.**
  Bands: Excellent 80–100 · Good 60–79 · Fair 40–59 · Poor 20–39 · Critical 0–19; at risk = health < 60.
* RFM = Recency (days since last activity) · Frequency (active days /30) · Monetary (ARR), 1–5 quintiles, Recency reversed.
* Driver impacts = share of adverse composite signals (8 churn / 8 adoption drivers) × health shortfall — *associations, not causation*.
* TTM churn & NRR come from `account_spend_history` + `churn_events` (cohort live 12 months ago).
* Dates are relative to the data-through date (**Sep 30, 2026**), so the board stays consistent whenever you open it.

Reference run (seed 42): 3,000 accounts · avg health 69 · 827 at risk (27.6%) · TTM churn 4.3% · NRR 111% ·
RF AUROC 0.86 vs legacy heuristic 0.73 · 3 of 10 features drifting · $692M synthetic ARR.

## Project layout
```
RUN_PROJECT.bat  REBUILD_DATA.bat  RUN_TESTS.bat  requirements*.txt  pytest.ini
src/        your pipeline + API (api.py, mcp_tools.py, explanation_agent.py, graph_rag.py, drift_monitor.py, ...)
            + generate_synthetic_data.py, run_pipeline.py, action_center_service.py, action_center_routes.py, ac_content/
frontend/   Vite + React 18 + Recharts (src/App.jsx, pages/*, lib/api.js, ActionCenter.css, your theme.css ...)
tests/      132 pytest tests (data, model gates, MCP tools, explanation, GraphRAG, API contracts, Action Center logic)
docs/       PAGES_MAP.md, CHANGES.md
data/       created on first run (SQLite DB, model scores, graph, narrative index)
```

## Honest notes
* The reference prototype’s sample figures (12,842 accounts, 4.2%…) are replaced by values computed from this dataset.
* The Playbook launch in the legacy flow now also **logs a real “Scheduled” intervention** through `mcp_tools.log_intervention`.
* `dashboard_service` used `strftime("%-d")`, which fails on Windows and silently blanked every renewal date — fixed.
* Chart components are Recharts (as in your files). Intervention results are observational pre/post, never causal.
* **Verification done here:** 132 backend tests pass; every API route was exercised over HTTP; every page component was server-rendered
  against real API responses and all frontend files were syntax-checked. I could **not** run `npm install` / a browser in my sandbox,
  so the first `npm run dev` on your machine is the first real browser render — if anything looks off, send me a screenshot.

## Troubleshooting
* *“Couldn’t reach the churn-scoring API”* → the API window is closed or crashed; run `RUN_PROJECT.bat` again.
* Port busy → close old windows (API 5050, UI 5173). To change the API address set `VITE_API_BASE` in `frontend/.env`.
* `PermissionError` while rebuilding data → stop the API first (it holds the SQLite file open).
* Python/Node not found → reopen the terminal after installing so PATH refreshes.
