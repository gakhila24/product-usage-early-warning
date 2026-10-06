import { useState } from "react";
import { ArrowRight, CircleHelp, Timer, TrendingUp, Wallet } from "lucide-react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge } from "../components";
import { ac } from "../lib/api";
import { useApi } from "../lib/useApi";
import { Async, ExportLink, HBars, Info, Kpi, Pager, Panel, Select, nf } from "./ui";

const OUT_COLOR = { Improved: "#167d8d", Watch: "#d9a441", "No lift": "#c5525f", Pending: "#9aa9b0" };
const OUT_TONE = { Improved: "success", Watch: "warning", "No lift": "danger", Pending: "neutral" };

export function SlopeChart({ rows }) {
  if (!rows?.length) return <p className="chart-empty-note">No measured interventions for the current filters.</p>;
  const data = [{ x: "Baseline" }, { x: "Current" }];
  rows.forEach((r) => { data[0][r.account] = r.baseline; data[1][r.account] = r.current; });
  return <div style={{ height: 250 }}><ResponsiveContainer width="100%" height="100%">
    <LineChart data={data} margin={{ left: -10, right: 20, top: 10, bottom: 0 }}>
      <CartesianGrid strokeDasharray="3 4" vertical={false} stroke="var(--border)" />
      <XAxis dataKey="x" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "var(--muted)" }} />
      <YAxis domain={[0, 100]} axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "var(--muted)" }} />
      <Tooltip contentStyle={{ borderRadius: 10, fontSize: 12 }} />
      <Legend wrapperStyle={{ fontSize: 10 }} />
      {rows.map((r) => <Line key={r.account} type="linear" dataKey={r.account} stroke={OUT_COLOR[r.outcome]} strokeWidth={2} dot={{ r: 3 }} />)}
    </LineChart></ResponsiveContainer></div>;
}

export function InterventionsView({ data, outcome, onOutcome, onPage, onNavigate, exportHref }) {
  const s = data.summary;
  return <>
    <div className="metrics-grid ac-kpis">
      <Kpi label="Observed success rate" value={s.successRate == null ? "—" : `${s.successRate}%`} sub={`${nf(s.improved)} of ${nf(s.measured)} improved`} icon={TrendingUp} accent="green" />
      <Kpi label="Avg. health lift" value={`${s.avgLift > 0 ? "+" : ""}${s.avgLift}`} sub="post vs pre intervention" icon={TrendingUp} accent="violet" />
      <Kpi label="Value under monitoring" value={s.valueLabel ?? "$0"} sub={`${nf(s.activeWindows)} active outcome windows`} icon={Wallet} accent="amber" />
      <Kpi label="Median time to signal" value={s.medianDaysToSignal == null ? "—" : `${s.medianDaysToSignal} days`} sub="first measurable improvement" icon={Timer} accent="violet" />
    </div>
    <div className="ac-grid ac-grid-2">
      <Panel title="Health score before and after intervention" description={`Each line connects baseline to current score for one account (top ${data.slope.length} by ARR)`}><SlopeChart rows={data.slope} />
        <div className="chart-legend">{Object.entries(OUT_COLOR).slice(0, 3).map(([k, c]) => <span key={k}><i className="legend-dot" style={{ background: c }} />{k}</span>)}</div></Panel>
      <Panel title="Effectiveness by intervention type" description="Average health lift (points) and share improved">
        <HBars rows={data.byType} labelKey="type" valueKey="avgLift" color={(r) => (r.avgLift >= 0 ? "#167d8d" : "#c5525f")} signed format={(v) => `${v > 0 ? "+" : ""}${v}`} extra={(r) => `${r.successRate}% improved · n=${r.n}`} />
        <Info icon={CircleHelp}><b>Interpretation:</b> these are observational pre/post outcomes, not causal estimates. Production tracking should define eligibility, control/comparison logic, attribution windows and confounders.</Info>
      </Panel>
    </div>
    <Panel title="Intervention register" description="Baseline, current result, outcome window and next decision"
      right={<div className="ac-tools"><Select label="Outcome" value={outcome} onChange={onOutcome} options={[{ value: "all", label: "All outcomes" }, "Improved", "Watch", "No lift", "Pending"]} /><ExportLink href={exportHref} label="Export interventions" /></div>}>
      <div className="table-scroll"><table className="ac-table">
        <thead><tr><th>Account</th><th>Intervention</th><th>Started</th><th>Baseline</th><th>Current</th><th>Lift</th><th>Adoption change</th><th>Outcome</th><th>Next decision</th></tr></thead>
        <tbody>{data.register.map((x) => <tr key={x.accountId}>
          <td><strong>{x.account}</strong><small className="cell-sub">{x.owner}</small></td><td>{x.type}</td><td>{x.started}</td><td>{x.baseline ?? "—"}</td><td><b>{x.current ?? "—"}</b></td>
          <td className={x.lift > 0 ? "positive" : x.lift < 0 ? "negative" : ""}>{x.lift == null ? "—" : `${x.lift > 0 ? "+" : ""}${x.lift}`}</td>
          <td>{x.adoptionChange == null ? "—" : `${x.adoptionChange > 0 ? "+" : ""}${x.adoptionChange}`}</td>
          <td><Badge tone={OUT_TONE[x.outcome]}>{x.outcome}</Badge></td><td className="wrap-cell">{x.decision}</td></tr>)}
        {data.register.length === 0 && <tr><td colSpan={9} className="ac-empty-row">No interventions match.</td></tr>}</tbody>
      </table></div>
      <Pager meta={data} onPage={onPage} noun="interventions" />
    </Panel>
    <p className="ac-foot">{data.note} <button className="text-button inline" onClick={() => onNavigate("Follow-Up Monitoring")}>Open follow-up board <ArrowRight size={13} /></button></p>
  </>;
}

export default function InterventionsPage({ filters, onNavigate }) {
  const [outcome, setOutcome] = useState("all");
  const [page, setPage] = useState(1);
  const state = useApi(() => ac.interventions(filters, { outcome, page, page_size: 8 }), [JSON.stringify(filters), outcome, page]);
  return <Async state={state} label="Loading intervention effectiveness…">{(d) =>
    <InterventionsView data={d} outcome={outcome} onOutcome={(v) => { setOutcome(v); setPage(1); }} onPage={setPage} onNavigate={onNavigate} exportHref={ac.url("/interventions/export", filters)} />}</Async>;
}
