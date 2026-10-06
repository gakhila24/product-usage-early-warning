import { useState } from "react";
import { CalendarClock, ShieldAlert, ShieldCheck, Timer, Users } from "lucide-react";
import { ac } from "../lib/api";
import { useApi } from "../lib/useApi";
import { Async, HealthBadge, Kpi, Pager, Panel, Select, nf } from "./ui";
import { downloadCsv } from "../data";

const BAND_COLOR = { Excellent: "#167d8d", Good: "#73b6bc", Fair: "#e4bf83", "Poor / Critical": "#c5525f" };

export function RenewalsView({ data, horizon, onHorizon, sort, onSort, onPage, onAction, onSelect, onExport }) {
  const d = data.ownerCoverageDelta;
  return <>
    <div className="ac-toolbar">
      <Select label="Renewal horizon" value={horizon} onChange={onHorizon} options={[{ value: "30", label: "Next 30 days" }, { value: "60", label: "Next 60 days" }, { value: "90", label: "Next 90 days" }, { value: "180", label: "Next 180 days" }, { value: "365", label: "Next 365 days" }]} />
      <div className="ac-tools"><Select label="Sort" value={sort} onChange={onSort} options={[{ value: "days", label: "Soonest first" }, { value: "arr", label: "Highest value first" }]} />
        <button className="button" onClick={onExport}>Export renewals</button></div>
    </div>
    <div className="metrics-grid ac-kpis five">
      <Kpi label={`${data.horizon}-Day Pipeline`} value={data.pipelineLabel} sub={`${nf(data.count)} renewals`} icon={CalendarClock} accent="violet" />
      <Kpi label="Poor / Critical" value={data.poorCritical.label} sub={`${data.poorCritical.pct}% of pipeline`} icon={ShieldAlert} accent="red" />
      <Kpi label="Best / Good" value={data.bestGood.label} sub={`${data.bestGood.pct}% of pipeline`} icon={ShieldCheck} accent="green" />
      <Kpi label="Avg. Days to Renewal" value={data.avgDays} sub="Across active queue" icon={Timer} accent="amber" />
      <Kpi label="Owner Coverage" value={`${data.ownerCoverage}%`} sub="Renewals with an assigned owner" delta={d} deltaLabel="pp vs last month" tone={d >= 0 ? "positive" : "negative"} icon={Users} accent="violet" />
    </div>
    <Panel title="Pipeline by health band" description="Renewal ARR assigned to the latest health band of each account">
      <div className="stack-bar big">{data.bands.map((b) => <span key={b.band} style={{ width: `${b.pct}%`, background: BAND_COLOR[b.band] }} title={`${b.band}: ${b.label}`} />)}</div>
      <div className="ren-bands inline">{data.bands.map((b) => <div key={b.band}><i style={{ background: BAND_COLOR[b.band] }} /><span>{b.band === "Excellent" ? "Excellent (80–100)" : b.band === "Good" ? "Good (60–79)" : b.band === "Fair" ? "Fair (40–59)" : "Poor / Critical (0–39)"}</span><strong>{b.label}</strong><small>{b.pct}%</small></div>)}</div>
    </Panel>
    <Panel title="Upcoming renewals" description="Account, health exposure, top driver and recommended action">
      <div className="table-scroll"><table className="ac-table">
        <thead><tr><th>Account</th><th>Renewal Date</th><th>Days</th><th>Health</th><th>Top Driver</th><th>Amount</th><th>Recommended action</th><th>Follow-up</th></tr></thead>
        <tbody>{data.rows.map((r) => <tr key={r.id}>
          <td><button className="account-cell" onClick={() => onSelect(r.id)}><span className="acct-glyph">▦</span><span><strong>{r.name}</strong><small>{r.product}</small></span></button></td>
          <td>{r.renewal}</td><td>{r.renewalDays}</td><td><div className="health-cell"><b>{r.health}</b><HealthBadge band={r.healthBand} /></div></td>
          <td>{r.topDriver}</td><td className="arr-cell">{r.amount}</td><td className="wrap-cell">{r.recommendedAction}</td>
          <td><button className="button small" onClick={() => onAction(r, r.followup ? "task" : "email")}>{r.followup ? r.followup.status : "Follow up"}</button></td></tr>)}
        {data.rows.length === 0 && <tr><td colSpan={8} className="ac-empty-row">No renewals in this horizon for the current filters.</td></tr>}</tbody>
      </table></div>
      <Pager meta={data} onPage={onPage} noun="renewals" />
    </Panel>
  </>;
}

export default function RenewalsPage({ filters, onSelect, onAction, refreshKey }) {
  const [horizon, setHorizon] = useState(String(filters.horizon ?? 90));
  const [sort, setSort] = useState("days");
  const [page, setPage] = useState(1);
  const state = useApi(() => ac.renewals(filters, { horizon, sort, page, page_size: 8 }), [JSON.stringify(filters), horizon, sort, page, refreshKey]);
  const exportRows = async () => {
    const all = await ac.renewals(filters, { horizon, sort, page: 1, page_size: 200 });
    downloadCsv("renewals.csv", ["Account", "Renewal date", "Days", "Health", "Risk level", "Top driver", "ARR (USD)", "Recommended action"],
      all.rows.map((r) => [r.name, r.renewal, r.renewalDays, r.health, r.healthBand, r.topDriver, Math.round(r.arr), r.recommendedAction]));
  };
  return <Async state={state} label="Loading renewals…">{(d) => <RenewalsView data={d} horizon={horizon} onHorizon={(v) => { setHorizon(v); setPage(1); }} sort={sort} onSort={(v) => { setSort(v); setPage(1); }}
    onPage={setPage} onAction={onAction} onSelect={onSelect} onExport={exportRows} />}</Async>;
}
