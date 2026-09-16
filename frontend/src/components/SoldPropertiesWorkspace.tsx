import { useState } from 'react';
import {
  analyzeSoldProperties,
  deleteSoldPropertiesJob,
  downloadSoldPropertiesExport,
  getAxiosErrorMessage,
} from '../services/api';
import type { SoldPropertiesCompletedResponse } from '../types/soldProperties';
import SoldPropertiesResults from './SoldPropertiesResults';

interface SoldPropertiesWorkspaceProps {
  onRunComplete?: () => void;
  onOpenResult?: (data: SoldPropertiesCompletedResponse) => void;
}

const SoldPropertiesWorkspace = ({
  onRunComplete,
  onOpenResult,
}: SoldPropertiesWorkspaceProps) => {
  const [reisiftFile, setReisiftFile] = useState<File | null>(null);
  const [qlFile, setQlFile] = useState<File | null>(null);
  const [oppsFile, setOppsFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SoldPropertiesCompletedResponse | null>(null);
  const [exporting, setExporting] = useState(false);

  const handleRun = async () => {
    if (!reisiftFile || !qlFile) {
      setError('Upload REISift export (with in_sold_properties_full) and Salesforce Total Qualified Leads.');
      return;
    }
    setLoading(true);
    setError(null);
    setProgress(0);
    setStatusMessage('');
    try {
      const data = await analyzeSoldProperties(
        reisiftFile,
        qlFile,
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
        await deleteSoldPropertiesJob(result.job_id);
      } catch {
        /* ignore */
      }
    }
    setResult(null);
    setReisiftFile(null);
    setQlFile(null);
    setOppsFile(null);
  };

  const handleExport = async () => {
    if (!result?.job_id) return;
    setExporting(true);
    try {
      const blob = await downloadSoldPropertiesExport(result.job_id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `sold_properties_${result.job_id}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  if (result) {
    return (
      <SoldPropertiesResults
        result={result}
        onNewRun={handleNewRun}
        onExport={handleExport}
        exporting={exporting}
      />
    );
  }

  return (
    <div className="rounded-2xl border border-teal-200/90 bg-teal-50/40 p-6 shadow-sm">
      <h2 className="text-xl font-bold text-teal-950">Sold properties</h2>
      <p className="text-sm text-teal-950/80 mt-2 leading-relaxed max-w-2xl">
        Properties in your REISift records that sold (external sale month in{' '}
        <code className="text-xs">in_sold_properties_full</code>). Shows how hard you marketed them
        and how far they got in your pipeline (Prospect → Marketed → Lead → Qualified Lead →
        Opportunity → Under contract → Closed) before that sale month.{' '}
        <code className="text-xs">PodioSellerLeads</code> is Lead (pre-Salesforce CRM). Upload
        Opportunities for Opportunity-stage depth. Rows with no contact tags are often federal Do
        Not Call or suppression — bought onto REISift but never reached out.
      </p>

      <div className="mt-6 grid gap-4 max-w-md">
        <label className="block text-sm font-medium text-teal-950">
          REISift export (.csv / .xlsx) with in_sold_properties_full — required
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setReisiftFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-teal-950">
          Salesforce Total Qualified Leads (.csv / .xlsx) — required
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setQlFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-teal-950">
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
          <div className="h-2 rounded-full bg-teal-100 overflow-hidden">
            <div
              className="h-full bg-teal-600 transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
          <p className="text-xs text-teal-900 mt-2">{statusMessage || 'Working…'}</p>
        </div>
      )}

      <button
        type="button"
        onClick={handleRun}
        disabled={loading || !reisiftFile || !qlFile}
        className="mt-6 px-5 py-2.5 rounded-xl bg-teal-800 text-white text-sm font-semibold hover:bg-teal-900 disabled:opacity-50"
      >
        {loading ? 'Analyzing…' : 'Run sold-properties report'}
      </button>
    </div>
  );
};

export default SoldPropertiesWorkspace;
