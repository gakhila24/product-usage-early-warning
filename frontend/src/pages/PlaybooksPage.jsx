import { useState } from "react";
import { ArrowRight, BookOpen, CalendarClock, Layers, LifeBuoy, RefreshCw, Sparkles, Target, Users, Zap } from "lucide-react";
import { Badge, Modal } from "../components";
import { ac } from "../lib/api";
import { useApi } from "../lib/useApi";
import { Async, Segmented, nf } from "./ui";
import { Playbooks as ModelPlays } from "../Views";

const ICONS = { zap: Zap, target: Target, "calendar-clock": CalendarClock, "refresh-cw": RefreshCw, "life-buoy": LifeBuoy, users: Users, layers: Layers };

export function HealthPlaybooks({ data, onLaunch }) {
  return <>
    <div className="info-banner"><Sparkles size={19} /><span><strong>Recommended interventions</strong> connected to the leading risk and adoption signals. Eligibility counts apply each playbook's trigger and exclude accounts that already have an open follow-up.</span></div>
    <div className="playbooks-grid">{data.playbooks.map((p) => {
      const Icon = ICONS[p.icon] ?? BookOpen;
      return <section className="panel playbook-card" key={p.id}>
        <div className="playbook-top"><span className={`playbook-icon ${p.color}`}><Icon size={23} /></span><Badge tone="purple" dot>{p.category}</Badge></div>
        <h2>{p.title}</h2><p>{p.description}</p>
        <div className="eligible"><b>{nf(p.eligible)}</b><span>eligible accounts · {p.eligibleArrLabel} ARR{p.suppressed ? ` · ${p.suppressed} suppressed` : ""}</span></div>
        <div className="trigger">Trigger · {p.trigger}</div>
        <button className="button primary" disabled={p.eligible === 0} onClick={() => onLaunch(p)}>Launch <ArrowRight size={16} /></button>
      </section>;
    })}</div>
  </>;
}

export function LaunchHealthPlaybook({ playbook, onClose, onLaunch }) {
  const [id, setId] = useState(playbook.topAccounts[0]?.id ?? "");
  const [busy, setBusy] = useState(false);
  return <Modal title={`Launch · ${playbook.title}`} onClose={onClose}>
    <form className="modal-content launch-form" onSubmit={async (e) => { e.preventDefault(); setBusy(true); await onLaunch(playbook, id); }}>
      <Badge tone="purple">{playbook.category}</Badge><h3>{playbook.title}</h3><p>{playbook.description}</p>
      <label className="form-label" htmlFor="hp-acct">Choose an account (top priority among eligible)</label>
      <select id="hp-acct" value={id} onChange={(e) => setId(e.target.value)}>{playbook.topAccounts.map((a) => <option key={a.id} value={a.id}>{a.name} — health {a.health} · {a.amount}</option>)}</select>
      <div className="notice">Creates a tracked follow-up in the "Action committed" stage. Trigger: {playbook.trigger}.</div>
      <button className="button primary" type="submit" disabled={busy || !id}>Launch playbook</button>
    </form>
  </Modal>;
}

export default function PlaybooksPage({ filters, plays, onLaunchModel, notify, bump, refreshCounts, refreshKey }) {
  const [tab, setTab] = useState("health");
  const [modal, setModal] = useState(null);
  const state = useApi(() => ac.playbooks(filters), [JSON.stringify(filters), refreshKey]);
  return <>
    <div className="ac-toolbar"><Segmented ariaLabel="Playbook set" value={tab} onChange={setTab} options={[{ value: "health", label: "Customer-health playbooks" }, { value: "model", label: "Model-recommended plays" }]} /></div>
    {tab === "health"
      ? <Async state={state} label="Loading playbooks…">{(d) => <><HealthPlaybooks data={d} onLaunch={setModal} />
        {modal && <LaunchHealthPlaybook playbook={modal} onClose={() => setModal(null)} onLaunch={async (p, accountId) => {
          try { await ac.launchPlaybook(p.id, { accountId }); notify(`${p.title} launched. Track it in Follow-Up Monitoring.`); bump(); refreshCounts(); } catch (e) { notify(e.message); }
          setModal(null); }} />}</>}</Async>
      : <ModelPlays plays={plays} onLaunch={onLaunchModel} />}
  </>;
}
