import { useMemo, useRef, useState } from 'react';
import type { InvestorSoldPropertyScreening, InvestorSoldScreeningRow } from '../types/investorSold';

interface Props {
  screening?: InvestorSoldPropertyScreening;
  rows: InvestorSoldScreeningRow[];
}

const humanize = (value: string) => value.replace(/_/g, ' ');

export default function InvestorSoldScreening({ screening, rows }: Props) {
  const [status, setStatus] = useState('review');
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState(100);
  const auditRef = useRef<HTMLDetailsElement>(null);
  const filtered = useMemo(() => rows.filter((row) => {
    const matchesStatus = status === 'all' || (status === 'review'
      ? row.status === 'excluded' || row.status === 'unresolved'
      : row.status === status);
    return matchesStatus && `${row.address} ${row.dataflik_id} ${row.seller_name} ${row.reason}`.toLowerCase().includes(query.trim().toLowerCase());
  }), [rows, status, query]);

  if (!screening?.enabled) {
    return <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
      Geographic-only report. Property details were not supplied, so property attributes and seller ownership categories were not evaluated.
    </p>;
  }

  return (
    <section className="rounded-xl border border-stone-200 bg-white p-4 space-y-4">
      <div>
        <h3 className="font-bold text-stone-800">Property screening</h3>
        <p className="text-xs text-stone-600 mt-1">
          Snapshot attributes screen {screening.target_count.toLocaleString()} geographic properties.
          This is not a complete assessment of the buybox at the sale date. Seller categories are
          name-based estimates from a seller matched to the earliest observed sale, not verified
          legal ownership types. Unmatched sellers remain Unclassified.
        </p>
      </div>
      <div className="grid grid-cols-3 gap-3">
        {(['eligible', 'excluded', 'unresolved'] as const).map((key) => (
          <button key={key} type="button" aria-pressed={status === key} onClick={() => {
            setStatus(key); setLimit(100);
            if (auditRef.current) auditRef.current.open = true;
          }}
            className={`rounded-lg border p-3 text-left ${status === key ? 'border-violet-400 bg-violet-50' : 'border-stone-200'}`}>
            <span className="block text-xs capitalize text-stone-600">{key}</span>
            <span className="text-lg font-bold">{screening[key].toLocaleString()}</span>
          </button>
        ))}
      </div>
      <p className="text-xs text-stone-600">
        Estimated seller categories among eligible properties: {['Trust', 'Company', 'Individual', 'Unclassified'].map((category) => `${category}: ${(screening.seller_categories?.[category] ?? 0).toLocaleString()}`).join(' · ')}
      </p>
      {Object.keys(screening.reasons ?? {}).length > 0 && <p className="text-xs text-stone-600">
        Screening reasons · {Object.entries(screening.reasons).map(([reason, count]) => `${humanize(reason)}: ${count.toLocaleString()}`).join(' · ')}
      </p>}
      <p className="text-xs text-amber-900">
        Not evaluated: {screening.unsupported_rules?.length
          ? screening.unsupported_rules.map(humanize).join('; ')
          : 'ownership tenure; LTV; non-seller/religious-owner exclusions'}.
      </p>
      {!!screening.warnings?.length && <ul className="text-xs text-amber-900 list-disc pl-4">{screening.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul>}
      <details ref={auditRef}>
        <summary className="text-sm font-semibold text-violet-900 cursor-pointer">Review screening decisions ({rows.length.toLocaleString()} properties)</summary>
        <div className="flex flex-wrap gap-3 my-3">
          <label className="text-xs text-stone-600">Status{' '}
            <select value={status} onChange={(e) => { setStatus(e.target.value); setLimit(100); }} className="border border-stone-300 rounded p-1">
              <option value="review">Excluded + unresolved</option><option value="all">All geographic properties</option>
              <option value="eligible">Eligible</option><option value="excluded">Excluded</option><option value="unresolved">Unresolved</option>
            </select>
          </label>
          <input type="search" aria-label="Search screening decisions" value={query} onChange={(e) => { setQuery(e.target.value); setLimit(100); }} placeholder="Address, seller, ID or reason…" className="border border-stone-300 rounded p-1 text-xs w-64" />
        </div>
        <div className="overflow-auto max-h-96">
          <table className="w-full text-xs text-left">
            <thead className="bg-stone-50 sticky top-0"><tr>{['Address', 'Property ID', 'Status', 'Reason', 'Property type', 'Seller before sale', 'Seller category', 'Seller match'].map((label) => <th key={label} className="p-2 whitespace-nowrap">{label}</th>)}</tr></thead>
            <tbody>{filtered.slice(0, limit).map((row, i) => <tr key={`${row.dataflik_id}-${i}`} className="border-t border-stone-100">
              {[row.address, row.dataflik_id, row.status, humanize(row.reason || ''), row.property_type, row.seller_name, row.seller_category || 'Unclassified', row.seller_match_status].map((value, j) => <td key={j} className="p-2">{value || '—'}</td>)}
            </tr>)}</tbody>
          </table>
        </div>
        <p className="text-xs text-stone-500 mt-2">Showing {Math.min(limit, filtered.length).toLocaleString()} of {filtered.length.toLocaleString()} matching properties.</p>
        {filtered.length > limit && <button type="button" onClick={() => setLimit((value) => value + 100)} className="mt-2 text-xs font-semibold text-violet-800">Show 100 more</button>}
      </details>
    </section>
  );
}
