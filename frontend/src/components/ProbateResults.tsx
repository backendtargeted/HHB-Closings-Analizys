import { useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { copyReportShareUrl } from '../utils/reportShareUrl';
import type {
  CountShareRow,
  CrmBeforeFirstListRow,
  ProbateCompletedResponse,
  ProbateRow,
} from '../types/probate';

interface ProbateResultsProps {
  result: ProbateCompletedResponse;
  onNewRun: () => void;
  onExport: () => void;
  exporting: boolean;
}

function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return String(n);
}

function displaySourceLabel(raw: string): string {
  const map: Record<string, string> = {
    'LIP only': 'LIP Probates only',
    'LIP first': 'LIP Probates first',
    lip_only: 'LIP Probates only',
    lip_first: 'LIP Probates first',
  };
  if (map[raw]) return map[raw];
  if (raw.startsWith('LIP ') && !raw.startsWith('LIP Probates')) {
    return `LIP Probates ${raw.slice(4)}`;
  }
  return raw;
}

function displayCampaign(raw: string): string {
  const text = (raw || '').trim();
  if (!text || text === '(blank)' || text.toLowerCase() === 'nan') {
    return 'No Campaign in Salesforce';
  }
  if (/smarter\s+contact/i.test(text) && /res/i.test(text)) return 'RES SMS';
  if (/launch\s*control/i.test(text)) return 'RES SMS';
  return text;
}

function yAxisWidth(labels: string[]): number {
  const longest = labels.reduce((max, label) => Math.max(max, label.length), 0);
  return Math.min(260, Math.max(112, Math.round(longest * 7.5)));
}

function barPlotHeight(rows: number, rowPx = 40): number {
  return Math.max(200, rows * rowPx + 24);
}

function VerticalBars({
  data,
  series,
  grouped = false,
}: {
  data: Array<{ name: string; [key: string]: string | number }>;
  series: Array<{ key: string; name: string; color: string }>;
  grouped?: boolean;
}) {
  if (data.length === 0) return null;
  const labels = data.map((d) => d.name);
  const width = yAxisWidth(labels);
  const height = barPlotHeight(data.length, grouped ? 56 : 42);
  return (
    <div className="mt-4 w-full" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout="vertical"
          margin={{ left: 4, right: 40, top: 8, bottom: 8 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#e7e5e4" horizontal={false} />
          <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
          <YAxis
            type="category"
            dataKey="name"
            width={width}
            interval={0}
            tick={{ fontSize: 12, fill: '#1c1917' }}
          />
          <Tooltip />
          {grouped ? <Legend /> : null}
          {series.map((s) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.name}
              fill={s.color}
              radius={[0, 4, 4, 0]}
              maxBarSize={22}
            >
              {!grouped ? (
                <LabelList dataKey={s.key} position="right" fontSize={11} fill="#44403c" />
              ) : null}
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

const CompactTable = ({
  title,
  subtitle,
  columns,
  rows,
}: {
  title: string;
  subtitle?: string;
  columns: string[];
  rows: Array<Array<string | number>>;
}) => {
  if (rows.length === 0) return null;
  return (
    <section className="rounded-xl border border-stone-200 bg-white p-5">
      <h3 className="text-lg font-semibold text-stone-900">{title}</h3>
      {subtitle ? <p className="text-sm text-stone-600 mt-1">{subtitle}</p> : null}
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
                  <td key={j} className="py-2 pr-4">
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
};

const ProbateResults = ({ result, onNewRun, onExport, exporting }: ProbateResultsProps) => {
  const [shareStatus, setShareStatus] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const m = result.metrics;
  const warnings = result.warnings ?? m.warnings ?? [];
  const campaigns = m.campaigns ?? m.other_campaigns ?? [];

  const firstSourceChart = useMemo(
    () =>
      m.first_source.map((r) => ({
        name: displaySourceLabel(r.label ?? r.key ?? ''),
        listed: r.count ?? 0,
        prospects: r.prospects ?? 0,
      })),
    [m.first_source]
  );
  const campaignChart = useMemo(() => {
    const rolled = new Map<string, number>();
    for (const r of campaigns) {
      const name = displayCampaign(r.label ?? '');
      rolled.set(name, (rolled.get(name) ?? 0) + (r.count ?? 0));
    }
    return [...rolled.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([name, count]) => ({ name, count }));
  }, [campaigns]);
  const lagChart = useMemo(
    () =>
      m.lag_buckets
        .filter((b) => (b.count ?? 0) > 0)
        .map((b) => ({ name: b.bucket ?? '', count: b.count ?? 0 })),
    [m.lag_buckets]
  );
  const monthChart = useMemo(
    () =>
      m.cohorts.map((c) => ({
        name: c.lip_month ?? '',
        listed: c.listed ?? 0,
        prospects: c.prospects ?? 0,
      })),
    [m.cohorts]
  );
  const funnelChart = useMemo(
    () => [
      { name: 'LIP Probates listed', count: m.funnel.lip },
      { name: 'Prospect', count: m.funnel.prospect },
      { name: 'Opportunity', count: m.funnel.opportunity },
      { name: 'Transaction', count: m.funnel.transaction },
    ],
    [m.funnel]
  );

  const handleShare = async () => {
    setShareStatus(null);
    const mode = await copyReportShareUrl(result.job_id, 'probate');
    setShareStatus(mode === 'copied' ? 'Report link copied.' : 'Copy the report link from the prompt.');
  };

  const campaignTableRows = useMemo(() => {
    const rolled = new Map<string, number>();
    for (const r of campaigns) {
      const name = displayCampaign(r.label ?? '');
      rolled.set(name, (rolled.get(name) ?? 0) + (r.count ?? 0));
    }
    const total = [...rolled.values()].reduce((sum, n) => sum + n, 0);
    return [...rolled.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([label, count]) => [
        label,
        count,
        `${total > 0 ? Math.round((10000 * count) / total) / 100 : 0}%`,
      ]);
  }, [campaigns]);

  const reasonRows = (items: CountShareRow[]) =>
    items.map((r) => [r.label ?? '', r.count ?? 0, `${r.share_pct}%`]);

  const filteredRows: ProbateRow[] = m.rows.filter((row) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return [
      row.address,
      row.county,
      row.first_source_label,
      row.ql_campaign,
      row.lip_month,
      row.txn_primary_reason,
      row.txn_secondary_reason,
    ]
      .join(' ')
      .toLowerCase()
      .includes(q);
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-rose-950">Gate 5 — Probate lifecycle</h2>
          <p className="text-sm text-stone-600 mt-1">
            {m.date_window_start} → {m.date_window_end}
            {' · '}
            {m.inputs.lip_universe.toLocaleString()} LIP Probates properties
            {' · '}
            {m.match.prospect_matched.toLocaleString()} Prospects ({m.match.prospect_rate_pct}%)
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onExport}
            disabled={exporting}
            className="px-4 py-2 rounded-lg border border-rose-700 text-rose-900 text-sm font-medium hover:bg-rose-50 disabled:opacity-50"
          >
            {exporting ? 'Exporting…' : 'Download XLSX'}
          </button>
          <button
            type="button"
            onClick={handleShare}
            className="px-4 py-2 rounded-lg border border-stone-300 text-rose-900 text-sm font-medium hover:bg-stone-50"
          >
            Copy Link
          </button>
          <button
            type="button"
            onClick={onNewRun}
            className="px-4 py-2 rounded-lg bg-rose-800 text-white text-sm font-medium hover:bg-rose-900"
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

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="LIP Probates universe" value={m.inputs.lip_universe.toLocaleString()} />
        <Stat
          label="Became Prospect"
          value={`${m.match.prospect_matched.toLocaleString()} (${m.match.prospect_rate_pct}%)`}
        />
        <Stat label="Median months to CRM" value={fmt(m.lag.median_months_lip_to_prospect)} />
        <Stat label="Mean months to CRM" value={fmt(m.lag.mean_months_lip_to_prospect)} />
        <Stat
          label="Opportunities"
          value={`${m.match.opp_matched.toLocaleString()} (${m.match.opp_rate_pct}%)`}
        />
        <Stat
          label="Transactions"
          value={`${m.match.txn_matched.toLocaleString()} (${m.match.txn_rate_pct}%)`}
        />
        <Stat
          label="In CRM before first list"
          value={(m.match.crm_before_first_list ?? m.crm_before_first_list?.length ?? 0).toLocaleString()}
        />
      </div>

      <section className="rounded-xl border border-stone-200 bg-white p-5">
        <h3 className="text-lg font-semibold text-stone-900">Funnel</h3>
        <p className="text-sm text-stone-600 mt-1">
          First list is the source. A Prospect is a QL whose Create Date is on or after that
          first-list month.
        </p>
        <VerticalBars
          data={funnelChart}
          series={[{ key: 'count', name: 'Properties', color: '#9f1239' }]}
        />
      </section>

      <section className="rounded-xl border border-stone-200 bg-white p-5">
        <h3 className="text-lg font-semibold text-stone-900">Who delivered first</h3>
        <p className="text-sm text-stone-600 mt-1">
          QL credit is this first list. Same REISift row: Long Island Profiles vs List Purchased 8020.
        </p>
        <VerticalBars
          data={firstSourceChart}
          grouped
          series={[
            { key: 'listed', name: 'Listed', color: '#1c1917' },
            { key: 'prospects', name: 'Prospects', color: '#be123c' },
          ]}
        />
      </section>

      <CompactTable
        title="Who delivered first"
        columns={['Source / QL credit', 'Listed', 'Share', 'Prospects', 'Prospect %']}
        rows={m.first_source.map((r) => [
          displaySourceLabel(r.label ?? r.key ?? ''),
          r.count ?? 0,
          `${r.share_pct}%`,
          r.prospects ?? 0,
          `${r.prospect_rate_pct ?? 0}%`,
        ])}
      />

      <CompactTable
        title="County"
        columns={['County', 'Listed', 'Share', 'Prospects', 'Prospect %']}
        rows={m.counties
          .filter((r) => (r.count ?? 0) > 0)
          .map((r) => [
            r.county ?? '',
            r.count ?? 0,
            `${r.share_pct}%`,
            r.prospects ?? 0,
            `${r.prospect_rate_pct ?? 0}%`,
          ])}
      />

      <section className="rounded-xl border border-stone-200 bg-white p-5">
        <h3 className="text-lg font-semibold text-stone-900">Months first list to CRM push</h3>
        <p className="text-sm text-stone-600 mt-1">
          Calendar months from the first-list month to Salesforce Create Date for counted
          Prospects. Earlier CRM rows are not conversions.
        </p>
        {lagChart.length > 0 ? (
          <VerticalBars
            data={lagChart}
            series={[{ key: 'count', name: 'Prospects', color: '#9f1239' }]}
          />
        ) : null}
      </section>

      <CompactTable
        title="Months first list to CRM push"
        columns={['Bucket', 'Prospects', 'Share']}
        rows={m.lag_buckets
          .filter((r) => (r.count ?? 0) > 0)
          .map((r) => [r.bucket ?? '', r.count ?? 0, `${r.share_pct}%`])}
      />

      <section className="rounded-xl border border-stone-200 bg-white p-5">
        <h3 className="text-lg font-semibold text-stone-900">Campaign</h3>
        <p className="text-sm text-stone-600 mt-1">
          How the team worked the matched Prospect (Total Qualified Leads Campaign). Not the list
          source.
        </p>
        {campaignChart.length > 0 ? (
          <VerticalBars
            data={campaignChart}
            series={[{ key: 'count', name: 'Prospects', color: '#44403c' }]}
          />
        ) : null}
      </section>

      <CompactTable
        title="Campaign"
        subtitle="From the Campaign column on Total Qualified Leads. Extra context, not QL credit."
        columns={['Campaign', 'Count', 'Share of Prospects']}
        rows={campaignTableRows}
      />

      <section className="rounded-xl border border-stone-200 bg-white p-5">
        <h3 className="text-lg font-semibold text-stone-900">Listed by first LIP Probates month</h3>
        <p className="text-sm text-stone-600 mt-1">
          Drop size that month. Recent months have had less time to become Prospects.
        </p>
        {monthChart.length > 0 ? (
          <VerticalBars
            data={monthChart}
            grouped
            series={[
              { key: 'listed', name: 'Listed', color: '#44403c' },
              { key: 'prospects', name: 'Prospects', color: '#be123c' },
            ]}
          />
        ) : null}
      </section>

      <CompactTable
        title="By first LIP Probates month"
        columns={['Month', 'Listed', 'Prospects', 'Prospect %', 'Txns', 'Mean months']}
        rows={m.cohorts.map((r) => [
          r.lip_month ?? '',
          r.listed ?? 0,
          r.prospects ?? 0,
          `${r.prospect_rate_pct ?? 0}%`,
          r.txns ?? 0,
          fmt(r.mean_months_lip_to_prospect),
        ])}
      />

      <CompactTable
        title="In CRM before first list"
        subtitle="Address or phone matched a Qualified Lead, but Create Date is before the first LIP Probates/8020 list month. Not a conversion from this list. Not source credit."
        columns={['Address', 'County', 'LIP Probates', '8020', 'CRM date', 'Match', 'Campaign']}
        rows={(m.crm_before_first_list ?? []).map((r: CrmBeforeFirstListRow) => [
          r.address ?? '',
          r.county ?? '',
          r.lip_month ?? '',
          r.eight_month || '—',
          r.prospect_date || '—',
          r.prospect_match_via || '—',
          r.ql_campaign ? displayCampaign(r.ql_campaign) : '—',
        ])}
      />

      <CompactTable
        title="Transactions — Primary Reason for Selling"
        subtitle="From the Transactions pipeline only, after address match. Not used to decide who is probate."
        columns={['Reason', 'Count', 'Share of matched txns']}
        rows={reasonRows(m.primary_reasons)}
      />

      <CompactTable
        title="Transactions — Secondary Reason for Selling"
        columns={['Reason', 'Count', 'Share of matched txns']}
        rows={reasonRows(m.secondary_reasons)}
      />

      <section className="rounded-xl border border-stone-200 bg-white p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-lg font-semibold text-stone-900">Property rows</h3>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter address, county, reason…"
            className="text-sm border border-stone-300 rounded-lg px-3 py-1.5 w-64"
          />
        </div>
        <div className="mt-4 overflow-x-auto max-h-[28rem]">
          <table className="min-w-full text-xs">
            <thead>
              <tr className="border-b text-left text-stone-500">
                <th className="py-2 pr-3">Address</th>
                <th className="py-2 pr-3">County</th>
                <th className="py-2 pr-3">LIP Probates</th>
                <th className="py-2 pr-3">8020</th>
                <th className="py-2 pr-3">QL credit</th>
                <th className="py-2 pr-3">Campaign</th>
                <th className="py-2 pr-3">Prospect</th>
                <th className="py-2 pr-3">Months</th>
                <th className="py-2 pr-3">Txn primary</th>
                <th className="py-2 pr-3">Txn secondary</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((r) => (
                <tr key={r.address_key + r.lip_month + r.address} className="border-b border-stone-100">
                  <td className="py-2 pr-3 whitespace-nowrap">{r.address}</td>
                  <td className="py-2 pr-3">{r.county}</td>
                  <td className="py-2 pr-3">{r.lip_month}</td>
                  <td className="py-2 pr-3">{r.eight_month || '—'}</td>
                  <td className="py-2 pr-3">
                    {r.prospect_matched ? displaySourceLabel(r.first_source_label) : '—'}
                  </td>
                  <td className="py-2 pr-3">
                    {r.prospect_matched ? displayCampaign(r.ql_campaign) : '—'}
                  </td>
                  <td className="py-2 pr-3">{r.prospect_date || '—'}</td>
                  <td className="py-2 pr-3">{fmt(r.months_winner_to_prospect)}</td>
                  <td className="py-2 pr-3">{r.txn_primary_reason || '—'}</td>
                  <td className="py-2 pr-3">{r.txn_secondary_reason || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-stone-500 mt-2">
          {filteredRows.length.toLocaleString()} of {m.rows.length.toLocaleString()} rows
        </p>
      </section>
    </div>
  );
};

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-stone-200 bg-white px-4 py-3">
      <p className="text-xs uppercase tracking-wide text-stone-500">{label}</p>
      <p className="text-lg font-semibold text-stone-900 mt-1">{value}</p>
    </div>
  );
}

export default ProbateResults;
