import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, Bell, Briefcase, CalendarClock, ChevronRight, CircleHelp, ClipboardCheck, Database, FileClock,
  FileText, Fingerprint, Layers, LayoutDashboard, Menu, Plus, Radio, Search, Settings, TrendingDown, TrendingUp, Users, Workflow, BookOpen,
} from "lucide-react";
import { accountColor, accountsCsv, filterAccounts } from "./data";
import { Badge, Modal, RiskBadge, Spinner, StepList, Toast } from "./components";
import { DashboardBottom, DashboardCharts } from "./Dashboard";
import Evaluation from "./Evaluation";
import { AccountDetail, ActivityLog, LaunchForm, OutcomeForm } from "./Views";
import ChurnChat from "./ChurnChat";
import * as api from "./lib/api";
import { Segmented } from "./pages/ui";
import { DEFAULT_FILTERS, FilterBar, FilterDrawer } from "./pages/Filters";
import ActionModal from "./pages/ActionModal";
import OverviewPage from "./pages/OverviewPage";
import PortfolioPage from "./pages/PortfolioPage";
import AccountsPage from "./pages/AccountsPage";
import FollowUpsPage from "./pages/FollowUpsPage";
import InterventionsPage from "./pages/InterventionsPage";
import AlertsPage from "./pages/AlertsPage";
import RenewalsPage from "./pages/RenewalsPage";
import PlaybooksPage from "./pages/PlaybooksPage";
import ReportsPage from "./pages/ReportsPage";
import DataExplorerPage from "./pages/DataExplorerPage";
import MethodologyPage from "./pages/MethodologyPage";
import FaqsPage from "./pages/FaqsPage";
import SettingsPage from "./pages/SettingsPage";
import "./App.css";
import "./theme.css";
import "./ActionCenter.css";

const navGroups = [
  { caption: "MONITOR", items: [{ name: "Overview", icon: LayoutDashboard }, { name: "Portfolio", icon: Briefcase }, { name: "Accounts", icon: Users }, { name: "Follow-Up Monitoring", icon: ClipboardCheck, badge: "followups" }, { name: "Interventions", icon: TrendingUp }] },
  { caption: "ANALYZE", items: [{ name: "Alerts", icon: Bell, badge: "alerts" }, { name: "Renewals", icon: CalendarClock }] },
  { caption: "ACT", items: [{ name: "Playbooks", icon: Workflow }, { name: "Reports", icon: FileText }, { name: "Activity log", icon: FileClock }] },
  { caption: "MODEL & DATA", items: [{ name: "Evaluation", icon: Activity }, { name: "Data Explorer", icon: Database }] },
  { caption: "GOVERN", items: [{ name: "Source & Methodology", icon: BookOpen }, { name: "FAQs", icon: CircleHelp }] },
];
const FILTERED_PAGES = new Set(["Overview", "Portfolio", "Accounts", "Follow-Up Monitoring", "Interventions", "Renewals", "Playbooks", "Reports", "Data Explorer"]);
const titles = {
  Overview: ["Customer Health Overview", "Real-time view of customer health, risk and retention for your portfolio — including health score bands, churn and adoption drivers, and segment comparisons."],
  Portfolio: ["Portfolio", "Compare health, risk and retention across products and regions."],
  Accounts: ["Account Action Center", "Move from health signal to accountable follow-through at the account level."],
  "Follow-Up Monitoring": ["Follow-Up Monitoring", "Track every generated account action across five clear operating stages."],
  Interventions: ["Intervention Effectiveness", "Compare pre/post health movement and adoption response after each tracked action."],
  Alerts: ["Alerts", "Prioritized changes that require owner review or intervention."],
  Renewals: ["Renewals", "Near-term pipeline, health exposure and owner actions."],
  Playbooks: ["The right action, at the right time.", "Recommended interventions connected to the leading risk and adoption signals."],
  Reports: ["Reports", "Create focused portfolio, renewal and driver views from the active filters."],
  Evaluation: ["Understand the evidence behind the scores.", "What we evaluate, how we measure it, and what the results can tell us."],
  "Activity log": ["Small actions. Lasting impact.", "Live actions from the outcomes log, plus anything you launch this session."],
  "Data Explorer": ["Data Explorer", "Inspect the synthetic account records behind this dashboard."],
  "Source & Methodology": ["Source & Methodology", "Metric definitions, formulas, lineage and operating rules for the Customer Health dashboard."],
  FAQs: ["Frequently Asked Questions", "How to interpret, validate and use the Customer Health dashboard responsibly."],
  Settings: ["Make Signal work for you.", "Manage your personal workspace preferences."],
};
const defaultPreferences = { compact: false, reminders: true };

function readStorage(key, fallback, validate) {
  try { const value = JSON.parse(localStorage.getItem(key)); return validate(value) ? value : fallback; } catch { return fallback; }
}
function validLocalActions(value) {
  return Array.isArray(value) && value.every((a) => a && typeof a.id === "string" && typeof a.accountId === "string" && typeof a.playbookId === "string" && ["In progress", "Retained", "Monitoring", "Churned"].includes(a.status) && typeof a.note === "string" && Number.isFinite(Date.parse(a.date)));
}

function App() {
  const [page, setPage] = useState("Overview");
  const [overviewTab, setOverviewTab] = useState("health");
  const [query, setQuery] = useState("");
  const [band, setBand] = useState("All accounts");
  const [plan, setPlan] = useState("All plans");
  const [industry, setIndustry] = useState("All industries");
  const [region, setRegion] = useState("All regions");
  const [sort, setSort] = useState("risk");
  const [mobileNav, setMobileNav] = useState(false);
  const [notifications, setNotifications] = useState(false);
  const [notificationsRead, setNotificationsRead] = useState(false);
  const [dialog, setDialog] = useState(null);
  const [toast, setToast] = useState("");
  const [localActions, setLocalActionsState] = useState(() => readStorage("churn-actions-v1", [], validLocalActions));
  const [preferences, setPreferencesState] = useState(() => readStorage("churn-preferences-v1", defaultPreferences, (v) => v && typeof v.compact === "boolean" && typeof v.reminders === "boolean"));
  const [summary, setSummary] = useState([]);
  const [distribution, setDistribution] = useState([]);
  const [trend, setTrend] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [plays, setPlays] = useState([]);
  const [recentActions, setRecentActions] = useState([]);
  const [drift, setDrift] = useState(null);
  const [meta, setMeta] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [detail, setDetail] = useState(null);
  const [acContext, setAcContext] = useState(null);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [filterOptions, setFilterOptions] = useState(null);
  const [counts, setCounts] = useState({ followups: 0, alerts: 0 });
  const [acSettings, setAcSettings] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const searchRef = useRef(null);
  const toastTimer = useRef(null);
  const closeDialog = useCallback(() => setDialog(null), []);
  const notify = useCallback((message) => { clearTimeout(toastTimer.current); setToast(message); toastTimer.current = setTimeout(() => setToast(""), 4500); }, []);
  const bump = useCallback(() => setRefreshKey((k) => k + 1), []);
  useEffect(() => () => clearTimeout(toastTimer.current), []);

  const refreshCounts = useCallback(() => {
    Promise.all([api.ac.followups(DEFAULT_FILTERS), api.ac.alerts({ status: "open" })])
      .then(([fu, al]) => setCounts({ followups: fu.stats.open, alerts: al.open }))
      .catch(() => { /* counts are cosmetic; pages surface their own errors */ });
  }, []);

  useEffect(() => {
    Promise.all([
      api.getSummary(), api.getRiskDistribution(), api.getRiskTrend(), api.getAccounts(),
      api.getPlays(), api.getRecentActions(), api.getDrift(), api.getMeta(),
    ])
      .then(([summaryRes, distributionRes, trendRes, accountsRes, playsRes, actionsRes, driftRes, metaRes]) => {
        setSummary(summaryRes); setDistribution(distributionRes); setTrend(trendRes); setAccounts(accountsRes);
        setPlays(playsRes); setRecentActions(actionsRes); setDrift(driftRes); setMeta(metaRes);
      })
      .catch((err) => {
        console.error(err);
        setLoadError("Couldn't reach the churn-scoring API. Is the Flask API running (see /src/api.py, python api.py — or use RUN_PROJECT.bat)?");
      });
    api.ac.filters().then(setFilterOptions).catch((e) => console.error(e));
    api.ac.settings().then(setAcSettings).catch((e) => console.error(e));
    refreshCounts();
  }, [refreshCounts]);

  const selectedAccount = dialog?.type === "account" ? dialog.id : null;
  useEffect(() => {
    if (!selectedAccount) { setDetail(null); setAcContext(null); return; }
    setDetail(null); setAcContext(null);
    api.getAccountDetail(selectedAccount).then((raw) => setDetail({ ...raw, color: accountColor(selectedAccount) })).catch((err) => { console.error(err); notify("Couldn't load that account's detail."); });
    api.ac.account(selectedAccount).then(setAcContext).catch((err) => console.error(err));
  }, [selectedAccount, notify, refreshKey]);

  useEffect(() => {
    const keydown = (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "k") { e.preventDefault(); searchRef.current?.focus(); } if (e.key === "Escape") { setNotifications(false); setMobileNav(false); } };
    document.addEventListener("keydown", keydown);
    return () => document.removeEventListener("keydown", keydown);
  }, []);

  const saveLocally = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; } };
  const setLocalActions = (next) => {
    const value = typeof next === "function" ? next(localActions) : next;
    setLocalActionsState(value);
    return saveLocally("churn-actions-v1", value);
  };
  const setPreferences = (value) => {
    setPreferencesState(value);
    if (!saveLocally("churn-preferences-v1", value)) notify("Browser storage unavailable. Preferences last for this session only.");
  };

  const resetFilters = () => { setQuery(""); setBand("All accounts"); setPlan("All plans"); setIndustry("All industries"); setRegion("All regions"); setSort("risk"); };
  const navigate = (destination) => { setPage(destination); setMobileNav(false); setNotifications(false); window.scrollTo?.({ top: 0 }); };
  const viewBand = (value) => { navigate("Accounts"); resetFilters(); setBand(value); };
  const viewHealthBand = (value) => { setFilters((f) => ({ ...f, risk: value })); navigate("Data Explorer"); };
  const showAccount = (id) => setDialog({ type: "account", id });
  const showLaunch = (playbookId) => setDialog({ type: "launch", playbookId });
  const openAction = (row, type = "email") => setDialog({ type: "action", row, actionType: type });

  const launch = (accountId, playbookId) => {
    if (localActions.some((a) => a.accountId === accountId && a.playbookId === playbookId && a.status === "In progress")) { notify("This playbook is already in progress for this account."); return; }
    const saved = setLocalActions((previous) => [{ id: crypto.randomUUID(), accountId, playbookId, date: new Date().toISOString(), status: "In progress", note: "Playbook launched. Awaiting the first customer touchpoint." }, ...previous]);
    const play = plays.find((p) => p.id === playbookId);
    const acct = accounts.find((a) => a.id === accountId);
    if (play) api.logIntervention(accountId, play.title, acct?.csmOwner ?? "CS Manager").then(() => api.getRecentActions().then(setRecentActions)).catch((e) => console.error(e));
    closeDialog(); notify(saved ? "Playbook launched and logged. Track next steps in the activity log." : "Playbook launched for this session. Browser storage is unavailable.");
  };

  const exportAccounts = () => {
    const decorated = accounts.map((a) => ({ ...a, color: accountColor(a.id) }));
    const filtered = filterAccounts(decorated, { query, band, plan, industry, region, sort });
    const url = URL.createObjectURL(new Blob(["\uFEFF" + accountsCsv(filtered)], { type: "text/csv;charset=utf-8;" }));
    const link = document.createElement("a"); link.href = url; link.download = "churn-account-risk.csv"; document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    notify(`Exported ${filtered.length} accounts.`);
  };

  const combinedActions = useMemo(() => {
    const local = localActions.map((a) => {
      const account = accounts.find((acc) => acc.id === a.accountId);
      const play = plays.find((p) => p.id === a.playbookId);
      return { id: a.id, accountId: a.accountId, account: account?.name ?? a.accountId, play: play?.title ?? a.playbookId, status: a.status, note: a.note, date: a.date, local: true };
    });
    const real = recentActions.map((a, i) => ({ id: `log-${i}`, accountId: a.accountId, account: a.account, play: a.play, status: a.status, note: a.action, date: a.date, local: false }));
    return [...local, ...real];
  }, [localActions, recentActions, accounts, plays]);

  const totalAccounts = accounts.length;
  const criticalAccount = accounts.find((a) => a.band === "Critical");
  const arrTotal = accounts.reduce((sum, a) => sum + (a.arr ?? 0), 0);
  const criticalTotal = accounts.filter((a) => a.band === "Critical").length;
  const showFilters = FILTERED_PAGES.has(page);
  const heading = titles[page] ?? titles.Overview;

  if (loadError) {
    return <div className="app-shell" style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
      <p style={{ maxWidth: 420, textAlign: "center", color: "var(--muted)" }}>{loadError}</p>
    </div>;
  }

  const registerProps = {
    page: "Accounts", accounts, query, setQuery, band, setBand, plan, setPlan, industry, setIndustry, region, setRegion, sort, setSort,
    compact: preferences.compact, onSelect: showAccount, onGuide: () => setDialog({ type: "guide" }),
  };
  const common = { filters, onNavigate: navigate, onSelectAccount: showAccount, onSelect: showAccount, onAction: openAction, notify, bump, refreshCounts, refreshKey };
  const modelView = summary.length
    ? <><DashboardCharts summary={summary} distribution={distribution} trend={trend} totalAccounts={totalAccounts} viewRisk={() => viewBand("Critical")} viewBand={viewBand} />
      {plays.length > 0 && <DashboardBottom navigate={navigate} onLaunch={showLaunch} plays={plays} driftCount={drift?.nFeaturesAlerting ?? 0} />}</>
    : <Spinner label="Loading portfolio metrics…" />;

  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to content</a>
    {mobileNav && <button className="sidebar-scrim" aria-label="Close navigation" onClick={() => setMobileNav(false)} />}
    <aside className={`sidebar sidebar-icons ${mobileNav ? "open" : ""}`} aria-label="Main navigation">
      <button className="brand" onClick={() => navigate("Overview")} aria-label="Signal home" title="Signal home"><span className="brand-mark"><Radio size={24} strokeWidth={2.5} /></span><span className="brand-word nav-label">Signal<i className="brand-period">.</i></span></button>
      <button className="workspace-switch" onClick={() => setDialog({ type: "workspace" })} aria-label="Churn early warning workspace" title="Churn early warning workspace"><span className="workspace-logo"><Layers size={18} /></span><span className="nav-label ws-text"><strong>Customer Health</strong><small>Churn early warning</small></span></button>
      <nav>{navGroups.map((g) => <div className="nav-group" key={g.caption}>
        <div className="nav-caption" aria-hidden="true"><span>{g.caption}</span></div>
        {g.items.map(({ name, icon: Icon, badge }) => {
          const n = badge ? counts[badge] : 0;
          return <button key={name} className={`nav-item ${page === name ? "active" : ""}`} aria-label={name} title={name} aria-current={page === name ? "page" : undefined} onClick={() => navigate(name)}>
            <Icon size={20} strokeWidth={1.75} /><span className="nav-label">{name}</span>
            {n > 0 && <span className="nav-badge">{n > 99 ? "99+" : n}</span>}
          </button>;
        })}
      </div>)}</nav>
      <div className="sidebar-bottom">
        <button className={`nav-item ${page === "Settings" ? "active" : ""}`} aria-label="Settings" title="Settings" aria-current={page === "Settings" ? "page" : undefined} onClick={() => navigate("Settings")}><Settings size={20} strokeWidth={1.75} /><span className="nav-label">Settings</span></button>
        <button className="nav-item" aria-label="Help & getting started" title="Help & getting started" onClick={() => setDialog({ type: "guide" })}><CircleHelp size={20} strokeWidth={1.75} /><span className="nav-label">Help & getting started</span></button>
        <div className="user-profile"><button className="nav-item" aria-label="Profile and workspace" title="Profile and workspace" onClick={() => setDialog({ type: "workspace" })}><Fingerprint size={20} strokeWidth={1.75} /><span className="nav-label">Workspace</span></button></div>
      </div>
    </aside>
    <div className="main-shell">
      <header className="topbar">
        <div className="breadcrumb"><button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setMobileNav(true)}><Menu size={20} /></button><span className="breadcrumb-workspace">Workspace</span><ChevronRight size={13} /><strong>{page}</strong></div>
        <div className="topbar-actions">
          <div className="global-search"><Search size={17} /><input ref={searchRef} aria-label="Search accounts" placeholder="Search accounts…" value={query} onChange={(e) => { setQuery(e.target.value); if (page !== "Accounts") { navigate("Accounts"); } }} /><kbd>Ctrl K</kbd></div>
          <span className="topbar-divider" />
          <div className="notification-wrap">
            <button className="icon-button notification-button" aria-label="Notifications" aria-expanded={notifications} onClick={() => setNotifications(!notifications)}><Bell size={19} />{!notificationsRead && <span />}</button>
            {notifications && <div className="notification-popover">
              <div className="popover-title"><h3>Notifications</h3><Badge tone="purple">Live</Badge></div>
              {counts.alerts > 0 && <button className="notification-item" onClick={() => { setNotificationsRead(true); navigate("Alerts"); }}><span className="notification-icon"><Bell size={18} /></span><span><strong>{counts.alerts} open alerts</strong><small>Review score movements, renewals and support signals.</small></span><ChevronRight size={15} /></button>}
              {criticalAccount && <button className="notification-item" onClick={() => { setNotificationsRead(true); setNotifications(false); showAccount(criticalAccount.id); }}><span className="notification-icon"><TrendingDown size={18} /></span><span><strong>{criticalAccount.name} needs attention</strong><small>Risk score {criticalAccount.score}, {criticalAccount.wow >= 0 ? "+" : ""}{criticalAccount.wow} pts this run.</small></span><ChevronRight size={15} /></button>}
              {drift?.nFeaturesAlerting > 0 && <div className="notification-item"><span className="notification-icon blue"><Activity size={18} /></span><span><strong>Feature drift detected</strong><small>{drift.nFeaturesAlerting} feature{drift.nFeaturesAlerting === 1 ? "" : "s"} exceeded the PSI threshold.</small></span></div>}
              <button className="text-button mark-read" onClick={() => { setNotificationsRead(true); setNotifications(false); notify("All notifications marked as read."); }}>Mark all as read</button>
            </div>}
          </div>
          <button className="avatar top-avatar" aria-label="Open profile" onClick={() => setDialog({ type: "workspace" })}>CS</button>
        </div>
      </header>
      <main id="main-content" tabIndex={-1}>
        <div className="page-heading">
          <div><div className="eyebrow"><span />CUSTOMER INTELLIGENCE</div><h1>{heading[0]}</h1><p>{heading[1]}</p></div>
          <div className="heading-actions">
            {page === "Overview" && <button className="button primary" onClick={() => navigate("Reports")}>Send filtered report</button>}
            {page === "Accounts" && <button className="button primary" onClick={() => navigate("Follow-Up Monitoring")}><ClipboardCheck size={15} />Monitor follow-ups</button>}
            {page === "Interventions" && <button className="button" onClick={() => navigate("Follow-Up Monitoring")}>Open follow-up board</button>}
            {page === "Activity log" && plays.length > 0 && <button className="button primary" onClick={() => showLaunch(plays[0].id)}><Plus size={16} />Launch a playbook</button>}
          </div>
        </div>
        {showFilters && <FilterBar options={filterOptions} filters={filters} onChange={setFilters} onOpenDrawer={() => setDialog({ type: "filters" })} />}

        {page === "Overview" && <>
          <div className="ac-toolbar"><Segmented ariaLabel="Overview view" value={overviewTab} onChange={setOverviewTab} options={[{ value: "health", label: "Customer health" }, { value: "model", label: "Early-warning model" }]} /></div>
          {overviewTab === "health" ? <OverviewPage {...common} onSelectRiskBand={viewHealthBand} settings={acSettings} /> : modelView}
        </>}
        {page === "Portfolio" && <PortfolioPage filters={filters} />}
        {page === "Accounts" && <AccountsPage {...common} registerProps={registerProps} onExportRegister={exportAccounts} />}
        {page === "Follow-Up Monitoring" && <FollowUpsPage {...common} />}
        {page === "Interventions" && <InterventionsPage filters={filters} onNavigate={navigate} />}
        {page === "Alerts" && <AlertsPage {...common} />}
        {page === "Renewals" && <RenewalsPage {...common} />}
        {page === "Playbooks" && <PlaybooksPage {...common} plays={plays} onLaunchModel={showLaunch} />}
        {page === "Reports" && <ReportsPage filters={filters} notify={notify} />}
        {page === "Evaluation" && <Evaluation />}
        {page === "Activity log" && <ActivityLog actions={combinedActions} onSelect={showAccount} onOutcome={(action) => setDialog({ type: "outcome", action })} />}
        {page === "Data Explorer" && <DataExplorerPage filters={filters} onSelect={showAccount} />}
        {page === "Source & Methodology" && <MethodologyPage onNavigate={navigate} />}
        {page === "FAQs" && <FaqsPage onNavigate={navigate} />}
        {page === "Settings" && <SettingsPage preferences={preferences} setPreferences={setPreferences} settings={acSettings} onSettings={setAcSettings} notify={notify}
          onReset={() => setDialog({ type: "reset" })} onRoadmap={() => setDialog({ type: "roadmap" })} />}
        <footer className="page-footer"><span><Radio size={13} />A little signal. A lot of clarity.</span><div><span className="demo-pill">SYNTHETIC DATA</span><span>Snapshot · {meta?.asOf ?? "loading…"}</span></div></footer>
      </main>
    </div>
    {selectedAccount && <Modal title="Account intelligence" onClose={closeDialog} drawer><AccountDetail id={selectedAccount} detail={detail} reminders={preferences.reminders} localActions={localActions} onLaunch={(accId) => launch(accId, detail?.play?.key)} acContext={acContext} onAction={(row, type) => openAction(row, type)} /></Modal>}
    {dialog?.type === "filters" && filterOptions && <FilterDrawer options={filterOptions} filters={filters} onClose={closeDialog} onApply={(f) => { setFilters(f); closeDialog(); }} />}
    {dialog?.type === "action" && <ActionModal account={dialog.row} initialType={dialog.actionType} asOf={filterOptions?.asOf} onClose={closeDialog}
      onViewMonitoring={() => { closeDialog(); navigate("Follow-Up Monitoring"); }}
      onCreated={(res) => { closeDialog(); notify(`${res.created ? "Follow-up created" : "Follow-up updated"} for ${res.account} — ${res.status}.`); bump(); refreshCounts(); }} />}
    {dialog?.type === "launch" && <Modal title="Launch a playbook" onClose={closeDialog}><LaunchForm playbook={plays.find((p) => p.id === dialog.playbookId)} accounts={accounts} onLaunch={launch} /></Modal>}
    {dialog?.type === "outcome" && <Modal title="Capture the outcome" onClose={closeDialog}><OutcomeForm action={dialog.action} onSave={(status, note) => { if (dialog.action.local) { const saved = setLocalActions(localActions.map((a) => a.id === dialog.action.id ? { ...a, status, note } : a)); closeDialog(); notify(saved ? "Outcome recorded for this session." : "Outcome recorded for this session. Browser storage is unavailable."); } else { closeDialog(); notify("This action comes from the live log — outcome editing isn't wired to the outcomes service yet."); } }} /></Modal>}
    {dialog?.type === "reset" && <Modal title="Reset session activity?" onClose={closeDialog}><div className="modal-content"><p>This removes playbooks you launched in this browser this session. The live actions log and preferences are not affected. This cannot be undone.</p><div className="modal-actions"><button className="button" onClick={closeDialog}>Cancel</button><button className="button primary" onClick={() => { setLocalActions([]); closeDialog(); notify("Session activity cleared."); }}>Reset session</button></div></div></Modal>}
    {dialog?.type === "workspace" && <Modal title="Your workspace" onClose={closeDialog}><div className="modal-content workspace-details"><span className="workspace-logo"><Layers size={25} /></span><h3>Customer Health · Churn early warning</h3><Badge tone="purple">Connected to churn-scoring API</Badge><p>This workspace reads live account scores, signals, follow-ups, alerts and playbooks from the churn-scoring service (model {meta?.modelVersion ?? "…"}). All data is synthetic. Authentication and team management aren't wired up yet.</p><button className="button" onClick={() => { closeDialog(); navigate("Settings"); }}><Settings size={15} />Workspace preferences</button></div></Modal>}
    {dialog?.type === "guide" && <Modal title="A clearer picture, before the renewal" onClose={closeDialog}><div className="modal-content guide-content"><div className="guide-hero"><Fingerprint size={31} /><span>Understand the why.<br /><strong>Choose your next step.</strong></span></div><p>Signal brings usage decay, feature abandonment, support friction, RFM engagement and renewal timing into one account view, scored live by the churn-scoring model.</p><h3>How to read a risk band</h3><div className="risk-guide"><RiskBadge band="Critical" /><span>Prioritize a personal check-in this week.</span><RiskBadge band="High" /><span>Investigate the top signal soon.</span><RiskBadge band="Medium" /><span>Monitor closely, no urgent action yet.</span><RiskBadge band="Low" /><span>Maintain healthy engagement.</span></div><h3>Try the workflow</h3><StepList steps={["Open Accounts → Action queue and pick an at-risk account.", "Draft a follow-up, request a decision or assign a playbook.", "Track it on the Follow-Up Monitoring board and review the impact under Interventions."]} /><p className="notice">Scores, signals, follow-ups, alerts and reports are served by the Flask API and stored in SQLite. Everything is synthetic.</p></div></Modal>}
    {dialog?.type === "roadmap" && <Modal title="From prototype to production" onClose={closeDialog}><div className="modal-content"><Badge tone="success">Connected · all pages live</Badge><p className="roadmap-intro">This workspace reads from the real churn-scoring services over a synthetic dataset.</p><StepList steps={["UI foundation — responsive dashboards and workflows. Done.", "Synthetic data — seeded generator for accounts, telemetry, revenue, interventions. Done.", "Risk scoring + API — churn-scoring serves live scores and attribution. Done.", "Customer-health layer — health bands, RFM, drivers, renewals, alerts, reports. Done.", "Follow-up workflow — actions, board, interventions and effectiveness persisted in SQLite. Done.", "Evaluation + monitoring — ranking quality, gains, PSI drift. Done.", "Remaining for production: real source systems, authentication, CI release gates with canary rollout + rollback."]} /></div></Modal>}
    <Toast message={toast} />
    <ChurnChat />
  </div>;
}

export default App;
