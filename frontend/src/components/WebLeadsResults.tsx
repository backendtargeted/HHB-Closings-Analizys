import { useState } from 'react';
import { copyReportShareUrl } from '../utils/reportShareUrl';
import type { WebLeadsCompletedResponse } from '../types/webLeads';
import WebLeadsRowTable from './WebLeadsRowTable';

interface WebLeadsResultsProps {
  result: WebLeadsCompletedResponse;
  onNewRun: () => void;
  onExport: () => void;
  exporting: boolean;
}

const WebLeadsResults = ({ result, onNewRun, onExport, exporting }: WebLeadsResultsProps) => {
  const [shareStatus, setShareStatus] = useState<string | null>(null);
  const m = result.metrics;
  const warnings = result.warnings ?? m.warnings ?? [];
  const rowCount =
    m.inputs.cohort_rows ??
    m.inputs.reisift_reference_rows ??
    m.inputs.website_ql_total;

  const handleShare = async () => {
    setShareStatus(null);
    const mode = await copyReportShareUrl(result.job_id, 'web_leads');
    setShareStatus(mode === 'copied' ? 'Report link copied.' : 'Copy the report link from the prompt.');
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-violet-950">Gate 4 — Web Leads</h2>
          <p className="text-sm text-stone-600 mt-1">
            {m.date_window_start} → {m.date_window_end}
            {' · '}
            {rowCount.toLocaleString()} REISift rows
            {m.prior_history.new_to_db_count > 0
              ? ` · ${m.prior_history.new_to_db_count.toLocaleString()} without 8020 tag`
              : ''}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onExport}
            disabled={exporting}
            className="px-4 py-2 rounded-lg border border-violet-700 text-violet-900 text-sm font-medium hover:bg-violet-50 disabled:opacity-50"
          >
            {exporting ? 'Exporting…' : 'Download XLSX'}
          </button>
          <button
            type="button"
            onClick={handleShare}
            className="px-4 py-2 rounded-lg border border-stone-300 text-violet-900 text-sm font-medium hover:bg-stone-50"
          >
            Copy Link
          </button>
          <button
            type="button"
            onClick={onNewRun}
            className="px-4 py-2 rounded-lg bg-violet-800 text-white text-sm font-medium hover:bg-violet-900"
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

      <p className="text-sm text-stone-600">{m.methodology_note}</p>

      {m.age_buckets.some((b) => b.count > 0) && (
        <section className="rounded-xl border border-stone-200 bg-white p-5">
          <h3 className="text-lg font-semibold text-stone-900">List age before web lead</h3>
          <p className="text-sm text-stone-600 mt-1">
            Days from earliest list purchase to web-lead anchor (prior-history rows only).
          </p>
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b text-left text-stone-500">
                  <th className="py-2 pr-4">Bucket</th>
                  <th className="py-2 pr-4">Count</th>
                  <th className="py-2">Share</th>
                </tr>
              </thead>
              <tbody>
                {m.age_buckets
                  .filter((b) => b.count > 0)
                  .map((b) => (
                    <tr key={b.bucket} className="border-b border-stone-100">
                      <td className="py-2 pr-4">{b.bucket}</td>
                      <td className="py-2 pr-4">{b.count}</td>
                      <td className="py-2">{b.share_pct}%</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {m.top_lists.length > 0 && (
        <CompactTable
          title="Top lists (REISift matches)"
          columns={['List', 'Count', 'Share']}
          rows={m.top_lists.map((l) => [l.list, l.count, `${l.share_pct}%`])}
        />
      )}

      {m.combinations.length > 0 && (
        <CompactTable
          title="List combinations (≥3 leads, max 12)"
          columns={['Combination', 'Count', 'Share']}
          rows={m.combinations.map((c) => [c.lists_key, c.row_count, `${c.share_pct}%`])}
        />
      )}

      {m.top_paths.length > 0 && (
        <CompactTable
          title="Journey paths (max 10)"
          columns={['Path', 'Count', 'Share']}
          rows={m.top_paths.map((p) => [p.path, p.count, `${p.share_pct}%`])}
        />
      )}

      <WebLeadsRowTable rows={m.rows} />
    </div>
  );
};

function CompactTable({
  title,
  columns,
  rows,
}: {
  title: string;
  columns: string[];
  rows: (string | number)[][];
}) {
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-5">
      <h3 className="text-lg font-semibold text-stone-900">{title}</h3>
      <div className="mt-4 overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b text-left text-stone-500">
              {columns.map((c) => (
                <th key={c} className="py-2 pr-4">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-stone-100">
                {row.map((cell, j) => (
                  <td key={j} className={`py-2 pr-4 ${j === 0 ? 'font-mono text-xs' : ''}`}>
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default WebLeadsResults;
