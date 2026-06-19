import { useState } from 'react';
import { copyReportShareUrl } from '../utils/reportShareUrl';
import type { WebLeadsCompletedResponse } from '../types/webLeads';

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
  const cohortRows = m.inputs.cohort_rows ?? m.inputs.website_ql_total;
  const matchedRows = m.rows;

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
            {cohortRows.toLocaleString()} cohort track
            {' · '}
            {m.match.matched.toLocaleString()} matched REISift
            {m.match.unmatched > 0
              ? ` (${m.match.unmatched.toLocaleString()} not in reference)`
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

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Cohort track" value={cohortRows} />
        <StatCard label="Matched" value={m.match.matched} sub={`${m.match.match_rate_pct}%`} />
        <StatCard
          label="Prior history"
          value={m.prior_history.count}
          sub={`${m.prior_history.share_pct}% of matched`}
        />
        <StatCard
          label="New to database"
          value={m.prior_history.new_to_db_count}
          sub={`${m.prior_history.new_to_db_pct}% of matched`}
        />
      </div>

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

      <section className="rounded-xl border border-stone-200 bg-white p-5">
        <h3 className="text-lg font-semibold text-stone-900">Row detail</h3>
        <div className="mt-4 overflow-x-auto max-h-[480px] overflow-y-auto">
          <table className="min-w-full text-xs">
            <thead className="sticky top-0 bg-white">
              <tr className="border-b text-left text-stone-500">
                <th className="py-2 pr-3">Address</th>
                <th className="py-2 pr-3">Track date</th>
                <th className="py-2 pr-3">REISift Created</th>
                <th className="py-2 pr-3">Anchor</th>
                <th className="py-2 pr-3">Lists</th>
                <th className="py-2 pr-3">Prior?</th>
                <th className="py-2 pr-3">Days list→web</th>
                <th className="py-2 pr-3">8020 before</th>
                <th className="py-2 pr-3">Closed</th>
                <th className="py-2">Path</th>
              </tr>
            </thead>
            <tbody>
              {matchedRows.map((r) => (
                <tr key={r.address_key + r.anchor_date} className="border-b border-stone-100">
                  <td className="py-2 pr-3">{r.address}</td>
                  <td className="py-2 pr-3">
                    {r.cohort_track_date || r.ql_create_date || '—'}
                  </td>
                  <td className="py-2 pr-3">{r.reisift_created_on || '—'}</td>
                  <td className="py-2 pr-3">{r.anchor_date || '—'}</td>
                  <td className="py-2 pr-3">{r.lists.join(', ') || '—'}</td>
                  <td className="py-2 pr-3">{r.had_prior_history ? 'Yes' : 'No'}</td>
                  <td className="py-2 pr-3">
                    {r.days_list_to_web != null ? r.days_list_to_web : '—'}
                  </td>
                  <td className="py-2 pr-3">{r.prior_8020_channels.join(', ') || '—'}</td>
                  <td className="py-2 pr-3">
                    {r.closings_matched
                      ? `${r.closings_date_closed || '—'} (${r.closings_stage || '—'})`
                      : '—'}
                  </td>
                  <td className="py-2 font-mono">
                    {r.journey_path_compact || r.journey_path}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
};

function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: number;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-violet-100 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-stone-500">{label}</p>
      <p className="text-2xl font-bold text-violet-950 mt-1">{value.toLocaleString()}</p>
      {sub ? <p className="text-xs text-stone-500 mt-1">{sub}</p> : null}
    </div>
  );
}

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
