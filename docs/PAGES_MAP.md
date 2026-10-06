# Reference tab → Signal page → API → data

| Reference tab | Signal page | Endpoint(s) (`/api/action-center/…`) | Computed from |
|---|---|---|---|
| Overview (KPIs, RFM lens, distribution, trend, drivers, actions, at-risk table, renewals, about) | Overview → *Customer health* | `/overview` `/trend` `/at-risk` | model_scores, enriched metrics, spend history, churn_events |
| *(your original overview)* | Overview → *Early-warning model* | `/api/dashboard/*` | unchanged |
| Portfolio | Portfolio | `/portfolio` | account_products (multi-product), scores, revenue |
| Accounts / Account Action Center | Accounts → *Action queue* (+ *Risk register* = your table) | `/queue` `/accounts/<id>` | priority score, RFM, drivers, follow-ups |
| Follow-Up Monitoring | Follow-Up Monitoring | `/followups` (+POST/PATCH/advance/DELETE/reset/events) | `ac_followups`, `ac_followup_events` |
| Interventions | Interventions | `/interventions` `/interventions/export` | interventions + score before/after |
| Health Scores | Health Scores | `/health-scores` | model_scores (100 − risk) |
| RFM Analysis | RFM Analysis | `/rfm` | days_since_last_login, active_days_30d, ARR |
| Alerts | Alerts | `/alerts` (+review, review-all, reopen) | month-over-month movement, renewals, support, drift |
| Renewals | Renewals | `/renewals` | days_to_renewal, ARR, health band |
| Drivers | Drivers | `/drivers` | 8 churn + 8 adoption composite indices |
| Reports | Reports | `/reports` (+POST, `/<id>/download`) | any of the above → stored + HTML download |
| Segments | Segments | `/segments` | segment × health × NRR |
| Playbooks | Playbooks | `/playbooks` `/playbooks/<id>/launch` | eligibility rules (+ your 4 model plays) |
| Data Explorer | Data Explorer | `/explorer` `/explorer/export` | account snapshot |
| Source & Methodology | Source & Methodology | `/methodology` | `src/ac_content/*.json` (42 metrics, 11 sources, 8 controls) |
| FAQs | FAQs | `/faqs` | `src/ac_content/faqs.json` |
| Settings | Settings | `/settings` | `ac_settings` |
| Dashboard Guide chatbot | Ask AI (existing widget) | `/api/dashboard/chat` | guide intents first, then your GraphRAG |
| Filters drawer / product / region / period | Global filter bar + drawer | every GET accepts `product region segment risk owner horizon` | server-side |
| Action modal (5 action types) | Account action modal | `POST /followups` | persisted; email types open a `mailto:` draft |

Original routes (`/api/accounts…`, `/api/interventions`, `/api/metrics/model`, `/api/cohort/…`, `/api/dashboard/*`, `/api/dashboard/graph-rag`) are unchanged.
