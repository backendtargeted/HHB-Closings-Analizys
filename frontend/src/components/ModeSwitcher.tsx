export type WorkspaceMode = 'regular' | 'pastPatches';

interface ModeSwitcherProps {
  mode: WorkspaceMode;
  onChange: (mode: WorkspaceMode) => void;
}

const ModeSwitcher = ({ mode, onChange }: ModeSwitcherProps) => {
  return (
    <div className="mb-8">
      <p className="text-sm font-medium text-stone-500 uppercase tracking-wide mb-3">
        Choose workflow
      </p>
      <div
        className="grid grid-cols-1 md:grid-cols-2 gap-4"
        role="tablist"
        aria-label="Analysis workflow type"
      >
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'regular'}
          id="tab-regular"
          aria-controls="panel-workspace"
          onClick={() => onChange('regular')}
          className={`text-left rounded-2xl border-2 p-6 transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-navy focus-visible:ring-offset-2 ${
            mode === 'regular'
              ? 'border-navy bg-white shadow-md ring-1 ring-navy/10'
              : 'border-stone-200 bg-white/80 hover:border-stone-300 hover:bg-white'
          }`}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold text-navy tracking-tight">Regular updates</h2>
              <p className="text-stone-600 text-sm mt-2 leading-relaxed">
                Your recurring run: latest closings Excel plus current REISift export. Same files each
                cycle—no extra options unless you need them.
              </p>
            </div>
            <span
              className={`shrink-0 text-xs font-semibold uppercase tracking-wide px-2 py-1 rounded-md ${
                mode === 'regular' ? 'bg-gold/25 text-navy' : 'bg-stone-100 text-stone-500'
              }`}
            >
              Default
            </span>
          </div>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={mode === 'pastPatches'}
          id="tab-past"
          aria-controls="panel-workspace"
          onClick={() => onChange('pastPatches')}
          className={`text-left rounded-2xl border-2 p-6 transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-700 focus-visible:ring-offset-2 ${
            mode === 'pastPatches'
              ? 'border-amber-600/80 bg-amber-50/90 shadow-md ring-1 ring-amber-600/20'
              : 'border-stone-200 bg-white/80 hover:border-amber-200 hover:bg-amber-50/40'
          }`}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold text-amber-950 tracking-tight">Past patches</h2>
              <p className="text-amber-950/80 text-sm mt-2 leading-relaxed">
                Build REISift bulk-import CSVs from cold calling + SMS logs + CRM + closings so tags
                and statuses line up before you run regular attribution. Kept separate from monthly
                analysis.
              </p>
            </div>
            <span className="shrink-0 text-xs font-semibold uppercase tracking-wide px-2 py-1 rounded-md bg-amber-200/80 text-amber-950">
              Temporary
            </span>
          </div>
        </button>
      </div>
    </div>
  );
};

export default ModeSwitcher;
