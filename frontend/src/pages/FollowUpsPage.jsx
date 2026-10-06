import { useState } from "react";
import { ArrowRight, Plus, RotateCcw, Trash2 } from "lucide-react";
import { ac } from "../lib/api";
import { useApi, useDebounced } from "../lib/useApi";
import { Async, HealthBadge, MiniStat, Panel, SearchInput, Select, nf } from "./ui";

function History({ id }) {
  const [open, setOpen] = useState(false);
  const state = useApi(() => (open ? ac.followupEvents(id) : Promise.resolve(null)), [open, id]);
  return <div className="fu-history">
    <button className="text-button" onClick={() => setOpen(!open)}>{open ? "Hide history" : "History"}</button>
    {open && (state.data ? <ul>{state.data.events.map((e, i) => <li key={i}><b>{e.event}</b> · {e.detail}<small>{String(e.ts).replace("T", " ")} UTC</small></li>)}</ul> : <small>Loading…</small>)}
  </div>;
}

export function Board({ data, onAdvance, onMove, onRemove, onSelect }) {
  const stages = data.stages;
  return <div className="follow-board">
    {stages.map((st, si) => {
      const cards = data.items.filter((x) => x.status === st.name);
      return <section className="follow-column" key={st.name} style={{ "--stage": st.color }}>
        <div className="column-head"><div><b>{st.name}</b><span>{st.hint}</span></div><i className="stage-count">{cards.length}</i></div>
        <div className="column-body">
          {cards.length === 0 && <p className="column-empty">Nothing here.</p>}
          {cards.map((f) => <article className="follow-card" key={f.id}>
            <div className="fc-top"><span className="fc-id">{f.id}</span><HealthBadge band={f.healthBand} /></div>
            <button className="fc-account" onClick={() => onSelect(f.accountId)}>{f.account}</button>
            <p className="fc-action">{f.action}</p>
            <p className="fc-note">{f.note}</p>
            <div className="fc-meta"><span>{f.ownerRole} · {f.ownerName}</span><span>Due {f.dueLabel}</span><span>{f.amount} · renews {f.renewal}</span></div>
            <div className="fc-actions">
              {si < stages.length - 1 && <button className="button small primary" onClick={() => onAdvance(f)}>Move to {stages[si + 1].name} <ArrowRight size={13} /></button>}
              <select aria-label={`Move ${f.id} to stage`} className="ac-select mini" value={f.status} onChange={(e) => onMove(f, e.target.value)}>{stages.map((s) => <option key={s.name}>{s.name}</option>)}</select>
              <button className="icon-button" aria-label={`Remove ${f.id}`} title="Remove follow-up" onClick={() => onRemove(f)}><Trash2 size={15} /></button>
            </div>
            <History id={f.id} />
          </article>)}
        </div>
      </section>;
    })}
  </div>;
}

export function NbaPanel({ nba, onNavigate }) {
  return <div className="ac-grid ac-grid-2">
    <Panel title="Recommended next-best actions" description="Ranked by risk, value, RFM engagement and response state · rule-based" right={<span className="badge purple">rule-based</span>}>
      <ol className="nba-list">{nba.map((n) => <li key={n.accountId}><i className="rank">{n.rank}</i><div><b>{n.account} · {n.action}</b><span>{n.why}</span></div><strong className="priority-score">{n.priority}</strong></li>)}</ol>
    </Panel>
    <Panel title="Decision guidance" description="Use recommendations as a starting point. Review context before sending or committing an intervention.">
      <ul className="guidance"><li>Protect near-term, high-value renewals first.</li><li>Match action to the dominant health driver.</li><li>Set a due date and success measure before outreach.</li><li>Move to Monitoring only after the intervention is delivered.</li><li>Close after the outcome window has elapsed.</li></ul>
      <button className="text-button" onClick={() => onNavigate("Interventions")}>Review intervention impact <ArrowRight size={14} /></button>
    </Panel>
  </div>;
}

export default function FollowUpsPage({ filters, onNavigate, onSelect, notify, refreshCounts, refreshKey, bump }) {
  const [role, setRole] = useState("all");
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const key = JSON.stringify(filters);
  const board = useApi(() => ac.followups(filters, { role, q: dq }), [key, role, dq, refreshKey]);
  const queue = useApi(() => ac.queue(filters, { page: 1, page_size: 1 }), [key, refreshKey]);
  const run = async (fn, msg) => { try { await fn(); notify(msg); bump(); refreshCounts(); } catch (e) { notify(e.message || "That change couldn't be saved."); } };
  return <>
    <section className="panel action-hero">
      <div><span className="card-eyebrow">ACTION STATUS CONTROL</span><h2>Every action created from the account queue lands here with an owner and status.</h2>
        <p>Status changes are saved to the database. Move a card forward after outreach, manager response, task completion or intervention delivery.</p></div>
      {board.data && <div className="ac-facts three"><MiniStat value={board.data.stats.open} label="open follow-ups" /><MiniStat value={board.data.stats.dueIn7} label="due in 7 days" tone="warn" /><MiniStat value={board.data.stats.closed} label="closed / validated" /></div>}
      <div className="hero-actions">
        <button className="button" onClick={() => run(() => ac.resetFollowups(), "Sample follow-ups restored.")}><RotateCcw size={15} />Reset sample state</button>
        <button className="button primary" onClick={() => onNavigate("Accounts")}><Plus size={15} />Add from account queue</button>
      </div>
    </section>
    <div className="ac-toolbar">
      <div className="ac-tools"><SearchInput value={q} onChange={setQ} placeholder="Search account, action, owner" />
        <Select label="Owner" value={role} onChange={setRole} options={[{ value: "all", label: "All owners" }, "CS Manager", "Account Executive", "Solutions Consultant"]} /></div>
      <span className="ac-muted">Stages: Needs outreach → Waiting → Committed → Monitoring → Closed</span>
    </div>
    <Async state={board} label="Loading follow-up board…">{(d) => <Board data={d}
      onAdvance={(f) => run(() => ac.advanceFollowup(f.id), `${f.account} moved forward.`)}
      onMove={(f, status) => run(() => ac.updateFollowup(f.id, { status }), `${f.account} moved to ${status}.`)}
      onRemove={(f) => { if (window.confirm(`Remove follow-up ${f.id} for ${f.account}?`)) run(() => ac.deleteFollowup(f.id), `${f.id} removed.`); }}
      onSelect={onSelect} />}</Async>
    {queue.data && <NbaPanel nba={queue.data.nba} onNavigate={onNavigate} />}
  </>;
}
