import { useEffect, useState } from "react";
import { Activity, CircleHelp, RefreshCw, ShieldCheck, BarChart3 } from "lucide-react";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { Badge, Spinner } from "./components";
import {
  getDrift, getModelPerformance, getFeatureImportance, getRiskHistogram,
  getGainsChart, getRiskHeatmap, getBoxplotStats,
} from "./lib/api";
import "./Evaluation.css";

const isNumber = (value) => typeof value === "number" && Number.isFinite(value);
const isRate = (value) => isNumber(value) && value >= 0 && value <= 1;
const percent = (value) => isRate(value) ? `${(value * 100).toFixed(1)}%` : "Not available";
const displayMetric = (value) => value != null && Number.isFinite(Number.parseFloat(String(value))) ? String(value) : "Not available";
const HEATMAP_COLORS = { Critical: "#c5525f", High: "#dd929c", Medium: "#e4bf83", Low: "#167d8d" };

function GateBadge({ value }) {
  return <Badge tone={value === true ? "success" : value === false ? "warning" : "neutral"}>
    {value === true ? "Passed" : value === false ? "Needs review" : "Not reported"}
  </Badge>;
}

function FeatureImportanceChart({ data }) {
  if (!data?.length) return <p className="evaluation-footnote">No feature-importance data was supplied.</p>;
  const chartData = [...data].sort((a, b) => a.importance - b.importance);
  return <div style={{ height: Math.max(220, chartData.length * 28) }}>
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={chartData} layout="vertical" margin={{ left: 10, right: 20, top: 5, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 4" horizontal={false} stroke="var(--border)" />
        <XAxis type="number" tick={{ fontSize: 11, fill: "var(--muted)" }} axisLine={false} tickLine={false} />
        <YAxis type="category" dataKey="label" width={170} tick={{ fontSize: 11, fill: "var(--ink)" }} axisLine={false} tickLine={false} />
        <Tooltip formatter={(v) => v.toFixed(4)} />
        <Bar dataKey="importance" fill="var(--primary)" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  </div>;
}

function RiskHistogramChart({ data }) {
  if (!data?.length) return <p className="evaluation-footnote">No risk-score distribution data was supplied.</p>;
  return <div style={{ height: 220 }}>
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ left: -10, right: 15, top: 5, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 4" vertical={false} stroke="var(--border)" />
        <XAxis dataKey="bucket" tick={{ fontSize: 9, fill: "var(--muted)" }} axisLine={false} tickLine={false} interval={1} />
        <YAxis tick={{ fontSize: 11, fill: "var(--muted)" }} axisLine={false} tickLine={false} allowDecimals={false} />
        <Tooltip />
        <Bar dataKey="count" fill="var(--primary)" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  </div>;
}

function GainsChart({ data }) {
  if (!data?.model?.length) return <p className="evaluation-footnote">No gains-chart data was supplied.</p>;
  const merged = data.model.map((m, i) => ({
    pctAccounts: m.pctAccounts,
    model: m.pctChurnersCaptured,
    heuristic: data.heuristic?.[i]?.pctChurnersCaptured ?? null,
    baseline: m.pctAccounts,
  }));
  return <div style={{ height: 260 }}>
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={merged} margin={{ left: -10, right: 15, top: 5, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 4" stroke="var(--border)" />
        <XAxis dataKey="pctAccounts" tickFormatter={(v) => `${Math.round(v * 100)}%`} tick={{ fontSize: 11, fill: "var(--muted)" }} axisLine={false} tickLine={false} />
        <YAxis tickFormatter={(v) => `${Math.round(v * 100)}%`} tick={{ fontSize: 11, fill: "var(--muted)" }} axisLine={false} tickLine={false} />
        <Tooltip formatter={(v) => `${(v * 100).toFixed(1)}%`} labelFormatter={(v) => `Top ${Math.round(v * 100)}% of accounts`} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <Line type="monotone" dataKey="model" name="Model" stroke="var(--primary)" strokeWidth={2.5} dot={false} />
        <Line type="monotone" dataKey="heuristic" name="Legacy heuristic" stroke="#aa751b" strokeWidth={2} dot={false} strokeDasharray="4 3" />
        <Line type="monotone" dataKey="baseline" name="Random (baseline)" stroke="var(--muted)" strokeWidth={1.5} dot={false} strokeDasharray="2 3" />
      </LineChart>
    </ResponsiveContainer>
  </div>;
}

function RiskHeatmap({ data }) {
  if (!data?.length) return <p className="evaluation-footnote">No risk-segment heatmap data was supplied.</p>;
  const segments = [...new Set(data.map((d) => d.segment))];
  const bands = ["Critical", "High", "Medium", "Low"];
  const maxCount = Math.max(...data.map((d) => d.count), 1);
  const cell = (segment, band) => data.find((d) => d.segment === segment && d.band === band);
  return <div className="table-scroll"><table className="heatmap-table"><thead><tr><th>Segment</th>{bands.map((b) => <th key={b}>{b}</th>)}</tr></thead><tbody>
    {segments.map((segment) => <tr key={segment}>
      <th scope="row">{segment}</th>
      {bands.map((band) => {
        const c = cell(segment, band);
        const opacity = c ? 0.18 + 0.75 * (c.count / maxCount) : 0;
        return <td key={band}>
          {c ? <div className="heatmap-cell" style={{ background: HEATMAP_COLORS[band], opacity }}>
            <strong>{c.count}</strong><small>{(c.churnRate * 100).toFixed(1)}% churn</small>
          </div> : <span className="heatmap-empty">—</span>}
        </td>;
      })}
    </tr>)}
  </tbody></table></div>;
}

function BoxPlotRow({ label, stats }) {
  const groups = [{ key: "retained", title: "Retained", tone: "success" }, { key: "churned", title: "Churned", tone: "danger" }];
  const allVals = groups.flatMap((g) => stats[g.key] ? [stats[g.key].min, stats[g.key].max] : []);
  if (!allVals.length) return null;
  const lo = Math.min(...allVals), hi = Math.max(...allVals) || 1;
  const pct = (v) => `${((v - lo) / (hi - lo || 1)) * 100}%`;
  return <div className="boxplot-row">
    <span className="boxplot-label">{label}</span>
    <div className="boxplot-groups">
      {groups.map(({ key, title, tone }) => {
        const s = stats[key];
        if (!s) return <div className="boxplot-group" key={key}><small>{title}: not available</small></div>;
        return <div className="boxplot-group" key={key}>
          <small>{title}</small>
          <div className="boxplot-track">
            <span className="boxplot-whisker" style={{ left: pct(s.min), width: `calc(${pct(s.max)} - ${pct(s.min)})` }} />
            <span className={`boxplot-box tone-${tone}`} style={{ left: pct(s.q1), width: `calc(${pct(s.q3)} - ${pct(s.q1)})` }} />
            <span className="boxplot-median" style={{ left: pct(s.median) }} />
          </div>
          <small className="boxplot-range">{s.min} – {s.max} (median {s.median})</small>
        </div>;
      })}
    </div>
  </div>;
}

export default function Evaluation() {
  const [reload, setReload] = useState(0);
  const [state, setState] = useState({ loading: true, error: null, report: null, drift: null });
  const [charts, setCharts] = useState({ loading: true, error: null, data: null });

  useEffect(() => {
    let active = true;
    setState({ loading: true, error: null, report: null, drift: null });
    Promise.all([getModelPerformance(), getDrift()])
      .then(([report, drift]) => {
        if (!report || !Array.isArray(report.metrics) || !drift || !Array.isArray(drift.signals)) {
          throw new Error("Invalid report response");
        }
        if (active) setState({ loading: false, error: null, report, drift });
      })
      .catch((err) => {
        if (active) setState({ loading: false, error: err.message || "Evaluation reports could not be loaded. Check the scoring API and its saved evaluation and drift reports, then retry.", report: null, drift: null });
      });
    return () => { active = false; };
  }, [reload]);

  useEffect(() => {
    let active = true;
    setCharts({ loading: true, error: null, data: null });
    Promise.all([getFeatureImportance(), getRiskHistogram(), getGainsChart(), getRiskHeatmap(), getBoxplotStats()])
      .then(([featureImportance, riskHistogram, gains, heatmap, boxplots]) => {
        if (active) setCharts({ loading: false, error: null, data: { featureImportance, riskHistogram, gains, heatmap, boxplots } });
      })
      .catch((err) => {
        if (active) setCharts({ loading: false, error: err.message || "Chart data could not be loaded.", data: null });
      });
    return () => { active = false; };
  }, [reload]);

  const { loading, error, report, drift } = state;
  const metrics = Object.fromEntries((report?.metrics ?? []).map((metric) => [metric.label, metric.value]));
  const withPlay = report?.playEffectiveness?.churn_rate_with_play;
  const withoutPlay = report?.playEffectiveness?.churn_rate_without_play;
  const difference = isRate(withPlay) && isRate(withoutPlay) ? (withoutPlay - withPlay) * 100 : null;
  const gateChecks = [
    { name: "Risk ranking", rule: "AUROC ≥ 0.75", value: report?.gateChecks?.ranking_quality_ok, scope: "Included in saved gate" },
    { name: "Drift validation", rule: "Synthetic drift accuracy ≥ 60%", value: report?.gateChecks?.drift_monitor_validated, scope: "Included in saved gate" },
    { name: "Attribution coverage", rule: "Coverage ≥ 100%", value: isNumber(report?.attributionCoverage) ? report.attributionCoverage >= 1 : null, scope: "Additional display check" },
    { name: "Lookup latency estimate", rule: "Estimated p95 < 50 ms", value: isNumber(report?.p95LatencyMs) ? report.p95LatencyMs < 50 : null, scope: "Additional display check" },
  ];

  return <div className="evaluation-page">
    <div className="evaluation-toolbar">
      <Badge tone="purple">Saved reports · synthetic demonstration</Badge>
      <button className="button" onClick={() => setReload((value) => value + 1)} disabled={loading && charts.loading}><RefreshCw size={15} />{loading ? "Loading reports…" : "Reload reports"}</button>
    </div>
    <div className="evaluation-notice"><CircleHelp size={20} /><p><strong>Results, not a new evaluation run.</strong> This page reads saved backend reports. Reloading fetches those reports again; it does not retrain the model or run evaluation. The project uses synthetic risk labels and simulated outcomes—not verified production results.</p></div>
    {loading ? <Spinner label="Loading evaluation reports…" /> : error ? <section className="panel evaluation-section" role="alert"><h2>Reports unavailable</h2><p>{error}</p><button className="button" onClick={() => setReload((value) => value + 1)}>Retry reports</button></section> : <>
      <div className="evaluation-metrics">
        <section className="panel evaluation-metric"><span>Risk-ranking quality</span><strong>{displayMetric(metrics["Risk ranking quality"])}</strong><small>AUROC · target ≥ 0.75</small></section>
        <section className="panel evaluation-metric"><span>Attribution coverage</span><strong>{percent(report.attributionCoverage)}</strong><small>Recognized top-signal labels</small></section>
        <section className="panel evaluation-metric"><span>Lookup latency estimate</span><strong>{isNumber(report.p95LatencyMs) ? `${report.p95LatencyMs.toFixed(2)} ms` : "Not available"}</strong><small>p95 · includes fixed 4 ms overhead</small></section>
        <section className="panel evaluation-metric"><span>Input drift alerts</span><strong>{isNumber(drift.nFeaturesAlerting) ? drift.nFeaturesAlerting : "Not available"}</strong><small>Drift snapshot · {drift.asOfDate ?? "Not reported"}</small></section>
      </div>
      <section className="panel evaluation-section">
        <div className="evaluation-heading"><div><h2>How we evaluate</h2><p>The question, the calculation, and the limits of each result.</p></div><ShieldCheck size={22} /></div>
        <div className="table-scroll"><table className="evaluation-table"><thead><tr><th scope="col">What we check</th><th scope="col">How it is calculated</th><th scope="col">Saved result</th><th scope="col">What it does not prove</th></tr></thead><tbody>
          <tr><th scope="row">Model risk ranking</th><td>Join account scores to synthetic latent-risk labels and calculate AUROC on the scored cohort.</td><td>{displayMetric(metrics["Risk ranking quality"])}</td><td>Not accuracy, calibrated churn probability, or independent future-period validation.</td></tr>
          <tr><th scope="row">Explanation coverage</th><td>Of the evaluated top signals, count the share mapped to a known human-readable feature label.</td><td>{percent(report.attributionCoverage)}</td><td>Does not validate causal explanations; accounts with no top signal are not counted in this calculation.</td></tr>
          <tr><th scope="row">Serving-path estimate</th><td>Time cached score lookups, add a fixed 4 ms overhead to each, and take the 95th percentile.</td><td>{isNumber(report.p95LatencyMs) ? `${report.p95LatencyMs.toFixed(2)} ms` : "Not available"}</td><td>Not measured HTTP latency, browser performance, or on-demand model inference time.</td></tr>
          <tr><th scope="row">Drift detection validation</th><td>Read detection accuracy from the synthetic drift-injection validation report.</td><td>{displayMetric(metrics["Drift alert accuracy"])}</td><td>Does not guarantee that every real-world change will be detected.</td></tr>
        </tbody></table></div>
        <p className="evaluation-footnote">Evaluation source: saved outcomes evaluation report. Its model version and evaluation timestamp are not exposed by this API response; the global footer refers to the score snapshot, not evaluation freshness.</p>
      </section>
      <section className="panel evaluation-section">
        <h2>Playbook effectiveness</h2><p>For Critical and High accounts, join logged actions with outcomes and compare the churn rate where an action timestamp exists versus where it does not.</p>
        <div className="evaluation-comparison">
          {[{ label: "With a recorded play", value: withPlay }, { label: "Without a recorded play", value: withoutPlay }].map(({ label, value }) => <div key={label}><span>{label}</span><strong>{percent(value)}</strong><div className="evaluation-rate-track" aria-hidden="true"><span style={{ width: `${isRate(value) ? value * 100 : 0}%` }} /></div><small>Simulated churn rate</small></div>)}
        </div>
        <p className="evaluation-difference">{difference === null ? "A comparison requires both churn rates; one or both are not available." : difference === 0 ? "No observed difference between the reported churn rates." : `${Math.abs(difference).toFixed(1)} percentage points ${difference > 0 ? "lower" : "higher"} churn with a recorded play.`}</p>
        <p className="evaluation-footnote">Descriptive comparison of simulated outcomes—not proof that the play caused a reduction. Group sizes, confidence intervals, and randomized assignment evidence are not supplied here. Browser-local launches and outcome edits are not included in this report.</p>
      </section>
      <section className="panel evaluation-section">
        <div className="evaluation-heading"><div><h2>Input data drift</h2><p>Population Stability Index (PSI) compares current feature distributions with their stored baseline. Larger values indicate greater change—not necessarily poorer model quality.</p></div><Activity size={22} /></div>
        <p className="evaluation-footnote">Report date: {drift.asOfDate ?? "Not reported"} · Reported review threshold: {isNumber(drift.alertThreshold) ? drift.alertThreshold : "Not reported"}. Status is taken from each feature's saved alert flag.</p>
        {drift.signals.length ? <div className="table-scroll"><table className="evaluation-table"><thead><tr><th scope="col">Input signal</th><th scope="col">PSI</th><th scope="col">Status</th></tr></thead><tbody>{drift.signals.map((signal) => <tr key={signal.feature}><th scope="row">{signal.name}</th><td>{isNumber(signal.psi) ? signal.psi.toFixed(4) : "Not available"}</td><td><Badge tone={signal.alert === true ? "warning" : signal.alert === false ? "success" : "neutral"}>{signal.alert === true ? "Review drift" : signal.alert === false ? "Stable" : "Not reported"}</Badge></td></tr>)}</tbody></table></div> : <p>No feature-level drift results were supplied.</p>}
      </section>
      <section className="panel evaluation-section">
        <div className="evaluation-heading"><div><h2>Evaluation checks</h2><p>The saved aggregate gate combines ranking quality and drift validation only.</p></div><Badge tone={report.gate === "passed" ? "success" : report.gate === "failed" ? "warning" : "neutral"}>Saved gate: {report.gate === "passed" ? "passed" : report.gate === "failed" ? "failed" : "not reported"}</Badge></div>
        <div className="table-scroll"><table className="evaluation-table"><thead><tr><th scope="col">Check</th><th scope="col">Current criterion</th><th scope="col">Result</th><th scope="col">Gate scope</th></tr></thead><tbody>{gateChecks.map((check) => <tr key={check.name}><th scope="row">{check.name}</th><td>{check.rule}</td><td><GateBadge value={check.value} /></td><td>{check.scope}</td></tr>)}</tbody></table></div>
        <p className="evaluation-footnote">Display only: these checks do not trigger or block deployments. Current criteria reflect the project's evaluation code, not configurable thresholds returned by the API.</p>
      </section>

      {/* ---- Charts ported from the legacy static dashboard's Tab 2 & Tab 3 ---- */}
      {charts.loading ? <Spinner label="Loading charts…" /> : charts.error ? <section className="panel evaluation-section" role="alert"><h2>Charts unavailable</h2><p>{charts.error}</p></section> : <>
        <section className="panel evaluation-section">
          <div className="evaluation-heading"><div><h2>Feature importance</h2><p>Global drivers of the model's risk ranking, from the trained classifier. Ported from the legacy dashboard's Predictive Signals tab.</p></div><BarChart3 size={22} /></div>
          <FeatureImportanceChart data={charts.data.featureImportance} />
        </section>
        <div className="evaluation-two-col">
          <section className="panel evaluation-section">
            <h2>Risk score distribution</h2><p>Count of accounts by risk-score bucket, latest scoring run.</p>
            <RiskHistogramChart data={charts.data.riskHistogram} />
          </section>
          <section className="panel evaluation-section">
            <h2>Cumulative gains (model vs. legacy heuristic)</h2><p>Share of actual churners captured by targeting the top X% highest-risk accounts, holdout months only.</p>
            <GainsChart data={charts.data.gains} />
          </section>
        </div>
        <section className="panel evaluation-section">
          <h2>Risk segmentation heatmap</h2><p>Account count and churn rate by commercial segment and risk band. Ported from the legacy dashboard's Risk Segmentation tab.</p>
          <RiskHeatmap data={charts.data.heatmap} />
        </section>
        <section className="panel evaluation-section">
          <h2>Engagement & friction, churned vs. retained</h2><p>Five-number summaries (min–q1–median–q3–max) for key signals, split by outcome.</p>
          <div className="boxplot-grid">
            {Object.entries(charts.data.boxplots ?? {}).map(([label, stats]) => <BoxPlotRow key={label} label={label} stats={stats} />)}
          </div>
        </section>
      </>}

      <section className="evaluation-notice"><CircleHelp size={20} /><div><h2>What is not evaluated here?</h2><ul><li>A complete data-quality audit of missing values, duplicates, schema validity, or invalid records.</li><li>Independent temporal holdout results, production customer outcomes, or causal playbook impact.</li><li>Automatic retraining, CI release enforcement, canary deployment, or rollback readiness.</li></ul></div></section>
    </>}
  </div>;
}
