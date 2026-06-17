import { useMemo } from 'react';
import QualifiedLeadsResults from './QualifiedLeadsResults';
import LifecycleSection from './LifecycleSection';
import type { MonthlyConsolidatedMetrics } from '../types/monthlyConsolidated';
import type { QualifiedLeadsAnalyzeResponse } from '../types/qualifiedLeads';
import type { SummaryStats } from '../types/analysis';

interface ConsolidatedReportSectionsProps {
  metrics: MonthlyConsolidatedMetrics;
  jobId: string;
  channelLabels: Record<string, string>;
  onNewRun?: () => void;
  accent?: 'indigo' | 'emerald';
}

const pct = (rate: number) => `${(rate * 100).toFixed(2)}%`;

const ConsolidatedReportSections = ({
  metrics: m,
  jobId,
  channelLabels,
  onNewRun,
  accent = 'indigo',
}: ConsolidatedReportSectionsProps) => {
  const cohort = m.cohort;

  const qlWrapped: QualifiedLeadsAnalyzeResponse = {
    job_id: jobId,
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

  const headingClass =
    accent === 'emerald' ? 'text-lg font-semibold text-emerald-950' : 'text-lg font-semibold text-stone-800';
  const groupHeadingClass =
    accent === 'emerald' ? 'text-sm font-semibold text-emerald-900' : 'text-sm font-semibold text-indigo-900';

  return (
    <div className="space-y-8">
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
        <h3 className={`${headingClass} mb-4`}>List performance (distress focus)</h3>
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
        <h3 className={`${headingClass} mb-2`}>
          List combinations (≥{comboMinRows.toLocaleString()} properties)
        </h3>
        <p className="text-xs text-stone-500 mb-4">
          Distress-only stacks (excludes source/import and hygiene lists such as DNC, Dead Deals, Closings
          App, MLSLI, TBD, Buyers). Threshold = median multi-list combo size for this cohort.
        </p>
        {m.combinations.length === 0 ? (
          <p className="text-sm text-stone-500 py-4">
            No combinations met the minimum row threshold for this cohort.
          </p>
        ) : (
          <div className="space-y-6">
            {comboGroups.map(([group, combos]) => (
              <div key={group}>
                <h4 className={`${groupHeadingClass} mb-2`}>{group}</h4>
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
          <h3 className={`${headingClass} mb-2`}>Lead source (from tags)</h3>
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
          onNewRun={onNewRun ?? (() => {})}
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

export default ConsolidatedReportSections;
