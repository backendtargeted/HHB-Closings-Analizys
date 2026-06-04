import { useState } from 'react';
import {
  analyzeMonthlyConsolidated,
  deleteMonthlyConsolidatedJob,
  downloadMonthlyConsolidatedExport,
  getAxiosErrorMessage,
} from '../services/api';
import type { MonthlyConsolidatedCompletedResponse } from '../types/monthlyConsolidated';
import MonthlyConsolidatedResults from './MonthlyConsolidatedResults';

interface MonthlyConsolidatedWorkspaceProps {
  channelLabels: Record<string, string>;
  onRunComplete?: () => void;
  onOpenResult?: (data: MonthlyConsolidatedCompletedResponse) => void;
}

const MonthlyConsolidatedWorkspace = ({
  channelLabels,
  onRunComplete,
  onOpenResult,
}: MonthlyConsolidatedWorkspaceProps) => {
  const [reisiftFile, setReisiftFile] = useState<File | null>(null);
  const [qlFile, setQlFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MonthlyConsolidatedCompletedResponse | null>(null);
  const [exporting, setExporting] = useState(false);

  const handleRun = async () => {
    if (!reisiftFile || !qlFile) {
      setError('Upload both REISift export and Salesforce Total Qualified Leads export.');
      return;
    }
    setLoading(true);
    setError(null);
    setProgress(0);
    setStatusMessage('');
    try {
      const data = await analyzeMonthlyConsolidated(reisiftFile, qlFile, (pct, msg) => {
        setProgress(pct);
        setStatusMessage(msg);
      });
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
        await deleteMonthlyConsolidatedJob(result.job_id);
      } catch {
        /* ignore */
      }
    }
    setResult(null);
    setReisiftFile(null);
    setQlFile(null);
  };

  const handleExport = async () => {
    if (!result?.job_id) return;
    setExporting(true);
    try {
      const blob = await downloadMonthlyConsolidatedExport(result.job_id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `consolidated_report_${result.job_id}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert('Export failed');
    } finally {
      setExporting(false);
    }
  };

  if (result) {
    return (
      <MonthlyConsolidatedResults
        result={result}
        channelLabels={channelLabels}
        onNewRun={handleNewRun}
        onExport={handleExport}
        exporting={exporting}
      />
    );
  }

  return (
    <div className="rounded-2xl border border-indigo-200/90 bg-indigo-50/40 p-6 shadow-sm">
      <h2 className="text-xl font-bold text-indigo-950">Consolidated list report</h2>
      <p className="text-sm text-indigo-950/80 mt-2 leading-relaxed max-w-2xl">
        Upload your full REISift contacts export (large file is fine) plus Salesforce Total
        Qualified Leads. The report ranks distress <strong>Lists</strong>, stacked combinations,
        CRM <code className="text-xs bg-white/80 px-1 rounded">(SF)</code> tags, qualified-lead
        channels, and closing journey across <strong>every row in the file</strong> — no month
        picker.
      </p>

      <div className="mt-6 grid gap-4 max-w-md">
        <label className="block text-sm font-medium text-indigo-950">
          REISift contacts export (.csv)
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setReisiftFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-indigo-950">
          Salesforce Total Qualified Leads (.csv / .xlsx)
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setQlFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
      </div>

      {loading && statusMessage && (
        <p className="mt-4 text-sm text-indigo-900/90">
          {statusMessage}
          {progress > 0 ? ` (${progress}%)` : ''}
        </p>
      )}

      {error && (
        <p className="mt-4 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {error}
        </p>
      )}

      <button
        type="button"
        onClick={handleRun}
        disabled={loading}
        className="mt-6 px-5 py-2.5 rounded-lg bg-indigo-800 text-white font-medium hover:bg-indigo-900 disabled:opacity-50"
      >
        {loading ? 'Analyzing… (large files may take a minute)' : 'Run consolidated report'}
      </button>
    </div>
  );
};

export default MonthlyConsolidatedWorkspace;
