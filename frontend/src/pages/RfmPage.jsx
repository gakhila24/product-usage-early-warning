import { useState } from "react";
import { Activity, CalendarClock, DollarSign, ShieldAlert } from "lucide-react";
import { Cell, CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { Badge } from "../components";
import { ac } from "../lib/api";
import { useApi, useDebounced } from "../lib/useApi";
import { Async, ExportLink, HBars, HealthBadge, Info, Kpi, Pager, Panel, SearchInput, Select, nf } from "./ui";

export const RFM_COLORS = { Champions: "#167d8d", Loyal: "#4a9ca8", "Potential Loyalists": "#73b6bc", "Needs Attention": "#9aa9b0", "At Risk — High Value": "#c5525f", Hibernating: "#d9a441" };
const RFM_TONE = { Champions: "success", Loyal: "success", "Potential Loyalists": "purple", "Needs Attention": "neutral", "At Risk — High Value": "danger", Hibernating: "warning" };

function BubbleTip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return <div className="chart-tip"><b>R{p.r} · F{p.f}</b><span>{nf(p.count)} accounts · {p.arrLabel} ARR</span><span>Avg health {p.avgHealth} · {p.segment}</span></div>;
}

export function RfmMap({ grid }) {
  return <div style={{ height: 300 }}><ResponsiveContainer width="100%" height="100%">
    <ScatterChart margin={{ left: -6, right: 20, top: 10, bottom: 14 }}>
      <CartesianGrid strokeDasharray="3 4" stroke="var(--border)" />
      <XAxis type="number" dataKey="r" domain={[0.4, 5.6]} ticks={[1, 2, 3, 4, 5]} tick={{ fontSize: 11, fill: "var(--muted)" }} label={{ value: "Recency score (5 = most recent)", position: "insideBottom", offset: -8, fontSize: 11, fill: "var(--muted)" }} />
      <YAxis type="number" dataKey="f" domain={[0.4, 5.6]} ticks={[1, 2, 3, 4, 5]} tick={{ fontSize: 11, fill: "var(--muted)" }} label={{ value: "Frequency score", angle: -90, position: "insideLeft", offset: 12, fontSize: 11, fill: "var(--muted)" }} />
      <ZAxis type="number" dataKey="arr" range={[120, 2400]} />
      <Tooltip content={<BubbleTip />} cursor={{ strokeDasharray: "3 3" }} />
      <Scatter data={grid} fillOpacity={0.78}>{grid.map((g) => <Cell key={`${g.r}-${g.f}`} fill={RFM_COLORS[g.segment] ?? "#9aa9b0"} />)}</Scatter>
    </ScatterChart></ResponsiveContainer></div>;
}

export function RfmView({ data, segment, onSegment, q, onQ, onPage, exportHref, onSelect }) {
  const s = data.summary;
  return <>
    <Info icon={Activity}><b>Source-aware, synthetic view.</b> Values are synthetic. The production design uses the latest qualifying product activity for Recency, distinct active days from product telemetry for Frequency, and Finance-approved account ARR from contract and billing data for Monetary.</Info>
    <div className="metrics-grid ac-kpis">
      <Kpi label="Average Recency" value={s.avgRecency} unit=" days" sub="Lower is more recent" icon={CalendarClock} accent="violet" />
      <Kpi label="Average Frequency" value={s.avgFrequency} unit=" /30" sub="Active days, qualifying product activity" icon={Activity} accent="violet" />
      <Kpi label="Portfolio Monetary Value" value={s.monetaryLabel} sub="Synthetic ARR total" icon={DollarSign} accent="green" />
      <Kpi label="High-Value At Risk" value={s.highValueAtRiskLabel} sub={`${nf(s.highValueAtRiskCount)} accounts · R/F ≤ 2, M = 5`} icon={ShieldAlert} accent="red" />
    </div>
    <div className="rfm-defs">{data.definitions.map((d) => <section className="panel rfm-def" key={d.k}><h3>{d.k}</h3><p>{d.v}</p><small>{d.src}</small></section>)}</div>
    <div className="ac-grid ac-grid-2">
      <Panel title="Recency × Frequency map" description="Bubble area represents Monetary value; upper-right is strongest engagement">
        <RfmMap grid={data.grid} />
        <div className="chart-legend wrap">{Object.entries(RFM_COLORS).map(([k, c]) => <span key={k}><i className="legend-dot" style={{ background: c }} />{k}</span>)}</div>
      </Panel>
      <Panel title="RFM segment distribution" description="Actionable groupings from the composite score rules below">
        <HBars rows={data.segments} labelKey="segment" valueKey="count" color={(r) => RFM_COLORS[r.segment]} format={(v) => nf(v)} extra={(r) => `${r.arrLabel} · health ${r.avgHealth}`} />
        <Info icon={ShieldAlert} tone="warn"><b>Priority:</b> {data.priorityNote}</Info>
      </Panel>
    </div>
    <Panel title="Account-level RFM detail" description={`${nf(data.total)} records`}
      right={<div className="ac-tools"><SearchInput value={q} onChange={onQ} placeholder="Search account" />
        <Select label="RFM segment" value={segment} onChange={onSegment} options={[{ value: "all", label: "All RFM segments" }, ...Object.keys(RFM_COLORS)]} /><ExportLink href={exportHref} label="Export RFM" /></div>}>
      <div className="table-scroll"><table className="ac-table">
        <thead><tr><th>Account</th><th>Recency</th><th>Frequency</th><th>Monetary</th><th>R / F / M</th><th>RFM score</th><th>Segment</th><th>Health</th><th>Recommended action</th></tr></thead>
        <tbody>{data.rows.map((r) => <tr key={r.id}>
          <td><button className="account-cell" onClick={() => onSelect(r.id)}><span className="acct-glyph">▦</span><span><strong>{r.name}</strong><small>{r.product}</small></span></button></td>
          <td>{r.rfm.recencyDays} days</td><td>{r.rfm.activeDays} / 30</td><td className="arr-cell">{r.amount}</td>
          <td><span className="rfm-code">{r.rfm.r} · {r.rfm.f} · {r.rfm.m}</span></td><td>{r.rfm.score}</td>
          <td><Badge tone={RFM_TONE[r.rfm.segment]}>{r.rfm.segment}</Badge></td><td><HealthBadge band={r.healthBand} /></td><td className="wrap-cell">{r.nextBestAction}</td></tr>)}</tbody>
      </table></div>
      <Pager meta={data} onPage={onPage} noun="RFM records" />
    </Panel>
    <div className="ac-grid ac-grid-2">
      <Panel title="Scoring and operating rules" description="Method">
        <ol className="rules">{data.rules.map((r) => <li key={r.step}><b>{r.step}</b><span>{r.text}</span></li>)}</ol></Panel>
      <Panel title="Segment rules" description="Versioned R/F engagement rules; M prioritizes value">
        <div className="threshold-table">{data.segmentRules.map((r) => <div key={r.segment}><i className="legend-dot" style={{ background: RFM_COLORS[r.segment] }} />{r.segment}<span>{r.rule}</span></div>)}</div></Panel>
    </div>
    <p className="ac-foot">RFM segmentation complements — not replaces — the health score. Values are synthetic.</p>
  </>;
}

export default function RfmPage({ filters, onSelect }) {
  const [segment, setSegment] = useState("all");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const dq = useDebounced(q);
  const state = useApi(() => ac.rfm(filters, { segment, q: dq, page, page_size: 8 }), [JSON.stringify(filters), segment, dq, page]);
  return <Async state={state} label="Loading RFM analysis…">{(d) => <RfmView data={d} segment={segment} onSegment={(v) => { setSegment(v); setPage(1); }} q={q} onQ={(v) => { setQ(v); setPage(1); }} onPage={setPage} onSelect={onSelect}
    exportHref={ac.url("/explorer/export", { ...filters, q: dq })} />}</Async>;
}
