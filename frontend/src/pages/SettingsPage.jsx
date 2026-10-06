import { ArrowUpRight, Check } from "lucide-react";
import { ac } from "../lib/api";
import { useApi } from "../lib/useApi";
import { SectionHeader } from "../components";

function Toggle({ label, on, onClick }) {
  return <button role="switch" aria-checked={on} aria-label={label} className={`toggle ${on ? "on" : ""}`} onClick={onClick}><span /></button>;
}

export default function SettingsPage({ preferences, setPreferences, settings, onSettings, onReset, onRoadmap, notify }) {
  const save = async (key) => { try { onSettings(await ac.saveSettings({ [key]: !settings[key] })); notify("Setting saved."); } catch (e) { notify(e.message); } };
  const rows = [
    ["weekly_refresh", "Weekly model refresh", "Refresh health scores and driver impacts each week."],
    ["critical_alerts", "Critical risk alerts", "Surface accounts that enter the Critical score band."],
    ["renewal_reminders", "Renewal reminders", "Notify owners at 90, 60 and 30 days before renewal."],
    ["include_adoption_drivers", "Include adoption drivers", "Show positive adoption drivers next to churn drivers."],
  ];
  return <div className="settings-layout">
    <section className="panel settings-card"><SectionHeader title="Alert & model preferences" description="Saved to the database (shared by every browser using this API)." />
      {rows.map(([k, h, p]) => <div className="setting-row" key={k}><div><h3>{h}</h3><p>{p}</p></div><Toggle label={h} on={settings?.[k] !== false} onClick={() => save(k)} /></div>)}
    </section>
    <section className="panel settings-card"><SectionHeader title="Personal preferences" description="These settings apply to this browser only." />
      <div className="setting-row"><div><h3>Compact account rows</h3><p>Fit more of your portfolio into a single view.</p></div><Toggle label="Compact account rows" on={preferences.compact} onClick={() => setPreferences({ ...preferences, compact: !preferences.compact })} /></div>
      <div className="setting-row"><div><h3>Renewal reminders in account details</h3><p>Highlight renewals within 30 days in account details.</p></div><Toggle label="Renewal reminders" on={preferences.reminders} onClick={() => setPreferences({ ...preferences, reminders: !preferences.reminders })} /></div>
      <div className="settings-info"><Check size={15} />Preferences save automatically.</div>
    </section>
    <section className="panel settings-card"><SectionHeader title="Session activity" description="Playbooks you launch are stored in this browser only." />
      <div className="setting-row"><div><h3>Reset session activity</h3><p>Clear locally-launched playbooks. The live outcomes log is unaffected.</p></div><button className="button danger-button" onClick={onReset}>Reset session</button></div>
      <div className="setting-row"><div><h3>What's next?</h3><p>See what's connected live vs. still session-only.</p></div><button className="text-button" onClick={onRoadmap}>View implementation notes <ArrowUpRight size={15} /></button></div>
    </section>
  </div>;
}
