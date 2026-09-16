import { useMemo, useState } from 'react';
import { copyReportShareUrl } from '../utils/reportShareUrl';
import type {
  InvestorSoldCompletedResponse,
  InvestorSoldRow,
} from '../types/investorSold';

interface InvestorSoldResultsProps {
  result: InvestorSoldCompletedResponse;
  onNewRun: () => void;
  onExport: () => void;
  exporting: boolean;
}

type SegmentFilter = 'all' | 'investor' | 'in_our_list' | 'both' | 'neither';
type JourneyFilter = 'all' | 'never_marketed' | 'prospects' | 'opps' | 'uc' | 'hhb' | string;
type SortKey = keyof InvestorSoldRow;
type SortDir = 'asc' | 'desc';

const DETAIL_COLS: Array<{ key: SortKey; label: string }> = [
  { key: 'address', label: 'Address' },
  { key: 'sold_month', label: 'Sold month' },
  { key: 'buyer_full_name', label: 'Buyer' },
  { key: 'sale_amount', label: 'Sale amount' },
  { key: 'transaction_count', label: 'Txns' },
  { key: 'segment', label: 'Segment' },
  { key: 'pipeline_stage_label', label: 'Pipeline' },
  { key: 'marketed', label: 'Marketed' },
  { key: 'prospect_source', label: 'Prospect source' },
  { key: 'prospect_date', label: 'Prospect date' },
  { key: 'opp_matched', label: 'Opp' },
  { key: 'months_list_to_sold', label: 'Mo list→sold' },
  { key: 'investor_score', label: 'Investor score' },
];

const SEGMENT_LABELS: Record<string, string> = {
  investor: 'Investor',
  in_our_list: 'In Our List',
  both: 'Both',
  neither: 'Neither',
};

const PREVIEW_LIMIT = 500;

function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return String(n);
}

function cellValue(row: InvestorSoldRow, key: SortKey): string {
  const v = row[key];
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (v === null || v === undefined || v === '') return '—';
  if (key === 'prospect_source') {
    const map: Record<string, string> = { ql: 'QL', sf_tag: 'SF', podio: 'Podio' };
    return map[String(v)] || String(v);
  }
  return String(v);
}

function sortValue(row: InvestorSoldRow, key: SortKey): string | number | boolean {
  const v = row[key];
  if (
    key === 'sale_amount' ||
    key === 'transaction_count' ||
    key === 'investor_score' ||
    key === 'months_list_to_sold' ||
    key === 'months_list_to_prospect'
  ) {
    const n = Number(String(v ?? '').replace(/[^0-9.-]/g, ''));
    return Number.isFinite(n) ? n : 0;
  }
  if (typeof v === 'boolean') return v ? 1 : 0;
  return String(v ?? '').toLowerCase();
}

const InvestorSoldResults = ({
  result,
  onNewRun,
  onExport,
  exporting,
}: InvestorSoldResultsProps) => {
  const m = result.metrics;
  const propertyRows = m.inputs.property_rows ?? m.rows.length;
  const txnRows = m.inputs.sold_rows_ingested;
  const marketing = m.marketing ?? {
    marketed_count: 0,
    marketed_pct: 0,
    never_marketed_count: 0,
    total_touch_counts: {},
    avg_touches_per_marketed: null,
  };
  const match = m.match ?? {
    prospect_matched: 0,
    prospect_rate_pct: 0,
    opp_matched: 0,
    opp_rate_pct: 0,
    under_contract_count: 0,
    hhb_closed_count: 0,
    reisift_matched_count: 0,
  };
  const lag = m.lag ?? {
    mean_months_list_to_sold: null,
    median_months_list_to_sold: null,
    mean_months_list_to_prospect: null,
    median_months_list_to_prospect: null,
  };
  const prospectSources = m.prospect_sources ?? { ql: 0, sf_tag: 0, podio: 0, unmatched: 0 };
  const pipelineFunnel = m.pipeline_funnel ?? [];
  const bySegment = m.by_segment ?? [];

  const [shareMsg, setShareMsg] = useState('');
  const [segmentFilter, setSegmentFilter] = useState<SegmentFilter>('all');
  const [journeyFilter, setJourneyFilter] = useState<JourneyFilter>('all');
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('sold_month');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    let rows = m.rows;
    if (segmentFilter === 'investor') rows = rows.filter((r) => r.investor);
    else if (segmentFilter === 'in_our_list') rows = rows.filter((r) => r.in_my_records);
    else if (segmentFilter !== 'all') rows = rows.filter((r) => r.segment === segmentFilter);

    if (journeyFilter === 'never_marketed') rows = rows.filter((r) => !r.marketed);
    else if (journeyFilter === 'prospects') rows = rows.filter((r) => r.prospect_matched);
    else if (journeyFilter === 'opps') rows = rows.filter((r) => r.opp_matched);
    else if (journeyFilter === 'uc') rows = rows.filter((r) => Boolean(r.under_contract_date));
    else if (journeyFilter === 'hhb') rows = rows.filter((r) => Boolean(r.hhb_closed_date));
    else if (journeyFilter !== 'all') {
      rows = rows.filter((r) => r.pipeline_stage === journeyFilter);
    }

    if (q) {
      rows = rows.filter((r) => {
        const blob =
          `${r.address} ${r.buyer_full_name} ${r.segment} ${r.prospect_source} ${r.pipeline_stage_label} ${r.dataflik_id}`.toLowerCase();
        return blob.includes(q);
      });
    }

    const sorted = [...rows].sort((a, b) => {
      const av = sortValue(a, sortKey);
      const bv = sortValue(b, sortKey);
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [m.rows, segmentFilter, journeyFilter, search, sortKey, sortDir]);

  const handleShare = async () => {
    const mode = await copyReportShareUrl(result.job_id, 'investor_sold');
    setShareMsg(mode === 'copied' ? 'Link copied' : 'Copy the link from the prompt');
    setTimeout(() => setShareMsg(''), 2500);
  };

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir(key === 'sold_month' || key === 'sale_amount' ? 'desc' : 'asc');
    }
  };

  const chips: Array<{ id: SegmentFilter; label: string; count: number }> = [
    { id: 'all', label: 'All', count: propertyRows },
    { id: 'investor', label: 'Investor', count: m.segments.investor_count },
    { id: 'in_our_list', label: 'In Our List', count: m.segments.in_our_list_count },
    { id: 'both', label: 'Both', count: m.segments.both_count },
    { id: 'neither', label: 'Neither', count: m.segments.neither_count },
  ];

  const kpiCards: Array<{
    label: string;
    value: string;
    subtitle?: string;
    onClick?: () => void;
    active?: boolean;
  }> = [
    {
      label: 'Properties',
      value: propertyRows.toLocaleString(),
      onClick: () => {
        setSegmentFilter('all');
        setJourneyFilter('all');
      },
      active: segmentFilter === 'all' && journeyFilter === 'all',
    },
    {
      label: 'Marketed',
      value: `${marketing.marketed_count.toLocaleString()} (${marketing.marketed_pct}%)`,
    },
    {
      label: 'Never marketed',
      value: marketing.never_marketed_count.toLocaleString(),
      subtitle: 'Often DNC / suppression — click to spot-check',
      onClick: () => setJourneyFilter('never_marketed'),
      active: journeyFilter === 'never_marketed',
    },
    {
      label: 'Prospects',
      value: `${match.prospect_matched.toLocaleString()} (${match.prospect_rate_pct}%)`,
      subtitle: `Podio ${prospectSources.podio} · QL ${prospectSources.ql} · SF ${prospectSources.sf_tag}`,
      onClick: () => setJourneyFilter('prospects'),
      active: journeyFilter === 'prospects',
    },
    {
      label: 'Opportunities',
      value: `${match.opp_matched.toLocaleString()} (${match.opp_rate_pct}%)`,
      onClick: () => setJourneyFilter('opps'),
      active: journeyFilter === 'opps',
    },
    {
      label: 'Under contract',
      value: match.under_contract_count.toLocaleString(),
      onClick: () => setJourneyFilter('uc'),
      active: journeyFilter === 'uc',
    },
    {
      label: 'HHB closed',
      value: match.hhb_closed_count.toLocaleString(),
      onClick: () => setJourneyFilter('hhb'),
      active: journeyFilter === 'hhb',
    },
    {
      label: 'Median mo list→sold',
      value: fmt(lag.median_months_list_to_sold),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wider text-violet-800">Gate 8</p>
          <h2 className="text-2xl font-bold text-violet-950 tracking-tight">
            Investor &amp; In-List Sold
          </h2>
          <p className="text-sm text-stone-600 mt-1">
            Sold months {m.date_window_start || '—'} → {m.date_window_end || '—'} ·{' '}
            {propertyRows.toLocaleString()} properties (from {txnRows.toLocaleString()}{' '}
            transactions) · {m.inputs.unique_addresses.toLocaleString()} unique addresses
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleShare}
            className="px-3 py-2 text-sm font-medium rounded-lg border border-violet-200 text-violet-900 hover:bg-violet-50"
          >
            Share link
          </button>
          <button
            type="button"
            onClick={onExport}
            disabled={exporting}
            className="px-3 py-2 text-sm font-medium rounded-lg bg-violet-800 text-white hover:bg-violet-900 disabled:opacity-50"
          >
            {exporting ? 'Exporting…' : 'Download XLSX'}
          </button>
          <button
            type="button"
            onClick={onNewRun}
            className="px-3 py-2 text-sm font-medium rounded-lg border border-stone-300 text-stone-700 hover:bg-stone-50"
          >
            New run
          </button>
        </div>
      </div>
      {shareMsg && <p className="text-xs text-violet-800">{shareMsg}</p>}

      {(result.warnings?.length || m.warnings?.length) > 0 && (
        <ul className="text-sm text-amber-900 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 space-y-1">
          {(result.warnings?.length ? result.warnings : m.warnings).map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {kpiCards.map((card) => (
          <div
            key={card.label}
            className={`rounded-xl border px-4 py-3 shadow-sm ${
              card.active
                ? 'border-violet-400 bg-violet-50'
                : 'border-violet-100 bg-white'
            } ${card.onClick ? 'cursor-pointer hover:border-violet-300' : ''}`}
            onClick={card.onClick}
            onKeyDown={
              card.onClick
                ? (e) => {
                    if (e.key === 'Enter' || e.key === ' ') card.onClick?.();
                  }
                : undefined
            }
            role={card.onClick ? 'button' : undefined}
            tabIndex={card.onClick ? 0 : undefined}
          >
            <p className="text-[11px] uppercase tracking-wide text-stone-500 font-semibold">
              {card.label}
            </p>
            <p className="text-lg font-bold text-violet-950 mt-1">{card.value}</p>
            {card.subtitle ? (
              <p className="text-[10px] text-stone-500 mt-1 leading-snug">{card.subtitle}</p>
            ) : null}
          </div>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        {chips.map((chip) => (
          <button
            key={chip.id}
            type="button"
            onClick={() => setSegmentFilter(chip.id)}
            className={`px-3 py-1.5 rounded-full text-xs font-semibold border ${
              segmentFilter === chip.id
                ? 'bg-violet-800 text-white border-violet-800'
                : 'bg-white text-violet-900 border-violet-200 hover:bg-violet-50'
            }`}
          >
            {chip.label} ({chip.count.toLocaleString()})
          </button>
        ))}
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="rounded-xl border border-stone-200 bg-white p-4 overflow-x-auto">
          <h3 className="text-sm font-bold text-stone-800">By segment</h3>
          <p className="text-xs text-stone-500 mt-1">
            Marketed / prospect rates within each investor / in-list cut. Podio prospects counted
            separately.
          </p>
          <table className="mt-3 w-full text-sm min-w-[520px]">
            <thead>
              <tr className="text-left text-xs uppercase text-stone-500">
                <th className="py-1">Segment</th>
                <th className="py-1">N</th>
                <th className="py-1">Marketed %</th>
                <th className="py-1">Prospect %</th>
                <th className="py-1">Podio</th>
              </tr>
            </thead>
            <tbody>
              {bySegment.map((row) => (
                <tr
                  key={row.segment}
                  className={`border-t border-stone-100 cursor-pointer hover:bg-violet-50/60 ${
                    segmentFilter === row.segment ? 'bg-violet-50' : ''
                  }`}
                  onClick={() => setSegmentFilter(row.segment as SegmentFilter)}
                >
                  <td className="py-1.5">{SEGMENT_LABELS[row.segment] || row.segment}</td>
                  <td className="py-1.5">{row.count}</td>
                  <td className="py-1.5">{row.marketed_pct ?? 0}%</td>
                  <td className="py-1.5">{row.prospect_pct ?? 0}%</td>
                  <td className="py-1.5">{row.prospects_podio}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="rounded-xl border border-stone-200 bg-white p-4">
          <h3 className="text-sm font-bold text-stone-800">Pipeline depth (highest stage)</h3>
          <p className="text-xs text-stone-500 mt-1 leading-relaxed">
            Each property counted once at its furthest HHB stage. Prospect includes QL, SF engaged
            tags, or <code className="bg-stone-100 px-1 rounded">PodioSellerLeads</code>.
          </p>
          <table className="mt-3 w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-stone-500">
                <th className="py-1">Stage</th>
                <th className="py-1">Count</th>
                <th className="py-1">Share</th>
              </tr>
            </thead>
            <tbody>
              {pipelineFunnel.map((row) => (
                <tr
                  key={row.stage}
                  className={`border-t border-stone-100 cursor-pointer hover:bg-violet-50/60 ${
                    journeyFilter === row.stage ? 'bg-violet-50' : ''
                  }`}
                  onClick={() => setJourneyFilter(row.stage)}
                >
                  <td className="py-1.5">{row.label}</td>
                  <td className="py-1.5">{row.count}</td>
                  <td className="py-1.5">{row.share_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {m.by_sold_month.length > 0 && (
        <div className="rounded-xl border border-stone-200 bg-white p-4 overflow-x-auto">
          <h3 className="text-sm font-bold text-stone-800">By sold month</h3>
          <table className="mt-3 w-full text-sm min-w-[640px]">
            <thead>
              <tr className="text-left text-xs uppercase text-stone-500">
                <th className="py-1">Sold month</th>
                <th className="py-1">Count</th>
                <th className="py-1">Investor</th>
                <th className="py-1">In list</th>
                <th className="py-1">Both</th>
                <th className="py-1">Marketed</th>
                <th className="py-1">Prospects</th>
              </tr>
            </thead>
            <tbody>
              {m.by_sold_month.map((row) => (
                <tr key={row.sold_month} className="border-t border-stone-100">
                  <td className="py-1.5 font-mono text-xs">{row.sold_month}</td>
                  <td className="py-1.5">{row.count}</td>
                  <td className="py-1.5">{row.investor}</td>
                  <td className="py-1.5">{row.in_our_list}</td>
                  <td className="py-1.5">{row.both}</td>
                  <td className="py-1.5">{row.marketed ?? 0}</td>
                  <td className="py-1.5">{row.prospects ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="rounded-xl border border-stone-200 bg-white overflow-hidden">
        <div className="px-4 py-3 border-b border-stone-100 flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-sm font-bold text-stone-800">
            Journey ({filteredRows.length.toLocaleString()} properties)
          </h3>
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-xs text-stone-600">
              Stage{' '}
              <select
                value={journeyFilter}
                onChange={(e) => setJourneyFilter(e.target.value)}
                className="ml-1 border border-stone-300 rounded-md px-2 py-1 text-sm"
              >
                <option value="all">All</option>
                <option value="never_marketed">Never marketed</option>
                <option value="prospects">Prospects</option>
                <option value="opps">Opportunities</option>
                <option value="uc">Under contract</option>
                <option value="hhb">HHB closed</option>
                {pipelineFunnel.map((row) => (
                  <option key={row.stage} value={row.stage}>
                    {row.label}
                  </option>
                ))}
              </select>
            </label>
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter address or buyer…"
              className="w-56 max-w-full rounded-lg border border-stone-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
            />
          </div>
        </div>
        {journeyFilter === 'never_marketed' && (
          <p className="mx-4 mt-3 text-xs text-amber-900 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
            No <code className="bg-white/80 px-1 rounded">(8020) CC/SMS/DM</code> tags on/before the
            sold month — often DNC or suppression. Full list is on the Never Marketed XLSX sheet.
          </p>
        )}
        <div className="overflow-x-auto max-h-[28rem]">
          <table className="min-w-full text-sm">
            <thead className="bg-stone-50 sticky top-0">
              <tr>
                {DETAIL_COLS.map((c) => {
                  const active = sortKey === c.key;
                  return (
                    <th
                      key={c.key}
                      className="px-3 py-2 text-left text-xs font-semibold text-stone-500 whitespace-nowrap"
                    >
                      <button
                        type="button"
                        onClick={() => toggleSort(c.key)}
                        className={`inline-flex items-center gap-1 hover:text-violet-900 ${
                          active ? 'text-violet-900' : ''
                        }`}
                      >
                        {c.label}
                        <span className="text-[10px] tabular-nums">
                          {active ? (sortDir === 'asc' ? '▲' : '▼') : '↕'}
                        </span>
                      </button>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {filteredRows.slice(0, PREVIEW_LIMIT).map((row, idx) => (
                <tr
                  key={`${row.dataflik_id || row.address_key}-${row.sold_month}-${idx}`}
                  className="border-t border-stone-100"
                >
                  {DETAIL_COLS.map((c) => (
                    <td key={c.key} className="px-3 py-2 whitespace-nowrap">
                      {c.key === 'transaction_count' && row.transaction_count > 1 ? (
                        <span
                          className="inline-flex min-w-[1.5rem] justify-center rounded-md bg-amber-100 px-1.5 py-0.5 text-xs font-semibold text-amber-950"
                          title="Multiple Dataflik transaction_ids for this property×month"
                        >
                          {row.transaction_count}
                        </span>
                      ) : (
                        cellValue(row, c.key)
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {filteredRows.length > PREVIEW_LIMIT ? (
            <p className="px-4 py-2 text-xs text-stone-500 border-t border-stone-100">
              Showing first {PREVIEW_LIMIT.toLocaleString()} of{' '}
              {filteredRows.length.toLocaleString()} filtered properties — download XLSX for full
              detail.
            </p>
          ) : null}
          {filteredRows.length === 0 ? (
            <p className="px-4 py-6 text-sm text-stone-500">No rows match the current filters.</p>
          ) : null}
        </div>
      </div>

      <p className="text-xs text-stone-500 leading-relaxed max-w-3xl">{m.methodology_note}</p>
    </div>
  );
};

export default InvestorSoldResults;
