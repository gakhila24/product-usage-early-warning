import { useState } from "react";
import { ArrowDown, ArrowUpRight, ChartNoAxesCombined, ChevronLeft, ChevronRight, CircleHelp, Search, SlidersHorizontal, TrendingDown, X } from "lucide-react";
import { BAND_ORDER, accountColor, filterAccounts, initialsFromName, money } from "./data";
import { AccountLogo, Badge, Delta, EmptyState } from "./components";

export default function AccountsTable({ page, accounts, query, setQuery, band, setBand, plan, setPlan, industry, setIndustry, region, setRegion, sort, setSort, compact, onSelect, onGuide }) {
  const [tablePage, setTablePage] = useState(1);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const decorated = accounts.map((a) => ({ ...a, color: accountColor(a.id), initials: initialsFromName(a.name) }));
  const filtered = filterAccounts(decorated, { query, band, plan, industry, region, sort });
  const totalPages = Math.max(1, Math.ceil(filtered.length / 6));
  const currentPage = Math.min(tablePage, totalPages);
  const pageGroupStart = Math.floor((currentPage - 1) / 10) * 10 + 1;
  const visiblePages = Array.from({ length: Math.min(10, totalPages - pageGroupStart + 1) }, (_, index) => pageGroupStart + index);
  const visibleAccounts = filtered.slice((currentPage - 1) * 6, currentPage * 6);
  const criticalCount = accounts.filter((a) => a.band === "Critical").length;
  const hasRegions = accounts.some((a) => a.region);
  const resetFilters = () => { setQuery(""); setBand("All accounts"); setPlan("All plans"); setIndustry("All industries"); setRegion?.("All regions"); setSort("risk"); setTablePage(1); };
  return <section className={`panel accounts-panel ${compact ? "compact" : ""}`}>
    <div className="accounts-title">
      <div className="title-with-count"><h2>{page === "Overview" ? "Accounts to keep an eye on" : "Your accounts"}</h2><Badge tone="purple">{accounts.length} accounts</Badge></div>
      <button className="text-button muted-button" aria-label="How risk is scored" onClick={onGuide}><CircleHelp size={17} /><span>How risk is scored</span></button>
    </div>
    <div className="table-toolbar">
      <div className="tabs" role="group" aria-label="Filter by risk">
        {["All accounts", ...BAND_ORDER].map((item) => <button className={band === item ? "active" : ""} key={item} onClick={() => { setBand(item); setTablePage(1); }}>
          {item}{item === "Critical" && <span>{criticalCount}</span>}
        </button>)}
      </div>
      <button className={`button small ${filtersOpen ? "selected" : ""}`} aria-expanded={filtersOpen} onClick={() => setFiltersOpen(!filtersOpen)}><SlidersHorizontal size={15} />Filters{(plan !== "All plans" || industry !== "All industries" || region !== "All regions") && <span className="filter-dot" />}</button>
    </div>
    {filtersOpen && <div className="filter-bar">
      <label>Plan<select aria-label="Plan" value={plan} onChange={(e) => { setPlan(e.target.value); setTablePage(1); }}>
        <option>All plans</option>{[...new Set(accounts.map((a) => a.plan))].map((p) => <option key={p}>{p}</option>)}
      </select></label>
      <label>Industry<select aria-label="Industry" value={industry} onChange={(e) => { setIndustry(e.target.value); setTablePage(1); }}>
        <option>All industries</option>{[...new Set(accounts.map((a) => a.industry))].map((name) => <option key={name}>{name}</option>)}
      </select></label>
      {hasRegions && <label>Region<select aria-label="Region" value={region} onChange={(e) => { setRegion(e.target.value); setTablePage(1); }}>
        <option>All regions</option>{[...new Set(accounts.map((a) => a.region).filter(Boolean))].map((name) => <option key={name}>{name}</option>)}
      </select></label>}
      <label>Sort by<select aria-label="Sort by" value={sort} onChange={(e) => { setSort(e.target.value); setTablePage(1); }}>
        <option value="risk">Highest risk</option><option value="arr">Highest ARR</option><option value="renewal">Soonest renewal</option>
      </select></label>
      <button className="text-button" onClick={resetFilters}>Reset filters</button>
    </div>}
    {query && <div className="search-summary">Results for &ldquo;{query}&rdquo;<button className="text-button" onClick={() => setQuery("")}>Clear search <X size={13} /></button></div>}
    <div className="table-scroll"><table><thead><tr>
      <th>Account</th>
      <th><button className="column-sort" onClick={() => { setSort("risk"); setTablePage(1); }}>Risk score <ArrowDown size={12} /></button></th>
      <th>ARR</th><th>Usage trend (30d) <CircleHelp size={12} /></th><th>Top signal</th><th>Industry</th>
      {hasRegions && <th>Payment risk</th>}
      <th><span className="sr-only">View account</span></th>
    </tr></thead><tbody>{visibleAccounts.map((account) => <tr key={account.id}>
      <td><button className="account-cell" onClick={() => onSelect(account.id)}><AccountLogo account={account} /><span><strong>{account.name}</strong><small>{account.id} · {account.plan}</small></span></button></td>
      <td><div className="score-cell"><span className={`score ${account.score >= 70 ? "high" : account.score >= 40 ? "medium" : "low"}`}>{account.score}</span><Delta value={account.wow} suffix="" /></div></td>
      <td className="arr-cell">{money(account.arr)}</td>
      <td><span className={`usage-change ${account.usage < 0 ? "negative" : "positive"}`}>{account.usage < 0 ? <TrendingDown size={15} /> : <ChartNoAxesCombined size={15} />}{account.usage > 0 ? "+" : ""}{account.usage}%</span></td>
      <td><span className={`signal-tag ${account.band === "Critical" ? "signal-danger" : ""}`}><span />{account.signal}</span></td>
      <td>{account.industry}</td>
      {hasRegions && <td>{account.paymentRisk ? <Badge tone="warning">At risk</Badge> : "—"}</td>}
      <td><button className="icon-button" aria-label={`View ${account.name}`} onClick={() => onSelect(account.id)}><ArrowUpRight size={17} /></button></td>
    </tr>)}</tbody></table></div>
    {filtered.length === 0 && <EmptyState icon={Search} title="No accounts found" description="Try a different search or clear your filters."><button className="button" onClick={resetFilters}>Clear filters</button></EmptyState>}
    <div className="table-footer">
      <span>Showing <strong>{filtered.length ? (currentPage - 1) * 6 + 1 : 0}–{Math.min(currentPage * 6, filtered.length)}</strong> of <strong>{filtered.length}</strong> accounts</span>
      <div className="pagination">
        <button className="icon-button" aria-label="Previous page" disabled={currentPage === 1} onClick={() => setTablePage(currentPage - 1)}><ChevronLeft size={16} /></button>
        {visiblePages.map((pageNumber) => <button key={pageNumber} className={currentPage === pageNumber ? "active" : ""} aria-label={`Page ${pageNumber}`} aria-current={currentPage === pageNumber ? "page" : undefined} onClick={() => setTablePage(pageNumber)}>{pageNumber}</button>)}
        <button className="icon-button" aria-label="Next page" disabled={currentPage === totalPages} onClick={() => setTablePage(currentPage + 1)}><ChevronRight size={16} /></button>
      </div>
    </div>
  </section>;
}
