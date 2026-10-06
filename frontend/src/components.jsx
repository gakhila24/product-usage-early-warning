import { useEffect, useId, useRef } from "react";
import { ArrowDownLeft, ArrowUpRight, X, Check, ChevronRight } from "lucide-react";
import { BAND_TONE } from "./data";

export function Badge({ children, tone = "neutral", dot = false }) {
  return <span className={`badge ${tone}`}>{dot && <span className="status-dot" />}{children}</span>;
}

export function RiskBadge({ band }) {
  return <Badge tone={BAND_TONE[band] ?? "neutral"} dot>{band}</Badge>;
}

export function AccountLogo({ account, large = false }) {
  return <span aria-hidden="true" className={`account-logo ${account.color} ${large ? "large" : ""}`}>{account.initials}</span>;
}

export function Delta({ value, suffix = " pts" }) {
  const Icon = value > 0 ? ArrowUpRight : ArrowDownLeft;
  return <span className={`delta ${value > 0 ? "negative" : "positive"}`}><Icon size={13} />{Math.abs(value)}{suffix}</span>;
}

export function EmptyState({ icon: Icon, title, description, children }) {
  return <div className="empty-state"><div className="empty-icon"><Icon size={25} /></div><h3>{title}</h3><p>{description}</p>{children}</div>;
}

export function Modal({ title, children, onClose, drawer = false }) {
  const ref = useRef(null);
  const titleId = useId();
  useEffect(() => {
    const previous = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    ref.current?.focus();
    const handleKey = (event) => {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab") {
        const focusable = [...ref.current.querySelectorAll('button, a[href], input, select, textarea, [tabindex="0"]')].filter((el) => !el.disabled && el.getClientRects().length);
        const first = focusable[0];
        const last = focusable.at(-1);
        if (!first) { event.preventDefault(); return; }
        if (event.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || document.activeElement === ref.current)) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener("keydown", handleKey); previous?.focus(); };
  }, [onClose]);
  return <div className={`modal-backdrop ${drawer ? "drawer-backdrop" : ""}`} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <section ref={ref} tabIndex={-1} className={drawer ? "drawer" : "modal"} role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <div className="modal-header"><h2 id={titleId}>{title}</h2><button className="icon-button" aria-label="Close dialog" onClick={onClose}><X size={20} /></button></div>
      {children}
    </section>
  </div>;
}

export function StepList({ steps }) {
  return <ol className="step-list">{steps.map((step, index) => <li key={step}><span>{index + 1}</span>{step}</li>)}</ol>;
}

export function Toast({ message }) {
  return <div className={`toast ${message ? "visible" : ""}`} role="status" aria-live="polite">{message && <><span><Check size={16} /></span>{message}</>}</div>;
}

export function SectionHeader({ title, description, action, onAction }) {
  return <div className="section-header"><div><h2>{title}</h2>{description && <p>{description}</p>}</div>{action && <button className="text-button" onClick={onAction}>{action}<ChevronRight size={15} /></button>}</div>;
}

export function Spinner({ label = "Loading…" }) {
  return <div className="empty-state" role="status" aria-live="polite"><p>{label}</p></div>;
}
