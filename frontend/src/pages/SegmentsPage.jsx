import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ac } from "../lib/api";
import { useApi } from "../lib/useApi";
import { Async, MiniStat, Panel, nf } from "./ui";

export function SegmentsView({ data }) {
  const chart = data.segments.map((s) => ({ segment: s.segment, "At risk %": s.atRiskPct, "Avg health": s.avgHealth }));
  return <>
    <div className="ac-grid ac-grid-3">{data.segments.map((s) => <section className="panel segment-card" key={s.segment}>
      <h2>{s.segment}</h2><small>{s.arrLabel} ARR</small>
      <div className="seg-stats">
        <MiniStat value={nf(s.accounts)} label="Accounts" /><MiniStat value={s.avgHealth} label="Avg. health" />
        <MiniStat value={`${s.atRiskPct}%`} label="At risk" tone={s.atRiskPct >= 25 ? "warn" : ""} /><MiniStat value={s.nrr == null ? "—" : `${s.nrr}%`} label="NRR" />
      </div></section>)}</div>
    <Panel title="Segment comparison" description="Average health and share of accounts at risk (health below 60)">
      <div style={{ height: 260 }}><ResponsiveContainer width="100%" height="100%">
        <BarChart data={chart} margin={{ left: -10, right: 15, top: 8, bottom: 0 }} barGap={6}>
          <CartesianGrid strokeDasharray="3 4" vertical={false} stroke="var(--border)" />
          <XAxis dataKey="segment" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "var(--muted)" }} />
          <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "var(--muted)" }} />
          <Tooltip contentStyle={{ borderRadius: 10, fontSize: 12 }} />
          <Bar dataKey="Avg health" fill="#167d8d" radius={[4, 4, 0, 0]} /><Bar dataKey="At risk %" fill="#c5525f" radius={[4, 4, 0, 0]} />
        </BarChart></ResponsiveContainer></div>
    </Panel>
  </>;
}

export default function SegmentsPage({ filters }) {
  const state = useApi(() => ac.segments(filters), [JSON.stringify(filters)]);
  return <Async state={state} label="Loading segments…">{(d) => <SegmentsView data={d} />}</Async>;
}
