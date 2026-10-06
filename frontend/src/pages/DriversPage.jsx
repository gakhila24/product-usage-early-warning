import { ac } from "../lib/api";
import { useApi } from "../lib/useApi";
import { Async, HBars, Info, Panel, nf } from "./ui";
import { CircleHelp } from "lucide-react";

export function DriversView({ data, showAdoption }) {
  return <>
    <div className={`ac-grid ${showAdoption ? "ac-grid-2" : ""}`}>
      <Panel title="Churn Drivers" description="Negative impact on health score" right={<span className="badge danger">Risk</span>}>
        <HBars rows={data.churn} labelKey="driver" valueKey="impact" color="#c5525f" signed format={(v) => v.toFixed(1)} extra={(r) => `${nf(r.accounts)} accts`} />
        <p className="takeaway">{data.takeawayChurn}</p>
      </Panel>
      {showAdoption && <Panel title="Adoption Drivers" description="Positive impact on health score" right={<span className="badge success">Growth</span>}>
        <HBars rows={data.adoption} labelKey="driver" valueKey="impact" color="#167d8d" signed format={(v) => `+${v.toFixed(1)}`} />
        <p className="takeaway">{data.takeawayAdoption}</p>
      </Panel>}
    </div>
    <Info icon={CircleHelp}>{data.note} Based on {nf(data.atRiskAccounts)} at-risk accounts; mean health shortfall vs. Excellent: {data.shortfall} pts; uplift of healthy vs. at-risk accounts: {data.uplift} pts.</Info>
  </>;
}

export default function DriversPage({ filters, settings }) {
  const state = useApi(() => ac.drivers(filters), [JSON.stringify(filters)]);
  return <Async state={state} label="Loading drivers…">{(d) => <DriversView data={d} showAdoption={settings?.include_adoption_drivers !== false} />}</Async>;
}
