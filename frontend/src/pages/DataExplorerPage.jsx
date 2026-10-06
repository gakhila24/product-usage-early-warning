import { useState } from "react";
import { ac } from "../lib/api";
import { useApi, useDebounced } from "../lib/useApi";
import { Async, ExportLink, HealthBadge, Pager, Panel, ScoreBar, SearchInput, Select } from "./ui";

export function ExplorerView({ data, onPage, onSelect }) {
  return <>
    <div className="table-scroll"><table className="ac-table">
      <thead><tr><th>Account</th><th>Product(s)</th><th>Health Score</th><th>Risk Level</th><th>Top Driver</th><th>Renewal Date</th><th>Amount</th><th>Owner</th><th>Region</th><th>Segment</th></tr></thead>
      <tbody>{data.rows.map((r) => <tr key={r.id}>
        <td><button className="account-cell" onClick={() => onSelect(r.id)}><span className="acct-glyph">▦</span><span><strong>{r.name}</strong><small>{r.id}</small></span></button></td>
        <td><span className="product-tag">{r.product}</span></td><td><ScoreBar score={r.health} /></td><td><HealthBadge band={r.healthBand} /></td>
        <td>{r.topDriver}</td><td>{r.renewal}</td><td className="arr-cell">{r.amount}</td><td>{r.owner}</td><td>{r.region}</td><td>{r.segment}</td></tr>)}
      {data.rows.length === 0 && <tr><td colSpan={10} className="ac-empty-row">No records match.</td></tr>}</tbody>
    </table></div>
    <Pager meta={data} onPage={onPage} noun="records" />
  </>;
}

export default function DataExplorerPage({ filters, onSelect }) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("health");
  const [risk, setRisk] = useState("All risk levels");
  const [page, setPage] = useState(1);
  const dq = useDebounced(q);
  const f = { ...filters, risk: risk !== "All risk levels" ? risk : filters.risk };
  const state = useApi(() => ac.explorer(f, { q: dq, sort, page, page_size: 12 }), [JSON.stringify(f), dq, sort, page]);
  return <Panel title="Account records" description="Inspect the synthetic account records behind this dashboard"
    right={<div className="ac-tools"><SearchInput value={q} onChange={(v) => { setQ(v); setPage(1); }} placeholder="Search account, product, driver, owner" />
      <Select label="Risk level" value={risk} onChange={(v) => { setRisk(v); setPage(1); }} options={["All risk levels", "Critical", "Poor", "Fair", "Good", "Excellent"]} />
      <Select label="Sort" value={sort} onChange={(v) => { setSort(v); setPage(1); }} options={[{ value: "health", label: "Lowest health" }, { value: "arr", label: "Highest ARR" }, { value: "renewal", label: "Soonest renewal" }, { value: "priority", label: "Highest priority" }, { value: "name", label: "Name A–Z" }]} />
      <ExportLink href={ac.url("/explorer/export", { ...f, q: dq })} label="Export CSV" /></div>}>
    <Async state={state} label="Loading records…">{(d) => <ExplorerView data={d} onPage={setPage} onSelect={onSelect} />}</Async>
  </Panel>;
}
