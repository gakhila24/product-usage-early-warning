import { TriangleAlert, ArrowDownRight, ArrowUpRight, BookOpen, SquareCheck, ChevronLeft, ChevronRight, Download, CircleHelp, Mail, RefreshCw, Search } from "lucide-react";
import { Spinner } from "../components";

export const BAND_COLORS = { Excellent: "#167d8d", Good: "#73b6bc", Fair: "#e4bf83", Poor: "#dd929c", Critical: "#c5525f" };
export const RISK_LEVELS = ["Critical", "Poor", "Fair", "Good", "Excellent"];

export const scoreColor = (s) => (s < 20 ? BAND_COLORS.Critical : s < 40 ? BAND_COLORS.Poor : s < 60 ? "#d9a441" : s < 80 ? BAND_COLORS.Good : BAND_COLORS.Excellent);

export function HealthBadge({ band }) {
  return <span className={`badge hb hb-${String(band ?? "").toLowerCase()}`}><span className="status-dot" />{band}</span>;
}

export function ScoreBar({ score }) {
  return <div className="score-bar"><b>{score}</b><span className="score-mini"><i style={{ width: `${Math.max(0, Math.min(100, score))}%`, background: scoreColor(score) }} /></span></div>;
}

export function Kpi({ label, value, unit, delta, deltaLabel, tone = "neutral", sub, icon: Icon, accent = "violet" }) {
  const up = delta > 0;
  return <section className={`panel metric-card kpi-card metric-${accent}`}>
    <div className="metric-label"><span>{label}</span>{Icon && <Icon size={17} />}</div>
    <div className="metric-value-row"><strong>{value ?? "—"}{unit && <small className="kpi-unit">{unit}</small>}</strong></div>
    {sub && <p className="kpi-sub">{sub}</p>}
    {delta !== undefined && delta !== null && delta !== 0 && <div className={`kpi-delta ${tone}`}>{up ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}{up ? "+" : ""}{Math.abs(delta) < 10 ? delta : Math.round(delta)} {deltaLabel}</div>}
    {(delta === 0 || delta === null || delta === undefined) && deltaLabel && <div className="kpi-delta neutral">— {deltaLabel}</div>}
  </section>;
}

export function Panel({ title, description, action, onAction, right, children, className = "" }) {
  return <section className={`panel ac-panel ${className}`}>
    {(title || right) && <div className="ac-panel-head">
      <div><h2>{title}</h2>{description && <p>{description}</p>}</div>
      <div className="ac-panel-right">{right}{action && <button className="text-button" onClick={onAction}>{action}<ChevronRight size={15} /></button>}</div>
    </div>}
    {children}
  </section>;
}

export function Pager({ meta, onPage, noun = "records" }) {
  if (!meta) return null;
  const { page, pages, total, pageSize } = meta;
  const start = total ? (page - 1) * pageSize + 1 : 0;
  const end = Math.min(page * pageSize, total);
  const groupStart = Math.floor((page - 1) / 5) * 5 + 1;
  const visible = Array.from({ length: Math.min(5, pages - groupStart + 1) }, (_, i) => groupStart + i);
  return <div className="table-footer">
    <span>Showing <strong>{start}–{end}</strong> of <strong>{total.toLocaleString("en-US")}</strong> {noun}</span>
    <div className="pagination">
      <button className="icon-button" aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)}><ChevronLeft size={16} /></button>
      {visible.map((n) => <button key={n} className={n === page ? "active" : ""} aria-current={n === page ? "page" : undefined} onClick={() => onPage(n)}>{n}</button>)}
      {groupStart + 4 < pages && <span className="pager-gap">…</span>}
      <button className="icon-button" aria-label="Next page" disabled={page >= pages} onClick={() => onPage(page + 1)}><ChevronRight size={16} /></button>
    </div>
  </div>;
}

export function SearchInput({ value, onChange, placeholder = "Search…", label = "Search" }) {
  return <label className="ac-search"><Search size={15} /><input aria-label={label} placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} /></label>;
}

export function Select({ value, onChange, options, label, className = "" }) {
  return <select className={`ac-select ${className}`} aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
    {options.map((o) => typeof o === "string" ? <option key={o} value={o}>{o}</option> : <option key={o.value} value={o.value}>{o.label}</option>)}
  </select>;
}

export function Segmented({ options, value, onChange, ariaLabel }) {
  return <div className="tabs ac-segmented" role="group" aria-label={ariaLabel}>
    {options.map((o) => {
      const v = typeof o === "string" ? o : o.value;
      const l = typeof o === "string" ? o : o.label;
      return <button key={v} className={value === v ? "active" : ""} onClick={() => onChange(v)}>{l}</button>;
    })}
  </div>;
}

export function ExportLink({ href, label = "Export" }) {
  return <a className="button" href={href} download><Download size={15} />{label}</a>;
}

export function ErrorPanel({ message, onRetry }) {
  return <section className="panel chart-section" role="alert">
    <p className="chart-empty-note">{message}</p>
    {onRetry && <div className="center"><button className="button small" onClick={onRetry}><RefreshCw size={14} />Retry</button></div>}
  </section>;
}

/** Renders loading / error / data states for a useApi() result. */
export function Async({ state, label = "Loading…", children }) {
  if (state.error && !state.data) return <ErrorPanel message={state.error} onRetry={state.reload} />;
  if (!state.data) return <Spinner label={label} />;
  return <div className={state.loading ? "is-refreshing" : ""}>{children(state.data)}</div>;
}

export function HBars({ rows, labelKey, valueKey, max, color = "var(--primary)", format = (v) => v, signed = false, extra }) {
  const m = max ?? Math.max(1, ...rows.map((r) => Math.abs(r[valueKey])));
  return <div className="hbars">
    {rows.map((r) => <div className="hbar-row" key={r[labelKey]}>
      <span className="hbar-label">{r[labelKey]}</span>
      <div className="hbar-track"><span style={{ width: `${Math.min(100, (Math.abs(r[valueKey]) / m) * 100)}%`, background: typeof color === "function" ? color(r) : color }} /></div>
      <strong className={`hbar-value ${signed ? (r[valueKey] < 0 ? "negative" : "positive") : ""}`}>{format(r[valueKey], r)}</strong>
      {extra && <small className="hbar-extra">{extra(r)}</small>}
    </div>)}
  </div>;
}

export function MiniStat({ value, label, tone }) {
  return <div className={`mini-stat ${tone ?? ""}`}><b>{value}</b><span>{label}</span></div>;
}

export function Info({ icon: Icon, children, tone = "" }) {
  return <div className={`info-banner ${tone}`}>{Icon && <Icon size={19} />}<span>{children}</span></div>;
}

export const nf = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("en-US"));
export const dollars = (n) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0, notation: "compact" }).format(n ?? 0);

export function ActionButtons({ row, onAction }) {
  const items = [["email", Mail, "Send follow-up email"], ["request", CircleHelp, "Request next action"], ["playbook", BookOpen, "Assign playbook"], ["escalate", TriangleAlert, "Escalate risk"], ["task", SquareCheck, "Create task"]];
  return <div className="row-actions">{items.map(([t, Icon, label]) =>
    <button key={t} className="icon-button action-ico" title={label} aria-label={`${label}: ${row.name}`} onClick={() => onAction(row, t)}><Icon size={16} /></button>)}</div>;
}

