import { useState } from 'react';
import {
  analyzeWebLeads,
  deleteWebLeadsJob,
  downloadWebLeadsExport,
  getAxiosErrorMessage,
} from '../services/api';
import type { WebLeadsCohortSource, WebLeadsCompletedResponse } from '../types/webLeads';
import WebLeadsResults from './WebLeadsResults';

interface WebLeadsWorkspaceProps {
  onRunComplete?: () => void;
  onOpenResult?: (data: WebLeadsCompletedResponse) => void;
}

const COHORT_OPTIONS: Array<{ value: WebLeadsCohortSource; label: string }> = [
  { value: 'web_leads', label: 'Web Leads track' },
  { value: 'court_alerts', label: 'Court alerts track' },
  { value: 'long_island_profiles', label: 'Long Island profiles track' },
];

const WebLeadsWorkspace = ({ onRunComplete, onOpenResult }: WebLeadsWorkspaceProps) => {
  const [cohortFile, setCohortFile] = useState<File | null>(null);
  const [reisiftReferenceFile, setReisiftReferenceFile] = useState<File | null>(null);
  const [closingsFile, setClosingsFile] = useState<File | null>(null);
  const [cohortSource, setCohortSource] = useState<WebLeadsCohortSource>('web_leads');
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WebLeadsCompletedResponse | null>(null);
  const [exporting, setExporting] = useState(false);

  const handleRun = async () => {
    if (!cohortFile) {
      setError('Upload your cohort track file (manually filtered leads).');
      return;
    }
    if (!reisiftReferenceFile) {
      setError('Upload the full REISift reference export.');
      return;
    }
    setLoading(true);
    setError(null);
    setProgress(0);
    setStatusMessage('');
    try {
      const data = await analyzeWebLeads(
        cohortFile,
        reisiftReferenceFile,
        closingsFile ?? undefined,
        cohortSource,
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
        await deleteWebLeadsJob(result.job_id);
      } catch {
        /* ignore */
      }
    }
    setResult(null);
    setCohortFile(null);
    setReisiftReferenceFile(null);
    setClosingsFile(null);
    setCohortSource('web_leads');
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
        Upload your manually filtered cohort track (e.g. web leads you exported from REISift for
        analysis). Match each row to the <strong>full REISift export</strong> to see lists, tag
        history, journey paths, and combinations. Only rows that match REISift are shown in the
        report. Optional closings workbook adds close date and stage.
      </p>

      <div className="mt-6 grid gap-4 max-w-md">
        <label className="block text-sm font-medium text-violet-950">
          Cohort track type
          <select
            value={cohortSource}
            onChange={(e) => setCohortSource(e.target.value as WebLeadsCohortSource)}
            className="mt-1 block w-full text-sm rounded-lg border border-violet-200 bg-white px-3 py-2"
          >
            {COHORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm font-medium text-violet-950">
          Cohort track file (.csv) — required
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setCohortFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-violet-950">
          Full REISift reference export (.csv) — required
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setReisiftReferenceFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-violet-950">
          Closings workbook (.xlsx) — optional
          <input
            type="file"
            accept=".xlsx,.xls"
            onChange={(e) => setClosingsFile(e.target.files?.[0] ?? null)}
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
          disabled={loading || !cohortFile || !reisiftReferenceFile}
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
