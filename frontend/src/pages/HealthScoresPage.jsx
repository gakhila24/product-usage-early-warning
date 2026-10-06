import { Gauge, ShieldCheck } from "lucide-react";
import { ac } from "../lib/api";
import { useApi } from "../lib/useApi";
import { Async, Info, MiniStat, Panel, nf } from "./ui";

export function HealthScoresView({ data }) {
  const max = Math.max(1, ...data.distribution.map((d) => d.count));
  return <div className="ac-grid ac-grid-2-1">
    <Panel title="Score band distribution" description={`${nf(data.total)} accounts · average ${data.average} · median ${data.median}`} right={<span className="badge purple">{data.model.version}</span>}>
      <div className="band-rows">{data.distribution.map((d) => <div className="band-row" key={d.band}>
        <div className="band-label"><i className="legend-dot" style={{ background: d.color }} /><b>{d.band}</b><small>{d.range}</small></div>
        <div className="band-track"><span style={{ width: `${(d.count / max) * 100}%`, background: d.color }} /></div>
        <div className="band-num"><b>{nf(d.count)}</b><small>{d.pctExact}%</small></div>
      </div>)}</div>
      <Info icon={ShieldCheck}>The score predicts renewal likelihood from behavioral, engagement, commercial and feedback signals. Thresholds are versioned; at-risk means health below {data.atRiskThreshold}.</Info>
    </Panel>
    <div className="ac-stack">
      <Panel title="Model health" description="Current scoring run" right={<Gauge size={17} className="ac-muted" />}>
        <div className="ac-facts two">
          <MiniStat value={`${data.model.dataSources}+`} label="Data sources" />
          <MiniStat value={data.model.signals} label="Signals tracked" />
          <MiniStat value={data.model.confidence} label={`Confidence · AUROC ${data.model.auroc}`} />
          <MiniStat value={data.model.refresh} label={`Next refresh ${data.model.nextRefresh}`} />
        </div>
      </Panel>
      <Panel title="Methodology" description="How scores and bands are defined">
        <ul className="guidance">{data.methodology.map((m) => <li key={m}>{m}</li>)}</ul>
        <div className="threshold-table">{data.bands.map((b) => <div key={b.band}><i className="legend-dot" style={{ background: b.color }} />{b.band}<span>{b.range}</span></div>)}</div>
      </Panel>
    </div>
  </div>;
}

export default function HealthScoresPage({ filters }) {
  const state = useApi(() => ac.healthScores(filters), [JSON.stringify(filters)]);
  return <Async state={state} label="Loading health scores…">{(d) => <HealthScoresView data={d} />}</Async>;
}
