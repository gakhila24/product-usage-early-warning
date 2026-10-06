import { useState } from "react";
import { CalendarDays, Clock3, Filter, Globe } from "lucide-react";
import { Modal } from "../components";

export const DEFAULT_FILTERS = { product: "All Products", region: "Global", segment: "All segments", risk: "All risk levels", owner: "All accounts", horizon: 90 };

export function drawerFilterCount(f) {
  return ["segment", "risk", "owner"].filter((k) => f[k] !== DEFAULT_FILTERS[k]).length + (f.horizon !== DEFAULT_FILTERS.horizon ? 1 : 0);
}

export function describeFilters(f) {
  const parts = [f.product, f.region, f.segment];
  if (f.risk !== DEFAULT_FILTERS.risk) parts.push(`Risk: ${f.risk}`);
  if (f.owner !== DEFAULT_FILTERS.owner) parts.push(`Owner: ${f.owner}`);
  return parts.join(" · ");
}

export function FilterBar({ options, filters, onChange, onOpenDrawer }) {
  if (!options) return null;
  const active = drawerFilterCount(filters);
  return <div className="global-filters" role="group" aria-label="Global filters">
    <label className="gf-select"><Globe size={14} /><span className="sr-only">Product</span>
      <select aria-label="Product" value={filters.product} onChange={(e) => onChange({ ...filters, product: e.target.value })}>{options.products.map((p) => <option key={p}>{p}</option>)}</select></label>
    <label className="gf-select"><span className="sr-only">Region</span>
      <select aria-label="Region" value={filters.region} onChange={(e) => onChange({ ...filters, region: e.target.value })}>{options.regions.map((p) => <option key={p}>{p}</option>)}</select></label>
    <span className="gf-pill" title={`Data through ${options.asOfLabel}`}><CalendarDays size={14} />{options.period.label}</span>
    <button className={`button small ${active ? "selected" : ""}`} onClick={onOpenDrawer}><Filter size={14} />Filters{active > 0 && <span className="filter-dot" />}</button>
    <span className="gf-updated"><Clock3 size={13} />Last updated: {options.lastUpdated}</span>
  </div>;
}

export function FilterDrawer({ options, filters, onApply, onClose }) {
  const [draft, setDraft] = useState(filters);
  const set = (k, v) => setDraft((d) => ({ ...d, [k]: v }));
  return <Modal title="Filters" onClose={onClose} drawer>
    <div className="drawer-content ac-filter-drawer">
      <p className="ac-muted">Refine every tab. Filters are applied server-side to both numerators and denominators.</p>
      <label className="form-label" htmlFor="f-seg">Customer segment</label>
      <select id="f-seg" className="ac-input" value={draft.segment} onChange={(e) => set("segment", e.target.value)}>{options.segments.map((s) => <option key={s}>{s}</option>)}</select>
      <label className="form-label" htmlFor="f-risk">Risk level (health band)</label>
      <select id="f-risk" className="ac-input" value={draft.risk} onChange={(e) => set("risk", e.target.value)}>{options.risks.map((s) => <option key={s}>{s}</option>)}</select>
      <label className="form-label" htmlFor="f-hz">Renewal horizon</label>
      <select id="f-hz" className="ac-input" value={draft.horizon} onChange={(e) => set("horizon", Number(e.target.value))}>{options.horizons.map((h) => <option key={h.value} value={h.value}>{h.label}</option>)}</select>
      <label className="form-label" htmlFor="f-own">Owner coverage</label>
      <select id="f-own" className="ac-input" value={draft.owner} onChange={(e) => set("owner", e.target.value)}>{options.owners.map((s) => <option key={s}>{s}</option>)}</select>
      <div className="modal-actions">
        <button className="button" onClick={() => setDraft({ ...draft, segment: DEFAULT_FILTERS.segment, risk: DEFAULT_FILTERS.risk, horizon: DEFAULT_FILTERS.horizon, owner: DEFAULT_FILTERS.owner })}>Reset</button>
        <button className="button primary" onClick={() => onApply(draft)}>Apply filters</button>
      </div>
    </div>
  </Modal>;
}
