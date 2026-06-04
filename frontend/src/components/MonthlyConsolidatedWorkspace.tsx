import { useState } from 'react';
import {
  analyzeMonthlyConsolidated,
  deleteMonthlyConsolidatedJob,
  downloadMonthlyConsolidatedExport,
} from '../services/api';
import type { MonthlyConsolidatedAnalyzeResponse } from '../types/monthlyConsolidated';
import MonthlyConsolidatedResults from './MonthlyConsolidatedResults';

const defaultMonth = () => {
  const d = new Date();
  d.setMonth(d.getMonth() - 1);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  return `${y}-${m}`;
};

interface MonthlyConsolidatedWorkspaceProps {
  channelLabels: Record<string, string>;
  onRunComplete?: () => void;
  onOpenResult?: (data: MonthlyConsolidatedAnalyzeResponse) => void;
}

const MonthlyConsolidatedWorkspace = ({
  channelLabels,
  onRunComplete,
  onOpenResult,
}: MonthlyConsolidatedWorkspaceProps) => {
  const [reisiftFile, setReisiftFile] = useState<File | null>(null);
  const [qlFile, setQlFile] = useState<File | null>(null);
  const [reportMonth, setReportMonth] = useState(defaultMonth);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MonthlyConsolidatedAnalyzeResponse | null>(null);
  const [exporting, setExporting] = useState(false);

  const handleRun = async () => {
    if (!reisiftFile || !qlFile) {
      setError('Upload both REISift export and Salesforce Total Qualified Leads export.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await analyzeMonthlyConsolidated(reisiftFile, qlFile, reportMonth);
      setResult(data);
      onOpenResult?.(data);
      onRunComplete?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Analysis failed');
    } finally {
      setLoading(false);
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
      a.download = `monthly_consolidated_${result.metrics.report_month}_${result.job_id}.xlsx`;
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
      <h2 className="text-xl font-bold text-indigo-950">Monthly consolidated report</h2>
      <p className="text-sm text-indigo-950/80 mt-2 leading-relaxed max-w-2xl">
        Combine REISift list performance (distress lists, stacked leads, combinations), CRM
        signals from <code className="text-xs bg-white/80 px-1 rounded">(SF)</code> tags, qualified
        leads by channel, and closing lifecycle for one calendar month. Cohort is filtered by
        REISift <strong>Created</strong> date.
      </p>

      <div className="mt-6 grid gap-4 max-w-md">
        <label className="block text-sm font-medium text-indigo-950">
          Report month
          <input
            type="month"
            value={reportMonth}
            onChange={(e) => setReportMonth(e.target.value)}
            className="mt-1 block w-full rounded-lg border border-indigo-200 px-3 py-2 text-stone-800"
          />
        </label>
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
        {loading ? 'Analyzing…' : 'Run monthly report'}
      </button>
    </div>
  );
};

export default MonthlyConsolidatedWorkspace;
