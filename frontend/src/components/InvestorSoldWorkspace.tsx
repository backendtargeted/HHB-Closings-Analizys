import { useState } from 'react';
import {
  analyzeInvestorSold,
  deleteInvestorSoldJob,
  downloadInvestorSoldExport,
  getAxiosErrorMessage,
} from '../services/api';
import type { InvestorSoldCompletedResponse } from '../types/investorSold';
import InvestorSoldResults from './InvestorSoldResults';

interface InvestorSoldWorkspaceProps {
  onRunComplete?: () => void;
  onOpenResult?: (data: InvestorSoldCompletedResponse) => void;
}

const InvestorSoldWorkspace = ({
  onRunComplete,
  onOpenResult,
}: InvestorSoldWorkspaceProps) => {
  const [soldFile, setSoldFile] = useState<File | null>(null);
  const [reisiftFile, setReisiftFile] = useState<File | null>(null);
  const [qlFile, setQlFile] = useState<File | null>(null);
  const [oppsFile, setOppsFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<InvestorSoldCompletedResponse | null>(null);
  const [exporting, setExporting] = useState(false);

  const handleRun = async () => {
    if (!soldFile) {
      setError('Upload CleanREISift sold_properties_full.csv (investor + in_my_records columns).');
      return;
    }
    setLoading(true);
    setError(null);
    setProgress(0);
    setStatusMessage('');
    try {
      const data = await analyzeInvestorSold(
        soldFile,
        reisiftFile ?? undefined,
        qlFile ?? undefined,
        oppsFile ?? undefined,
        (pct, msg) => {
          setProgress(pct);
          setStatusMessage(msg);
        }
      );
      setResult(data);
      onOpenResult?.(data);
      onRunComplete?.();
    } catch (e) {
      setError(getAxiosErrorMessage(e, 'Analysis failed'));
    } finally {
      setLoading(false);
      setStatusMessage('');
    }
  };

  const handleNewRun = async () => {
    if (result?.job_id) {
      try {
        await deleteInvestorSoldJob(result.job_id);
      } catch {
        /* ignore */
      }
    }
    setResult(null);
    setSoldFile(null);
    setReisiftFile(null);
    setQlFile(null);
    setOppsFile(null);
  };

  const handleExport = async () => {
    if (!result?.job_id) return;
    setExporting(true);
    try {
      const blob = await downloadInvestorSoldExport(result.job_id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `investor_sold_${result.job_id}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  if (result) {
    return (
      <InvestorSoldResults
        result={result}
        onNewRun={handleNewRun}
        onExport={handleExport}
        exporting={exporting}
      />
    );
  }

  return (
    <div className="rounded-2xl border border-violet-200/90 bg-violet-50/40 p-6 shadow-sm">
      <h2 className="text-xl font-bold text-violet-950">Investor &amp; In-List Sold</h2>
      <p className="text-sm text-violet-950/80 mt-2 leading-relaxed max-w-2xl">
        Universe is CleanREISift <code className="text-xs">sold_properties_full.csv</code> (Dataflik
        All Transactions) with <code className="text-xs">investor</code> and{' '}
        <code className="text-xs">in_my_records</code> flags. Shows how many external sales are
        investor buyers, already in your REISift records, both, or neither. Optionally upload REISift
        + QL (+ Opps) to enrich matched addresses with marketing / pipeline depth (same clocks as
        Gate 6).
      </p>

      <div className="mt-6 grid gap-4 max-w-md">
        <label className="block text-sm font-medium text-violet-950">
          Sold transactions (.csv) — required
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setSoldFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-violet-950">
          REISift export (.csv / .xlsx) — optional enrichment
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setReisiftFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-violet-950">
          Salesforce Total Qualified Leads (.csv / .xlsx) — optional
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setQlFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-violet-950">
          Opportunities (.xlsx) — optional
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setOppsFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
      </div>

      {error && (
        <p className="mt-4 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {error}
        </p>
      )}

      {loading && (
        <div className="mt-4">
          <div className="h-2 rounded-full bg-violet-100 overflow-hidden">
            <div
              className="h-full bg-violet-600 transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
          <p className="text-xs text-violet-900 mt-2">{statusMessage || 'Working…'}</p>
        </div>
      )}

      <button
        type="button"
        onClick={handleRun}
        disabled={loading || !soldFile}
        className="mt-6 px-5 py-2.5 rounded-xl bg-violet-800 text-white text-sm font-semibold hover:bg-violet-900 disabled:opacity-50"
      >
        {loading ? 'Analyzing…' : 'Run investor & in-list sold report'}
      </button>
    </div>
  );
};

export default InvestorSoldWorkspace;
