# What changed in the files you sent

## Backend (`src/`)
| File | Change |
|---|---|
| `api.py` | registers the Action Center blueprint; CORS allows PUT/PATCH/DELETE; `/api/dashboard/chat` tries “dashboard guide” intents first, then GraphRAG (unchanged); warms the snapshot on start |
| `dashboard_service.py` | company names (`name`) instead of raw ids, `id/region/segment/csmOwner` in account detail, **Windows-safe renewal date formatting** (`%-d` bug) |
| `narratives.py` | narrative text now also carries risk band, payment-risk and renewal-within-90-days so chat questions like “Critical”, “payment risk”, “renewing in 90 days” can match |
| `train_model.py` | only the printed base-rate text (now computed, not hard-coded) |
| `derive_fields.py` `build_graph.py` `drift_monitor.py` `mcp_tools.py` `explanation_agent.py` `graph_rag.py` `export_*.py` | **unchanged** |
| `api_root_route_snippet.py` | already merged into `api.py`; kept in `docs/` |
| NEW | `generate_synthetic_data.py`, `run_pipeline.py`, `action_center_service.py`, `action_center_routes.py`, `ac_content/` |

## Frontend (`frontend/src/`)
| File | Change |
|---|---|
| `App.jsx` | grouped icon rail with hover labels + live badges, 19 pages, global filters, action modal, richer notifications, playbook launch also logs a real intervention |
| `Views.jsx` | account drawer gets an **Action Center** section (health band, RFM, priority, next-best action, follow-up, 5 action buttons); copy updated |
| `AccountsTable.jsx` | avatar initials, account id sub-line |
| `ChurnChat.jsx` | + 4 suggestion chips (Top priorities, Waiting on manager, Effective interventions, Explain RFM) |
| `components.jsx` | fixed garbled default text (`Loadingâ€¦` → `Loading…`) |
| `data.js` | + `downloadCsv` |
| `App.css` | your `app.css` with `App.additions.css` appended (as that file instructed) |
| `Dashboard.jsx` `Evaluation.jsx/.css` `theme.css` `index.css` `main.jsx` `index.html` | **unchanged** |
| NEW | `ActionCenter.css`, `lib/api.js` (was missing), `lib/useApi.js`, `pages/*` (19 pages + modal + filters + ui kit) |
