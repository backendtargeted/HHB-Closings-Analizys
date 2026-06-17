import { useMemo, useState } from 'react';
import { copyReportShareUrl } from '../utils/reportShareUrl';
import type { MarketingRampCompletedResponse, MarketingRampRow } from '../types/marketingRamp';

interface MarketingRampResultsProps {
  result: MarketingRampCompletedResponse;
  channelLabels: Record<string, string>;
  onNewRun: () => void;
  onExport: () => void;
  exporting: boolean;
}

const ROW_PREVIEW_LIMIT = 25;

function formatCell(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return value.toLocaleString();
  return String(value);
}

function humanizeKey(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

const MarketingRampResults = ({
  result,
  channelLabels,
  onNewRun,
  onExport,
  exporting,
}: MarketingRampResultsProps) => {
  const [shareStatus, setShareStatus] = useState<string | null>(null);
  const m = result.metrics;
  const warnings = m.warnings ?? [];
  const rows = result.rows ?? [];

  const channelEntries = useMemo(
    () =>
      Object.entries(m.channel_counts)
        .filter(([, v]) => v > 0)
        .sort((a, b) => b[1] - a[1]),
    [m.channel_counts]
  );

  const touchEntries = useMemo(
    () =>
      Object.entries(m.touch_counts)
        .filter(([, v]) => v > 0)
        .sort((a, b) => b[1] - a[1]),
    [m.touch_counts]
  );

  const opportunityEntries = useMemo(
    () =>
      Object.entries(m.opportunity_counts)
        .filter(([, v]) => v > 0)
        .sort((a, b) => b[1] - a[1]),
    [m.opportunity_counts]
  );

  const populationEntries = useMemo(
    () =>
      Object.entries(m.population_counts).filter(
        ([, v]) => v !== undefined && v !== null && v > 0
      ),
    [m.population_counts]
  );

  const rowColumns = useMemo(() => {
    if (rows.length === 0) return [] as string[];
    const keys = new Set<string>();
    for (const row of rows.slice(0, 50)) {
      Object.keys(row).forEach((k) => keys.add(k));
    }
    return Array.from(keys);
  }, [rows]);

  const previewRows = rows.slice(0, ROW_PREVIEW_LIMIT);

  const handleShare = async () => {
    setShareStatus(null);
    const mode = await copyReportShareUrl(result.job_id, 'marketing_ramp');
    setShareStatus(mode === 'copied' ? 'Report link copied.' : 'Copy the report link from the prompt.');
  };

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-emerald-950">Gate 3 — Marketing ramp report</h2>
          <p className="text-sm text-stone-600 mt-1">
            Window: {m.date_window_start} → {m.date_window_end}
            {rows.length > 0 ? ` · ${rows.length.toLocaleString()} journey rows` : ''}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onExport}
            disabled={exporting}
            className="px-4 py-2 rounded-lg border border-emerald-700 text-emerald-900 text-sm font-medium hover:bg-emerald-50 disabled:opacity-50"
          >
            {exporting ? 'Exporting…' : 'Download CSV'}
          </button>
          <button
            type="button"
            onClick={handleShare}
            className="px-4 py-2 rounded-lg border border-stone-300 text-emerald-900 text-sm font-medium hover:bg-stone-50"
          >
            Copy Link
          </button>
          <button
            type="button"
            onClick={onNewRun}
            className="px-4 py-2 rounded-lg bg-emerald-800 text-white text-sm font-medium hover:bg-emerald-900"
          >
            New run
          </button>
        </div>
      </div>
      {shareStatus ? <p className="text-xs text-stone-500 -mt-4">{shareStatus}</p> : null}

      {warnings.length > 0 && (
        <ul className="text-sm text-amber-900 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 list-disc pl-6 space-y-1">
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      <p className="text-sm text-stone-600 bg-stone-50 border border-stone-200 rounded-lg px-4 py-3 leading-relaxed">
        {m.methodology_note}
      </p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {populationEntries.map(([key, value]) => (
          <Stat key={key} label={humanizeKey(key)} value={value ?? 0} />
        ))}
        <Stat
          label="REISift match rate"
          value={`${m.reisift_match.match_rate_pct}%`}
          sub={`${m.reisift_match.matched.toLocaleString()} matched · ${m.reisift_match.unmatched.toLocaleString()} unmatched`}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <CountPanel title="Channel counts" entries={channelEntries} channelLabels={channelLabels} />
        <CountPanel title="Touch counts" entries={touchEntries} />
        <CountPanel title="Opportunity counts" entries={opportunityEntries} />
      </div>

      {rows.length > 0 && rowColumns.length > 0 && (
        <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm overflow-x-auto">
          <h3 className="text-lg font-semibold text-stone-800 mb-2">Lead journey rows</h3>
          <p className="text-xs text-stone-500 mb-4">
            Showing first {Math.min(ROW_PREVIEW_LIMIT, rows.length).toLocaleString()} of{' '}
            {rows.length.toLocaleString()} rows. Download CSV for the full export.
          </p>
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-stone-500 border-b">
                {rowColumns.map((col) => (
                  <th key={col} className="py-2 pr-4 whitespace-nowrap">
                    {humanizeKey(col)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {previewRows.map((row: MarketingRampRow, idx) => (
                <tr key={idx} className="border-b border-stone-100">
                  {rowColumns.map((col) => (
                    <td key={col} className="py-2 pr-4 text-stone-800 whitespace-nowrap tabular-nums">
                      {formatCell(row[col])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
};

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: number | string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-stone-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium text-stone-500 uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold text-stone-900 mt-1 tabular-nums">
        {typeof value === 'number' ? value.toLocaleString() : value}
      </p>
      {sub && <p className="text-xs text-stone-500 mt-1">{sub}</p>}
    </div>
  );
}

function CountPanel({
  title,
  entries,
  channelLabels,
}: {
  title: string;
  entries: [string, number][];
  channelLabels?: Record<string, string>;
}) {
  return (
    <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
      <h3 className="text-lg font-semibold text-stone-800 mb-4">{title}</h3>
      {entries.length === 0 ? (
        <p className="text-sm text-stone-500">No data in this category.</p>
      ) : (
        <table className="min-w-full text-sm">
          <thead>
            <tr className="text-left text-stone-500 border-b">
              <th className="py-2 pr-4">Label</th>
              <th className="py-2 text-right">Count</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([key, count]) => (
              <tr key={key} className="border-b border-stone-100">
                <td className="py-2 pr-4 font-medium text-stone-800">
                  {channelLabels?.[key] ?? humanizeKey(key)}
                </td>
                <td className="py-2 text-right tabular-nums">{count.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export default MarketingRampResults;
