import { useRef, useState } from 'react';
import InvestorSoldScreening from './InvestorSoldScreening';
import InvestorSoldFunnel from './InvestorSoldFunnel';
import InvestorSoldPropertyTable from './InvestorSoldPropertyTable';
import { copyReportShareUrl } from '../utils/reportShareUrl';
import type { InvestorSoldCompletedResponse } from '../types/investorSold';

interface Props {
  result: InvestorSoldCompletedResponse;
  onNewRun: () => void;
  onExport: () => void;
  exporting: boolean;
}

const ownershipColors: Record<string, string> = {
  Trust: '#7c3aed', Company: '#0f766e', Individual: '#2563eb', Unclassified: '#d6d3d1',
};
const count = (value: number | undefined) => (value ?? 0).toLocaleString();
const humanize = (value: string) => value.replace(/_/g, ' ');
const segmentNames: Record<string, string> = {
  investor: 'Investor buyer · not scrape-listed',
  in_our_list: 'Other buyer · scrape-listed',
  both: 'Investor buyer · scrape-listed',
  neither: 'Other buyer · not scrape-listed',
};

export default function InvestorSoldResults({ result, onNewRun, onExport, exporting }: Props) {
  const m = result.metrics;
  const screening = m.property_screening;
  const hasScreening = screening?.enabled === true;
  const earliest = m.inputs.property_grain === 'property_earliest_sale';
  const unit = earliest ? 'properties' : 'property-months';
  const total = m.inputs.property_rows ?? m.rows.length;
  const lost = m.lost;
  const [section, setSection] = useState<'report' | 'review'>('report');
  const [focus, setFocus] = useState('all');
  const [tableSelectionVersion, setTableSelectionVersion] = useState(0);
  const [shareMessage, setShareMessage] = useState('');
  const tableRef = useRef<HTMLDivElement>(null);
  const warnings = result.warnings?.length ? result.warnings : m.warnings;
  const categories = Object.keys(ownershipColors).map((name) => ({
    name, value: screening?.seller_categories?.[name] ?? 0, color: ownershipColors[name],
  }));
  const sellerTotal = categories.reduce((n, item) => n + item.value, 0);
  let ringOffset = 0;
  const ringSegments = categories.map((item) => {
    const length = sellerTotal ? item.value / sellerTotal * 100 : 0;
    const segment = { ...item, length, offset: ringOffset };
    ringOffset += length;
    return segment;
  });

  function inspect(next: string) {
    setFocus(next);
    setTableSelectionVersion(value => value + 1);
    setSection('report');
    requestAnimationFrame(() => tableRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  }

  async function share() {
    const mode = await copyReportShareUrl(result.job_id, 'investor_sold');
    setShareMessage(mode === 'copied' ? 'Link copied' : 'Copy the link from the prompt');
    setTimeout(() => setShareMessage(''), 2500);
  }

  return <div className="space-y-6 pb-8">
    <header className="flex flex-wrap justify-between items-start gap-5">
      <div className="max-w-2xl">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-violet-700">Gate 7 · Sold-property coverage</p>
        <h2 className="mt-2 text-3xl font-bold tracking-tight text-stone-900">How far did we get before the sale?</h2>
        <p className="mt-2 text-sm text-stone-600">
          {earliest ? 'Nassau & Suffolk, NY' : 'Historical report universe'} · Source months {m.date_window_start || '—'} to {m.date_window_end || '—'}
        </p>
        <p className="mt-1 text-xs text-stone-500">{earliest ? 'Each property counts once, anchored to its earliest observed sale month.' : 'This saved report counts property-month observations.'}</p>
      </div>
      <div className="flex gap-2 flex-wrap">
        <button onClick={onExport} disabled={exporting} className="rounded-lg bg-violet-800 px-4 py-2.5 text-sm font-semibold text-white hover:bg-violet-900 disabled:opacity-50">{exporting ? 'Exporting…' : 'Download full report'}</button>
        <button onClick={share} className="rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-sm text-stone-700">Share link</button>
        <button onClick={onNewRun} className="rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-sm text-stone-700">New report</button>
      </div>
    </header>
    {shareMessage && <p role="status" className="text-sm text-violet-700">{shareMessage}</p>}

    <nav aria-label="Report sections" className="flex gap-1 border-b border-stone-200">
      <button onClick={() => setSection('report')} aria-pressed={section === 'report'} className={`px-4 py-3 text-sm font-semibold border-b-2 ${section === 'report' ? 'border-violet-700 text-violet-900' : 'border-transparent text-stone-500 hover:text-stone-800'}`}>Report & properties</button>
      <button onClick={() => setSection('review')} aria-pressed={section === 'review'} className={`px-4 py-3 text-sm font-semibold border-b-2 ${section === 'review' ? 'border-violet-700 text-violet-900' : 'border-transparent text-stone-500 hover:text-stone-800'}`}>
        Data review {hasScreening && <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-900">{count(screening?.unresolved)} unresolved</span>}
      </button>
    </nav>

    {section === 'report' ? <>
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-stone-200 bg-stone-50 px-4 py-3 text-xs text-stone-600">
        <span>{hasScreening ? 'KPIs include only properties passing supported snapshot rules. LTV, ownership duration and owner exclusions remain unchecked.' : 'Geography-only report: property details and historical seller categories were not evaluated.'}</span>
        <button onClick={() => setSection('review')} className="font-semibold text-violet-800 underline underline-offset-2">See scope & exclusions</button>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <button onClick={() => inspect('all')} className="rounded-xl border border-stone-200 bg-white p-5 text-left hover:border-violet-300 focus-visible:ring-2 focus-visible:ring-violet-500">
          <p className="text-xs font-semibold uppercase tracking-wide text-stone-500">{hasScreening ? 'Screened universe' : 'Geographic universe'}</p>
          <p className="mt-3 text-4xl font-bold tracking-tight text-stone-900">{count(total)}</p>
          <p className="mt-2 text-xs text-stone-500">{unit} in this report · view all →</p>
        </button>
        <button onClick={() => inspect('never_prospected')} aria-pressed={focus === 'never_prospected'} className={`rounded-xl border bg-white p-5 text-left hover:border-violet-300 focus-visible:ring-2 focus-visible:ring-violet-500 ${focus === 'never_prospected' ? 'border-violet-500 ring-1 ring-violet-200' : 'border-stone-200'}`}>
          <p className="text-xs font-semibold uppercase tracking-wide text-stone-500">Investor sales without a prospect list</p>
          <p className="mt-3 text-4xl font-bold tracking-tight text-violet-900">{count(lost?.never_prospected_investor_count)}</p>
          <p className="mt-2 text-xs text-stone-600">{lost?.never_prospected_investor_pct ?? 0}% of {count(m.segments.investor_count)} investor sales</p>
          <p className="mt-2 text-xs text-stone-500">No 8020, Court Alerts or LI Profiles prospect list; HHB closings excluded. Inspect coverage →</p>
        </button>
        <button onClick={() => inspect('lost')} aria-pressed={focus === 'lost'} className={`rounded-xl border bg-white p-5 text-left hover:border-violet-300 focus-visible:ring-2 focus-visible:ring-violet-500 ${focus === 'lost' ? 'border-violet-500 ring-1 ring-violet-200' : 'border-stone-200'}`}>
          <p className="text-xs font-semibold uppercase tracking-wide text-stone-500">Lost to an investor</p>
          <p className="mt-3 text-4xl font-bold tracking-tight text-stone-900">{count(lost?.lost_to_investor_count)}</p>
          <p className="mt-2 text-xs text-stone-600">{lost?.lost_to_investor_pct ?? 0}% of {count(lost?.had_presence_count)} properties we had</p>
          <p className="mt-2 text-xs text-stone-500">We had list or CRM presence before sale, but HHB did not close. Inspect losses →</p>
        </button>
      </div>
      <p className="text-xs text-stone-500">These coverage and loss groups can overlap; they should not be added together.</p>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.8fr)_minmax(280px,1fr)]">
        <InvestorSoldFunnel rows={m.pipeline_funnel ?? []} total={total} selectedStage={focus} onSelect={inspect} />
        <section className="rounded-xl border border-stone-200 bg-white p-5">
          <h3 className="font-bold text-stone-900">Who owned the properties?</h3>
          <p className="mt-1 text-xs text-stone-500">Seller before the anchored sale · eligible {unit}</p>
          {hasScreening && sellerTotal > 0 ? <>
            <div className="relative mx-auto my-5 h-44 w-44">
              <svg viewBox="0 0 120 120" role="img" aria-label={categories.map(item => `${item.name}: ${item.value}`).join(', ')} className="h-full w-full -rotate-90">
                {ringSegments.filter(item => item.value > 0).map(item => <circle key={item.name} cx="60" cy="60" r="48" pathLength="100" fill="none" stroke={item.color} strokeWidth="13" strokeDasharray={`${item.length} ${100 - item.length}`} strokeDashoffset={-item.offset} />)}
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none"><span className="text-2xl font-bold text-stone-900">{count(sellerTotal - (screening?.seller_categories?.Unclassified ?? 0))}</span><span className="text-xs text-stone-500">classified sellers</span></div>
            </div>
            <div className="space-y-1">
              {categories.map(item => <button key={item.name} onClick={() => inspect(`seller:${item.name}`)} aria-pressed={focus === `seller:${item.name}`} className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-sm hover:bg-stone-50 focus-visible:ring-2 focus-visible:ring-violet-500">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: item.color }} />
                <span>{item.name}</span><span className="ml-auto font-semibold tabular-nums">{count(item.value)}</span><span className="w-12 text-right text-xs text-stone-500">{(100 * item.value / sellerTotal).toFixed(1)}%</span>
              </button>)}
            </div>
            <p className="mt-4 border-t border-stone-100 pt-3 text-xs leading-relaxed text-stone-500">Name-based estimates from uniquely matched historical sales. Company groups all other entities, including estates. Unclassified means evidence was insufficient.</p>
          </> : <p className="mt-6 text-sm leading-relaxed text-stone-500">Upload property details to identify matched historical sellers. Current-owner names are not used as a substitute.</p>}
        </section>
      </div>

      <div ref={tableRef} className="scroll-mt-4">
        <InvestorSoldPropertyTable key={tableSelectionVersion} rows={m.rows} hasScreening={hasScreening} earliestSale={earliest} focus={focus} onFocusChange={setFocus} />
      </div>

      <details className="rounded-xl border border-stone-200 bg-white p-5">
        <summary className="cursor-pointer text-sm font-semibold text-stone-800">Supporting breakdowns · months, loss stages & source-list groups</summary>
        <p className="mt-3 text-xs text-stone-500">These breakdowns describe the full report; property-table filters do not change them.</p>
        <div className="mt-5 overflow-x-auto">
          <h3 className="mb-2 text-sm font-bold">{earliest ? 'By first sold month' : 'By sold month'}</h3>
          <table className="w-full min-w-[620px] text-left text-sm"><thead className="text-xs text-stone-500"><tr>{['Month', unit, 'Investor buyers', 'Lost to investor', 'Marketed', 'Lead matched', 'QL matched'].map(label => <th key={label} className="py-2 pr-3">{label}</th>)}</tr></thead>
            <tbody>{m.by_sold_month.map(row => <tr key={row.sold_month} className="border-t border-stone-100">{[row.sold_month, count(row.count), count(row.investor), count(row.lost_to_investor), count(row.marketed), count(row.leads), count(row.qualified_leads)].map((value, i) => <td key={i} className="py-2 pr-3">{value}</td>)}</tr>)}</tbody>
          </table>
          <p className="mt-2 text-xs text-stone-500">Lead/QL matched columns count direct evidence. The funnel also includes properties inferred to have reached earlier stages.</p>
        </div>
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <div><h3 className="mb-2 text-sm font-bold">Where we lost investor sales</h3><p className="mb-2 text-xs text-stone-500">Each loss appears once at its furthest recorded stage.</p>
            <table className="w-full text-left text-sm"><thead className="text-xs text-stone-500"><tr><th className="py-2">Furthest stage</th><th>Properties</th><th>Share of losses</th></tr></thead><tbody>{(lost?.lost_by_stage ?? []).map(row => <tr key={row.stage} className="border-t border-stone-100"><td className="py-2">{row.label}</td><td>{count(row.count)}</td><td>{row.share_pct}%</td></tr>)}</tbody></table>
          </div>
          <div className="overflow-x-auto"><h3 className="mb-2 text-sm font-bold">Buyer & scrape-list groups</h3><p className="mb-2 text-xs text-stone-500">Separate groups. Scrape-list presence is the source flag, not all CRM presence.</p>
            <table className="w-full min-w-[380px] text-left text-sm"><thead className="text-xs text-stone-500"><tr><th className="py-2">Group</th><th>Properties</th><th>Marketed</th></tr></thead><tbody>{m.by_segment.map(row => <tr key={row.segment} className="border-t border-stone-100"><td className="py-2 pr-2">{segmentNames[row.segment] ?? row.segment}</td><td>{count(row.count)}</td><td>{row.marketed_pct ?? 0}%</td></tr>)}</tbody></table>
          </div>
        </div>
      </details>
    </> : <div className="space-y-5">
      <section className="rounded-xl border border-stone-200 bg-white p-5">
        <h3 className="text-lg font-bold text-stone-900">How the report universe is built</h3>
        <p className="mt-1 text-sm text-stone-500">Geography first, then one row per property, then supported property rules. CRM matches never readmit excluded properties.</p>
        <ol className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[
            ['1 · Raw sold rows', m.inputs.sold_rows_scanned, 'Source transaction rows'],
            ['2 · Inside geography', m.inputs.sold_rows_ingested, 'Transaction rows after ZIP/city exclusions'],
            ['3 · Property deduplication', hasScreening ? screening?.target_count : total, earliest ? 'Unique properties at earliest observed sale' : 'Property-month observations'],
            ['4 · Report universe', total, hasScreening ? 'Properties passing supported details rules' : 'Geographic-only; details not supplied'],
          ].map(([label, value, note]) => <li key={String(label)} className="rounded-lg border border-stone-200 bg-stone-50 p-4"><p className="text-xs font-semibold text-stone-600">{label}</p><p className="mt-2 text-2xl font-bold">{value == null ? '—' : Number(value).toLocaleString()}</p><p className="mt-1 text-xs text-stone-500">{note}</p></li>)}
        </ol>
        <div className="mt-5 text-sm leading-relaxed text-stone-600">
          {earliest ? <p>Nassau/Suffolk, NY only. {count(m.inputs.buybox_excluded_zip_count)} excluded ZIPs take priority. The {count(m.inputs.buybox_excluded_city_count)} excluded city names apply only when ZIP is missing.</p> : <p>This historical report used its original saved geographic policy; rerun to apply the current buybox.</p>}
          <p className="mt-2">{count(m.inputs.sold_rows_excluded_buybox)} source rows excluded by geography: {Object.entries(m.inputs.buybox_exclusions ?? {}).map(([reason, n]) => `${humanize(reason)} ${count(n)}`).join(' · ') || 'reason detail unavailable in this saved report'}.</p>
        </div>
      </section>
      <InvestorSoldScreening screening={screening} rows={m.property_screening_rows ?? []} />
      {warnings.length > 0 && <section className="rounded-xl border border-amber-200 bg-amber-50 p-5"><h3 className="font-semibold text-amber-950">Source notes</h3><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-900">{warnings.map(w => <li key={w}>{w}</li>)}</ul></section>}
      <details className="rounded-xl border border-stone-200 bg-white p-5"><summary className="cursor-pointer text-sm font-semibold">Calculation methodology</summary><p className="mt-3 max-w-4xl text-sm leading-relaxed text-stone-600">{m.methodology_note}</p></details>
    </div>}
  </div>;
}
