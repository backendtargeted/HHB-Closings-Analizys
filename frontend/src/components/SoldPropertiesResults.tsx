import { useMemo, useState } from 'react';
import { copyReportShareUrl } from '../utils/reportShareUrl';
import type {
  SoldPropertiesCompletedResponse,
  SoldPropertyRow,
} from '../types/soldProperties';

interface SoldPropertiesResultsProps {
  result: SoldPropertiesCompletedResponse;
  onNewRun: () => void;
  onExport: () => void;
  exporting: boolean;
}

function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return String(n);
}

const JOURNEY_COLS: Array<{ key: keyof SoldPropertyRow; label: string }> = [
  { key: 'address', label: 'Address' },
  { key: 'sold_month', label: 'Sold month' },
  { key: 'list_purchase_date', label: 'List purchase' },
  { key: 'pipeline_stage_label', label: 'Pipeline stage' },
  { key: 'marketed', label: 'Marketed' },
  { key: 'cc_touch_count', label: 'CC' },
  { key: 'sms_touch_count', label: 'SMS' },
  { key: 'dm_touch_count', label: 'DM' },
  { key: 'first_touch_channel', label: 'First touch' },
  { key: 'prospect_date', label: 'Prospect date' },
  { key: 'opp_created_date', label: 'Opp date' },
  { key: 'under_contract_date', label: 'Under contract' },
  { key: 'hhb_closed_date', label: 'HHB closed' },
  { key: 'months_list_to_sold', label: 'Mo list→sold' },
  { key: 'months_list_to_prospect', label: 'Mo list→prospect' },
];

const SoldPropertiesResults = ({
  result,
  onNewRun,
  onExport,
  exporting,
}: SoldPropertiesResultsProps) => {
  const m = result.metrics;
  const [shareMsg, setShareMsg] = useState('');
  const [stageFilter, setStageFilter] = useState<string>('all');

  const neverMarketedCount = useMemo(
    () => m.rows.filter((r) => !r.marketed).length,
    [m.rows]
  );

  const filteredRows = useMemo(() => {
    if (stageFilter === 'all') return m.rows;
    if (stageFilter === 'never_marketed') return m.rows.filter((r) => !r.marketed);
    return m.rows.filter((r) => r.pipeline_stage === stageFilter);
  }, [m.rows, stageFilter]);

  const ccTotal = m.marketing.total_touch_counts?.CC ?? 0;
  const smsTotal = m.marketing.total_touch_counts?.SMS ?? 0;
  const dmTotal = m.marketing.total_touch_counts?.DM ?? 0;
  const marketedN = m.marketing.marketed_count || 0;
  const avgCc = marketedN ? (ccTotal / marketedN).toFixed(1) : '—';
  const avgSms = marketedN ? (smsTotal / marketedN).toFixed(1) : '—';
  const avgDm = marketedN ? (dmTotal / marketedN).toFixed(1) : '—';

  const handleShare = async () => {
    const mode = await copyReportShareUrl(result.job_id, 'sold_properties');
    setShareMsg(mode === 'copied' ? 'Link copied' : 'Copy the link from the prompt');
    setTimeout(() => setShareMsg(''), 2500);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wider text-teal-800">Gate 6</p>
          <h2 className="text-2xl font-bold text-teal-950 tracking-tight">Sold properties</h2>
          <p className="text-sm text-stone-600 mt-1">
            Sold months {m.date_window_start || '—'} → {m.date_window_end || '—'} ·{' '}
            {m.inputs.cohort_rows.toLocaleString()} cohort rows
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleShare}
            className="px-3 py-2 text-sm font-medium rounded-lg border border-teal-200 text-teal-900 hover:bg-teal-50"
          >
            Share link
          </button>
          <button
            type="button"
            onClick={onExport}
            disabled={exporting}
            className="px-3 py-2 text-sm font-medium rounded-lg bg-teal-800 text-white hover:bg-teal-900 disabled:opacity-50"
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
      {shareMsg && <p className="text-xs text-teal-800">{shareMsg}</p>}

      {(result.warnings?.length || m.warnings?.length) > 0 && (
        <ul className="text-sm text-amber-900 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 space-y-1">
          {(result.warnings?.length ? result.warnings : m.warnings).map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: 'Cohort', value: m.inputs.cohort_rows, onClick: () => setStageFilter('all') },
          {
            label: 'Marketed',
            value: `${m.marketing.marketed_count} (${m.marketing.marketed_pct}%)`,
            onClick: undefined as (() => void) | undefined,
          },
          {
            label: 'Never marketed',
            value: `${neverMarketedCount} (${m.inputs.cohort_rows ? ((100 * neverMarketedCount) / m.inputs.cohort_rows).toFixed(1) : 0}%)`,
            onClick: () => setStageFilter('never_marketed'),
          },
          { label: 'Prospects', value: `${m.match.prospect_matched} (${m.match.prospect_rate_pct}%)` },
          { label: 'Opportunities', value: `${m.match.opp_matched} (${m.match.opp_rate_pct}%)` },
          { label: 'Under contract', value: m.match.under_contract_count },
          { label: 'HHB closed', value: m.match.hhb_closed_count },
          {
            label: 'Median mo list→sold',
            value: fmt(m.lag.median_months_list_to_sold),
          },
        ].map((card) => (
          <div
            key={card.label}
            className={`rounded-xl border border-teal-100 bg-white px-4 py-3 shadow-sm ${
              card.onClick ? 'cursor-pointer hover:border-teal-300' : ''
            }`}
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
            <p className="text-lg font-bold text-teal-950 mt-1">{card.value}</p>
            {card.label === 'Never marketed' ? (
              <p className="text-[10px] text-stone-500 mt-1 leading-snug">
                Often DNC / federal Do Not Call / suppression — click to spot-check
              </p>
            ) : null}
          </div>
        ))}
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="rounded-xl border border-stone-200 bg-white p-4">
          <h3 className="text-sm font-bold text-stone-800">Pipeline depth (highest stage)</h3>
          <p className="text-xs text-stone-500 mt-1 leading-relaxed">
            Each property counted once at its furthest HHB stage. Click a stage to filter the journey
            table. Closed with HHB ={' '}
            <code className="bg-stone-100 px-1 rounded">(CLOSED) 8020</code> tag on REISift — not the
            Opportunities file. Never marketed = no{' '}
            <code className="bg-stone-100 px-1 rounded">(8020) CC/SMS/DM</code> tags on/before sold
            month; often federal Do Not Call, other DNC, or suppression imports (bought into REISift
            but never dialed/texted/mailed).
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
              {m.pipeline_funnel.map((row) => (
                <tr
                  key={row.stage}
                  className={`border-t border-stone-100 cursor-pointer hover:bg-teal-50/60 ${
                    stageFilter === row.stage ? 'bg-teal-50' : ''
                  }`}
                  onClick={() => setStageFilter(row.stage)}
                >
                  <td className="py-1.5">{row.label}</td>
                  <td className="py-1.5">{row.count}</td>
                  <td className="py-1.5">{row.share_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="rounded-xl border border-stone-200 bg-white p-4">
          <h3 className="text-sm font-bold text-stone-800">Touches (tag events, not unique dials)</h3>
          <p className="text-xs text-stone-500 mt-1 leading-relaxed">
            Totals are the sum of <code className="bg-stone-100 px-1 rounded">(8020) CC/SMS/DM</code>{' '}
            month tags across the cohort (on/before sold month). Example: {ccTotal.toLocaleString()}{' '}
            CC tags across {marketedN.toLocaleString()} marketed properties ≈ {avgCc} CC tags per
            marketed property — not {ccTotal.toLocaleString()} calls on all{' '}
            {m.inputs.cohort_rows.toLocaleString()} cohort rows.
          </p>
          <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
            {(
              [
                ['CC', ccTotal, avgCc],
                ['SMS', smsTotal, avgSms],
                ['DM', dmTotal, avgDm],
              ] as const
            ).map(([ch, total, avg]) => (
              <div key={ch} className="rounded-lg bg-teal-50/80 px-3 py-2">
                <dt className="text-xs text-stone-500">{ch} tag events</dt>
                <dd className="font-bold text-teal-950">{total.toLocaleString()}</dd>
                <dd className="text-[11px] text-stone-500 mt-0.5">≈ {avg} / marketed</dd>
              </div>
            ))}
          </dl>
          <p className="text-xs text-stone-500 mt-3">
            All-channel avg per marketed:{' '}
            <strong className="text-stone-700">{fmt(m.marketing.avg_touches_per_marketed)}</strong>
          </p>
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
                <th className="py-1">Marketed</th>
                <th className="py-1">Prospects</th>
                <th className="py-1">Opps</th>
                <th className="py-1">Contract</th>
                <th className="py-1">HHB closed</th>
              </tr>
            </thead>
            <tbody>
              {m.by_sold_month.map((row) => (
                <tr key={row.sold_month} className="border-t border-stone-100">
                  <td className="py-1.5 font-mono text-xs">{row.sold_month}</td>
                  <td className="py-1.5">{row.count}</td>
                  <td className="py-1.5">{row.marketed}</td>
                  <td className="py-1.5">{row.prospects}</td>
                  <td className="py-1.5">{row.opportunities}</td>
                  <td className="py-1.5">{row.under_contract}</td>
                  <td className="py-1.5">{row.hhb_closed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="rounded-xl border border-stone-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-bold text-stone-800">
            Journey ({filteredRows.length.toLocaleString()} rows)
          </h3>
          <label className="text-xs text-stone-600">
            Stage filter{' '}
            <select
              value={stageFilter}
              onChange={(e) => setStageFilter(e.target.value)}
              className="ml-1 border border-stone-300 rounded-md px-2 py-1 text-sm"
            >
              <option value="all">All</option>
              <option value="never_marketed">Never marketed (spot-check)</option>
              {m.pipeline_funnel.map((row) => (
                <option key={row.stage} value={row.stage}>
                  {row.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        {(stageFilter === 'never_marketed' || stageFilter === 'ON_LIST') && (
          <p className="text-xs text-amber-900 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2 mt-2">
            These REISift rows have no{' '}
            <code className="bg-white/80 px-1 rounded">(8020) CC/SMS/DM</code> contact tags
            on/before the sold month — so Gate 6 counts them as never marketed. That often means
            they were bought onto a list but intentionally not dialed/texted/mailed: federal Do Not
            Call, other DNC, or a suppression import. Spot-check{' '}
            <code className="bg-white/80 px-1 rounded">Tags</code> /{' '}
            <code className="bg-white/80 px-1 rounded">Lists</code> for DNC or suppression labels.
            Less common: missing contact-tag import or history on a duplicate row. Full list is on
            the <strong>Never Marketed</strong> XLSX sheet.
          </p>
        )}
        <div className="mt-3 overflow-x-auto max-h-[480px] overflow-y-auto">
          <table className="w-full text-xs min-w-[1100px]">
            <thead className="sticky top-0 bg-white">
              <tr className="text-left uppercase text-stone-500 border-b border-stone-200">
                {JOURNEY_COLS.map((c) => (
                  <th key={c.key} className="py-2 pr-3 font-semibold whitespace-nowrap">
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredRows.slice(0, 500).map((row) => (
                <tr key={row.address_key + row.sold_month} className="border-t border-stone-100">
                  {JOURNEY_COLS.map((c) => {
                    const val = row[c.key];
                    let display: string;
                    if (typeof val === 'boolean') display = val ? 'Yes' : 'No';
                    else if (val === null || val === undefined || val === '') display = '—';
                    else display = String(val);
                    return (
                      <td key={c.key} className="py-1.5 pr-3 whitespace-nowrap max-w-[220px] truncate">
                        {display}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          {filteredRows.length > 500 && (
            <p className="text-xs text-stone-500 mt-2">
              Showing first 500 rows — download XLSX for the full journey / Never Marketed sheets.
            </p>
          )}
        </div>
      </div>
    </div>
  );
};

export default SoldPropertiesResults;
