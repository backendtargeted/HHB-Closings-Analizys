import { useState } from 'react';
import {
  analyzeWebLeads,
  deleteWebLeadsJob,
  downloadWebLeadsExport,
  getAxiosErrorMessage,
} from '../services/api';
import type { WebLeadsCompletedResponse } from '../types/webLeads';
import WebLeadsResults from './WebLeadsResults';

interface WebLeadsWorkspaceProps {
  onRunComplete?: () => void;
  onOpenResult?: (data: WebLeadsCompletedResponse) => void;
}

const WebLeadsWorkspace = ({ onRunComplete, onOpenResult }: WebLeadsWorkspaceProps) => {
  const [reisiftFile, setReisiftFile] = useState<File | null>(null);
  const [qlFile, setQlFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WebLeadsCompletedResponse | null>(null);
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
      const data = await analyzeWebLeads(reisiftFile, qlFile, (pct, msg) => {
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
        await deleteWebLeadsJob(result.job_id);
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
      const blob = await downloadWebLeadsExport(result.job_id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `web_leads_${result.job_id}.xlsx`;
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
      <WebLeadsResults
        result={result}
        onNewRun={handleNewRun}
        onExport={handleExport}
        exporting={exporting}
      />
    );
  }

  return (
    <div className="rounded-2xl border border-violet-200/90 bg-violet-50/40 p-6 shadow-sm">
      <h2 className="text-xl font-bold text-violet-950">Web Leads report</h2>
      <p className="text-sm text-violet-950/80 mt-2 leading-relaxed max-w-2xl">
        Upload your full REISift contacts export plus Salesforce Total Qualified Leads.
        Website-channel leads are filtered automatically. For each match, the report checks
        whether the property was already on distress lists or touched via{' '}
        <code className="text-xs bg-white/80 px-1 rounded">(8020)</code> tags before the web-lead
        anchor date (earlier of REISift <strong>Created on</strong> and SF Create Date).
      </p>

      <div className="mt-6 grid gap-4 max-w-md">
        <label className="block text-sm font-medium text-violet-950">
          REISift contacts export (.csv)
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setReisiftFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-violet-950">
          Salesforce Total Qualified Leads (.csv)
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setQlFile(e.target.files?.[0] ?? null)}
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
          className="px-5 py-2.5 rounded-lg bg-violet-800 text-white text-sm font-semibold hover:bg-violet-900 disabled:opacity-50"
        >
          {loading ? 'Analyzing…' : 'Run Web Leads report'}
        </button>
        {loading ? (
          <span className="text-sm text-violet-900">
            {statusMessage || 'Working…'} {progress > 0 ? `(${progress}%)` : ''}
          </span>
        ) : null}
      </div>
    </div>
  );
};

export default WebLeadsWorkspace;
