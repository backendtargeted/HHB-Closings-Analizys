import type { InvestorSoldPipelineFunnelRow } from '../types/investorSold';

interface Props {
  rows: InvestorSoldPipelineFunnelRow[];
  total: number;
  selectedStage: string;
  onSelect: (stage: string) => void;
}

const STAGES = [
  { stage: 'PROSPECT', label: 'Prospect', color: '#8b7ac9' },
  { stage: 'MARKETED', label: 'Marketed', color: '#797cc5' },
  { stage: 'LEAD', label: 'Lead', color: '#6889bd' },
  { stage: 'QUALIFIED_LEAD', label: 'Qualified lead', color: '#5399b1' },
  { stage: 'OPPORTUNITY', label: 'Opportunity', color: '#3b9f9b' },
  { stage: 'HHB_CLOSED', label: 'HHB closed', color: '#238c80' },
] as const;

function safeCount(value: number | undefined): number {
  return value !== undefined && Number.isFinite(value) ? Math.max(0, value) : 0;
}

/** Cumulative reach, with every band drawn against the same count scale. */
export default function InvestorSoldFunnel({ rows, total, selectedStage, onSelect }: Props) {
  const eligible = safeCount(total);
  const counts = new Map(rows.map((row) => [row.stage, safeCount(row.count)]));
  const stages = STAGES.map((stage) => ({ ...stage, count: counts.get(stage.stage) ?? 0 }));
  const maximum = Math.max(0, ...stages.map((stage) => stage.count));
  const noPipeline = counts.get('NONE') ?? 0;
  const percent = (count: number) => eligible > 0 ? `${((count / eligible) * 100).toFixed(1)}%` : '—';

  if (eligible === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-6 py-12 text-center">
        <p className="font-medium text-slate-700">No eligible properties to chart</p>
        <p className="mt-1 text-sm text-slate-500">The pipeline funnel appears when the report includes eligible properties.</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3 sm:p-5">
      <div className="mb-5">
        <h3 className="font-bold text-stone-900">From prospect to closing</h3>
        <p className="mt-1 text-sm text-slate-600">Select a stage to inspect the properties behind it.</p>
        <p className="mt-1 text-xs leading-relaxed text-slate-500">
          Counts are cumulative, not separate groups. Percentages use all {eligible.toLocaleString()} eligible properties.
        </p>
      </div>

      <div className="mb-2 grid grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_minmax(0,1fr)] items-end gap-2 px-2 text-[11px] font-medium uppercase tracking-wide text-slate-500 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_minmax(0,1fr)] sm:px-3">
        <span>Stage reached</span>
        <span className="text-center">Pipeline</span>
        <span className="text-right">Properties</span>
      </div>

      <div role="group" aria-label="Cumulative pipeline stages">
        {stages.map(({ stage, label, count, color }, index) => {
          const topWidth = maximum > 0 ? (count / maximum) * 100 : 0;
          const next = stages[index + 1]?.count ?? count;
          const bottomWidth = maximum > 0 ? (next / maximum) * 100 : 0;
          const selected = selectedStage === stage;
          return (
            <button
              key={stage}
              type="button"
              aria-pressed={selected}
              aria-label={`${label} or further: ${count.toLocaleString()} properties, ${percent(count)} of all eligible properties. Inspect properties.`}
              onClick={() => onSelect(stage)}
              className={`group relative grid w-full grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_minmax(0,1fr)] items-center gap-2 rounded-lg px-2 text-left transition-colors focus-visible:z-10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-600 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_minmax(0,1fr)] sm:px-3 ${selected ? 'bg-violet-50 ring-1 ring-inset ring-violet-300' : 'hover:bg-slate-50'}`}
            >
              <span className="py-3 text-xs font-medium leading-relaxed text-slate-700 sm:text-sm">
                {label}
                {selected && <span className="mt-0.5 block text-[10px] font-normal text-violet-700 sm:text-xs">Selected</span>}
              </span>
              <svg
                viewBox="0 0 100 72"
                preserveAspectRatio="none"
                className="h-[84px] w-full sm:h-[72px]"
                aria-hidden="true"
              >
                {count > 0 && (
                  <polygon
                    points={`${50 - topWidth / 2},0 ${50 + topWidth / 2},0 ${50 + bottomWidth / 2},72 ${50 - bottomWidth / 2},72`}
                    fill={color}
                    className="transition-opacity group-hover:opacity-90"
                  />
                )}
              </svg>
              <span className="py-3 text-right tabular-nums">
                <span className="block text-lg font-semibold tracking-tight text-slate-900 sm:text-2xl">{count.toLocaleString()}</span>
                <span className="block text-xs text-slate-500">{percent(count)} of all</span>
              </span>
            </button>
          );
        })}
      </div>

      {maximum === 0 && <p className="mt-3 text-center text-sm text-slate-500">No properties have a recorded pipeline stage.</p>}
      <p className="mt-4 text-xs leading-relaxed text-slate-500">Each stage includes properties that reached a later stage. This describes recorded reach before sale, not a measured conversion rate over time.</p>

      <button
        type="button"
        aria-pressed={selectedStage === 'NONE'}
        aria-label={`No recorded pipeline: ${noPipeline.toLocaleString()} properties, ${percent(noPipeline)} of all eligible properties. Inspect properties.`}
        onClick={() => onSelect('NONE')}
        className={`mt-4 flex w-full items-center justify-between gap-4 rounded-lg border p-3 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-600 ${selectedStage === 'NONE' ? 'border-violet-300 bg-violet-50' : 'border-slate-200 bg-slate-50 hover:bg-slate-100'}`}
      >
        <span>
          <span className="block text-sm font-medium text-slate-700">No recorded pipeline</span>
          <span className="mt-0.5 block text-xs text-slate-500">Outside the recorded stages above</span>
        </span>
        <span className="shrink-0 text-right tabular-nums">
          <span className="block text-lg font-semibold text-slate-800">{noPipeline.toLocaleString()}</span>
          <span className="block text-xs text-slate-500">{percent(noPipeline)} of all</span>
        </span>
      </button>
    </div>
  );
}
