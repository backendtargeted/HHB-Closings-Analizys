import { useState } from 'react';
import ConsolidatedReportSections from './ConsolidatedReportSections';
import { copyReportShareUrl } from '../utils/reportShareUrl';
import type { MonthlyConsolidatedCompletedResponse } from '../types/monthlyConsolidated';

interface MonthlyConsolidatedResultsProps {
  result: MonthlyConsolidatedCompletedResponse;
  channelLabels: Record<string, string>;
  onNewRun: () => void;
  onExport: () => void;
  exporting: boolean;
}

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

  const handleShare = async () => {
    setShareStatus(null);
    const mode = await copyReportShareUrl(result.job_id, 'monthly_consolidated');
    setShareStatus(mode === 'copied' ? 'Report link copied.' : 'Copy the report link from the prompt.');
  };

  return (
    <div className="space-y-5">
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

      <p className="text-sm text-stone-600">
        <details>
          <summary className="cursor-pointer text-stone-500 hover:text-stone-700">
            Methodology note
          </summary>
          <p className="mt-2 leading-relaxed">{m.methodology_note}</p>
        </details>
      </p>

      <ConsolidatedReportSections
        metrics={m}
        jobId={result.job_id}
        channelLabels={channelLabels}
        onNewRun={onNewRun}
        accent="indigo"
      />
    </div>
  );
};

export default MonthlyConsolidatedResults;
