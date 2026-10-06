import { useEffect, useMemo, useState } from "react";
import { TriangleAlert, BookOpen, SquareCheck, CircleHelp, Mail, Workflow } from "lucide-react";
import { Modal } from "../components";
import { ac } from "../lib/api";
import { HealthBadge } from "./ui";

export const ACTION_TYPES = {
  email: {
    label: "Send Follow-Up Email", hint: "Draft outreach and track response", icon: Mail, button: "Open Email & Track", mail: true,
    subject: (a) => `Follow-up: ${a.name} health and renewal risk`,
    body: (a) => `Hi,\n\nFollowing up on ${a.name}. Current health is ${a.health} (${a.healthBand}), with ${a.topDriver} as the leading driver. Renewal is ${a.renewal} (${a.amount}).\n\nRecommended next-best action: ${a.nextBestAction}. ${a.why}\n\nCould we align on the owner and target date?\n\nThank you.`,
  },
  request: {
    label: "Request Next Action", hint: "Ask the manager for a decision", icon: CircleHelp, button: "Open Request Email & Track", mail: true,
    subject: (a) => `Decision requested: next action for ${a.name}`,
    body: (a) => `Hi,\n\nPlease confirm the next action for ${a.name}. Current health is ${a.health} (${a.healthBand}), the leading driver is ${a.topDriver}, and the renewal is ${a.renewal} (${a.amount}).\n\nRecommended next-best action: ${a.nextBestAction}.\n\nPlease reply with the owner, committed action and target date.\n\nThank you.`,
  },
  playbook: {
    label: "Assign Playbook", hint: "Start a recommended intervention", icon: BookOpen, button: "Assign & Track",
    subject: (a) => `Assign playbook: ${a.name}`,
    body: (a) => `Assign the recommended intervention for ${a.name}: ${a.nextBestAction}. Success measure: improve the leading driver (${a.topDriver}) and record a post-intervention health check before ${a.renewal}.`,
  },
  escalate: {
    label: "Escalate Risk", hint: "Raise visibility and ownership", icon: TriangleAlert, button: "Escalate & Track",
    subject: (a) => `Risk escalation: ${a.name} · ${a.healthBand}`,
    body: (a) => `${a.name} requires escalation. Health is ${a.health} (${a.healthBand}); renewal is ${a.renewal} for ${a.amount}; top driver is ${a.topDriver}. Requested decision: confirm executive owner, containment action and review date.`,
  },
  task: {
    label: "Create Task", hint: "Capture an accountable work item", icon: SquareCheck, button: "Create Task & Track",
    subject: (a) => `Complete next action for ${a.name}`,
    body: (a) => `Complete and document the next-best action for ${a.name}: ${a.nextBestAction}. Include the owner, completion date, evidence delivered and the outcome metric to monitor.`,
  },
};
const OWNER_ROLES = ["CS Manager", "Account Executive", "Solutions Consultant"];
const PLAYBOOK_OPTIONS = ["Role-based activation sprint", "Executive ROI review", "Critical renewal response", "Re-onboarding pathway", "Critical issue recovery", "Champion amplification"];

function addDays(iso, days) {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export default function ActionModal({ account, initialType = "email", asOf, onClose, onCreated, onViewMonitoring }) {
  const [type, setType] = useState(ACTION_TYPES[initialType] ? initialType : "email");
  const def = ACTION_TYPES[type];
  const [subject, setSubject] = useState(() => def.subject(account));
  const [message, setMessage] = useState(() => def.body(account));
  const [email, setEmail] = useState("");
  const [playbook, setPlaybook] = useState("recommended");
  const [ownerRole, setOwnerRole] = useState(account.ownerRole ?? "CS Manager");
  const [due, setDue] = useState(() => addDays(asOf ?? new Date().toISOString().slice(0, 10), 7));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setSubject(ACTION_TYPES[type].subject(account));
    setMessage(ACTION_TYPES[type].body(account));
  }, [type, account]);

  const playbookText = useMemo(() => (playbook === "recommended" ? account.nextBestAction : playbook), [playbook, account]);

  const submit = async (e) => {
    e.preventDefault();
    if (!subject.trim()) { setError("A subject / title is required."); return; }
    setBusy(true); setError("");
    try {
      const body = type === "playbook" && playbook !== "recommended" ? message.replace(account.nextBestAction, playbook) : message;
      const res = await ac.createFollowup({ accountId: account.id, actionType: type, subject, message: body, ownerRole, due, playbook: playbookText });
      if (def.mail) {
        const href = `mailto:${encodeURIComponent(email.trim())}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(message)}`;
        window.open(href, "_self");
      }
      onCreated?.(res);
    } catch (err) { setError(err.message || "Couldn't create the follow-up."); setBusy(false); }
  };

  return <Modal title={`${def.label} · ${account.name}`} onClose={onClose}>
    <form className="modal-content ac-action-form" onSubmit={submit}>
      <div className="ac-action-account">
        <div><strong>{account.name}</strong><small>{account.product} · {account.region} · {account.segment}</small></div>
        <HealthBadge band={account.healthBand} />
        <span className="signal-chip"><b>{account.health}</b> health</span>
        <span className="signal-chip">{account.amount} · renews {account.renewal}</span>
      </div>
      <p className="form-label">Choose action</p>
      <div className="action-choices" role="radiogroup" aria-label="Choose action">
        {Object.entries(ACTION_TYPES).map(([k, d]) => {
          const Icon = d.icon;
          return <button type="button" key={k} role="radio" aria-checked={type === k} className={`action-choice ${type === k ? "active" : ""}`} onClick={() => setType(k)}>
            <Icon size={17} /><span><b>{d.label}</b><small>{d.hint}</small></span>
          </button>;
        })}
      </div>

      {def.mail && <><label className="form-label" htmlFor="ac-mgr">Manager email</label>
        <input id="ac-mgr" className="ac-input" type="email" placeholder="manager@yourcompany.com" value={email} onChange={(e) => setEmail(e.target.value)} /></>}
      {type === "playbook" && <><label className="form-label" htmlFor="ac-pb">Playbook</label>
        <select id="ac-pb" className="ac-input" value={playbook} onChange={(e) => setPlaybook(e.target.value)}>
          <option value="recommended">Recommended: {account.nextBestAction}</option>
          {PLAYBOOK_OPTIONS.map((p) => <option key={p} value={p}>{p}</option>)}
        </select></>}

      <label className="form-label" htmlFor="ac-subject">{def.mail ? "Subject" : "Action title"}</label>
      <input id="ac-subject" className="ac-input" value={subject} maxLength={200} onChange={(e) => setSubject(e.target.value)} />
      <label className="form-label" htmlFor="ac-body">{def.mail ? "Message" : "Action details"}</label>
      <textarea id="ac-body" className="ac-input" rows={8} maxLength={1000} value={message} onChange={(e) => setMessage(e.target.value)} />

      <div className="ac-two">
        <div><label className="form-label" htmlFor="ac-owner">Action owner</label>
          <select id="ac-owner" className="ac-input" value={ownerRole} onChange={(e) => setOwnerRole(e.target.value)}>{OWNER_ROLES.map((r) => <option key={r}>{r}</option>)}</select></div>
        <div><label className="form-label" htmlFor="ac-due">Target due date</label>
          <input id="ac-due" className="ac-input" type="date" value={due} onChange={(e) => setDue(e.target.value)} /></div>
      </div>

      {error && <div className="notice ac-error" role="alert">{error}</div>}
      <div className="notice">Actions are saved to the follow-up board (SQLite). {def.mail ? "Your default mail client opens with the draft; no email is sent from this app." : "No external system is called."}</div>
      <div className="modal-actions">
        <button type="button" className="button" onClick={onClose}>Cancel</button>
        <button type="button" className="button" onClick={() => { onViewMonitoring?.(); }}><Workflow size={15} />View Monitoring</button>
        <button type="submit" className="button primary" disabled={busy}>{busy ? "Saving…" : def.button}</button>
      </div>
    </form>
  </Modal>;
}
