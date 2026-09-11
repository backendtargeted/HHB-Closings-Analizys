import { useState } from 'react';
import {
  analyzeCourtAlerts,
  deleteCourtAlertsJob,
  downloadCourtAlertsExport,
  getAxiosErrorMessage,
} from '../services/api';
import type { CourtAlertsCompletedResponse } from '../types/courtAlerts';
import CourtAlertsResults from './CourtAlertsResults';

interface CourtAlertsWorkspaceProps {
  onRunComplete?: () => void;
  onOpenResult?: (data: CourtAlertsCompletedResponse) => void;
}

const CourtAlertsWorkspace = ({ onRunComplete, onOpenResult }: CourtAlertsWorkspaceProps) => {
  const [courtAlertsFile, setCourtAlertsFile] = useState<File | null>(null);
  const [reisiftFile, setReisiftFile] = useState<File | null>(null);
  const [qlFile, setQlFile] = useState<File | null>(null);
  const [oppsFile, setOppsFile] = useState<File | null>(null);
  const [txnFile, setTxnFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CourtAlertsCompletedResponse | null>(null);
  const [exporting, setExporting] = useState(false);

  const handleRun = async () => {
    if (!courtAlertsFile || !reisiftFile || !qlFile) {
      setError('Upload Court Alerts CSV, REISift export, and Salesforce Total Qualified Leads.');
      return;
    }
    setLoading(true);
    setError(null);
    setProgress(0);
    setStatusMessage('');
    try {
      const data = await analyzeCourtAlerts(
        courtAlertsFile,
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
        await deleteCourtAlertsJob(result.job_id);
      } catch {
        /* ignore */
      }
    }
    setResult(null);
    setCourtAlertsFile(null);
    setReisiftFile(null);
    setQlFile(null);
    setOppsFile(null);
    setTxnFile(null);
  };

  const handleExport = async () => {
    if (!result?.job_id) return;
    setExporting(true);
    try {
      const blob = await downloadCourtAlertsExport(result.job_id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `court_alerts_${result.job_id}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  if (result) {
    return (
      <CourtAlertsResults
        result={result}
        onNewRun={handleNewRun}
        onExport={handleExport}
        exporting={exporting}
      />
    );
  }

  return (
    <div className="rounded-2xl border border-sky-200/90 bg-sky-50/40 p-6 shadow-sm">
      <h2 className="text-xl font-bold text-sky-950">Court Alerts lifecycle</h2>
      <p className="text-sm text-sky-950/80 mt-2 leading-relaxed max-w-2xl">
        Court Alerts CSV is the universe. REISift supplies competing 8020 list tags on the same
        address. First list is the QL credit. A Prospect counts only when Salesforce Create Date is
        on or after that first-list month. Campaign is how they worked it. Transactions supply
        reason for selling after the match.
      </p>

      <div className="mt-6 grid gap-4 max-w-md">
        <label className="block text-sm font-medium text-sky-950">
          Court Alerts export (.csv / .xlsx) — required
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setCourtAlertsFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-sky-950">
          REISift export (.csv / .xlsx) — required
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setReisiftFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-sky-950">
          Salesforce Total Qualified Leads (.csv / .xlsx) — required
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setQlFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-sky-950">
          Opportunities (.xlsx) — optional
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setOppsFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-sky-950">
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
          disabled={loading || !courtAlertsFile || !reisiftFile || !qlFile}
          className="px-5 py-2.5 rounded-lg bg-sky-800 text-white text-sm font-semibold hover:bg-sky-900 disabled:opacity-50"
        >
          {loading ? 'Analyzing…' : 'Run Court Alerts report'}
        </button>
        {loading ? (
          <span className="text-sm text-sky-900">
            {statusMessage || 'Working…'} {progress > 0 ? `(${progress}%)` : ''}
          </span>
        ) : null}
      </div>
    </div>
  );
};

export default CourtAlertsWorkspace;
