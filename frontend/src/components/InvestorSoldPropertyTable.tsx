import { Fragment, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { InvestorSoldRow } from '../types/investorSold';

interface Props {
  rows: InvestorSoldRow[];
  hasScreening: boolean;
  earliestSale: boolean;
  focus: string;
  onFocusChange: (focus: string) => void;
}

const STAGES = ['NONE', 'PROSPECT', 'MARKETED', 'LEAD', 'QUALIFIED_LEAD', 'OPPORTUNITY', 'HHB_CLOSED'];
const STAGE_LABELS: Record<string, string> = {
  NONE: 'No stage reached', PROSPECT: 'Prospect', MARKETED: 'Marketed', LEAD: 'Lead',
  QUALIFIED_LEAD: 'Qualified Lead', OPPORTUNITY: 'Opportunity', HHB_CLOSED: 'Closed',
};
const SELLERS = ['Trust', 'Company', 'Individual', 'Unclassified'];
const PAGE_SIZE = 50;
const listSource = (row: InvestorSoldRow) => {
  const source = (row.prospect_list_source || '').trim().toLowerCase();
  return source === 'eight' ? '8020' : source || 'unknown';
};
const listSourceLabel = (source: string) => ({
  '8020': '8020', lip: 'LI Profiles', court_alerts: 'Court Alerts', unknown: 'Unknown / not recorded',
}[source] || source.replace(/_/g, ' '));
type SortField = 'property' | 'month' | 'buyer' | 'sellerName' | 'seller' | 'stage' | 'amount';
const words = (value?: string) => value ? value.replace(/_/g, ' ') : '—';
const display = (value: unknown) => value === null || value === undefined || value === '' ? '—' : String(value);
const yesNo = (value: boolean | null | undefined) => value == null ? '—' : value ? 'Yes' : 'No';
const rank = (stage: string) => Math.max(0, STAGES.indexOf(stage));
const seller = (row: InvestorSoldRow) => row.seller_category || 'Unclassified';
const moneyValue = (value: string) => {
  const normalized = String(value ?? '').replace(/[$,\s]/g, '');
  return /^-?\d+(\.\d+)?$/.test(normalized) ? Number(normalized) : null;
};
const currency = (value: string) => {
  const amount = moneyValue(value);
  return amount == null ? '—' : amount.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
};
const focusLabel = (focus: string) => {
  if (focus.startsWith('seller:')) return `Seller: ${focus.slice(7)} (estimate)`;
  if (focus === 'never_prospected') return 'Never prospected · investor';
  if (focus === 'lost') return 'Lost to investor';
  if (focus === 'NONE') return STAGE_LABELS.NONE;
  if (focus === 'HHB_CLOSED') return 'Reached Closed';
  return STAGE_LABELS[focus] ? `Reached ${STAGE_LABELS[focus]} or further` : words(focus);
};
const matchExplanation = (status?: string) => ({
  matched_sale_history: 'Seller matched to the observed sale history',
  sale_event_not_matched: 'No matching sale event found',
  ambiguous_seller_events: 'Multiple possible seller events; no seller assigned',
  not_matched: 'Seller could not be matched',
  missing_seller_name: 'Matched sale has no seller name',
}[status || ''] || words(status));

function Evidence({ label, value }: { label: string; value: unknown }) {
  return <div className="min-w-0"><dt className="text-[11px] text-stone-500">{label}</dt><dd className="mt-0.5 text-xs text-stone-800 break-words">{display(value)}</dd></div>;
}

export default function InvestorSoldPropertyTable({ rows, hasScreening, earliestSale, focus, onFocusChange }: Props) {
  const [buyerFilter, setBuyerFilter] = useState('all');
  const [sellerFilter, setSellerFilter] = useState('all');
  const [sourceFilter, setSourceFilter] = useState('all');
  const [monthFilter, setMonthFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [sortField, setSortField] = useState<SortField>('month');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const instanceId = useId();
  const tableTop = useRef<HTMLElement>(null);
  const monthLabel = earliestSale ? 'First sale month' : 'Sold month';
  const countLabel = earliestSale ? 'properties' : 'property-months';
  const validFocus = ['all', 'never_prospected', 'lost', ...STAGES].includes(focus)
    || (hasScreening && focus.startsWith('seller:') && SELLERS.includes(focus.slice(7)));
  const activeFocus = validFocus ? focus : 'all';
  const focusedSeller = activeFocus.startsWith('seller:') ? activeFocus.slice(7) : null;

  // A chart selection starts a fresh table view so its count matches the selected cohort.
  useEffect(() => {
    setBuyerFilter('all'); setSellerFilter(focusedSeller || 'all'); setMonthFilter('all'); setSourceFilter('all'); setSearch('');
    setPage(1); setExpanded(new Set());
  }, [focus, focusedSeller]);
  useEffect(() => { setPage(1); setExpanded(new Set()); }, [buyerFilter, sellerFilter, monthFilter, sourceFilter, search, rows]);

  const months = useMemo(() => [...new Set(rows.map((row) => row.sold_month).filter(Boolean))].sort().reverse(), [rows]);
  const sources = useMemo(() => [...new Set(rows.map(listSource))].sort((a, b) => listSourceLabel(a).localeCompare(listSourceLabel(b))), [rows]);
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return rows.map((row, originalIndex) => ({ row, originalIndex })).filter(({ row }) => {
      if (focus === 'never_prospected' && !row.never_prospected_investor) return false;
      if (focus === 'lost' && !(row.had_presence && row.investor && !row.hhb_closed_date)) return false;
      if (focus === 'NONE' && rank(row.pipeline_stage) !== 0) return false;
      if (STAGES.includes(focus) && focus !== 'NONE' && rank(row.pipeline_stage) < rank(focus)) return false;
      if (focusedSeller && seller(row) !== focusedSeller) return false;
      if (buyerFilter === 'investor' && !row.investor) return false;
      if (buyerFilter === 'non_investor' && row.investor) return false;
      if (hasScreening && !focusedSeller && sellerFilter !== 'all' && seller(row) !== sellerFilter) return false;
      if (sourceFilter !== 'all' && listSource(row) !== sourceFilter) return false;
      if (monthFilter !== 'all' && row.sold_month !== monthFilter) return false;
      return !query || [row.address, row.street, row.city, row.zip, row.buyer_full_name, row.seller_name, row.dataflik_id, row.transaction_id]
        .filter(Boolean).join(' ').toLowerCase().includes(query);
    }).sort((a, b) => {
      const value = (row: InvestorSoldRow): string | number | null => {
        if (sortField === 'amount') return moneyValue(row.sale_amount);
        if (sortField === 'stage') return rank(row.pipeline_stage);
        if (sortField === 'month') return row.sold_month || null;
        if (sortField === 'buyer') return row.buyer_full_name?.toLowerCase() || null;
        if (sortField === 'sellerName') return row.seller_name?.trim().toLowerCase() || null;
        if (sortField === 'seller') return seller(row).toLowerCase();
        return (row.street || row.address || '').toLowerCase();
      };
      const av = value(a.row), bv = value(b.row);
      if (av == null || bv == null) return av == null && bv == null ? a.originalIndex - b.originalIndex : av == null ? 1 : -1;
      const comparison = av < bv ? -1 : av > bv ? 1 : 0;
      return comparison ? comparison * (sortDirection === 'asc' ? 1 : -1) : a.originalIndex - b.originalIndex;
    });
  }, [rows, focus, focusedSeller, buyerFilter, hasScreening, sellerFilter, monthFilter, sourceFilter, search, sortField, sortDirection]);

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pages);
  const start = (currentPage - 1) * PAGE_SIZE;
  const visibleRows = filtered.slice(start, start + PAGE_SIZE);
  const changePage = (next: number) => {
    setPage(next);
    tableTop.current?.scrollIntoView({ block: 'start' });
  };
  const changeSort = (field: SortField) => {
    setSortField(field); setSortDirection(sortField === field && sortDirection === 'asc' ? 'desc' : 'asc'); setPage(1);
  };
  const clearAll = () => {
    setBuyerFilter('all'); setSellerFilter('all'); setMonthFilter('all'); setSourceFilter('all'); setSearch(''); setPage(1); setExpanded(new Set()); onFocusChange('all');
  };
  const chips: Array<{ label: string; clear: () => void }> = [];
  if (activeFocus !== 'all') chips.push({ label: focusLabel(activeFocus), clear: () => onFocusChange('all') });
  if (buyerFilter !== 'all') chips.push({ label: buyerFilter === 'investor' ? 'Buyer: Investor' : 'Buyer: Non-investor', clear: () => setBuyerFilter('all') });
  if (hasScreening && sellerFilter !== 'all' && sellerFilter !== focusedSeller) chips.push({ label: `Seller: ${sellerFilter}`, clear: () => setSellerFilter('all') });
  if (monthFilter !== 'all') chips.push({ label: `${monthLabel}: ${monthFilter}`, clear: () => setMonthFilter('all') });
  if (sourceFilter !== 'all') chips.push({ label: `Prospect list source: ${listSourceLabel(sourceFilter)}`, clear: () => setSourceFilter('all') });
  if (search.trim()) chips.push({ label: `Search: ${search.trim()}`, clear: () => setSearch('') });
  const headers: Array<{ key: SortField; label: string }> = [
    { key: 'property', label: 'Property' }, { key: 'month', label: monthLabel },
    { key: 'buyer', label: 'Buyer' }, { key: 'sellerName', label: 'Seller before sale' }, { key: 'seller', label: 'Seller category' },
    { key: 'stage', label: 'Furthest stage' }, { key: 'amount', label: 'Sale amount' },
  ];
  const selectClass = 'mt-1 w-full rounded-md border border-stone-300 bg-white px-2 py-2 text-xs text-stone-800';
  const cellClass = 'min-w-0 px-3 py-3 align-top text-xs md:table-cell';
  const mobileLabel = (label: string) => <span className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-stone-500 md:hidden">{label}</span>;

  return <section ref={tableTop} className="scroll-mt-4 overflow-hidden rounded-xl border border-stone-200 bg-white">
    <div className="space-y-3 border-b border-stone-200 p-4">
      <div><h3 className="font-bold text-stone-900">Property review</h3>
        <p className="mt-1 text-xs text-stone-600">Stage filters include properties that reached that stage or further. Each row shows its furthest stage. Table filters do not change report totals or charts.</p>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <label className="text-xs font-medium text-stone-600">Report focus<select aria-label="Filter properties by report focus" value={activeFocus} onChange={(event) => onFocusChange(event.target.value)} className={selectClass}>
          <option value="all">All properties</option><option value="never_prospected">Never prospected · investor</option><option value="lost">Lost to investor</option>
          {STAGES.map((stage) => <option key={stage} value={stage}>{focusLabel(stage)}</option>)}
          {focusedSeller && <option value={activeFocus}>{focusLabel(activeFocus)}</option>}
        </select></label>
        <label className="text-xs font-medium text-stone-600">Buyer<select aria-label="Filter properties by buyer investor status" value={buyerFilter} onChange={(event) => setBuyerFilter(event.target.value)} className={selectClass}>
          <option value="all">All buyers</option><option value="investor">Investor</option><option value="non_investor">Non-investor</option>
        </select></label>
        <label className="text-xs font-medium text-stone-600">Seller category (estimate)<select aria-label="Filter properties by estimated seller category" disabled={!hasScreening} value={focusedSeller || sellerFilter} onChange={(event) => focusedSeller ? onFocusChange(event.target.value === 'all' ? 'all' : `seller:${event.target.value}`) : setSellerFilter(event.target.value)} className={`${selectClass} disabled:bg-stone-50 disabled:text-stone-400`}>
          <option value="all">{hasScreening ? 'All sellers' : 'Not evaluated'}</option>{hasScreening && SELLERS.map((category) => <option key={category}>{category}</option>)}
        </select></label>
        <label className="text-xs font-medium text-stone-600">{monthLabel}<select aria-label={`Filter properties by ${monthLabel.toLowerCase()}`} value={monthFilter} onChange={(event) => setMonthFilter(event.target.value)} className={selectClass}>
          <option value="all">All months</option>{months.map((month) => <option key={month}>{month}</option>)}
        </select></label>
        <label className="text-xs font-medium text-stone-600">Prospect list source<select aria-label="Filter properties by prospect list source" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)} className={selectClass}>
          <option value="all">All sources</option>{sources.map(source => <option key={source} value={source}>{listSourceLabel(source)}</option>)}
        </select></label>
        <label className="col-span-2 lg:col-span-3 text-xs font-medium text-stone-600">Search<input aria-label="Search property address, buyer, seller or identifiers" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Address, buyer, seller or ID" className={selectClass} /></label>
      </div>
      {chips.length > 0 && <div className="rounded-lg bg-violet-50 p-3 text-xs text-violet-950">
        <p className="mb-2 font-semibold">Active table filters · {filtered.length.toLocaleString()} {countLabel}</p>
        <div className="flex flex-wrap items-center gap-2">{chips.map((chip) => <button key={chip.label} type="button" onClick={chip.clear} aria-label={`Remove filter ${chip.label}`} className="rounded-full border border-violet-200 bg-white px-2 py-1 text-left">{chip.label} <span aria-hidden="true">×</span></button>)}
          <button type="button" onClick={clearAll} className="px-2 py-1 font-semibold underline">Clear all</button>
        </div>
      </div>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p role="status" className="text-xs text-stone-600">Showing {filtered.length ? `${(start + 1).toLocaleString()}–${Math.min(start + PAGE_SIZE, filtered.length).toLocaleString()}` : '0'} of {filtered.length.toLocaleString()} matching {countLabel} · {rows.length.toLocaleString()} in report</p>
        <div className="flex items-center gap-2"><label className="text-xs text-stone-600">Sort by <select aria-label="Sort property table by" value={sortField} onChange={(event) => { setSortField(event.target.value as SortField); setPage(1); }} className="rounded-md border border-stone-300 p-1">{headers.map((header) => <option key={header.key} value={header.key}>{header.label}</option>)}</select></label>
          <button type="button" onClick={() => { setSortDirection((value) => value === 'asc' ? 'desc' : 'asc'); setPage(1); }} aria-label={`Sort ${sortDirection === 'asc' ? 'descending' : 'ascending'}`} className="rounded-md border border-stone-300 px-2 py-1 text-xs">{sortDirection === 'asc' ? 'Ascending ↑' : 'Descending ↓'}</button>
        </div>
      </div>
    </div>
    <table className="block w-full table-fixed text-left md:table">
      <caption className="sr-only">Property review. Expand a property to see sale and pipeline evidence.</caption>
      <thead className="hidden bg-stone-50 md:table-header-group"><tr>{headers.map((header) => <th key={header.key} aria-sort={sortField === header.key ? sortDirection === 'asc' ? 'ascending' : 'descending' : 'none'} className={`px-3 py-3 text-[11px] font-semibold text-stone-600 ${header.key === 'property' ? 'w-[21%]' : ''}`}>
        <button type="button" onClick={() => changeSort(header.key)} className="text-left hover:text-violet-800">{header.label}{header.key === 'seller' && <span className="block font-normal">Estimate</span>}{sortField === header.key && <span aria-hidden="true"> {sortDirection === 'asc' ? '↑' : '↓'}</span>}</button>
      </th>)}<th className="w-20 px-3 py-3 text-[11px] font-semibold text-stone-600">Details</th></tr></thead>
      <tbody className="block md:table-row-group">{visibleRows.map(({ row, originalIndex }) => {
        const open = expanded.has(originalIndex);
        const detailId = `${instanceId}-property-${originalIndex}`;
        const address = row.street || row.address || 'Unknown property';
        return <Fragment key={originalIndex}>
          <tr className={`grid grid-cols-2 border-t border-stone-100 md:table-row ${open ? 'bg-violet-50/40' : ''}`}>
            <td className={`${cellClass} col-span-2 md:col-span-1`}>{mobileLabel('Property')}<span className="block break-words font-semibold text-stone-900">{address}</span><span className="mt-1 block break-words text-stone-500">{[row.city, row.state, row.zip].filter(Boolean).join(', ') || '—'}</span></td>
            <td className={cellClass}>{mobileLabel(monthLabel)}{display(row.sold_month)}</td>
            <td className={cellClass}>{mobileLabel('Buyer')}<span className="block break-words">{display(row.buyer_full_name)}</span><span className={`mt-1 inline-block rounded px-1.5 py-0.5 text-[10px] ${row.investor ? 'bg-violet-100 text-violet-900' : 'bg-stone-100 text-stone-600'}`}>{row.investor ? 'Investor' : 'Non-investor'}</span></td>
            <td className={cellClass}>{mobileLabel('Seller before sale')}<span className="block break-words">{row.seller_name?.trim() || 'Not identified'}</span></td>
            <td className={cellClass}>{mobileLabel('Seller category · estimate')}{hasScreening ? seller(row) : '—'}</td>
            <td className={cellClass}>{mobileLabel('Furthest stage')}<span className="break-words">{STAGE_LABELS[row.pipeline_stage] || row.pipeline_stage_label || '—'}</span></td>
            <td className={cellClass}>{mobileLabel('Sale amount')}{currency(row.sale_amount)}</td>
            <td className={cellClass}><button type="button" aria-expanded={open} aria-controls={detailId} aria-label={`${open ? 'Hide' : 'Show'} details for ${address}`} onClick={() => setExpanded((current) => { const next = new Set(current); if (next.has(originalIndex)) next.delete(originalIndex); else next.add(originalIndex); return next; })} className="rounded-md border border-violet-200 px-2 py-1.5 text-xs font-semibold text-violet-800 hover:bg-violet-50">{open ? 'Hide' : 'Details'}</button></td>
          </tr>
          {open && <tr id={detailId} className="block bg-stone-50/70 md:table-row"><td colSpan={headers.length + 1} className="block p-4 md:table-cell">
            <div className="grid gap-6 md:grid-cols-3">
              <div><h4 className="mb-3 text-xs font-bold text-stone-800">Property and seller evidence</h4><dl className="grid grid-cols-2 gap-3">
                <Evidence label="Seller before sale" value={row.seller_name} /><Evidence label="Estimated seller category" value={hasScreening ? seller(row) : null} />
                <Evidence label="Seller match" value={hasScreening ? matchExplanation(row.seller_match_status) : null} /><Evidence label="Property type" value={words(row.property_type)} />
                <Evidence label="Property screening" value={words(row.property_details_status)} /><Evidence label="Screening reason" value={words(row.property_details_reason)} />
                <Evidence label="County" value={row.county} /><Evidence label="Property ID" value={row.dataflik_id} /><Evidence label="Parcel / APN" value={row.parcel_number} /><Evidence label="Address match key" value={row.address_key} />
              </dl>{hasScreening && <p className="mt-3 text-[11px] text-stone-500">Seller categories are name-based estimates from matched sale history, not verified legal ownership types.</p>}</div>
              <div><h4 className="mb-3 text-xs font-bold text-stone-800">Sale and list history</h4><dl className="grid grid-cols-2 gap-3">
                <Evidence label="Transaction IDs for displayed sale" value={row.transaction_id} /><Evidence label={earliestSale ? 'Observed transactions across report' : 'Observed transactions in sold month'} value={row.transaction_count} />
                <Evidence label="Last observed sale month" value={row.last_sold_month} /><Evidence label="Source sale period" value={row.period_label || row.period_date} />
                <Evidence label="Scrape list membership" value={yesNo(row.in_my_records)} /><Evidence label="We had it before sale" value={yesNo(row.had_presence)} />
                <Evidence label="REISift address match" value={yesNo(row.reisift_matched)} /><Evidence label="REISift present at sale" value={yesNo(row.reisift_present_at_sale)} />
                <Evidence label="Prospect list source" value={listSourceLabel(listSource(row))} /><Evidence label="List purchase date" value={row.list_purchase_date} />
                <Evidence label="Months from list to sale" value={row.months_list_to_sold} /><Evidence label="Investor score (source)" value={row.investor_score} /><Evidence label="Distress indicators (source)" value={row.distressors} />
              </dl></div>
              <div><h4 className="mb-3 text-xs font-bold text-stone-800">Pipeline evidence at sale</h4><dl className="grid grid-cols-2 gap-3">
                <Evidence label="Calls / SMS / direct mail touches" value={`${row.cc_touch_count ?? 0} / ${row.sms_touch_count ?? 0} / ${row.dm_touch_count ?? 0}`} /><Evidence label="First touch" value={[row.first_touch_date, row.first_touch_channel].filter(Boolean).join(' · ')} />
                <Evidence label="Lead date" value={row.lead_date} /><Evidence label="Lead source" value={words(row.lead_source)} />
                <Evidence label="Qualified Lead date" value={row.qualified_lead_date} /><Evidence label="Qualified Lead matched" value={yesNo(row.qualified_lead_matched)} />
                <Evidence label="Prospect date / source" value={[row.prospect_date, row.prospect_source ? words(row.prospect_source) : ''].filter(Boolean).join(' · ')} /><Evidence label="Months from list to Qualified Lead" value={row.months_list_to_qualified_lead} />
                <Evidence label="Opportunity date" value={row.opp_created_date} /><Evidence label="Opportunity matched" value={yesNo(row.opp_matched)} />
                <Evidence label="Under contract date" value={row.under_contract_date} /><Evidence label="HHB closed date" value={row.hhb_closed_date} />
              </dl></div>
            </div>
          </td></tr>}
        </Fragment>;
      })}</tbody>
    </table>
    {!filtered.length && <div className="p-8 text-center text-sm text-stone-500">No properties match these filters.{chips.length > 0 && <button type="button" onClick={clearAll} className="ml-2 font-semibold text-violet-800 underline">Clear all filters</button>}</div>}
    <div className="flex items-center justify-between border-t border-stone-200 px-4 py-3 text-xs text-stone-600">
      <span>Page {currentPage.toLocaleString()} of {pages.toLocaleString()} · {PAGE_SIZE} per page</span><div className="flex gap-2">
        <button type="button" disabled={currentPage <= 1} onClick={() => changePage(currentPage - 1)} aria-label="Previous page of properties" className="rounded-md border border-stone-300 px-3 py-1.5 disabled:opacity-40">Previous</button>
        <button type="button" disabled={currentPage >= pages} onClick={() => changePage(currentPage + 1)} aria-label="Next page of properties" className="rounded-md border border-stone-300 px-3 py-1.5 disabled:opacity-40">Next</button>
      </div>
    </div>
  </section>;
}
