import { useMemo, useState } from 'react';
import type { WebLeadRow } from '../types/webLeads';

type SortKey =
  | 'address'
  | 'cohort_track_date'
  | 'reisift_created_on'
  | 'anchor_date'
  | 'lists'
  | 'had_prior_history'
  | 'has_8020_tag'
  | 'days_list_to_web'
  | 'closings_date_closed'
  | 'journey_path_compact';

type Filter8020 = 'all' | 'yes' | 'no';
type FilterPrior = 'all' | 'yes' | 'no';
type FilterClosing = 'all' | 'yes' | 'no';

const COLUMNS: Array<{ key: SortKey; label: string; mono?: boolean }> = [
  { key: 'address', label: 'Address' },
  { key: 'cohort_track_date', label: 'Track date' },
  { key: 'reisift_created_on', label: 'REISift Created' },
  { key: 'anchor_date', label: 'Anchor' },
  { key: 'lists', label: 'Lists' },
  { key: 'had_prior_history', label: 'Prior history' },
  { key: 'has_8020_tag', label: '8020 tag' },
  { key: 'days_list_to_web', label: 'Days list→web' },
  { key: 'closings_date_closed', label: 'Closed' },
  { key: 'journey_path_compact', label: 'Path', mono: true },
];

function cellValue(row: WebLeadRow, key: SortKey): string | number | boolean {
  switch (key) {
    case 'lists':
      return row.lists.join(', ');
    case 'journey_path_compact':
      return row.journey_path_compact || row.journey_path;
    case 'closings_date_closed':
      return row.closings_matched
        ? `${row.closings_date_closed || '—'} (${row.closings_stage || '—'})`
        : '—';
    case 'cohort_track_date':
      return row.cohort_track_date || row.ql_create_date || '';
    default:
      return row[key] as string | number | boolean;
  }
}

function compareRows(a: WebLeadRow, b: WebLeadRow, key: SortKey, direction: 'asc' | 'desc') {
  const aVal = cellValue(a, key);
  const bVal = cellValue(b, key);
  const aEmpty = aVal === '' || aVal === '—' || aVal == null;
  const bEmpty = bVal === '' || bVal === '—' || bVal == null;
  if (aEmpty && bEmpty) return 0;
  if (aEmpty) return 1;
  if (bEmpty) return -1;

  let cmp = 0;
  if (typeof aVal === 'boolean' && typeof bVal === 'boolean') {
    cmp = aVal === bVal ? 0 : aVal ? 1 : -1;
  } else if (typeof aVal === 'number' && typeof bVal === 'number') {
    cmp = aVal - bVal;
  } else {
    cmp = String(aVal).localeCompare(String(bVal));
  }
  return direction === 'asc' ? cmp : -cmp;
}

function escapeCsv(value: string) {
  if (/[",\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function exportRowsCsv(rows: WebLeadRow[]) {
  const headers = COLUMNS.map((c) => c.label);
  const lines = [
    headers.join(','),
    ...rows.map((row) =>
      COLUMNS.map((col) => escapeCsv(String(cellValue(row, col.key)))).join(',')
    ),
  ];
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `web_leads_rows_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

interface WebLeadsRowTableProps {
  rows: WebLeadRow[];
}

const WebLeadsRowTable = ({ rows }: WebLeadsRowTableProps) => {
  const [search, setSearch] = useState('');
  const [filter8020, setFilter8020] = useState<Filter8020>('all');
  const [filterPrior, setFilterPrior] = useState<FilterPrior>('all');
  const [filterClosing, setFilterClosing] = useState<FilterClosing>('all');
  const [sortConfig, setSortConfig] = useState<{ key: SortKey; direction: 'asc' | 'desc' } | null>(
    null
  );
  const [page, setPage] = useState(1);
  const itemsPerPage = 25;

  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((row) => {
      if (filter8020 === 'yes' && !row.has_8020_tag) return false;
      if (filter8020 === 'no' && row.has_8020_tag) return false;
      if (filterPrior === 'yes' && !row.had_prior_history) return false;
      if (filterPrior === 'no' && row.had_prior_history) return false;
      if (filterClosing === 'yes' && !row.closings_matched) return false;
      if (filterClosing === 'no' && row.closings_matched) return false;
      if (!q) return true;
      const haystack = [
        row.address,
        row.lists.join(' '),
        row.journey_path_compact || row.journey_path,
        row.prior_8020_channels.join(' '),
      ]
        .join(' ')
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [rows, search, filter8020, filterPrior, filterClosing]);

  const sortedRows = useMemo(() => {
    if (!sortConfig) return filteredRows;
    return [...filteredRows].sort((a, b) => compareRows(a, b, sortConfig.key, sortConfig.direction));
  }, [filteredRows, sortConfig]);

  const totalPages = Math.max(1, Math.ceil(sortedRows.length / itemsPerPage));
  const safePage = Math.min(page, totalPages);
  const paginatedRows = sortedRows.slice(
    (safePage - 1) * itemsPerPage,
    safePage * itemsPerPage
  );

  const handleSort = (key: SortKey) => {
    setSortConfig((current) => {
      if (current?.key === key) {
        return { key, direction: current.direction === 'asc' ? 'desc' : 'asc' };
      }
      return { key, direction: 'asc' };
    });
  };

  const no8020Count = filteredRows.filter((r) => !r.has_8020_tag).length;

  return (
    <section className="rounded-xl border border-stone-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-stone-900">Row detail</h3>
          <p className="text-sm text-stone-600 mt-1">
            {filteredRows.length.toLocaleString()} of {rows.length.toLocaleString()} matched rows
            {no8020Count > 0 ? ` · ${no8020Count.toLocaleString()} without 8020 tag` : ''}
          </p>
        </div>
        <button
          type="button"
          onClick={() => exportRowsCsv(sortedRows)}
          disabled={sortedRows.length === 0}
          className="px-3 py-2 rounded-lg border border-stone-300 text-sm font-medium text-violet-900 hover:bg-stone-50 disabled:opacity-50"
        >
          Export filtered CSV
        </button>
      </div>

      <div className="mt-4 flex flex-wrap gap-3 items-end">
        <label className="block text-sm min-w-[200px] flex-1">
          <span className="text-stone-600">Search</span>
          <input
            type="search"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            placeholder="Address, lists, path…"
            className="mt-1 block w-full rounded-lg border border-stone-300 px-3 py-2 text-sm"
          />
        </label>
        <label className="block text-sm">
          <span className="text-stone-600">8020 tag</span>
          <select
            value={filter8020}
            onChange={(e) => {
              setFilter8020(e.target.value as Filter8020);
              setPage(1);
            }}
            className="mt-1 block rounded-lg border border-stone-300 px-3 py-2 text-sm"
          >
            <option value="all">All</option>
            <option value="yes">Has 8020</option>
            <option value="no">No 8020 (new to DB)</option>
          </select>
        </label>
        <label className="block text-sm">
          <span className="text-stone-600">Prior history</span>
          <select
            value={filterPrior}
            onChange={(e) => {
              setFilterPrior(e.target.value as FilterPrior);
              setPage(1);
            }}
            className="mt-1 block rounded-lg border border-stone-300 px-3 py-2 text-sm"
          >
            <option value="all">All</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </label>
        <label className="block text-sm">
          <span className="text-stone-600">Closing</span>
          <select
            value={filterClosing}
            onChange={(e) => {
              setFilterClosing(e.target.value as FilterClosing);
              setPage(1);
            }}
            className="mt-1 block rounded-lg border border-stone-300 px-3 py-2 text-sm"
          >
            <option value="all">All</option>
            <option value="yes">Matched</option>
            <option value="no">No match</option>
          </select>
        </label>
      </div>

      <div className="mt-4 overflow-x-auto max-h-[560px] overflow-y-auto border border-stone-100 rounded-lg">
        <table className="min-w-full text-xs">
          <thead className="sticky top-0 bg-stone-50">
            <tr className="border-b text-left text-stone-500">
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  onClick={() => handleSort(col.key)}
                  className="py-2 px-3 cursor-pointer hover:bg-stone-100 whitespace-nowrap"
                >
                  {col.label}
                  {sortConfig?.key === col.key ? (
                    <span className="ml-1">{sortConfig.direction === 'asc' ? '↑' : '↓'}</span>
                  ) : null}
                </th>
              ))}
              <th className="py-2 px-3 whitespace-nowrap">8020 before</th>
            </tr>
          </thead>
          <tbody>
            {paginatedRows.length === 0 ? (
              <tr>
                <td colSpan={COLUMNS.length + 1} className="py-8 text-center text-stone-500">
                  No rows match your filters.
                </td>
              </tr>
            ) : (
              paginatedRows.map((r) => (
                <tr key={r.address_key + r.anchor_date} className="border-b border-stone-100">
                  {COLUMNS.map((col) => {
                    const val = cellValue(r, col.key);
                    if (col.key === 'had_prior_history' || col.key === 'has_8020_tag') {
                      return (
                        <td key={col.key} className="py-2 px-3">
                          {val ? 'Yes' : 'No'}
                        </td>
                      );
                    }
                    return (
                      <td
                        key={col.key}
                        className={`py-2 px-3 ${col.mono ? 'font-mono' : ''}`}
                      >
                        {val === '' ? '—' : String(val)}
                      </td>
                    );
                  })}
                  <td className="py-2 px-3">{r.prior_8020_channels.join(', ') || '—'}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 ? (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm text-stone-600">
          <span>
            Showing {(safePage - 1) * itemsPerPage + 1}–
            {Math.min(safePage * itemsPerPage, sortedRows.length)} of{' '}
            {sortedRows.length.toLocaleString()}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={safePage <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="px-3 py-1 rounded border border-stone-300 disabled:opacity-50"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={safePage >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="px-3 py-1 rounded border border-stone-300 disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
};

export default WebLeadsRowTable;
