import { useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { FirstTouchRow, SummaryStats, TopPathRow } from '../types/analysis';

const FUNNEL_STAGES = [
  { key: 'Acquired', label: 'List purchased', countKey: 'Funnel_Acquired_Count' as const },
  { key: 'Researched', label: 'Skip traced', countKey: 'Funnel_Researched_Count' as const },
  { key: 'First contact', label: '8020 CC/SMS/DM', countKey: 'Funnel_First_Contacted_Count' as const },
  { key: 'Engaged', label: 'SF engaged', countKey: 'Funnel_Engaged_Count' as const },
  {
    key: 'Converted',
    label: 'SF converted (under contract)',
    countKey: 'Funnel_Converted_Count' as const,
    help: 'Salesforce "converted" / under contract — contract signed, not settlement closed.',
  },
];

const COLORS = ['#1e3a5f', '#2d5a87', '#3d7aaf', '#c9a227', '#10b981', '#f59e0b'];

interface LifecycleSectionProps {
  stats: SummaryStats;
}

function safeJsonParse<T>(raw: string | null | undefined, fallback: T): T {
  if (!raw || !String(raw).trim()) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

const LifecycleSection = ({ stats }: LifecycleSectionProps) => {
  const [tab, setTab] = useState<'funnel' | 'paths' | 'first'>('funnel');

  const funnelChartData = useMemo(() => {
    return FUNNEL_STAGES.map((s) => ({
      name: s.label,
      short: s.key,
      count: stats[s.countKey] ?? 0,
      help: 'help' in s ? (s as { help?: string }).help : undefined,
    }));
  }, [stats]);

  const paths: TopPathRow[] = useMemo(
    () => safeJsonParse<TopPathRow[]>(stats.Top_Paths_Json, []),
    [stats.Top_Paths_Json]
  );

  const firstTouch: FirstTouchRow[] = useMemo(
    () => safeJsonParse<FirstTouchRow[]>(stats.First_Touch_Breakdown_Json, []),
    [stats.First_Touch_Breakdown_Json]
  );

  const hasLifecycle =
    stats.Funnel_Acquired_Count != null ||
    (stats.Top_Paths_Json && stats.Top_Paths_Json.length > 2) ||
    (stats.First_Touch_Breakdown_Json && stats.First_Touch_Breakdown_Json.length > 2);

  if (!hasLifecycle) {
    return (
      <div className="rounded-lg border border-stone-200 bg-stone-50/80 p-6 text-sm text-stone-600">
        <h3 className="text-lg font-semibold text-navy mb-2">Lead lifecycle</h3>
        <p>
          Run a new analysis to populate funnel, paths, and first-touch metrics from Tags (including
          (SF) and list/skip markers).
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-stone-200 bg-surface shadow-sm p-6">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h3 className="text-lg font-semibold text-navy">Lead lifecycle</h3>
        <div className="flex rounded-lg border border-stone-200 overflow-hidden text-sm">
          {(
            [
              ['funnel', 'Funnel'],
              ['paths', 'Paths'],
              ['first', 'First touch'],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={`px-4 py-2 font-medium transition-colors ${
                tab === id ? 'bg-navy text-white' : 'bg-white text-stone-700 hover:bg-stone-50'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {tab === 'funnel' && (
        <div className="h-80">
          <p className="text-xs text-stone-500 mb-2">
            Matched deals reaching each stage (tags strictly before Date Closed). Engaged / converted
            use CRM status labels on (SF) tags.
          </p>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={funnelChartData} layout="vertical" margin={{ left: 100, right: 24 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" allowDecimals={false} />
              <YAxis type="category" dataKey="name" width={96} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v: number) => [v, 'Deals']} />
              <Bar dataKey="count" name="Deals" radius={[0, 4, 4, 0]}>
                {funnelChartData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <dl className="mt-3 grid grid-cols-2 md:grid-cols-3 gap-2 text-xs text-stone-600">
            <div>
              <dt className="font-medium text-stone-800">Acquired rate</dt>
              <dd>{stats.Funnel_Acquired_Rate_Pct ?? '—'}%</dd>
            </div>
            <div>
              <dt className="font-medium text-stone-800">Engaged → converted</dt>
              <dd>{stats.Engaged_To_Converted_Rate_Pct ?? '—'}%</dd>
            </div>
            <div>
              <dt className="font-medium text-stone-800">First contact rate</dt>
              <dd>{stats.Funnel_First_Contact_Rate_Pct ?? '—'}%</dd>
            </div>
          </dl>
        </div>
      )}

      {tab === 'paths' && (
        <div className="space-y-3">
          <p className="text-xs text-stone-500">
            Top ordered tag paths before close. Paths collapse consecutive identical steps; identical tag tokens on one row are deduped when parsing Tags. Median days use first 8020 contact → close. See docs/REPORT_METHODOLOGY.md.
          </p>
          {paths.length === 0 ? (
            <p className="text-sm text-stone-600">No path data.</p>
          ) : (
            <div className="overflow-x-auto max-h-96">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="border-b border-stone-200 text-left text-stone-600">
                    <th className="py-2 pr-4">Path</th>
                    <th className="py-2 pr-4">Count</th>
                    <th className="py-2">Median days to close</th>
                  </tr>
                </thead>
                <tbody>
                  {paths.map((row) => (
                    <tr key={row.path} className="border-b border-stone-100">
                      <td className="py-2 pr-4 font-mono text-xs max-w-xl break-all">{row.path}</td>
                      <td className="py-2 pr-4">{row.count}</td>
                      <td className="py-2">
                        {row.median_days_to_close != null ? row.median_days_to_close.toFixed(1) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {paths.length > 0 && (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={paths} layout="vertical" margin={{ left: 8, right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" allowDecimals={false} />
                  <YAxis type="category" dataKey="path" width={200} tick={{ fontSize: 9 }} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#1e3a5f" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {tab === 'first' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="h-64">
            {firstTouch.length === 0 ? (
              <p className="text-sm text-stone-600">No first-touch breakdown.</p>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={firstTouch}
                    dataKey="count"
                    nameKey="channel"
                    cx="50%"
                    cy="50%"
                    outerRadius={90}
                  >
                    {firstTouch.map((_, i) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
          <div>
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-stone-200 text-left text-stone-600">
                  <th className="py-2 pr-4">First channel</th>
                  <th className="py-2 pr-4">Deals</th>
                  <th className="py-2">Median days to close</th>
                </tr>
              </thead>
              <tbody>
                {firstTouch.map((row) => (
                  <tr key={row.channel} className="border-b border-stone-100">
                    <td className="py-2 pr-4 font-medium">{row.channel}</td>
                    <td className="py-2 pr-4">{row.count}</td>
                    <td className="py-2">
                      {row.median_days_to_close != null ? row.median_days_to_close.toFixed(1) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

export default LifecycleSection;
