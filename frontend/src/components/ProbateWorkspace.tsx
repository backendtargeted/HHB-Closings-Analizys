import { useState } from 'react';
import {
  analyzeProbate,
  deleteProbateJob,
  downloadProbateExport,
  getAxiosErrorMessage,
} from '../services/api';
import type { ProbateCompletedResponse } from '../types/probate';
import ProbateResults from './ProbateResults';

interface ProbateWorkspaceProps {
  onRunComplete?: () => void;
  onOpenResult?: (data: ProbateCompletedResponse) => void;
}

const ProbateWorkspace = ({ onRunComplete, onOpenResult }: ProbateWorkspaceProps) => {
  const [reisiftFile, setReisiftFile] = useState<File | null>(null);
  const [qlFile, setQlFile] = useState<File | null>(null);
  const [oppsFile, setOppsFile] = useState<File | null>(null);
  const [txnFile, setTxnFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ProbateCompletedResponse | null>(null);
  const [exporting, setExporting] = useState(false);

  const handleRun = async () => {
    if (!reisiftFile || !qlFile) {
      setError('Upload REISift export and Salesforce Total Qualified Leads.');
      return;
    }
    setLoading(true);
    setError(null);
    setProgress(0);
    setStatusMessage('');
    try {
      const data = await analyzeProbate(
        reisiftFile,
        qlFile,
        oppsFile ?? undefined,
        txnFile ?? undefined,
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
        await deleteProbateJob(result.job_id);
      } catch {
        /* ignore */
      }
    }
    setResult(null);
    setReisiftFile(null);
    setQlFile(null);
    setOppsFile(null);
    setTxnFile(null);
  };

  const handleExport = async () => {
    if (!result?.job_id) return;
    setExporting(true);
    try {
      const blob = await downloadProbateExport(result.job_id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `probate_${result.job_id}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  if (result) {
    return (
      <ProbateResults
        result={result}
        onNewRun={handleNewRun}
        onExport={handleExport}
        exporting={exporting}
      />
    );
  }

  return (
    <div className="rounded-2xl border border-rose-200/90 bg-rose-50/40 p-6 shadow-sm">
      <h2 className="text-xl font-bold text-rose-950">Probate lifecycle</h2>
      <p className="text-sm text-rose-950/80 mt-2 leading-relaxed max-w-2xl">
        Long Island Profiles county tags vs 8020 on the same REISift row, then Salesforce Prospect
        (Qualified Leads Create Date). Transactions supply Primary and Secondary Reason for Selling
        after the match — they do not decide who is probate.
      </p>

      <div className="mt-6 grid gap-4 max-w-md">
        <label className="block text-sm font-medium text-rose-950">
          REISift export (.csv / .xlsx) — required
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setReisiftFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-rose-950">
          Salesforce Total Qualified Leads (.csv / .xlsx) — required
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setQlFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-rose-950">
          Opportunities (.xlsx) — optional
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setOppsFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-rose-950">
          Transactions pipeline (.xlsx) — for reason to sell
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setTxnFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
      </div>

      {error ? (
        <p className="mt-4 text-sm text-red-800 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {error}
        </p>
      ) : null}

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={handleRun}
          disabled={loading || !reisiftFile || !qlFile}
          className="px-5 py-2.5 rounded-lg bg-rose-800 text-white text-sm font-semibold hover:bg-rose-900 disabled:opacity-50"
        >
          {loading ? 'Analyzing…' : 'Run probate report'}
        </button>
        {loading ? (
          <span className="text-sm text-rose-900">
            {statusMessage || 'Working…'} {progress > 0 ? `(${progress}%)` : ''}
          </span>
        ) : null}
      </div>
    </div>
  );
};

export default ProbateWorkspace;
