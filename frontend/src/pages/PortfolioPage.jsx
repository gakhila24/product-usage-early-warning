import { ac } from "../lib/api";
import { useApi } from "../lib/useApi";
import { Async, ExportLink, HBars, MiniStat, Panel, nf } from "./ui";

export function PortfolioView({ data, filters }) {
  return <>
    <section className="panel portfolio-snapshot">
      <div><span className="card-eyebrow">PORTFOLIO SNAPSHOT</span><h2>Where the portfolio stands today</h2></div>
      <div className="ac-facts three">
        <MiniStat value={nf(data.snapshot.accounts)} label="Total accounts" />
        <MiniStat value={data.snapshot.avgHealth} label="Average health" />
        <MiniStat value={data.snapshot.nrr == null ? "—" : `${data.snapshot.nrr}%`} label="Net revenue retention" />
      </div>
      <ExportLink href={ac.url("/explorer/export", { ...filters })} label="Export portfolio" />
    </section>
    <div className="ac-grid ac-grid-2-1">
      <Panel title="Product portfolio" description="Health, risk and retention by product">
        <div className="table-scroll"><table className="ac-table">
          <thead><tr><th>Product</th><th>Accounts</th><th>Avg. score</th><th>At risk</th><th>NRR</th><th>ARR</th></tr></thead>
          <tbody>{data.products.map((p) => <tr key={p.product}>
            <td><strong>{p.product}</strong></td><td>{nf(p.accounts)}</td><td>{p.avgScore}</td>
            <td><span className={`risk-share ${p.atRiskPct >= 25 ? "hot" : ""}`}>{p.atRiskPct}%</span></td>
            <td>{p.nrr == null ? "—" : `${p.nrr}%`}</td><td className="arr-cell">{p.arrLabel}</td></tr>)}</tbody>
        </table></div>
        <p className="ac-note">{data.note}</p>
      </Panel>
      <Panel title="Risk by region" description="At-risk accounts (health below 60)">
        <HBars rows={data.regions} labelKey="region" valueKey="atRisk" color="#c5525f" format={(v) => nf(v)} extra={(r) => `${r.pct}% of ${nf(r.accounts)}`} />
      </Panel>
    </div>
  </>;
}

export default function PortfolioPage({ filters }) {
  const state = useApi(() => ac.portfolio(filters), [JSON.stringify(filters)]);
  return <Async state={state} label="Loading portfolio…">{(d) => <PortfolioView data={d} filters={filters} />}</Async>;
}
