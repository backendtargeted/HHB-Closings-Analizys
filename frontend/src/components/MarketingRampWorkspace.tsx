import { useState } from 'react';
import { analyzeMarketingRamp, getAxiosErrorMessage } from '../services/api';
import type { MarketingRampCompletedResponse } from '../types/marketingRamp';

interface MarketingRampWorkspaceProps {
  onRunComplete?: () => void;
  onOpenResult?: (data: MarketingRampCompletedResponse) => void;
}

const MarketingRampWorkspace = ({ onRunComplete, onOpenResult }: MarketingRampWorkspaceProps) => {
  const [qlFile, setQlFile] = useState<File | null>(null);
  const [reisiftFile, setReisiftFile] = useState<File | null>(null);
  const [closingsFile, setClosingsFile] = useState<File | null>(null);
  const [useFullSpan, setUseFullSpan] = useState(true);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleRun = async () => {
    if (!qlFile || !reisiftFile || !closingsFile) {
      setError('Upload all three files: Qualified Leads, REISift export, and Closings.');
      return;
    }
    if (!useFullSpan && (!startDate.trim() || !endDate.trim())) {
      setError('Enter start and end dates, or enable “Use full file date span”.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await analyzeMarketingRamp(qlFile, reisiftFile, closingsFile, {
        useFullFileSpan: useFullSpan,
        startDate: startDate.trim() || undefined,
        endDate: endDate.trim() || undefined,
      });
      onOpenResult?.(data);
      onRunComplete?.();
    } catch (e) {
      setError(getAxiosErrorMessage(e, 'Analysis failed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-2xl border border-emerald-200/90 bg-emerald-50/40 p-6 shadow-sm">
      <h2 className="text-xl font-bold text-emerald-950">Marketing ramp report</h2>
      <p className="text-sm text-emerald-950/80 mt-2 leading-relaxed max-w-2xl">
        Upload Salesforce Total Qualified Leads, REISift contacts export, and closings workbook.
        The report measures row-level lead journey timing — channel touches, REISift match, and
        opportunity progression within your chosen date window.
      </p>

      <div className="mt-6 grid gap-4 max-w-md">
        <label className="block text-sm font-medium text-emerald-950">
          Salesforce Total Qualified Leads (.csv / .xlsx)
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setQlFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-emerald-950">
          REISift contacts export (.csv / .xlsx)
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setReisiftFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-emerald-950">
          Closings workbook (.xlsx / .xls)
          <input
            type="file"
            accept=".xlsx,.xls"
            onChange={(e) => setClosingsFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
      </div>

      <fieldset className="mt-6 rounded-xl border border-emerald-200/80 bg-white/60 p-4 space-y-3 max-w-md">
        <legend className="text-xs font-semibold uppercase tracking-wide text-emerald-800 px-1">
          Date window
        </legend>
        <label className="flex items-start gap-3 text-sm text-emerald-950 cursor-pointer">
          <input
            type="checkbox"
            checked={useFullSpan}
            onChange={(e) => setUseFullSpan(e.target.checked)}
            className="mt-1"
          />
          <span>Use full file date span (min–max dates across uploads)</span>
        </label>
        {!useFullSpan && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="text-sm">
              <span className="block text-emerald-900/80 mb-1">Start date</span>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-full rounded-lg border border-stone-300 px-3 py-2"
              />
            </label>
            <label className="text-sm">
              <span className="block text-emerald-900/80 mb-1">End date</span>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="w-full rounded-lg border border-stone-300 px-3 py-2"
              />
            </label>
          </div>
        )}
      </fieldset>

      {error && (
        <p className="mt-4 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {error}
        </p>
      )}

      <button
        type="button"
        onClick={handleRun}
        disabled={loading}
        className="mt-6 px-5 py-2.5 rounded-lg bg-emerald-800 text-white font-medium hover:bg-emerald-900 disabled:opacity-50"
      >
        {loading ? 'Analyzing…' : 'Run marketing ramp report'}
      </button>
    </div>
  );
};

export default MarketingRampWorkspace;
