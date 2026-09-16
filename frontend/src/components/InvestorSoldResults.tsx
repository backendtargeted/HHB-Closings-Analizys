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
type SortKey = keyof InvestorSoldRow;
type SortDir = 'asc' | 'desc';

const DETAIL_COLS: Array<{ key: SortKey; label: string }> = [
  { key: 'address', label: 'Address' },
  { key: 'sold_month', label: 'Sold month' },
  { key: 'buyer_full_name', label: 'Buyer' },
  { key: 'sale_amount', label: 'Sale amount' },
  { key: 'transaction_count', label: 'Txns' },
  { key: 'investor', label: 'Investor' },
  { key: 'in_my_records', label: 'In our list' },
  { key: 'segment', label: 'Segment' },
  { key: 'investor_score', label: 'Investor score' },
  { key: 'reisift_matched', label: 'REISift match' },
  { key: 'marketed', label: 'Marketed' },
  { key: 'prospect_matched', label: 'Prospect' },
  { key: 'opp_matched', label: 'Opp' },
  { key: 'pipeline_stage_label', label: 'Pipeline' },
];

const PREVIEW_LIMIT = 500;

function cellValue(row: InvestorSoldRow, key: SortKey): string {
  const v = row[key];
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (v === null || v === undefined || v === '') return '—';
  return String(v);
}

function sortValue(row: InvestorSoldRow, key: SortKey): string | number | boolean {
  const v = row[key];
  if (key === 'sale_amount' || key === 'transaction_count' || key === 'investor_score') {
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
  const [shareMsg, setShareMsg] = useState('');
  const [segmentFilter, setSegmentFilter] = useState<SegmentFilter>('all');
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('sold_month');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    let rows = m.rows;
    if (segmentFilter === 'investor') rows = rows.filter((r) => r.investor);
    else if (segmentFilter === 'in_our_list') rows = rows.filter((r) => r.in_my_records);
    else if (segmentFilter !== 'all') rows = rows.filter((r) => r.segment === segmentFilter);

    if (q) {
      rows = rows.filter((r) => {
        const blob = `${r.address} ${r.buyer_full_name} ${r.segment} ${r.dataflik_id}`.toLowerCase();
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
  }, [m.rows, segmentFilter, search, sortKey, sortDir]);

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

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        {[
          {
            label: 'Properties',
            value: propertyRows.toLocaleString(),
            filter: 'all' as SegmentFilter,
          },
          {
            label: 'Investor',
            value: `${m.segments.investor_count.toLocaleString()} (${m.segments.investor_pct}%)`,
            filter: 'investor' as SegmentFilter,
          },
          {
            label: 'In Our List',
            value: `${m.segments.in_our_list_count.toLocaleString()} (${m.segments.in_our_list_pct}%)`,
            filter: 'in_our_list' as SegmentFilter,
          },
          {
            label: 'Both',
            value: `${m.segments.both_count.toLocaleString()} (${m.segments.both_pct}%)`,
            filter: 'both' as SegmentFilter,
          },
          {
            label: 'Neither',
            value: `${m.segments.neither_count.toLocaleString()} (${m.segments.neither_pct}%)`,
            filter: 'neither' as SegmentFilter,
          },
        ].map((card) => (
          <button
            key={card.label}
            type="button"
            onClick={() => setSegmentFilter(card.filter)}
            className={`text-left rounded-xl border px-4 py-3 shadow-sm ${
              segmentFilter === card.filter
                ? 'border-violet-400 bg-violet-50'
                : 'border-violet-100 bg-white hover:border-violet-300'
            }`}
          >
            <p className="text-[11px] uppercase tracking-wide text-stone-500 font-semibold">
              {card.label}
            </p>
            <p className="text-lg font-bold text-violet-950 mt-1">{card.value}</p>
          </button>
        ))}
      </div>

      {m.inputs.enrichment_enabled ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: 'REISift matched', value: m.enrichment.reisift_matched_count },
            { label: 'Marketed', value: m.enrichment.marketed_count },
            { label: 'Prospects', value: m.enrichment.prospect_matched },
            { label: 'Opportunities', value: m.enrichment.opp_matched },
          ].map((card) => (
            <div
              key={card.label}
              className="rounded-xl border border-stone-200 bg-white px-4 py-3 shadow-sm"
            >
              <p className="text-[11px] uppercase tracking-wide text-stone-500 font-semibold">
                {card.label}
              </p>
              <p className="text-lg font-bold text-stone-900 mt-1">
                {card.value.toLocaleString()}
              </p>
            </div>
          ))}
        </div>
      ) : null}

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

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="rounded-xl border border-stone-200 bg-white overflow-hidden">
          <div className="px-4 py-3 border-b border-stone-100">
            <h3 className="text-sm font-bold text-stone-800">By sold month</h3>
          </div>
          <div className="overflow-x-auto max-h-72">
            <table className="min-w-full text-sm">
              <thead className="bg-stone-50 sticky top-0">
                <tr>
                  {['Month', 'Total', 'Investor', 'In list', 'Both', 'Neither'].map((h) => (
                    <th key={h} className="px-3 py-2 text-left text-xs font-semibold text-stone-500">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {m.by_sold_month.map((r) => (
                  <tr key={r.sold_month} className="border-t border-stone-100">
                    <td className="px-3 py-2">{r.sold_month}</td>
                    <td className="px-3 py-2">{r.count}</td>
                    <td className="px-3 py-2">{r.investor}</td>
                    <td className="px-3 py-2">{r.in_our_list}</td>
                    <td className="px-3 py-2">{r.both}</td>
                    <td className="px-3 py-2">{r.neither}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-xl border border-stone-200 bg-white overflow-hidden">
          <div className="px-4 py-3 border-b border-stone-100">
            <h3 className="text-sm font-bold text-stone-800">By county</h3>
          </div>
          <div className="overflow-x-auto max-h-72">
            <table className="min-w-full text-sm">
              <thead className="bg-stone-50 sticky top-0">
                <tr>
                  {['County', 'Total', 'Investor', 'In list', 'Both', 'Neither'].map((h) => (
                    <th key={h} className="px-3 py-2 text-left text-xs font-semibold text-stone-500">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {m.by_county.slice(0, 40).map((r) => (
                  <tr key={r.county} className="border-t border-stone-100">
                    <td className="px-3 py-2">{r.county}</td>
                    <td className="px-3 py-2">{r.count}</td>
                    <td className="px-3 py-2">{r.investor}</td>
                    <td className="px-3 py-2">{r.in_our_list}</td>
                    <td className="px-3 py-2">{r.both}</td>
                    <td className="px-3 py-2">{r.neither}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-stone-200 bg-white overflow-hidden">
        <div className="px-4 py-3 border-b border-stone-100 flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-sm font-bold text-stone-800">
            Detail ({filteredRows.length.toLocaleString()} properties)
          </h3>
          <label className="flex items-center gap-2 text-sm text-stone-600">
            <span className="sr-only">Search</span>
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter address or buyer…"
              className="w-64 max-w-full rounded-lg border border-stone-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
            />
          </label>
        </div>
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
              detail. Search and sort apply to the full set before this preview.
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
