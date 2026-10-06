import { useState } from "react";
import { Download, FilePlus2 } from "lucide-react";
import { Badge, Modal } from "../components";
import { ac } from "../lib/api";
import { useApi } from "../lib/useApi";
import { Async, Panel } from "./ui";
import { describeFilters } from "./Filters";

export function CreateReportModal({ data, template, filters, onClose, onCreate }) {
  const tpl = data.templates.find((t) => t.id === template) ?? data.templates[0];
  const [tplId, setTplId] = useState(tpl.id);
  const current = data.templates.find((t) => t.id === tplId);
  const [sections, setSections] = useState(current.sections);
  const [name, setName] = useState(current.title);
  const [recipients, setRecipients] = useState("");
  const [busy, setBusy] = useState(false);
  const pick = (id) => { const t = data.templates.find((x) => x.id === id); setTplId(id); setSections(t.sections); setName(t.title); };
  const toggle = (id) => setSections((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  return <Modal title="Create report" onClose={onClose}>
    <form className="modal-content ac-action-form" onSubmit={async (e) => { e.preventDefault(); setBusy(true); await onCreate({ template: tplId, name, recipients, sections, filters }); }}>
      <p>Capture a report configuration using the active product, region and segment filters.</p>
      <label className="form-label" htmlFor="rp-t">Report template</label>
      <select id="rp-t" className="ac-input" value={tplId} onChange={(e) => pick(e.target.value)}>{data.templates.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}</select>
      <label className="form-label" htmlFor="rp-n">Report name</label>
      <input id="rp-n" className="ac-input" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
      <label className="form-label" htmlFor="rp-r">Recipients</label>
      <input id="rp-r" className="ac-input" value={recipients} onChange={(e) => setRecipients(e.target.value)} placeholder="name@company.com, team@company.com" />
      <p className="form-label">Include sections</p>
      <div className="check-grid">{data.sections.map((s) => <label key={s.id} className="check"><input type="checkbox" checked={sections.includes(s.id)} onChange={() => toggle(s.id)} />{s.label}</label>)}</div>
      <p className="form-label">Applied filters</p>
      <div className="notice">{describeFilters(filters)}</div>
      <div className="modal-actions"><button type="button" className="button" onClick={onClose}>Cancel</button>
        <button type="submit" className="button primary" disabled={busy || sections.length === 0}>{busy ? "Generating…" : "Create report"}</button></div>
    </form>
  </Modal>;
}

export function ReportsView({ data, onUse, onCreate }) {
  return <>
    <div className="ac-toolbar"><span className="ac-muted">Create focused portfolio, renewal and driver views from the active filters.</span>
      <button className="button primary" onClick={onCreate}><FilePlus2 size={15} />Create report</button></div>
    <div className="ac-grid ac-grid-3">{data.templates.map((t) => <section className="panel template-card" key={t.id}>
      <span className="card-eyebrow">{t.category.toUpperCase()}</span><h2>{t.title}</h2><p>{t.description}</p>
      <ul className="tpl-sections">{t.sectionLabels.map((s) => <li key={s}>{s}</li>)}</ul>
      <div className="tpl-foot"><Badge tone="purple">{t.sections.length} sections</Badge><button className="button small" onClick={() => onUse(t.id)}>Use template</button></div></section>)}</div>
    <Panel title="Generated reports" description="Reports are generated server-side and stored in SQLite; download as a standalone HTML file">
      <div className="table-scroll"><table className="ac-table">
        <thead><tr><th>Report</th><th>Template</th><th>Filters</th><th>Recipients</th><th>Created (UTC)</th><th>Status</th><th /></tr></thead>
        <tbody>{data.reports.map((r) => <tr key={r.id}>
          <td><strong>{r.name}</strong><small className="cell-sub">{r.id}</small></td><td>{data.templates.find((t) => t.id === r.template)?.title ?? r.template}</td>
          <td className="wrap-cell">{describeFilters(r.filters)}</td><td>{r.recipients || "—"}</td><td>{String(r.created_at).replace("T", " ")}</td>
          <td><Badge tone="success">{r.status}</Badge></td><td><a className="button small" href={ac.url(`/reports/${r.id}/download`)} download><Download size={13} />Download</a></td></tr>)}
        {data.reports.length === 0 && <tr><td colSpan={7} className="ac-empty-row">No reports yet — pick a template to generate one.</td></tr>}</tbody>
      </table></div>
    </Panel>
  </>;
}

export default function ReportsPage({ filters, notify }) {
  const state = useApi(() => ac.reports(), []);
  const [modal, setModal] = useState(null);
  return <>
    <Async state={state} label="Loading reports…">{(d) => <>
      <ReportsView data={d} onUse={(id) => setModal(id)} onCreate={() => setModal(d.templates[0].id)} />
      {modal && <CreateReportModal data={d} template={modal} filters={filters} onClose={() => setModal(null)}
        onCreate={async (body) => { try { const r = await ac.createReport(body); setModal(null); notify(`${r.name} generated.`); state.reload(); } catch (e) { notify(e.message); setModal(null); } }} />}
    </>}</Async>
  </>;
}
