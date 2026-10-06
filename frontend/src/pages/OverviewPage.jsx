import { useState } from "react";
import { AlertTriangle, ArrowRight, CalendarClock, Check, Gem, Info, Layers, Percent, ShieldCheck, TrendingDown, TrendingUp, Users } from "lucide-react";
import { Area, CartesianGrid, ComposedChart, Cell, Line, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ac } from "../lib/api";
import { useApi, useDebounced } from "../lib/useApi";
import { Async, ExportLink, HealthBadge, Kpi, Pager, Panel, ScoreBar, SearchInput, Segmented, Select, MiniStat, nf } from "./ui";
import { HealthScoresView } from "./HealthScoresPage";
import { DriversView } from "./DriversPage";
import { SegmentsView } from "./SegmentsPage";

// 2026-10 update: RFM Analysis, Health Scores, Drivers and Segments are no longer separate tabs.
// Health Scores, Drivers and Segments now render inline, below the existing Overview sections, reusing
// the same view components (and the same API calls) the standalone pages used. The RFM strip stays
// (it's Overview's own mini-summary, backed by /overview, not by the removed /rfm page) but no longer
// links anywhere, since there's no RFM Analysis page to open.
function SectionDivider({ title, subtitle }) {
  return <div style={{ margin: "36px 2px 14px" }}>
    <h2 style={{ fontSize: 18, color: "var(--primary-dark)", marginBottom: 4 }}>{title}</h2>
    {subtitle && <p style={{ fontSize: 12, color: "var(--muted)", maxWidth: 680, lineHeight: 1.6 }}>{subtitle}</p>}
  </div>;
}

const KPI_ICONS = { accounts: Users, health: ShieldCheck, atRisk: AlertTriangle, churn: TrendingDown, nrr: Percent };
const KPI_ACCENT = { accounts: "violet", health: "green", atRisk: "red", churn: "amber", nrr: "green" };
const ACTION_ICONS = { check: Check, trending: TrendingUp, diamond: Gem, calendar: CalendarClock, alert: AlertTriangle };

export function HealthDonut({ distribution, total, onSelect }) {
  return <div className="donut-layout ac-donut">
    <div className="donut-chart" role="img" aria-label={`Health score distribution across ${total} accounts`}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={distribution} cx="50%" cy="50%" innerRadius={62} outerRadius={82} paddingAngle={4} cornerRadius={4} dataKey="count" nameKey="band" startAngle={90} endAngle={-270} stroke="none">
            {distribution.map((d) => <Cell key={d.band} fill={d.color} />)}
          </Pie>
          <Tooltip contentStyle={{ borderRadius: 10, fontSize: 12, border: "1px solid var(--border)" }} />
        </PieChart>
      </ResponsiveContainer>
      <div className="donut-center"><strong>{nf(total)}</strong><span>Accounts</span></div>
    </div>
    <div className="distribution-legend">
      {distribution.map((d) => <button key={d.band} onClick={() => onSelect?.(d.band)}>
        <i className="legend-dot" style={{ background: d.color }} /><span>{d.band} ({d.range})</span><strong>{nf(d.count)}</strong>
      </button>)}
    </div>
  </div>;
}

export function TrendChart({ trend }) {
  if (!trend?.points?.length) return <p className="chart-empty-note">No trend data for the current filters.</p>;
  const vals = trend.points.flatMap((p) => [p.score, p.ma]).filter((v) => v != null);
  const lo = Math.floor(Math.min(...vals) - 1.5), hi = Math.ceil(Math.max(...vals) + 1.5);
  return <div className="area-chart ac-trend" role="img" aria-label="Average health score trend">
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={trend.points} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
        <defs><linearGradient id="hsFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#167d8d" stopOpacity={0.22} /><stop offset="100%" stopColor="#167d8d" stopOpacity={0.02} /></linearGradient></defs>
        <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="var(--border)" />
        <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fill: "#6d818a", fontSize: 10 }} dy={8} minTickGap={22} />
        <YAxis domain={[lo, hi]} axisLine={false} tickLine={false} tick={{ fill: "#6d818a", fontSize: 10 }} />
        <Tooltip contentStyle={{ borderRadius: 10, border: "1px solid var(--border)", fontSize: 12 }} formatter={(v) => (v == null ? "—" : Number(v).toFixed(1))} />
        <Area type="monotone" dataKey="score" name="Health score" stroke="#73b6bc" fill="url(#hsFill)" strokeWidth={1.8} dot={false} />
        <Line type="monotone" dataKey="ma" name="30-day moving average" stroke="#105e6b" strokeWidth={2.4} dot={false} connectNulls />
      </ComposedChart>
    </ResponsiveContainer>
  </div>;
}

export function AtRiskTable({ data, onSelect, onAction }) {
  return <div className="table-scroll"><table className="ac-table">
    <thead><tr><th>Account</th><th>Product(s)</th><th>Health Score</th><th>Risk Level</th><th>Top Driver</th><th>Renewal Date</th><th>Amount</th><th>Owner</th><th>Action</th></tr></thead>
    <tbody>{data.rows.map((r) => <tr key={r.id}>
      <td><button className="account-cell" onClick={() => onSelect(r.id)}><span className="acct-glyph">▦</span><span><strong>{r.name}</strong><small>{r.id}</small></span></button></td>
      <td><span className="product-tag">{r.product}</span></td>
      <td><ScoreBar score={r.health} /></td>
      <td><HealthBadge band={r.healthBand} /></td>
      <td>{r.topDriver}</td><td>{r.renewal}</td><td className="arr-cell">{r.amount}</td>
      <td>{r.ownerName === "Unassigned" ? <span className="ac-muted">Unassigned</span> : r.owner}</td>
      <td><button className="button small" onClick={() => onAction(r, "email")}>Follow Up</button></td>
    </tr>)}
    {data.rows.length === 0 && <tr><td colSpan={9} className="ac-empty-row">No accounts match the current filters.</td></tr>}
    </tbody></table></div>;
}

export function RenewalsMini({ r, onNavigate }) {
  const tot = r.pipeline || 1;
  return <>
    <div className="ren-head"><b>{r.pipelineLabel}</b><span>Total Pipeline · {nf(r.count)} renewals</span></div>
    <div className="ren-bands">{r.bands.map((b) => <div key={b.band}><i style={{ background: { Excellent: "#167d8d", Good: "#73b6bc", Fair: "#e4bf83", "Poor / Critical": "#c5525f" }[b.band] }} /><span>{b.band}</span><strong>{b.label}</strong></div>)}</div>
    <div className="stack-bar" aria-hidden="true">{r.bands.map((b) => <span key={b.band} style={{ width: `${(b.value / tot) * 100}%`, background: { Excellent: "#167d8d", Good: "#73b6bc", Fair: "#e4bf83", "Poor / Critical": "#c5525f" }[b.band] }} />)}</div>
    <ul className="ren-list">{r.rows.map((x) => <li key={x.id}><span><b>{x.name}</b><small>{x.renewal}</small></span><strong>{x.amount}</strong></li>)}</ul>
    <button className="text-button" onClick={() => onNavigate("Renewals")}>View all renewals <ArrowRight size={14} /></button>
  </>;
}

export function OverviewView({ data, trend, grain, onGrain, onNavigate, onSelectRiskBand, health, drivers, segments, showAdoption, children }) {
  const total = data.healthDistribution.reduce((s, d) => s + d.count, 0);
  return <>
    <div className="metrics-grid ac-kpis">
      {data.kpis.map((k) => <Kpi key={k.key} label={k.label} value={k.value} unit={k.unit} delta={k.delta} deltaLabel={k.deltaLabel} tone={k.tone} sub={k.sub} icon={KPI_ICONS[k.key]} accent={KPI_ACCENT[k.key]} />)}
    </div>
    <section className="panel rfm-strip">
      <div className="rfm-strip-text"><span className="card-eyebrow"><Layers size={13} />PORTFOLIO LENS</span><h2>RFM Snapshot</h2>
        <p>Recency, frequency and monetary value at a glance — engagement momentum alongside commercial value.</p></div>
      <div className="rfm-strip-stats">
        <MiniStat value={<>{data.rfm.recencyDays}<small> days</small></>} label="R · Recency — avg days since qualifying activity" />
        <MiniStat value={<>{data.rfm.activeDays}<small> days</small></>} label="F · Frequency — avg active days, trailing 30" />
        <MiniStat value={data.rfm.arrLabel} label="M · Monetary — synthetic ARR in portfolio" />
      </div>
    </section>
    <div className="ac-grid ac-grid-1-2">
      <Panel title="Health Score Distribution" description="Accounts by health band">
        <HealthDonut distribution={data.healthDistribution} total={total} onSelect={onSelectRiskBand} />
      </Panel>
      <Panel title="Average Health Score Trend" description="Portfolio average, with 30-day moving average"
        right={<Segmented ariaLabel="Trend grain" options={[{ value: "daily", label: "Daily" }, { value: "weekly", label: "Weekly" }]} value={grain} onChange={onGrain} />}>
        <div className="chart-legend"><span><i className="legend-dot" style={{ background: "#73b6bc" }} />Health Score</span><span><i className="legend-dot" style={{ background: "#105e6b" }} />30-Day Moving Average</span></div>
        {trend ? <TrendChart trend={trend} /> : <p className="chart-empty-note">Loading trend…</p>}
        <div className="chart-footnote"><span className="live-dot" />{trend?.note}</div>
      </Panel>
    </div>
    <Panel title="Recommended Actions" description="Accounts currently eligible, by rule" action="View all actions" onAction={() => onNavigate("Accounts")}>
      <div className="recommended-items ac-reco">{data.recommendedActions.map((a) => {
        const Icon = ACTION_ICONS[a.icon] ?? Check;
        return <button key={a.id} className="recommended-item" onClick={() => onNavigate(a.id === "renewals" ? "Renewals" : "Accounts")}>
          <span className="playbook-icon violet"><Icon size={18} /></span>
          <span><strong>{a.title}</strong><small>{a.subtitle}</small></span><b className="reco-count">{nf(a.count)}</b>
        </button>;
      })}</div>
    </Panel>
    {children}

    <SectionDivider title="Health Scores" subtitle="Distribution, thresholds and score methodology across the portfolio." />
    {health ? <HealthScoresView data={health} /> : <p className="chart-empty-note">Loading health scores…</p>}

    <SectionDivider title="Drivers" subtitle="Factors that reduce health alongside the behaviors that accelerate adoption." />
    {drivers ? <DriversView data={drivers} showAdoption={showAdoption} /> : <p className="chart-empty-note">Loading drivers…</p>}

    <SectionDivider title="Segments" subtitle="Compare customer health by market segment." />
    {segments ? <SegmentsView data={segments} /> : <p className="chart-empty-note">Loading segments…</p>}

    <div className="ac-grid ac-grid-2">
      <Panel title="Upcoming Renewals" description="Next 90 days · largest at-risk renewals" right={<span className="badge purple">{data.renewalsPreview.pipelineLabel} pipeline</span>}>
        <RenewalsMini r={data.renewalsPreview} onNavigate={onNavigate} />
      </Panel>
      <Panel title="About Health Score" description="How the score is produced" right={<Info size={16} className="ac-muted" />}>
        <p className="ac-para">Predicts likelihood of renewal from {data.about.signals}+ behavioral, engagement, commercial and feedback signals. In this build: <b>health = 100 − churn-model risk score</b>.</p>
        <div className="ac-facts">
          <MiniStat value={`${data.about.dataSources}+`} label="Data sources · internal & external" />
          <MiniStat value={`${data.about.signals}`} label="Signals tracked · behavioral & attitudinal" />
          <MiniStat value={data.about.refresh} label={`Model refresh · next ${data.about.nextRefresh}`} />
          <MiniStat value={data.about.confidence} label={`Confidence · AUROC ${data.about.auroc}`} />
        </div>
      </Panel>
    </div>
    <p className="ac-foot">All values and account names are synthetic and provided for illustration only.</p>
  </>;
}

export default function OverviewPage({ filters, onNavigate, onSelectAccount, onAction, onSelectRiskBand, settings }) {
  const [grain, setGrain] = useState("daily");
  const [q, setQ] = useState("");
  const [risk, setRisk] = useState("All risk levels");
  const [page, setPage] = useState(1);
  const dq = useDebounced(q);
  const key = JSON.stringify(filters);
  const overview = useApi(() => ac.overview(filters), [key]);
  const trend = useApi(() => ac.trend(filters, grain), [key, grain]);
  const atRisk = useApi(() => ac.atRisk({ ...filters, risk: risk === "All risk levels" ? filters.risk : risk }, { page, page_size: 6, q: dq }), [key, risk, page, dq]);
  // Health Scores, Drivers and Segments were previously separate pages; they now render inline below
  // (see OverviewView), each still backed by its own endpoint so the data and the maths are unchanged.
  const health = useApi(() => ac.healthScores(filters), [key]);
  const drivers = useApi(() => ac.drivers(filters), [key]);
  const segments = useApi(() => ac.segments(filters), [key]);
  return <Async state={overview} label="Loading customer health overview…">{(data) => <OverviewView data={data} trend={trend.data} grain={grain} onGrain={setGrain} onNavigate={onNavigate} onSelectRiskBand={onSelectRiskBand}
    health={health.data} drivers={drivers.data} segments={segments.data} showAdoption={settings?.include_adoption_drivers !== false}>
    <Panel title="At-Risk Accounts" description="Health below 60 · sorted by lowest score"
      right={<div className="ac-tools"><SearchInput value={q} onChange={(v) => { setQ(v); setPage(1); }} placeholder="Search account, product, driver" />
        <Select label="Risk level" value={risk} onChange={(v) => { setRisk(v); setPage(1); }} options={["All risk levels", "Critical", "Poor", "Fair"]} />
        <ExportLink href={ac.url("/explorer/export", { ...filters, risk: risk === "All risk levels" ? "At risk" : risk, q: dq })} label="Export" /></div>}>
      {atRisk.data ? <><AtRiskTable data={atRisk.data} onSelect={onSelectAccount} onAction={onAction} /><Pager meta={atRisk.data} onPage={setPage} noun="at-risk accounts" /></> : <p className="chart-empty-note">{atRisk.error ?? "Loading accounts…"}</p>}
    </Panel>
  </OverviewView>}</Async>;
}
