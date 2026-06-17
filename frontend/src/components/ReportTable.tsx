import type { ReactNode } from 'react';

export interface ReportTableColumn<T> {
  key: string;
  label: string;
  align?: 'left' | 'right';
  sticky?: boolean;
  render?: (row: T, index: number) => ReactNode;
}

interface ReportTableProps<T> {
  columns: ReportTableColumn<T>[];
  rows: T[];
  rowKey: (row: T, index: number) => string;
  maxHeight?: string;
  caption?: string;
  emptyMessage?: string;
}

export function ReportTable<T extends object>({
  columns,
  rows,
  rowKey,
  maxHeight = '28rem',
  caption,
  emptyMessage = 'No rows to display.',
}: ReportTableProps<T>) {
  if (rows.length === 0) {
    return <p className="text-sm text-stone-500 py-4">{emptyMessage}</p>;
  }

  return (
    <div
      className="relative rounded-lg border border-stone-200 overflow-hidden bg-white"
      style={{ maxHeight }}
    >
      <div className="overflow-auto max-h-[inherit]">
        <table className="w-full text-sm border-collapse">
          {caption ? <caption className="sr-only">{caption}</caption> : null}
          <thead className="sticky top-0 z-10 bg-stone-100 shadow-[0_1px_0_0_rgb(214_211_209)]">
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  scope="col"
                  className={[
                    'px-3 py-2.5 text-xs font-semibold uppercase tracking-wide text-stone-600 whitespace-nowrap',
                    col.align === 'right' ? 'text-right' : 'text-left',
                    col.sticky
                      ? 'sticky left-0 z-20 bg-stone-100 shadow-[1px_0_0_0_rgb(214_211_209)]'
                      : '',
                  ].join(' ')}
                >
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr
                key={rowKey(row, idx)}
                className={idx % 2 === 0 ? 'bg-white' : 'bg-stone-50/80'}
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={[
                      'px-3 py-2 text-stone-800 border-t border-stone-100',
                      col.align === 'right' ? 'text-right tabular-nums' : 'text-left',
                      col.sticky
                        ? `sticky left-0 z-[1] shadow-[1px_0_0_0_rgb(214_211_209)] ${
                            idx % 2 === 0 ? 'bg-white' : 'bg-stone-50'
                          }`
                        : '',
                    ].join(' ')}
                  >
                    {col.render
                      ? col.render(row, idx)
                      : formatTableCell((row as Record<string, unknown>)[col.key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function formatTableCell(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return value.toLocaleString();
  return String(value);
}
