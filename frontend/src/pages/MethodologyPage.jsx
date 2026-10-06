import { useMemo, useState } from "react";
import { Info as InfoIcon } from "lucide-react";
import { Badge } from "../components";
import { ac } from "../lib/api";
import { useApi } from "../lib/useApi";
import { Async, Info, MiniStat, Panel, SearchInput, Select, nf } from "./ui";
import { downloadCsv } from "../data";

export function MethodologyView({ data, onNavigate }) {
  const [q, setQ] = useState("");
  const [type, setType] = useState("all");
  const metrics = useMemo(() => data.metrics.filter((m) => (type === "all" || m.sourceType === type) &&
    `${m.metric} ${m.definition} ${m.source} ${m.formula} ${m.rules}`.toLowerCase().includes(q.trim().toLowerCase())), [data.metrics, q, type]);
  const exportDictionary = () => downloadCsv("metric-dictionary.csv", ["Metric", "Business definition", "Source", "Formula", "Calculation note", "Rules", "Refresh"],
    data.metrics.map((m) => [m.metric, m.definition, m.source, m.formula, m.calcNote, m.rules, m.refresh]));
  return <>
    <Info icon={InfoIcon}><b>Lineage disclosure.</b> {data.disclosure}</Info>
    <div className="ac-facts four spaced"><MiniStat value={data.stats.version} label="Methodology + RFM represented" /><MiniStat value={data.stats.refresh} label="Proposed score refresh" /><MiniStat value={`${data.stats.signals}`} label="Model & driver signals" /><MiniStat value={data.stats.dataStatus} label="Current data status" /></div>
    <Panel title="Source catalog" description="Logical systems of record and the information each is expected to capture" right={<button className="button" onClick={exportDictionary}>Export metric dictionary</button>}>
      <div className="table-scroll"><table className="ac-table wrap">
        <thead><tr><th>Source name</th><th>Internal / external</th><th>Information captured</th><th>Metrics supported</th><th>Status</th></tr></thead>
        <tbody>{data.sources.map((s) => <tr key={s.name}><td><strong>{s.name}</strong></td><td><Badge tone={s.type.startsWith("External") ? "warning" : s.type.startsWith("Embedded") ? "purple" : "neutral"}>{s.type}</Badge></td>
          <td className="wrap-cell">{s.captured}</td><td className="wrap-cell">{s.supports}</td><td><Badge tone={s.status === "Current" ? "success" : "neutral"}>{s.status}</Badge></td></tr>)}</tbody>
      </table></div>
    </Panel>
    <Panel title="Metric dictionary" description="Definitions and calculation logic for every metric family presented in the dashboard"
      right={<div className="ac-tools"><SearchInput value={q} onChange={setQ} placeholder="Search metric or source" /><Select label="Source type" value={type} onChange={setType} options={[{ value: "all", label: "All source types" }, { value: "Internal", label: "Internal" }, { value: "Mixed", label: "Internal + external" }]} /></div>}>
      <p className="ac-count">{nf(metrics.length)} metric definitions shown</p>
      <div className="table-scroll"><table className="ac-table wrap metric-table">
        <thead><tr><th>Metric</th><th>Business definition</th><th>Production source / where pulled</th><th>Calculation methodology</th><th>Rules &amp; interpretation</th><th>Refresh</th></tr></thead>
        <tbody>{metrics.map((m) => <tr key={m.metric}><td><strong>{m.metric}</strong></td><td className="wrap-cell">{m.definition}</td><td className="wrap-cell">{m.source}</td>
          <td className="wrap-cell"><code className="formula">{m.formula}</code>{m.calcNote && <small className="cell-sub">{m.calcNote}</small>}</td><td className="wrap-cell">{m.rules}</td><td>{m.refresh}</td></tr>)}
        {metrics.length === 0 && <tr><td colSpan={6} className="ac-empty-row">No metrics match.</td></tr>}</tbody>
      </table></div>
    </Panel>
    <Panel title="Calculation controls" description="Minimum governance controls required before production use">
      <ol className="controls">{data.controls.map((c) => <li key={c.title}><b>{c.title}:</b> {c.text}</li>)}</ol>
    </Panel>
    <p className="ac-foot">Specification page. Production owners and source-system names remain to be confirmed. <button className="text-button inline" onClick={() => onNavigate("FAQs")}>Read FAQs</button></p>
  </>;
}

export default function MethodologyPage({ onNavigate }) {
  const state = useApi(() => ac.methodology(), []);
  return <Async state={state} label="Loading methodology…">{(d) => <MethodologyView data={d} onNavigate={onNavigate} />}</Async>;
}
