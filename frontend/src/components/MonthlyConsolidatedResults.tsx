import { useMemo, useState } from 'react';
import QualifiedLeadsResults from './QualifiedLeadsResults';
import LifecycleSection from './LifecycleSection';
import { copyReportShareUrl } from '../utils/reportShareUrl';
import type { MonthlyConsolidatedCompletedResponse } from '../types/monthlyConsolidated';
import type { QualifiedLeadsAnalyzeResponse } from '../types/qualifiedLeads';
import type { SummaryStats } from '../types/analysis';

interface MonthlyConsolidatedResultsProps {
  result: MonthlyConsolidatedCompletedResponse;
  channelLabels: Record<string, string>;
  onNewRun: () => void;
  onExport: () => void;
  exporting: boolean;
}

const pct = (rate: number) => `${(rate * 100).toFixed(2)}%`;

const MonthlyConsolidatedResults = ({
  result,
  channelLabels,
  onNewRun,
  onExport,
  exporting,
}: MonthlyConsolidatedResultsProps) => {
  const [shareStatus, setShareStatus] = useState<string | null>(null);
  const m = result.metrics;
  const warnings = result.warnings ?? m.warnings ?? [];
  const cohort = m.cohort;

  const qlWrapped: QualifiedLeadsAnalyzeResponse = {
    job_id: result.job_id,
    metrics: m.qualified_leads,
    use_full_file_span: false,
  };

  const lifecycleStats = (m.lifecycle_stats || {}) as SummaryStats;
  const hasLifecycle =
    lifecycleStats.Funnel_Acquired_Count != null ||
    (lifecycleStats.Top_Paths_Json && lifecycleStats.Top_Paths_Json.length > 2);

  const openPipeline = m.open_pipeline_lifecycle;
  const tagLeadSource = m.tag_lead_source_counts ?? [];
  const comboMinRows = m.combo_min_rows ?? 10;

  const comboGroups = useMemo(() => {
    const grouped = new Map<string, typeof m.combinations>();
    for (const combo of m.combinations) {
      const group = combo.combo_group || combo.lists[0] || 'Other';
      const bucket = grouped.get(group) ?? [];
      bucket.push(combo);
      grouped.set(group, bucket);
    }
    return Array.from(grouped.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [m.combinations]);

  const handleShare = async () => {
    setShareStatus(null);
    const mode = await copyReportShareUrl(result.job_id, 'monthly_consolidated');
    setShareStatus(mode === 'copied' ? 'Report link copied.' : 'Copy the report link from the prompt.');
  };

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-indigo-950">Gate 2 — Consolidated report</h2>
          <p className="text-sm text-stone-600 mt-1">
            {m.cohort_scope === 'full_file' ? 'Full REISift export' : `Month ${m.report_month}`}
            {m.period.start && m.period.end ? (
              <> · Created span {m.period.start} → {m.period.end}</>
            ) : null}
            {' · '}
            {m.inputs.reisift_rows_ingested.toLocaleString()} rows ingested
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onExport}
            disabled={exporting}
            className="px-4 py-2 rounded-lg border border-indigo-700 text-indigo-900 text-sm font-medium hover:bg-indigo-50 disabled:opacity-50"
          >
            {exporting ? 'Exporting…' : 'Download consolidated XLSX'}
          </button>
          <button
            type="button"
            onClick={handleShare}
            className="px-4 py-2 rounded-lg border border-stone-300 text-indigo-900 text-sm font-medium hover:bg-stone-50"
          >
            Copy Link
          </button>
          <button
            type="button"
            onClick={onNewRun}
            className="px-4 py-2 rounded-lg bg-indigo-800 text-white text-sm font-medium hover:bg-indigo-900"
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

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <Stat label="REISift rows analyzed" value={cohort.total_rows} />
        <Stat label="CRM leads ((SF) tag)" value={cohort.crm_lead_rows} />
        <Stat label="Closings" value={cohort.closing_rows} />
        <Stat label="Stacked (multi-list)" value={cohort.stacked_rows} sub={`${cohort.stacked_pct}%`} />
        <Stat
          label="QL address match"
          value={`${m.list_attribution.match_rate_pct}%`}
          sub={`${m.list_attribution.matched_to_reisift} matched`}
        />
      </div>

      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm overflow-x-auto">
        <h3 className="text-lg font-semibold text-stone-800 mb-4">List performance (distress focus)</h3>
        <table className="min-w-full text-sm">
          <thead>
            <tr className="text-left text-stone-500 border-b">
              <th className="py-2 pr-4">List</th>
              <th className="py-2 pr-4 text-right">Rows</th>
              <th className="py-2 pr-4 text-right">CRM</th>
              <th className="py-2 pr-4 text-right">Qualified</th>
              <th className="py-2 pr-4 text-right">Closings</th>
              <th className="py-2 pr-4 text-right">Close rate</th>
              <th className="py-2 text-right">Stacked rows</th>
            </tr>
          </thead>
          <tbody>
            {m.lists.map((row) => (
              <tr key={row.token} className="border-b border-stone-100">
                <td className="py-2 pr-4 font-medium text-stone-800">{row.token}</td>
                <td className="py-2 pr-4 text-right tabular-nums">{row.row_count.toLocaleString()}</td>
                <td className="py-2 pr-4 text-right tabular-nums">{row.crm_lead_count.toLocaleString()}</td>
                <td className="py-2 pr-4 text-right tabular-nums">
                  {row.qualified_lead_count.toLocaleString()}
                </td>
                <td className="py-2 pr-4 text-right tabular-nums">{row.closing_count.toLocaleString()}</td>
                <td className="py-2 pr-4 text-right tabular-nums">{pct(row.closing_rate)}</td>
                <td className="py-2 text-right tabular-nums">{row.stacked_row_count.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm overflow-x-auto">
        <h3 className="text-lg font-semibold text-stone-800 mb-2">
          List combinations (≥{comboMinRows.toLocaleString()} properties)
        </h3>
        <p className="text-xs text-stone-500 mb-4">
          Distress-only stacks (excludes DNC + Dead Deals, Closings App MLSLI TBD). Threshold =
          median multi-list combo size for this cohort. Grouped by primary distress list.
        </p>
        {m.combinations.length === 0 ? (
          <p className="text-sm text-stone-500 py-4">
            No combinations met the minimum row threshold for this cohort.
          </p>
        ) : (
          <div className="space-y-6">
            {comboGroups.map(([group, combos]) => (
              <div key={group}>
                <h4 className="text-sm font-semibold text-indigo-900 mb-2">{group}</h4>
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="text-left text-stone-500 border-b">
                      <th className="py-2 pr-4">Combination</th>
                      <th className="py-2 pr-4 text-right">Rows</th>
                      <th className="py-2 pr-4 text-right">Closings</th>
                      <th className="py-2 text-right">Close rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {combos.map((c) => (
                      <tr key={c.lists_key} className="border-b border-stone-100">
                        <td className="py-2 pr-4 text-stone-800">{c.lists_key}</td>
                        <td className="py-2 pr-4 text-right tabular-nums">
                          {c.row_count.toLocaleString()}
                        </td>
                        <td className="py-2 pr-4 text-right tabular-nums">
                          {c.closing_count.toLocaleString()}
                        </td>
                        <td className="py-2 text-right tabular-nums">{pct(c.closing_rate)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        )}
      </section>

      {tagLeadSource.length > 0 && (
        <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
          <h3 className="text-lg font-semibold text-stone-800 mb-2">Lead source (from tags)</h3>
          <p className="text-xs text-stone-500 mb-4">
            Derived from REISift tag history — first 8020 channel or list purchase.
          </p>
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-stone-500 border-b">
                <th className="py-2 pr-4">Source</th>
                <th className="py-2 pr-4 text-right">Properties</th>
                <th className="py-2 text-right">Share</th>
              </tr>
            </thead>
            <tbody>
              {tagLeadSource.map((row) => (
                <tr key={row.source} className="border-b border-stone-100">
                  <td className="py-2 pr-4 font-medium text-stone-800">{row.source}</td>
                  <td className="py-2 pr-4 text-right tabular-nums">{row.count.toLocaleString()}</td>
                  <td className="py-2 text-right tabular-nums">{row.share_pct.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section>
        <h3 className="text-lg font-semibold text-teal-950 mb-3">Channel effectiveness (qualified leads)</h3>
        <QualifiedLeadsResults
          result={qlWrapped}
          channelLabels={channelLabels}
          onNewRun={onNewRun}
          onExportRows={() => {}}
          exporting={false}
          embedded
        />
      </section>

      {hasLifecycle && (
        <section>
          <h3 className="text-lg font-semibold text-navy mb-3">Lead journey (closing cohort)</h3>
          <LifecycleSection stats={lifecycleStats} />
        </section>
      )}

      {openPipeline && (openPipeline.stuck_at_stage?.length ?? 0) > 0 && (
        <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm overflow-x-auto">
          <h3 className="text-lg font-semibold text-navy mb-2">Open pipeline — where leads are stuck</h3>
          <p className="text-xs text-stone-500 mb-4">
            Non-closing cohort rows ranked by highest lifecycle stage reached (tag-derived).
          </p>
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-stone-500 border-b">
                <th className="py-2 pr-4">Highest stage</th>
                <th className="py-2 pr-4 text-right">Properties</th>
                <th className="py-2 text-right">Share of open</th>
              </tr>
            </thead>
            <tbody>
              {openPipeline.stuck_at_stage.map((row) => (
                <tr key={row.stage} className="border-b border-stone-100">
                  <td className="py-2 pr-4 font-medium text-stone-800">{row.stage}</td>
                  <td className="py-2 pr-4 text-right tabular-nums">{row.count.toLocaleString()}</td>
                  <td className="py-2 text-right tabular-nums">{row.share_pct.toFixed(1)}%</td>
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

export default MonthlyConsolidatedResults;
