// API client for the Flask backend (src/api.py).
// 2026-10: every request has a timeout so a slow endpoint shows a readable error instead of hanging forever
// (this was the cause of the Evaluation tab appearing stuck).
const BASE = (import.meta.env && import.meta.env.VITE_API_BASE) || "http://127.0.0.1:5050";
const TIMEOUT_MS = 30000;

export const apiBase = BASE;

export function qs(params = {}) {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") p.set(k, String(v)); });
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function request(path, { method = "GET", body, timeout = TIMEOUT_MS } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  try {
    const res = await fetch(`${BASE}${path}`, {
      method,
      signal: ctrl.signal,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch { /* non-JSON body */ }
    if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
    return data;
  } catch (err) {
    if (err.name === "AbortError") throw new Error("The API took too long to respond. Check that the Flask API is running.");
    throw err;
  } finally { clearTimeout(timer); }
}

const get = (path, params) => request(`${path}${qs(params)}`);

// ---------------------------------------------------------------- original dashboard routes
export const getSummary = () => get("/api/dashboard/summary");
export const getRiskDistribution = () => get("/api/dashboard/risk-distribution");
export const getRiskTrend = () => get("/api/dashboard/risk-trend");
export const getAccounts = () => get("/api/dashboard/accounts");
export const getAccountDetail = (id) => get(`/api/dashboard/accounts/${encodeURIComponent(id)}`);
export const getPlays = () => get("/api/dashboard/plays");
export const getRecentActions = () => get("/api/dashboard/recent-actions");
export const getDrift = () => get("/api/dashboard/drift");
export const getMeta = () => get("/api/dashboard/meta");
export const getModelPerformance = () => get("/api/dashboard/model-performance", undefined);
export const postChat = (question) => request("/api/dashboard/chat", { method: "POST", body: { question }, timeout: 60000 });

export const getRegionChurn = () => get("/api/dashboard/charts/region-churn");
export const getArrByBand = () => get("/api/dashboard/charts/arr-by-band");
export const getFeatureImportance = () => get("/api/dashboard/charts/feature-importance");
export const getRiskHistogram = () => get("/api/dashboard/charts/risk-histogram");
export const getGainsChart = () => get("/api/dashboard/charts/gains");
export const getRiskHeatmap = () => get("/api/dashboard/charts/risk-heatmap");
export const getBoxplotStats = () => get("/api/dashboard/charts/boxplots");
export const getInterventionFunnel = () => get("/api/dashboard/charts/intervention-funnel");
export const getCsmLeaderboard = () => get("/api/dashboard/charts/csm-leaderboard");
export const getWinRateByType = () => get("/api/dashboard/charts/win-rate-by-type");

// MCP-shaped write path: logs a real intervention row (see mcp_tools.log_intervention)
export const logIntervention = (account_id, intervention_type, owner) =>
  request("/api/interventions", { method: "POST", body: { account_id, intervention_type, owner } });

// ---------------------------------------------------------------- Action Center routes
const AC = "/api/action-center";
export const ac = {
  filters: () => get(`${AC}/filters`),
  overview: (f) => get(`${AC}/overview`, f),
  trend: (f, grain) => get(`${AC}/trend`, { ...f, grain }),
  atRisk: (f, p) => get(`${AC}/at-risk`, { ...f, ...p }),
  portfolio: (f) => get(`${AC}/portfolio`, f),
  queue: (f, p) => get(`${AC}/queue`, { ...f, ...p }),
  account: (id) => get(`${AC}/accounts/${encodeURIComponent(id)}`),
  followups: (f, p) => get(`${AC}/followups`, { ...f, ...p }),
  createFollowup: (body) => request(`${AC}/followups`, { method: "POST", body }),
  updateFollowup: (id, body) => request(`${AC}/followups/${id}`, { method: "PATCH", body }),
  advanceFollowup: (id) => request(`${AC}/followups/${id}/advance`, { method: "POST" }),
  deleteFollowup: (id) => request(`${AC}/followups/${id}`, { method: "DELETE" }),
  resetFollowups: () => request(`${AC}/followups/reset`, { method: "POST" }),
  followupEvents: (id) => get(`${AC}/followups/${id}/events`),
  interventions: (f, p) => get(`${AC}/interventions`, { ...f, ...p }),
  healthScores: (f) => get(`${AC}/health-scores`, f),
  rfm: (f, p) => get(`${AC}/rfm`, { ...f, ...p }),
  drivers: (f) => get(`${AC}/drivers`, f),
  renewals: (f, p) => get(`${AC}/renewals`, { ...f, ...p }),
  segments: (f) => get(`${AC}/segments`, f),
  explorer: (f, p) => get(`${AC}/explorer`, { ...f, ...p }),
  alerts: (p) => get(`${AC}/alerts`, p),
  reviewAlert: (id) => request(`${AC}/alerts/${id}/review`, { method: "POST" }),
  reviewAllAlerts: () => request(`${AC}/alerts/review-all`, { method: "POST" }),
  reopenAlerts: () => request(`${AC}/alerts/reopen`, { method: "POST" }),
  playbooks: (f) => get(`${AC}/playbooks`, f),
  launchPlaybook: (pid, body) => request(`${AC}/playbooks/${pid}/launch`, { method: "POST", body }),
  reports: () => get(`${AC}/reports`),
  createReport: (body) => request(`${AC}/reports`, { method: "POST", body }),
  methodology: () => get(`${AC}/methodology`),
  faqs: () => get(`${AC}/faqs`),
  settings: () => get(`${AC}/settings`),
  saveSettings: (body) => request(`${AC}/settings`, { method: "PUT", body }),
  // plain URLs for browser downloads
  url: (path, params) => `${BASE}${AC}${path}${qs(params)}`,
};
