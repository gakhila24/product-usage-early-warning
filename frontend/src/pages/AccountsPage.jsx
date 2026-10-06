import { useState } from "react";
import { Download } from "lucide-react";
import { ac } from "../lib/api";
import { useApi, useDebounced } from "../lib/useApi";
import { ActionButtons, Async, ExportLink, HealthBadge, MiniStat, Pager, Panel, ScoreBar, SearchInput, Segmented, Select, nf } from "./ui";
import { Badge } from "../components";
import AccountsTable from "../AccountsTable";

const STATUS_TONE = { "Needs outreach": "danger", "Waiting on manager": "warning", "Action committed": "purple", "Monitoring impact": "purple", "Closed / validated": "success" };
const RFM_TONE = { Champions: "success", Loyal: "success", "Potential Loyalists": "purple", "Needs Attention": "neutral", "At Risk — High Value": "danger", Hibernating: "warning" };

export function QueueView({ data, onSelect, onAction, onPage }) {
  const s = data.stats;
  return <>
    <section className="panel action-hero">
      <div><span className="card-eyebrow">ACTION-READY PORTFOLIO</span><h2>Every risk signal gets an owner, a next step and a measurable outcome.</h2>
        <p>Use the account actions below to draft a manager follow-up, request a decision, and create a tracked follow-up without leaving the dashboard.</p></div>
      <div className="ac-facts three">
        <MiniStat value={nf(s.queued)} label="accounts queued" />
        <MiniStat value={s.valueLabel} label="ARR monitored" />
        <MiniStat value={nf(s.highValueAtRisk)} label="high-value accounts at risk" tone="warn" />
      </div>
    </section>
    <div className="queue-stats">
      <MiniStat value={nf(data.total)} label="visible accounts" />
      <MiniStat value={nf(s.decisionsNeeded)} label="manager decisions needed" />
      <MiniStat value={nf(s.dueThisWeek)} label="follow-ups due this week" />
      <MiniStat value={s.interventionSuccess == null ? "—" : `${s.interventionSuccess}%`} label="observed intervention success" />
    </div>
    <div className="table-scroll"><table className="ac-table queue-table">
      <thead><tr><th>Account</th><th>Health / risk</th><th>RFM segment</th><th>Renewal / value</th><th>Recommended next-best action</th><th>Follow-up status</th><th>Account actions</th></tr></thead>
      <tbody>{data.rows.map((r) => <tr key={r.id}>
        <td><button className="account-cell" onClick={() => onSelect(r.id)}><span className="acct-glyph">▦</span><span><strong>{r.name}</strong><small>{r.product} · {r.id}</small></span></button></td>
        <td><ScoreBar score={r.health} /><HealthBadge band={r.healthBand} /></td>
        <td><Badge tone={RFM_TONE[r.rfm.segment] ?? "neutral"}>{r.rfm.segment}</Badge><small className="rfm-code">R{r.rfm.r} · F{r.rfm.f} · M{r.rfm.m}</small></td>
        <td><strong className="arr-cell">{r.amount}</strong><small className="cell-sub">Renews {r.renewal}</small></td>
        <td className="nba-cell"><strong>{r.nextBestAction}</strong><small className="cell-sub">{r.why}</small><span className="priority-chip" title="Rule-based priority score">Priority {r.priority}</span></td>
        <td>{r.followup ? <><Badge tone={STATUS_TONE[r.followup.status] ?? "neutral"}>{r.followup.status}</Badge><small className="cell-sub">{r.followup.ownerRole} · due {r.followup.dueLabel}</small></> : <><Badge tone="neutral">Not started</Badge><small className="cell-sub">Suggested owner: {r.ownerRole}</small></>}</td>
        <td><ActionButtons row={r} onAction={onAction} /></td>
      </tr>)}
      {data.rows.length === 0 && <tr><td colSpan={7} className="ac-empty-row">No accounts match the current filters.</td></tr>}</tbody>
    </table></div>
    <Pager meta={data} onPage={onPage} noun="accounts" />
    <p className="ac-foot">Actions create tracked follow-up records (stored in SQLite) or open an email draft; no production CRM or mail system is connected.</p>
  </>;
}

export default function AccountsPage({ filters, onSelect, onAction, refreshKey, registerProps, onExportRegister }) {
  const [view, setView] = useState("queue");
  const [q, setQ] = useState("");
  const [level, setLevel] = useState("All risk levels");
  const [page, setPage] = useState(1);
  const dq = useDebounced(q);
  const state = useApi(() => (view === "queue" ? ac.queue(filters, { page, page_size: 6, q: dq, level: level === "All risk levels" ? "" : level }) : Promise.resolve({})),
    [JSON.stringify(filters), page, dq, level, view, refreshKey]);
  return <>
    <div className="ac-toolbar">
      <Segmented ariaLabel="Accounts view" value={view} onChange={setView} options={[{ value: "queue", label: "Action queue" }, { value: "register", label: "Risk register" }]} />
      {view === "register" && <div className="ac-tools"><button className="button" onClick={onExportRegister}><Download size={15} />Export risk register</button></div>}
      {view === "queue" && <div className="ac-tools"><SearchInput value={q} onChange={(v) => { setQ(v); setPage(1); }} placeholder="Search account, driver, action" />
        <Select label="Risk level" value={level} onChange={(v) => { setLevel(v); setPage(1); }} options={["All risk levels", "Critical", "Poor", "Fair"]} />
        <ExportLink href={ac.url("/explorer/export", { ...filters, risk: level === "All risk levels" ? "At risk" : level, q: dq })} label="Export accounts" /></div>}
    </div>
    {view === "queue"
      ? <Panel title="Account action queue" description="Prioritized from health, RFM, renewal timing and intervention history">
        <Async state={state} label="Loading action queue…">{(d) => <QueueView data={d} onSelect={onSelect} onAction={onAction} onPage={setPage} />}</Async></Panel>
      : registerProps && <AccountsTable {...registerProps} />}
  </>;
}
