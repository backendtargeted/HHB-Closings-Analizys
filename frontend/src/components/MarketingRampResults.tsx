import { useMemo, useState, type ReactNode } from 'react';
import ConsolidatedReportSections from './ConsolidatedReportSections';
import CollapsibleSection from './CollapsibleSection';
import { ReportTable } from './ReportTable';
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
const TOUCH_CHANNEL_ORDER = ['CC', 'SMS', 'DM'] as const;

const JOURNEY_KEY_COLUMNS: { key: string; label: string; align?: 'left' | 'right'; sticky?: boolean }[] = [
  { key: 'street', label: 'Street', sticky: true },
  { key: 'city', label: 'City' },
  { key: 'state', label: 'St' },
  { key: 'population_kind', label: 'Population' },
  { key: 'reporting_channel', label: 'Channel' },
  { key: 'create_date', label: 'QL date' },
  { key: 'date_closed', label: 'Closed' },
  { key: 'date_under_contract', label: 'Contract' },
  { key: 'first_touch_channel', label: '1st touch' },
  { key: 'cc_touch_count', label: 'CC', align: 'right' },
  { key: 'sms_touch_count', label: 'SMS', align: 'right' },
  { key: 'dm_touch_count', label: 'DM', align: 'right' },
  { key: 'days_list_to_first_touch', label: 'Days→touch', align: 'right' },
  { key: 'days_list_to_create_date', label: 'Days→QL', align: 'right' },
  { key: 'days_list_to_close', label: 'Days→close', align: 'right' },
  { key: 'has_reisift_match', label: 'REISift' },
];

const POPULATION_LABELS: Record<string, string> = {
  population_rows: 'Population',
  qualified_leads_in_window: 'QL in window',
  qualified_leads_total: 'QL total',
  closings_in_window: 'Closings in window',
  closings_total: 'Closings total',
  qualified_only: 'Qualified only',
  closing_only: 'Closing only',
  both: 'QL + closing',
  reisift_rows: 'REISift rows',
};

function sumTouchCountsFromRows(rows: MarketingRampRow[], channel: string): number {
  const key = `${channel.toLowerCase()}_touch_count`;
  return rows.reduce((sum, row) => sum + (Number(row[key]) || 0), 0);
}

function channelLabel(channelLabels: Record<string, string>, key: string): string {
  return channelLabels[key] ?? key;
}

const MarketingRampResults = ({
  result,
  channelLabels,
  onNewRun,
  onExport,
  exporting,
}: MarketingRampResultsProps) => {
  const [shareStatus, setShareStatus] = useState<string | null>(null);
  const [showAllJourneyColumns, setShowAllJourneyColumns] = useState(false);
  const m = result.metrics;
  const warnings = m.warnings ?? [];
  const rows = result.rows ?? [];
  const consolidated = result.consolidated;

  const channelEntries = useMemo(
    () =>
      Object.entries(m.channel_counts)
        .filter(([, v]) => v > 0)
        .sort((a, b) => b[1] - a[1]),
    [m.channel_counts]
  );

  const totalTouchEntries = useMemo((): [string, number][] => {
    const fromMetrics = m.total_touch_counts;
    if (fromMetrics) {
      return TOUCH_CHANNEL_ORDER.map((ch) => [ch, fromMetrics[ch] ?? 0]);
    }
    return TOUCH_CHANNEL_ORDER.map((ch) => [ch, sumTouchCountsFromRows(rows, ch)]);
  }, [m.total_touch_counts, rows]);

  const opportunityEntries = useMemo(
    () =>
      Object.entries(m.opportunity_counts)
        .filter(([, v]) => v > 0)
        .sort((a, b) => b[1] - a[1]),
    [m.opportunity_counts]
  );

  const populationEntries = useMemo(
    () =>
      Object.entries(m.population_counts)
        .filter(([, v]) => v !== undefined && v !== null && v > 0)
        .map(([key, value]) => [POPULATION_LABELS[key] ?? key, value] as [string, number]),
    [m.population_counts]
  );

  const allJourneyColumns = useMemo(() => {
    if (rows.length === 0) return [] as string[];
    const keys = new Set<string>();
    for (const row of rows.slice(0, 50)) {
      Object.keys(row).forEach((k) => keys.add(k));
    }
    return Array.from(keys);
  }, [rows]);

  const journeyColumns = useMemo(() => {
    if (showAllJourneyColumns) {
      return allJourneyColumns.map((key) => ({
        key,
        label: key.replace(/_/g, ' '),
        align: key.includes('count') || key.startsWith('days_') ? ('right' as const) : undefined,
        sticky: key === 'street',
      }));
    }
    return JOURNEY_KEY_COLUMNS.map((col) => ({
      ...col,
      sticky: col.key === 'street',
    }));
  }, [showAllJourneyColumns, allJourneyColumns]);

  const previewRows = rows.slice(0, ROW_PREVIEW_LIMIT);
  const consolidatedWarnings = consolidated?.warnings ?? [];

  const handleShare = async () => {
    setShareStatus(null);
    const mode = await copyReportShareUrl(result.job_id, 'marketing_ramp');
    setShareStatus(mode === 'copied' ? 'Report link copied.' : 'Copy the report link from the prompt.');
  };

  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-emerald-950">Gate 3 — Monthly report</h2>
          <p className="text-sm text-stone-600 mt-1">
            {m.date_window_start} → {m.date_window_end}
            {rows.length > 0 ? ` · ${rows.length.toLocaleString()} rows` : ''}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onExport}
            disabled={exporting}
            className="px-4 py-2 rounded-lg border border-emerald-700 text-emerald-900 text-sm font-medium hover:bg-emerald-50 disabled:opacity-50"
          >
            {exporting ? 'Exporting…' : consolidated ? 'Download XLSX' : 'Download CSV'}
          </button>
          <button
            type="button"
            onClick={handleShare}
            className="px-4 py-2 rounded-lg border border-stone-300 text-emerald-900 text-sm font-medium hover:bg-stone-50"
          >
            Copy link
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

      {shareStatus ? <p className="text-xs text-stone-500 -mt-2">{shareStatus}</p> : null}

      {[...warnings, ...consolidatedWarnings].length > 0 && (
        <ul className="text-sm text-amber-900 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 list-disc pl-6 space-y-1">
          {[...warnings, ...consolidatedWarnings].map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      <nav
        aria-label="Report sections"
        className="sticky top-0 z-30 flex flex-wrap gap-2 py-2 px-3 -mx-3 bg-stone-50/95 backdrop-blur border border-stone-200 rounded-xl"
      >
        <NavPill label="Summary" onClick={() => scrollTo('ramp-summary')} />
        {rows.length > 0 ? (
          <NavPill label="Journey rows" onClick={() => scrollTo('ramp-journey')} />
        ) : null}
        {consolidated ? (
          <NavPill label="List analysis" onClick={() => scrollTo('ramp-consolidated')} />
        ) : null}
      </nav>

      <CollapsibleSection
        id="ramp-summary"
        title="Marketing ramp summary"
        subtitle="Population, channels, and touch totals"
        defaultOpen
      >
        <div className="space-y-5">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {populationEntries.map(([label, value]) => (
              <Stat key={label} label={label} value={value} />
            ))}
            <Stat
              label="REISift match"
              value={`${m.reisift_match.match_rate_pct}%`}
              sub={`${m.reisift_match.matched.toLocaleString()} matched`}
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <MetricCard title="Channels (QL attribution)">
              {channelEntries.length === 0 ? (
                <p className="text-sm text-stone-500">No data</p>
              ) : (
                <ul className="space-y-1.5 text-sm">
                  {channelEntries.map(([key, count]) => (
                    <li key={key} className="flex justify-between gap-3">
                      <span className="text-stone-700">{channelLabel(channelLabels, key)}</span>
                      <span className="font-medium tabular-nums">{count.toLocaleString()}</span>
                    </li>
                  ))}
                </ul>
              )}
            </MetricCard>
            <MetricCard title="Total touches" subtitle="(8020) tags in REISift">
              <ul className="space-y-1.5 text-sm">
                {totalTouchEntries.map(([key, count]) => (
                  <li key={key} className="flex justify-between gap-3">
                    <span className="text-stone-700">{channelLabel(channelLabels, key)}</span>
                    <span className="font-medium tabular-nums">{count.toLocaleString()}</span>
                  </li>
                ))}
              </ul>
            </MetricCard>
            <MetricCard title="Opportunities">
              {opportunityEntries.length === 0 ? (
                <p className="text-sm text-stone-500">No under-contract rows in window</p>
              ) : (
                <ul className="space-y-1.5 text-sm">
                  {opportunityEntries.map(([key, count]) => (
                    <li key={key} className="flex justify-between gap-3">
                      <span className="text-stone-700 capitalize">{key.replace(/_/g, ' ')}</span>
                      <span className="font-medium tabular-nums">{count.toLocaleString()}</span>
                    </li>
                  ))}
                </ul>
              )}
            </MetricCard>
          </div>

          <details className="text-sm text-stone-600">
            <summary className="cursor-pointer text-stone-500 hover:text-stone-700">
              Methodology note
            </summary>
            <p className="mt-2 leading-relaxed">{m.methodology_note}</p>
          </details>
        </div>
      </CollapsibleSection>

      {rows.length > 0 && journeyColumns.length > 0 && (
        <CollapsibleSection
          id="ramp-journey"
          title="Lead journey rows"
          subtitle={`Preview of ${Math.min(ROW_PREVIEW_LIMIT, rows.length).toLocaleString()} of ${rows.length.toLocaleString()} — export for full data`}
          badge="Key columns"
          defaultOpen
        >
          <div className="space-y-3">
            <label className="inline-flex items-center gap-2 text-sm text-stone-600 cursor-pointer">
              <input
                type="checkbox"
                checked={showAllJourneyColumns}
                onChange={(e) => setShowAllJourneyColumns(e.target.checked)}
                className="rounded border-stone-300"
              />
              Show all columns ({allJourneyColumns.length})
            </label>
            <ReportTable
              caption="Lead journey preview"
              maxHeight="32rem"
              rows={previewRows as MarketingRampRow[]}
              rowKey={(_, idx) => String(idx)}
              columns={journeyColumns.map((col) => ({
                ...col,
                render:
                  col.key === 'reporting_channel' || col.key === 'first_touch_channel'
                    ? (row: MarketingRampRow) =>
                        channelLabel(channelLabels, String(row[col.key] ?? ''))
                    : col.key === 'population_kind'
                      ? (row: MarketingRampRow) =>
                          String(row[col.key] ?? '').replace(/_/g, ' ')
                      : undefined,
              }))}
            />
          </div>
        </CollapsibleSection>
      )}

      {consolidated ? (
        <div id="ramp-consolidated" className="scroll-mt-24 space-y-4">
          <div className="pt-2">
            <h3 className="text-xl font-semibold text-indigo-950">Consolidated list analysis</h3>
            <p className="text-sm text-stone-600 mt-1">
              {consolidated.metrics.cohort_scope === 'full_file'
                ? 'Full REISift export'
                : `Month ${consolidated.metrics.report_month}`}
            </p>
          </div>
          <ConsolidatedReportSections
            metrics={consolidated.metrics}
            jobId={result.job_id}
            channelLabels={channelLabels}
            onNewRun={onNewRun}
            accent="emerald"
          />
        </div>
      ) : (
        <p className="text-sm text-stone-500 italic">
          Consolidated sections unavailable for this saved report. Re-run Gate 3 to include list
          analysis.
        </p>
      )}
    </div>
  );
};

function NavPill({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="px-3 py-1.5 text-sm font-medium rounded-lg bg-white border border-stone-200 text-stone-700 hover:bg-emerald-50 hover:border-emerald-200 hover:text-emerald-900 transition-colors"
    >
      {label}
    </button>
  );
}

function Stat({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="rounded-xl border border-stone-200 bg-white px-3 py-3">
      <p className="text-[11px] font-medium text-stone-500 uppercase tracking-wide">{label}</p>
      <p className="text-xl font-bold text-stone-900 mt-0.5 tabular-nums">
        {typeof value === 'number' ? value.toLocaleString() : value}
      </p>
      {sub ? <p className="text-xs text-stone-500 mt-0.5">{sub}</p> : null}
    </div>
  );
}

function MetricCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-stone-200 bg-stone-50/50 p-4">
      <h4 className="text-sm font-semibold text-stone-800">{title}</h4>
      {subtitle ? <p className="text-xs text-stone-500 mt-0.5">{subtitle}</p> : null}
      <div className="mt-3">{children}</div>
    </div>
  );
}

export default MarketingRampResults;
