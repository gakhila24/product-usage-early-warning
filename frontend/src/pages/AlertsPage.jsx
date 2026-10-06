import { useState } from "react";
import { TriangleAlert, Check, CheckCheck, RotateCcw, TrendingDown, TrendingUp } from "lucide-react";
import { Badge } from "../components";
import { ac } from "../lib/api";
import { useApi } from "../lib/useApi";
import { Async, Panel, Segmented } from "./ui";

const SEV = { Critical: { tone: "danger", Icon: TriangleAlert }, Warning: { tone: "warning", Icon: TrendingDown }, Positive: { tone: "success", Icon: TrendingUp } };

export function AlertsView({ data, severity, onSeverity, onReview, onReviewAll, onReopen, onSelectAccount }) {
  return <>
    <div className="ac-toolbar">
      <Segmented ariaLabel="Alert severity" value={severity} onChange={onSeverity} options={[{ value: "all", label: `All (${data.total})` }, { value: "Critical", label: `Critical (${data.bySeverity.Critical})` }, { value: "Warning", label: `Warning (${data.bySeverity.Warning})` }, { value: "Positive", label: `Positive (${data.bySeverity.Positive})` }]} />
      <div className="ac-tools"><span className="ac-muted">{data.open} open · {data.total - data.open} reviewed</span>
        <button className="button" onClick={onReopen}><RotateCcw size={14} />Reopen all</button>
        <button className="button primary" disabled={data.open === 0} onClick={onReviewAll}><CheckCheck size={15} />Mark all reviewed</button></div>
    </div>
    <Panel title="Alerts" description="Prioritized changes that require owner review or intervention">
      <ul className="alert-list">{data.items.map((a) => {
        const { tone, Icon } = SEV[a.severity] ?? SEV.Warning;
        return <li key={a.id} className={`alert-item ${a.status === "reviewed" ? "reviewed" : ""}`}>
          <span className={`alert-icon ${tone}`}><Icon size={18} /></span>
          <div className="alert-body"><div className="alert-title"><strong>{a.title}</strong><Badge tone={tone}>{a.severity}</Badge><Badge tone="neutral">{a.category}</Badge></div>
            <p>{a.detail}</p><small>{a.age}{a.status === "reviewed" ? " · reviewed" : ""}</small></div>
          <div className="alert-actions">
            {a.accountId && <button className="button small" onClick={() => onSelectAccount(a.accountId)}>View account</button>}
            {a.status === "open" ? <button className="button small" onClick={() => onReview(a)}><Check size={13} />Mark reviewed</button> : <Badge tone="success">Reviewed</Badge>}
          </div></li>;
      })}</ul>
      {data.items.length === 0 && <p className="chart-empty-note">No alerts in this view.</p>}
      <p className="ac-note">"Mark reviewed" changes alert status, not the underlying risk. Alerts are computed from the latest snapshot (month-over-month movement, renewal timing, support and relationship signals).</p>
    </Panel>
  </>;
}

export default function AlertsPage({ onSelectAccount, notify, refreshCounts, bump, refreshKey }) {
  const [severity, setSeverity] = useState("all");
  const state = useApi(() => ac.alerts({ severity }), [severity, refreshKey]);
  const run = async (fn, msg) => { try { await fn(); notify(msg); bump(); refreshCounts(); } catch (e) { notify(e.message); } };
  return <Async state={state} label="Loading alerts…">{(d) => <AlertsView data={d} severity={severity} onSeverity={setSeverity} onSelectAccount={onSelectAccount}
    onReview={(a) => run(() => ac.reviewAlert(a.id), "Alert marked as reviewed.")} onReviewAll={() => run(() => ac.reviewAllAlerts(), "All alerts marked as reviewed.")} onReopen={() => run(() => ac.reopenAlerts(), "Alerts reopened.")} />}</Async>;
}
