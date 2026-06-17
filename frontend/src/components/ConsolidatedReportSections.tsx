import { useMemo } from 'react';
import QualifiedLeadsResults from './QualifiedLeadsResults';
import LifecycleSection from './LifecycleSection';
import CollapsibleSection from './CollapsibleSection';
import { ReportTable } from './ReportTable';
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

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-3">
        <Stat label="REISift rows" value={cohort.total_rows} />
        <Stat label="CRM leads" value={cohort.crm_lead_rows} />
        <Stat label="Closings" value={cohort.closing_rows} />
        <Stat label="Stacked rows" value={cohort.stacked_rows} sub={`${cohort.stacked_pct}%`} />
        <Stat
          label="QL match"
          value={`${m.list_attribution.match_rate_pct}%`}
          sub={`${m.list_attribution.matched_to_reisift} matched`}
        />
      </div>

      <CollapsibleSection
        id="consolidated-lists"
        title="List performance"
        subtitle="Distress lists ranked by cohort activity"
        badge={`${m.lists.length} lists`}
        defaultOpen
      >
        <ReportTable
          caption="List performance"
          maxHeight="24rem"
          rows={m.lists}
          rowKey={(row) => row.token}
          columns={[
            { key: 'token', label: 'List', sticky: true },
            { key: 'row_count', label: 'Rows', align: 'right' },
            { key: 'crm_lead_count', label: 'CRM', align: 'right' },
            { key: 'qualified_lead_count', label: 'Qualified', align: 'right' },
            { key: 'closing_count', label: 'Closings', align: 'right' },
            {
              key: 'closing_rate',
              label: 'Close rate',
              align: 'right',
              render: (row) => pct(row.closing_rate),
            },
            { key: 'stacked_row_count', label: 'Stacked', align: 'right' },
          ]}
        />
      </CollapsibleSection>

      <CollapsibleSection
        id="consolidated-combos"
        title="List combinations"
        subtitle={`Stacks with ≥${comboMinRows.toLocaleString()} properties (distress lists only)`}
        badge={`${m.combinations.length} combos`}
        defaultOpen={false}
      >
        {m.combinations.length === 0 ? (
          <p className="text-sm text-stone-500 py-2">
            No combinations met the minimum row threshold for this cohort.
          </p>
        ) : (
          <div className="space-y-5">
            {comboGroups.map(([group, combos]) => (
              <div key={group}>
                <h4 className="text-sm font-semibold text-stone-800 mb-2">{group}</h4>
                <ReportTable
                  caption={`${group} combinations`}
                  maxHeight="16rem"
                  rows={combos}
                  rowKey={(row) => row.lists_key}
                  columns={[
                    { key: 'lists_key', label: 'Combination', sticky: true },
                    { key: 'row_count', label: 'Rows', align: 'right' },
                    { key: 'closing_count', label: 'Closings', align: 'right' },
                    {
                      key: 'closing_rate',
                      label: 'Close rate',
                      align: 'right',
                      render: (row) => pct(row.closing_rate),
                    },
                  ]}
                />
              </div>
            ))}
          </div>
        )}
      </CollapsibleSection>

      {tagLeadSource.length > 0 && (
        <CollapsibleSection
          id="consolidated-tag-source"
          title="Lead source (from tags)"
          subtitle="First 8020 channel or list purchase per property"
          defaultOpen={false}
        >
          <ReportTable
            caption="Tag lead source"
            maxHeight="16rem"
            rows={tagLeadSource}
            rowKey={(row) => row.source}
            columns={[
              { key: 'source', label: 'Source', sticky: true },
              { key: 'count', label: 'Properties', align: 'right' },
              {
                key: 'share_pct',
                label: 'Share',
                align: 'right',
                render: (row) => `${row.share_pct.toFixed(1)}%`,
              },
            ]}
          />
        </CollapsibleSection>
      )}

      <CollapsibleSection
        id="consolidated-channels"
        title="Channel effectiveness"
        subtitle="Qualified leads by Salesforce lead source"
        defaultOpen={false}
      >
        <QualifiedLeadsResults
          result={qlWrapped}
          channelLabels={channelLabels}
          onNewRun={onNewRun ?? (() => {})}
          onExportRows={() => {}}
          exporting={false}
          embedded
        />
      </CollapsibleSection>

      {hasLifecycle && (
        <CollapsibleSection
          id="consolidated-lifecycle"
          title="Lead journey (closing cohort)"
          defaultOpen={false}
        >
          <LifecycleSection stats={lifecycleStats} />
        </CollapsibleSection>
      )}

      {openPipeline && (openPipeline.stuck_at_stage?.length ?? 0) > 0 && (
        <CollapsibleSection
          id="consolidated-pipeline"
          title="Open pipeline"
          subtitle="Where non-closing leads are stuck"
          defaultOpen={false}
        >
          <ReportTable
            caption="Open pipeline stuck at stage"
            maxHeight="16rem"
            rows={openPipeline.stuck_at_stage}
            rowKey={(row) => row.stage}
            columns={[
              { key: 'stage', label: 'Highest stage', sticky: true },
              { key: 'count', label: 'Properties', align: 'right' },
              {
                key: 'share_pct',
                label: 'Share of open',
                align: 'right',
                render: (row) => `${row.share_pct.toFixed(1)}%`,
              },
            ]}
          />
        </CollapsibleSection>
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
    <div className="rounded-xl border border-stone-200 bg-white px-3 py-3 shadow-sm">
      <p className="text-[11px] font-medium text-stone-500 uppercase tracking-wide">{label}</p>
      <p className="text-xl font-bold text-stone-900 mt-0.5 tabular-nums">
        {typeof value === 'number' ? value.toLocaleString() : value}
      </p>
      {sub && <p className="text-xs text-stone-500 mt-0.5">{sub}</p>}
    </div>
  );
}

export default ConsolidatedReportSections;
