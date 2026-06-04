import { useMemo, useState } from 'react';
import { copyReportShareUrl } from '../utils/reportShareUrl';
import {
  Bar,
  BarChart,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { QualifiedLeadsAnalyzeResponse } from '../types/qualifiedLeads';

const PIE_COLORS = ['#0f766e', '#1B3A57', '#F4B942', '#8B7355', '#64748b', '#94a3b8', '#cbd5e1'];

interface QualifiedLeadsResultsProps {
  result: QualifiedLeadsAnalyzeResponse;
  channelLabels: Record<string, string>;
  onNewRun: () => void;
  onExportRows: () => void;
  exporting: boolean;
  /** When true, omit page header and action buttons (e.g. embedded in monthly consolidated). */
  embedded?: boolean;
}

const QualifiedLeadsResults = ({
  result,
  channelLabels,
  onNewRun,
  onExportRows,
  exporting,
  embedded = false,
}: QualifiedLeadsResultsProps) => {
  const [shareStatus, setShareStatus] = useState<string | null>(null);
  const m = result.metrics;

  const chartData = useMemo(() => {
    return Object.entries(m.channel_counts)
      .filter(([, v]) => v > 0)
      .map(([key, value]) => ({
        key,
        name: channelLabels[key] || key,
        value,
        share: m.channel_shares_pct[key] ?? 0,
      }))
      .sort((a, b) => b.value - a.value);
  }, [m.channel_counts, m.channel_shares_pct, channelLabels]);

  const unmappedEntries = Object.entries(m.lead_source_unmapped || {}).slice(0, 12);

  return (
    <div className="space-y-6">
      {!embedded && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-2xl font-bold text-teal-950">Qualified leads summary</h2>
              <p className="text-sm text-stone-600 mt-1">
                Window: {m.date_window_start} → {m.date_window_end}
                {m.create_date_min && (
                  <span className="text-stone-500">
                    {' '}
                    (file span {m.create_date_min} – {m.create_date_max})
                  </span>
                )}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={onExportRows}
                disabled={exporting}
                className="px-4 py-2 rounded-lg border border-teal-700 text-teal-900 text-sm font-medium hover:bg-teal-50 disabled:opacity-50"
              >
                {exporting ? 'Exporting…' : 'Download row detail CSV'}
              </button>
              <button
                type="button"
                onClick={async () => {
                  setShareStatus(null);
                  const mode = await copyReportShareUrl(result.job_id, 'qualified_leads');
                  setShareStatus(
                    mode === 'copied' ? 'Report link copied.' : 'Copy the report link from the prompt.'
                  );
                }}
                className="px-4 py-2 rounded-lg border border-stone-300 text-teal-900 text-sm font-medium hover:bg-stone-50"
              >
                Copy Link
              </button>
              <button
                type="button"
                onClick={onNewRun}
                className="px-4 py-2 rounded-lg bg-teal-800 text-white text-sm font-medium hover:bg-teal-900"
              >
                New upload
              </button>
            </div>
          </div>
          {shareStatus ? <p className="text-xs text-stone-500">{shareStatus}</p> : null}

          <p className="text-sm text-stone-600 bg-stone-50 border border-stone-200 rounded-lg px-4 py-3 leading-relaxed">
            {m.qualified_rate_window_note}
          </p>
        </>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Rows in file" value={m.rows_ingested} />
        <StatCard label="Posted in window" value={m.posted_in_window} highlight />
        <StatCard label="In-scope channels" value={m.in_scope_subtotal} sub={`${m.in_scope_share_pct}% of window`} />
        <StatCard label="Bad / missing dates" value={m.posted_excluded_bad_date} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
          <h3 className="text-lg font-semibold text-stone-800 mb-2">Share of posted leads by channel</h3>
          <p className="text-xs text-stone-500 mb-4">Hover slices for counts; legend lists full channel names.</p>
          <ResponsiveContainer width="100%" height={400}>
            <PieChart margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
              <Pie
                data={chartData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="42%"
                innerRadius={58}
                outerRadius={88}
                isAnimationActive={false}
              >
                {chartData.map((_, i) => (
                  <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} stroke="#fff" strokeWidth={1} />
                ))}
              </Pie>
              <Tooltip
                formatter={(v: number, _n, p) => {
                  const share = (p?.payload as { share?: number })?.share;
                  return [`${Number(v).toLocaleString()} leads (${share?.toFixed(1) ?? 0}%)`, 'Count'];
                }}
              />
              <Legend
                layout="vertical"
                align="right"
                verticalAlign="middle"
                wrapperStyle={{ fontSize: 12, lineHeight: '1.5', paddingLeft: 12 }}
                formatter={(value: string, entry) => {
                  const share = (entry?.payload as { share?: number })?.share;
                  return `${value} — ${share?.toFixed(1) ?? 0}%`;
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
          <h3 className="text-lg font-semibold text-stone-800 mb-4">Qualified lead counts</h3>
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={chartData} layout="vertical" margin={{ left: 8, right: 24, top: 8, bottom: 8 }}>
              <XAxis type="number" tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v))} />
              <YAxis type="category" dataKey="name" width={148} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="value" fill="#0f766e" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="rounded-2xl border border-stone-200 bg-white overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-stone-100 text-stone-700">
            <tr>
              <th className="text-left px-4 py-2 font-semibold">Channel</th>
              <th className="text-right px-4 py-2 font-semibold">Count</th>
              <th className="text-right px-4 py-2 font-semibold">Share of posted</th>
            </tr>
          </thead>
          <tbody>
            {chartData.map((row) => (
              <tr key={row.key} className="border-t border-stone-100">
                <td className="px-4 py-2">{row.name}</td>
                <td className="px-4 py-2 text-right font-mono">{row.value.toLocaleString()}</td>
                <td className="px-4 py-2 text-right font-mono">{row.share.toFixed(2)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(unmappedEntries.length > 0 || m.lead_source_blank > 0) && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/80 p-4 text-sm text-amber-950">
          <p className="font-semibold mb-2">Other bucket detail</p>
          {m.lead_source_blank > 0 && (
            <p className="mb-2">Blank lead source: {m.lead_source_blank} rows</p>
          )}
          {unmappedEntries.length > 0 && (
            <ul className="list-disc list-inside space-y-0.5 text-xs">
              {unmappedEntries.map(([src, cnt]) => (
                <li key={src}>
                  {src}: {cnt}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};

function StatCard({
  label,
  value,
  sub,
  highlight,
}: {
  label: string;
  value: number;
  sub?: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-xl border p-4 ${
        highlight ? 'border-teal-300 bg-teal-50/50' : 'border-stone-200 bg-white'
      }`}
    >
      <p className="text-xs font-medium text-stone-500 uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold text-stone-900 mt-1">{value.toLocaleString()}</p>
      {sub && <p className="text-xs text-stone-500 mt-1">{sub}</p>}
    </div>
  );
}

export default QualifiedLeadsResults;
