export type WorkspaceMode = 'regular' | 'pastPatches' | 'qualifiedLeads' | 'monthlyConsolidated';

/** Primary workflow modes shown in the workflow picker. */
export type GateMode = 'pastPatches' | 'monthlyConsolidated' | 'marketingRamp' | 'webLeads';

interface ModeSwitcherProps {
  mode: GateMode;
  onChange: (mode: GateMode) => void;
}

const ModeSwitcher = ({ mode, onChange }: ModeSwitcherProps) => {
  return (
    <div className="mb-8">
      <p className="text-sm font-medium text-stone-500 uppercase tracking-wide mb-3">
        Monthly workflow
      </p>
      <div
        className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4"
        role="tablist"
        aria-label="Monthly workflow gates"
      >
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'pastPatches'}
          id="tab-gate1"
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
              <p className="text-xs font-bold uppercase tracking-wider text-amber-800 mb-1">Gate 1</p>
              <h2 className="text-lg font-bold text-amber-950 tracking-tight">Monthly ingestion</h2>
              <p className="text-amber-950/80 text-sm mt-2 leading-relaxed">
                Upload cold calling, SMS, and CRM (closings optional) → download REISift import bundle.
                Import into REISift before running Gate 2.
              </p>
            </div>
            <span className="shrink-0 text-xs font-semibold uppercase tracking-wide px-2 py-1 rounded-md bg-amber-200/80 text-amber-950">
              Ingest
            </span>
          </div>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={mode === 'monthlyConsolidated'}
          id="tab-gate2"
          aria-controls="panel-workspace"
          onClick={() => onChange('monthlyConsolidated')}
          className={`text-left rounded-2xl border-2 p-6 transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-700 focus-visible:ring-offset-2 ${
            mode === 'monthlyConsolidated'
              ? 'border-indigo-600/80 bg-indigo-50/90 shadow-md ring-1 ring-indigo-600/20'
              : 'border-stone-200 bg-white/80 hover:border-indigo-200 hover:bg-indigo-50/40'
          }`}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-indigo-800 mb-1">Gate 2</p>
              <h2 className="text-lg font-bold text-indigo-950 tracking-tight">Run report</h2>
              <p className="text-indigo-950/80 text-sm mt-2 leading-relaxed">
                Upload REISift export + Salesforce Total Qualified Leads → consolidated analysis
                with list performance, channels, and lead journey.
              </p>
            </div>
            <span
              className={`shrink-0 text-xs font-semibold uppercase tracking-wide px-2 py-1 rounded-md ${
                mode === 'monthlyConsolidated'
                  ? 'bg-indigo-200/80 text-indigo-950'
                  : 'bg-stone-100 text-stone-500'
              }`}
            >
              Gate 2
            </span>
          </div>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={mode === 'marketingRamp'}
          id="tab-gate3"
          aria-controls="panel-workspace"
          onClick={() => onChange('marketingRamp')}
          className={`text-left rounded-2xl border-2 p-6 transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-700 focus-visible:ring-offset-2 ${
            mode === 'marketingRamp'
              ? 'border-emerald-600/80 bg-emerald-50/90 shadow-md ring-1 ring-emerald-600/20'
              : 'border-stone-200 bg-white/80 hover:border-emerald-200 hover:bg-emerald-50/40'
          }`}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-emerald-800 mb-1">Gate 3</p>
              <h2 className="text-lg font-bold text-emerald-950 tracking-tight">Marketing ramp report</h2>
              <p className="text-emerald-950/80 text-sm mt-2 leading-relaxed">
                Upload qualified leads, REISift export, and closings → row-level lead journey
                timing with channel touches and opportunity progression.
              </p>
            </div>
            <span className="shrink-0 text-xs font-semibold uppercase tracking-wide px-2 py-1 rounded-md bg-emerald-200/80 text-emerald-950">
              Ramp
            </span>
          </div>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={mode === 'webLeads'}
          id="tab-gate4"
          aria-controls="panel-workspace"
          onClick={() => onChange('webLeads')}
          className={`text-left rounded-2xl border-2 p-6 transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-700 focus-visible:ring-offset-2 ${
            mode === 'webLeads'
              ? 'border-violet-600/80 bg-violet-50/90 shadow-md ring-1 ring-violet-600/20'
              : 'border-stone-200 bg-white/80 hover:border-violet-200 hover:bg-violet-50/40'
          }`}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-violet-800 mb-1">Gate 4</p>
              <h2 className="text-lg font-bold text-violet-950 tracking-tight">Web Leads</h2>
              <p className="text-violet-950/80 text-sm mt-2 leading-relaxed">
                Upload REISift export + Salesforce qualified leads → see which website leads were
                already on your lists and how long ago, with compact journey paths.
              </p>
            </div>
            <span className="shrink-0 text-xs font-semibold uppercase tracking-wide px-2 py-1 rounded-md bg-violet-200/80 text-violet-950">
              Web
            </span>
          </div>
        </button>
      </div>
    </div>
  );
};

export default ModeSwitcher;
