import { useEffect, useState } from "react";
import { Activity, ArrowRight, ArrowUpRight, Building2, CalendarClock, CalendarDays, Check, CircleHelp, DollarSign, Filter, Fingerprint, Gauge, Layers, LifeBuoy, MessageCircle, RefreshCw, ShieldCheck, Sparkles, Target, UserRound, Users, Workflow, Zap, Trophy } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, Funnel, FunnelChart, LabelList, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { actionStatusTone, initialsFromName } from "./data";
import { AccountLogo, Badge, Delta, EmptyState, RiskBadge, SectionHeader, Spinner, StepList } from "./components";
import { ActionButtons } from "./pages/ui";
import { getInterventionFunnel, getCsmLeaderboard, getWinRateByType } from "./lib/api";

const PLAY_ICONS = { zap: Zap, users: Users, layers: Layers, "life-buoy": LifeBuoy, "user-round": UserRound, "refresh-cw": RefreshCw, "message-circle": MessageCircle, "calendar-clock": CalendarClock, dollar: DollarSign, building: Building2, activity: Activity };
const FUNNEL_COLORS = ["#167d8d", "#4a9ca8", "#7fbcc4"];

export function Playbooks({ plays, onLaunch }) {
  return <>
    <div className="info-banner"><Sparkles size={19} /><span><strong>From insight to action.</strong> These are the real interventions the churn-scoring policy recommends, served by the scoring API (dashboard_service.PLAY_META). Launching one records an action for this session and logs a “Scheduled” intervention in the outcomes database (via the log_intervention tool).</span></div>
    <div className="playbooks-grid">
      {(plays ?? []).map((playbook) => {
        const Icon = PLAY_ICONS[playbook.icon] ?? Activity;
        return <section className="panel playbook-card" key={playbook.id}>
          <div className="playbook-top"><span className={`playbook-icon ${playbook.color}`}><Icon size={23} /></span><Badge tone={playbook.band === "High risk" ? "danger" : "warning"} dot>{playbook.band}</Badge></div>
          <span className="card-eyebrow">{playbook.category}</span>
          <h2>{playbook.title}</h2>
          <p>Recommended when the top contributing signal is: {playbook.trigger}.</p>
          <StepList steps={playbook.steps} />
          <div className="trigger"><Filter size={14} />Top signal · {playbook.trigger}</div>
          <button className="button primary" onClick={() => onLaunch(playbook.id)}>Launch playbook <ArrowRight size={16} /></button>
        </section>;
      })}
    </div>
    <section className="policy-note"><ShieldCheck size={24} /><div><h3>Human-led, signal-informed.</h3><p>Suggested plays are guidance from the policy layer, not automatic interventions. Your team stays in control of every customer conversation.</p></div></section>
  </>;
}

function InterventionFunnelChart({ data }) {
  if (!data?.length) return <p className="chart-empty-note">No intervention funnel data was supplied.</p>;
  return <div style={{ height: 180 }}>
    <ResponsiveContainer width="100%" height="100%">
      <FunnelChart>
        <Tooltip />
        <Funnel dataKey="count" data={data} nameKey="status" isAnimationActive>
          <LabelList position="right" dataKey="status" fill="var(--ink)" stroke="none" fontSize={11} />
          <LabelList position="center" dataKey="count" fill="#fff" stroke="none" fontSize={12} fontWeight={700} />
          {data.map((entry, i) => <Cell key={entry.status} fill={FUNNEL_COLORS[i % FUNNEL_COLORS.length]} />)}
        </Funnel>
      </FunnelChart>
    </ResponsiveContainer>
  </div>;
}

function CsmLeaderboardChart({ data }) {
  if (!data?.length) return <p className="chart-empty-note">No completed interventions yet to rank CSMs by.</p>;
  return <div style={{ height: Math.max(180, data.length * 32) }}>
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} layout="vertical" margin={{ left: 10, right: 30, top: 5, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 4" horizontal={false} stroke="var(--border)" />
        <XAxis type="number" tickFormatter={(v) => `${Math.round(v * 100)}%`} tick={{ fontSize: 11, fill: "var(--muted)" }} axisLine={false} tickLine={false} domain={[0, 1]} />
        <YAxis type="category" dataKey="owner" width={120} tick={{ fontSize: 11, fill: "var(--ink)" }} axisLine={false} tickLine={false} />
        <Tooltip formatter={(v, name) => name === "winRate" ? `${(v * 100).toFixed(1)}%` : v} />
        <Bar dataKey="winRate" fill="var(--primary)" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  </div>;
}

function WinRateByTypeChart({ data }) {
  if (!data?.length) return <p className="chart-empty-note">No win-rate-by-type data was supplied.</p>;
  return <div style={{ height: 220 }}>
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ left: -10, right: 15, top: 5, bottom: 40 }}>
        <CartesianGrid strokeDasharray="3 4" vertical={false} stroke="var(--border)" />
        <XAxis dataKey="type" tick={{ fontSize: 9, fill: "var(--muted)" }} axisLine={false} tickLine={false} angle={-20} textAnchor="end" interval={0} height={60} />
        <YAxis tickFormatter={(v) => `${Math.round(v * 100)}%`} tick={{ fontSize: 11, fill: "var(--muted)" }} axisLine={false} tickLine={false} domain={[0, 1]} />
        <Tooltip formatter={(v) => `${(v * 100).toFixed(1)}%`} />
        <Bar dataKey="winRate" fill="var(--primary)" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  </div>;
}

function InterventionCharts() {
  const [state, setState] = useState({ loading: true, error: null, funnel: null, leaderboard: null, winRate: null });
  useEffect(() => {
    let active = true;
    Promise.all([getInterventionFunnel(), getCsmLeaderboard(), getWinRateByType()])
      .then(([funnel, leaderboard, winRate]) => { if (active) setState({ loading: false, error: null, funnel, leaderboard, winRate }); })
      .catch((err) => { if (active) setState({ loading: false, error: err.message || "Couldn't load intervention charts.", funnel: null, leaderboard: null, winRate: null }); });
    return () => { active = false; };
  }, []);
  if (state.loading) return <Spinner label="Loading intervention charts…" />;
  if (state.error) return <section className="panel chart-section" role="alert"><p className="chart-empty-note">{state.error}</p></section>;
  return <>
    <div className="evaluation-two-col">
      <section className="panel chart-section">
        <SectionHeader title="Intervention funnel" description="Where logged interventions stand right now. Ported from the legacy dashboard's Intervention Tracking tab." />
        <InterventionFunnelChart data={state.funnel} />
      </section>
      <section className="panel chart-section">
        <SectionHeader title="Win rate by intervention type" description="Share of completed interventions that led to retention or upsell." />
        <WinRateByTypeChart data={state.winRate} />
      </section>
    </div>
    <section className="panel chart-section">
      <SectionHeader title="CSM leaderboard" description="Completed-intervention win rate by owner." />
      <CsmLeaderboardChart data={state.leaderboard} />
    </section>
  </>;
}

export function ActivityLog({ actions, onSelect, onOutcome }) {
  const inProgress = actions.filter((a) => a.status === "In progress").length;
  const completed = actions.filter((a) => a.status === "Completed" || a.status === "Retained").length;
  return <>
    <section className="panel activity-panel">
      <SectionHeader title="Customer action timeline" description="Actions launched this session appear first; the rest come from the live actions log." />
      <div className="activity-summary"><Badge tone="purple">{actions.length} actions</Badge><Badge tone="warning">{inProgress} in progress</Badge><Badge tone="success">{completed} completed</Badge></div>
      {actions.length ? <div className="timeline">{actions.map((action) => <article className="timeline-item" key={action.id}>
        <span className={`timeline-icon ${action.status === "Completed" || action.status === "Retained" ? "success" : "purple"}`}>{action.status === "Completed" || action.status === "Retained" ? <Check size={19} /> : <Workflow size={19} />}</span>
        <div className="timeline-body">
          <div className="timeline-title"><h3>{action.play}</h3><Badge tone={actionStatusTone(action.status)}>{action.status}</Badge>{action.local && <Badge tone="neutral">This session</Badge>}</div>
          <button className="text-button" onClick={() => onSelect(action.accountId)}>{action.account}<ArrowUpRight size={13} /></button>
          <p>{action.note}</p>
          <small>{new Date(action.date).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" })}</small>
        </div>
        {action.local && <button className="button small" onClick={() => onOutcome(action)}>Record outcome</button>}
      </article>)}</div> : <EmptyState icon={Workflow} title="Every action starts a story" description="Launch a playbook to begin capturing customer outcomes." />}
    </section>
    <div className="activity-charts">
      <SectionHeader title="Intervention performance" description="Charts ported from the legacy dashboard's Intervention Tracking tab, computed from the live interventions log." />
      <InterventionCharts />
    </div>
  </>;
}

export function AccountDetail({ id, detail, reminders, localActions, onLaunch, acContext, onAction }) {
  const hasActive = detail && localActions.some((a) => a.accountId === id && a.status === "In progress");
  const account = detail ? { initials: initialsFromName(detail.name), color: detail.color } : null;
  if (!detail) return <div className="drawer-content"><EmptyState icon={Activity} title="Loading account…" description="Fetching the latest score from the scoring API." /></div>;
  return <div className="drawer-content">
    <div className="detail-account"><AccountLogo account={account} large /><div><h2>{detail.name}</h2><p>{detail.industry} · {detail.plan}</p></div><RiskBadge band={detail.band} /></div>
    <div className="detail-score"><div><span>Account risk score</span><strong>{detail.score}<small>/ 100</small></strong><Delta value={detail.wow} /></div><div className="risk-gauge"><Gauge size={35} /><span>{detail.band}</span></div></div>
    <div className="detail-facts"><div><small>Annual revenue</small><strong>{detail.arr}</strong></div><div><small>Next renewal</small><strong>{detail.renewal}</strong></div><div><small>Urgency</small><strong>{detail.urgency}</strong></div></div>
    {acContext && <section className="detail-section ac-detail">
      <h3>Action Center</h3><p>Customer-health band, RFM segment, priority and follow-up status</p>
      <div className="detail-facts">
        <div><small>Health score</small><strong>{acContext.health} · {acContext.healthBand}</strong></div>
        <div><small>RFM segment</small><strong>{acContext.rfm.segment}</strong></div>
        <div><small>Priority score</small><strong>{acContext.priority}</strong></div>
      </div>
      <div className="ac-nba-box"><span className="card-eyebrow"><Sparkles size={13} />NEXT-BEST ACTION</span><b>{acContext.nextBestAction}</b><small>{acContext.why}</small>
        {acContext.followup ? <div className="activity-summary"><Badge tone="purple">{acContext.followup.status}</Badge><Badge tone="neutral">{acContext.followup.ownerRole} · due {acContext.followup.dueLabel}</Badge></div> : <small>No open follow-up yet. Suggested owner: {acContext.ownerRole}.</small>}
        <ActionButtons row={acContext} onAction={onAction} />
      </div>
      {acContext.drivers?.length > 0 && <div className="ac-driver-chips">{acContext.drivers.map((d) => <span key={d.driver} className="signal-tag"><span />{d.driver}</span>)}</div>}
    </section>}
    {reminders && detail.renewalDays != null && detail.renewalDays <= 30 && <div className="renewal-alert"><CalendarDays size={17} />Renewal in {detail.renewalDays} days.</div>}
    {(detail.csat != null || detail.nps != null || detail.seatUtilizationPct != null || detail.monthlySpend != null) && <section className="detail-section"><h3>Account health</h3><p>Support, relationship, and commercial signals from the latest monthly snapshot</p>
      <div className="detail-facts">
        {detail.csat != null && <div><small>CSAT</small><strong>{detail.csat.toFixed(1)} / 5</strong></div>}
        {detail.nps != null && <div><small>NPS (last survey)</small><strong>{detail.nps}</strong></div>}
        {detail.seatUtilizationPct != null && <div><small>Seat utilization</small><strong>{detail.seatUtilizationPct.toFixed(0)}%</strong></div>}
        {detail.monthlySpend != null && <div><small>Monthly spend</small><strong>${detail.monthlySpend.toLocaleString()}</strong></div>}
        {detail.supportTickets90d != null && <div><small>Support tickets (90d)</small><strong>{detail.supportTickets90d}</strong></div>}
        {detail.daysSinceCsmTouchpoint != null && <div><small>Days since CSM touchpoint</small><strong>{detail.daysSinceCsmTouchpoint}</strong></div>}
      </div>
      {(detail.paymentRisk || detail.firmographicRisk) && <div className="activity-summary">
        {detail.paymentRisk && <Badge tone="warning">Payment risk</Badge>}
        {detail.firmographicRisk && <Badge tone="warning">Firmographic risk</Badge>}
      </div>}
    </section>}
    {detail.interventionHistory?.length > 0 && <section className="detail-section"><h3>Intervention history</h3><p>Recorded interventions for this account</p>
      <div className="timeline">{detail.interventionHistory.map((h, i) => <article className="timeline-item" key={i}>
        <span className={`timeline-icon ${h.status === "Completed" ? "success" : "purple"}`}>{h.status === "Completed" ? <Check size={19} /> : <Workflow size={19} />}</span>
        <div className="timeline-body">
          <div className="timeline-title"><h3>{h.type}</h3><Badge tone={actionStatusTone(h.status === "In Progress" ? "In progress" : h.status)}>{h.status}</Badge></div>
          <p>{h.owner}{h.outcome ? ` · ${h.outcome}` : ""}</p>
          <small>{h.date}</small>
        </div>
      </article>)}</div>
    </section>}
    <section className="detail-section"><h3>What's driving the score</h3><p>Top contributing signals from the model, most recent scoring run</p>
      <div className="signal-contributions">{detail.signals.map((s) => <div key={s.label}><div className="contribution-label"><strong>{s.label}</strong><span>{s.pct}%</span></div><div className="contribution-track"><span style={{ width: `${s.pct}%` }} /></div></div>)}</div>
    </section>
    <section className="detail-section"><div className="section-header"><div><h3>Product engagement</h3><p>Login activity, 90-day window binned into 6 periods</p></div><span className={`usage-change ${detail.last30.startsWith("-") ? "negative" : "positive"}`}>{detail.last30} (30d)</span></div>
      <div className="detail-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={detail.usage90d} margin={{ left: -12, right: 10, top: 15, bottom: 0 }}><CartesianGrid strokeDasharray="3 4" vertical={false} stroke="var(--border)" /><XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "var(--muted)" }} /><YAxis axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "var(--muted)" }} /><Tooltip /><Line dataKey="value" name="Logins" type="monotone" stroke="var(--primary)" strokeWidth={2.5} dot={false} /></LineChart></ResponsiveContainer></div>
    </section>
    <section className="detail-section"><h3>Signal attribution</h3><p>How each signal contributed to the score, vs baseline</p>
      <table className="attribution-table" style={{ width: "100%", marginTop: 12, fontSize: 12 }}><thead><tr style={{ textAlign: "left", color: "var(--muted)" }}><th>Signal</th><th style={{ textAlign: "right" }}>Contribution</th><th style={{ textAlign: "right" }}>Current vs baseline</th></tr></thead>
        <tbody>{detail.attribution.map((row) => <tr key={row.signal}><td style={{ padding: "6px 0" }}>{row.signal}</td><td style={{ textAlign: "right" }}>+{row.contribution}</td><td style={{ textAlign: "right", color: "var(--muted)" }}>{row.comparison}</td></tr>)}</tbody>
      </table>
    </section>
    <section className="detail-playbook"><span className="card-eyebrow"><Sparkles size={13} />RECOMMENDED PLAY</span>
      {detail.play.key === "default"
        ? <><h3>Keep the momentum going</h3><p>No urgent signal for this account right now. Keep regular check-ins and continue to monitor engagement.</p></>
        : <><h3>{detail.play.name}</h3><StepList steps={detail.play.steps} /><button disabled={hasActive} className="button primary" onClick={() => onLaunch(id)}>{hasActive ? <><Check size={16} />Playbook in progress</> : <>Launch playbook<ArrowRight size={16} /></>}</button></>}
    </section>
    <p className="detail-disclaimer"><CircleHelp size={14} />Score, signals, and the recommended play come live from the churn-scoring API.</p>
  </div>;
}

export function LaunchForm({ playbook, accounts, onLaunch }) {
  const [accountId, setAccountId] = useState(accounts[0]?.id);
  if (!playbook) return null;
  return <form className="modal-content launch-form" onSubmit={(e) => { e.preventDefault(); onLaunch(accountId, playbook.id); }}>
    <Badge tone="purple">{playbook.category}</Badge>
    <h3>{playbook.title}</h3>
    <p>Recommended when the top contributing signal is: {playbook.trigger}.</p>
    <label className="form-label" htmlFor="launch-account">Choose an account</label>
    <select id="launch-account" value={accountId} onChange={(e) => setAccountId(e.target.value)}>{accounts.map((a) => <option key={a.id} value={a.id}>{a.name} — {a.band} ({a.score})</option>)}</select>
    <StepList steps={playbook.steps} />
    <div className="notice">This records an action for this session and logs a “Scheduled” intervention in the outcomes database.</div>
    <button className="button primary" type="submit"><Workflow size={16} />Launch playbook</button>
  </form>;
}

export function OutcomeForm({ action, onSave }) {
  const [status, setStatus] = useState(action.status);
  const [note, setNote] = useState(action.note);
  return <form className="modal-content outcome-form" onSubmit={(e) => { e.preventDefault(); if (note.trim()) onSave(status, note.trim()); }}>
    <p>Close the feedback loop with a short, useful update.</p>
    <label className="form-label" htmlFor="outcome-status">Outcome</label>
    <select id="outcome-status" value={status} onChange={(e) => setStatus(e.target.value)}><option>In progress</option><option>Monitoring</option><option>Retained</option><option>Churned</option></select>
    <label className="form-label" htmlFor="outcome-note">What happened?</label>
    <textarea id="outcome-note" rows={5} maxLength={1000} required value={note} onChange={(e) => setNote(e.target.value)} placeholder="Capture the conversation, next step, or result…" />
    <small>{note.length}/1000 characters · Saved locally</small>
    <button className="button primary" disabled={!note.trim()} type="submit"><Check size={16} />Save outcome</button>
  </form>;
}

export function Monitoring({ modelPerf, drift, distribution, totalAccounts, onGuide }) {
  const [tab, setTab] = useState("Input drift");
  if (!modelPerf || !drift) return <EmptyState icon={Activity} title="Loading monitoring data…" description="Fetching model performance and drift reports." />;
  const metricByLabel = Object.fromEntries(modelPerf.metrics.map((m) => [m.label, m]));
  const cards = [
    { label: "Risk-ranking quality", value: metricByLabel["Risk ranking quality"]?.value, unit: "AUROC", icon: Target, status: modelPerf.gate === "passed" ? "Gate passed" : "Gate failed" },
    { label: "Signal attribution", value: metricByLabel["Attribution coverage"]?.value, unit: "", icon: Fingerprint, status: "Complete · live" },
    { label: "Scoring latency", value: Math.round(modelPerf.p95LatencyMs ?? 0).toString(), unit: "ms", icon: Gauge, status: "p95 · cache-served" },
    { label: "Drift alerts", value: drift.nFeaturesAlerting.toString(), unit: "features", icon: ShieldCheck, status: drift.nFeaturesAlerting ? "Needs review" : "Stable" },
  ];
  const gateRows = [
    { label: "Ranking quality gate: AUROC meets the deployment threshold", passed: modelPerf.gateChecks?.ranking_quality_ok },
    { label: "Drift monitor gate: feature drift is being tracked and validated", passed: modelPerf.gateChecks?.drift_monitor_validated },
    { label: "Attribution gate: every scored account has a top signal", passed: (modelPerf.attributionCoverage ?? 0) >= 1 },
    { label: "Latency gate: p95 scoring latency is served from cache", passed: (modelPerf.p95LatencyMs ?? 999) < 50 },
  ];
  return <>
    <div className="info-banner"><Activity size={19} /><span><strong>Live monitoring.</strong> These values are read from the churn-scoring, churn-monitoring, and churn-outcomes services — not simulated.</span></div>
    <div className="monitor-metrics">{cards.map(({ label, value, unit, icon: Icon, status }) => <section className="panel monitor-metric" key={label}><span>{label}<Icon size={18} /></span><strong>{value}<small>{unit}</small></strong><Badge tone="purple">{status}</Badge></section>)}</div>
    <section className="panel monitoring-panel">
      <SectionHeader title="Signal quality & data health" description="Catch changing inputs before they become changing outcomes." />
      <div className="tabs" role="group" aria-label="Monitoring view">{["Input drift", "Score distribution", "Release gates"].map((item) => <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item}</button>)}</div>
      {tab === "Input drift" && <>
        {drift.nFeaturesAlerting > 0 && <div className="drift-alert"><span><Activity size={20} /></span><div><strong>{drift.nFeaturesAlerting} feature{drift.nFeaturesAlerting > 1 ? "s" : ""} need a closer look</strong><p>Population stability index exceeds the {drift.alertThreshold} review threshold as of {drift.asOfDate}.</p></div><Badge tone="warning">{drift.nFeaturesAlerting} alert{drift.nFeaturesAlerting > 1 ? "s" : ""}</Badge></div>}
        <div className="table-scroll"><table><thead><tr><th>Input signal</th><th>PSI</th><th>Distribution shift</th><th>Status</th></tr></thead><tbody>
          {drift.signals.map((signal) => <tr key={signal.feature}><td><strong>{signal.name}</strong></td><td>{signal.psi.toFixed(4)}</td>
            <td><div className="drift-meter"><span style={{ width: `${Math.min(signal.psi * 250, 100)}%`, background: signal.alert ? "#d7a450" : "var(--primary)" }} /></div></td>
            <td><Badge dot tone={signal.alert ? "warning" : "success"}>{signal.alert ? "Review drift" : "Stable"}</Badge></td></tr>)}
        </tbody></table></div>
        <div className="monitor-note">PSI &lt; {drift.alertThreshold}: stable · PSI ≥ {drift.alertThreshold}: review. From churn-monitoring/data/drift_report.json, as of {drift.asOfDate}.</div>
      </>}
      {tab === "Score distribution" && <div className="score-distribution-view"><h3>Current risk bands</h3><p>Live distribution across all {totalAccounts} accounts in the latest scoring run.</p>
        {(distribution ?? []).map((d) => <div className="distribution-row" key={d.band}><span>{d.band}</span><div><span style={{ width: `${d.pct}%` }} /></div><strong>{d.count} accounts</strong></div>)}
      </div>}
      {tab === "Release gates" && <div className="release-gates">
        <div className="notice">Ranking-quality and drift gates below come from churn-outcomes/data/eval_report.json. Temporal holdout and rollback drills aren't automated yet.</div>
        {gateRows.map((gate) => <div className="release-gate" key={gate.label}><ShieldCheck size={19} /><span>{gate.label}</span><Badge tone={gate.passed ? "success" : "warning"}>{gate.passed ? "Passed" : "Review"}</Badge></div>)}
        <div className="release-gate"><ShieldCheck size={19} /><span>Temporal holdout: prevent future-data leakage</span><Badge>Planned</Badge></div>
        <div className="release-gate"><ShieldCheck size={19} /><span>Rollback gate: restore the previous model and verify parity</span><Badge>Planned</Badge></div>
        <button className="button" onClick={onGuide}>View implementation notes <ArrowRight size={15} /></button>
      </div>}
    </section>
  </>;
}
