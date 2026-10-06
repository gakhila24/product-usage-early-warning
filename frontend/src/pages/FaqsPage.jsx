import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { ac } from "../lib/api";
import { useApi } from "../lib/useApi";
import { Async, MiniStat, Panel } from "./ui";

export function FaqsView({ data, onNavigate }) {
  const [open, setOpen] = useState(0);
  return <div className="ac-grid ac-grid-2-1">
    <div className="faq-list">{data.items.map((f, i) => <article className={`panel faq-item ${open === i ? "open" : ""}`} key={f.q}>
      <button className="faq-q" aria-expanded={open === i} onClick={() => setOpen(open === i ? -1 : i)}><span>{f.q}</span><ChevronDown size={17} /></button>
      {open === i && <div className="faq-a"><p>{f.a}</p></div>}
    </article>)}</div>
    <div className="ac-stack">
      <Panel title="Quick reference" description="Start with the metric dictionary when a value is unclear or does not reconcile.">
        <div className="ac-facts two">{data.quick.map((q) => <MiniStat key={q.k} value={q.k} label={q.v} />)}</div>
        <div className="faq-links">
          <button className="text-button" onClick={() => onNavigate("Source & Methodology")}>View all metric formulas →</button>
          <button className="text-button" onClick={() => onNavigate("Overview")}>Review score bands →</button>
          <button className="text-button" onClick={() => onNavigate("Data Explorer")}>Inspect account records →</button>
        </div>
      </Panel>
      <p className="ac-foot">Answers describe the intended production design; current values remain synthetic.</p>
    </div>
  </div>;
}

export default function FaqsPage({ onNavigate }) {
  const state = useApi(() => ac.faqs(), []);
  return <Async state={state} label="Loading FAQs…">{(d) => <FaqsView data={d} onNavigate={onNavigate} />}</Async>;
}
