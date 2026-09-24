import { useState } from 'react';
import {
  analyzeInvestorSold,
  analyzeInvestorSoldBundle,
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
  const [uploadMode, setUploadMode] = useState<'bundle' | 'individual'>('bundle');
  const [bundleFile, setBundleFile] = useState<File | null>(null);
  const [detailsFile, setDetailsFile] = useState<File | null>(null);
  const [soldFile, setSoldFile] = useState<File | null>(null);
  const [reisiftFile, setReisiftFile] = useState<File | null>(null);
  const [qlFile, setQlFile] = useState<File | null>(null);
  const [oppsFile, setOppsFile] = useState<File | null>(null);
  const [txnFile, setTxnFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<InvestorSoldCompletedResponse | null>(null);
  const [exporting, setExporting] = useState(false);

  const canRun = uploadMode === 'bundle' ? Boolean(bundleFile) : Boolean(soldFile && reisiftFile && qlFile);

  const handleRun = async () => {
    if (!canRun) {
      setError(
        'Select a ZIP bundle, or upload sold transactions, REISift, and Qualified Leads in individual-file mode.'
      );
      return;
    }
    setLoading(true);
    setError(null);
    setProgress(0);
    setStatusMessage('');
    try {
      const onProgress = (pct: number, msg: string) => {
        setProgress(pct);
        setStatusMessage(msg);
      };
      const data = uploadMode === 'bundle'
        ? await analyzeInvestorSoldBundle(bundleFile!, onProgress)
        : await analyzeInvestorSold(
            soldFile!, reisiftFile!, qlFile!, oppsFile ?? undefined,
            txnFile ?? undefined, onProgress, detailsFile ?? undefined
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
    setBundleFile(null);
    setDetailsFile(null);
    setReisiftFile(null);
    setQlFile(null);
    setOppsFile(null);
    setTxnFile(null);
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
        Count each property once at its earliest observed sold month. Apply Nassau/Suffolk,
        NY geography and ZIP exclusions first, using city exclusions only when ZIP is missing.
        Property details screen supported buybox attributes and match seller evidence for that sale.
        Pipeline: Prospect → Marketed → Lead → Qualified Lead → Opportunity → Closed.
      </p>
      <p className="text-xs text-stone-600 mt-2 max-w-2xl">
        Details describe an exported snapshot, not a complete historical buybox assessment.
        Ownership tenure, LTV, and non-seller/religious-owner exclusions are not evaluated.
        Seller categories estimate ownership type from matched seller names; they are not verified legal types.
        Large files upload in chunks; property details stream on the server, with progress below.
      </p>
      <fieldset disabled={loading} className="mt-5 flex flex-wrap gap-4 text-sm text-violet-950">
        <legend className="font-semibold mb-2">Upload method</legend>
        <label><input type="radio" name="gate7-upload-mode" checked={uploadMode === 'bundle'} onChange={() => setUploadMode('bundle')} /> ZIP bundle (recommended)</label>
        <label><input type="radio" name="gate7-upload-mode" checked={uploadMode === 'individual'} onChange={() => setUploadMode('individual')} /> Individual files</label>
      </fieldset>
      {uploadMode === 'bundle' ? (
        <div className="mt-5 max-w-2xl space-y-3">
          <label className="block text-sm font-medium text-violet-950">
            Report bundle (.zip)
            <input type="file" accept=".zip" disabled={loading} onChange={(e) => setBundleFile(e.target.files?.[0] ?? null)} className="mt-1 block w-full text-sm" />
          </label>
          <div className="rounded-lg border border-violet-200 bg-white p-3 text-xs text-stone-700 space-y-2">
            <p>Use these exact filenames at the ZIP root or together inside one folder:</p>
            <ul className="list-disc pl-5 space-y-1">
              <li><code>sold_properties_full.csv</code></li>
              <li><code>reisift_export.csv</code></li>
              <li><code>qualified_leads.xlsx</code> or <code>qualified_leads.csv</code></li>
              <li><code>sold_property_details.jsonl</code></li>
            </ul>
            <p>Optional: <code>opportunities.xlsx</code> / <code>opportunities.csv</code> and <code>transactions.xlsx</code> / <code>transactions.csv</code>. Include only one format per report.</p>
          </div>
        </div>
      ) : (
      <div className="mt-6 grid gap-4 max-w-md">
        <label className="block text-sm font-medium text-violet-950">
          Sold transactions (.csv) — required
          <input
            type="file"
            disabled={loading}
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setSoldFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-violet-950">
          REISift export (.csv / .xlsx) — required
          <input
            type="file"
            disabled={loading}
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setReisiftFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-violet-950">
          Salesforce Total Qualified Leads (.csv / .xlsx) — required
          <input
            type="file"
            disabled={loading}
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setQlFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-violet-950">
          Opportunities (.xlsx) — optional
          <input
            type="file"
            disabled={loading}
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setOppsFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-violet-950">
          Transaction Pipeline (.xlsx) — optional
          <input
            type="file"
            disabled={loading}
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setTxnFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </label>
        <label className="block text-sm font-medium text-violet-950">
          Property details (.jsonl) — recommended
          <input type="file" accept=".jsonl" disabled={loading} onChange={(e) => setDetailsFile(e.target.files?.[0] ?? null)} className="mt-1 block w-full text-sm" />
        </label>
        {!detailsFile && <p className="text-xs text-amber-900">Without property details, this report is geographic-only: property attributes and seller categories cannot be verified.</p>}
      </div>
      )}

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
        disabled={loading || !canRun}
        className="mt-6 px-5 py-2.5 rounded-xl bg-violet-800 text-white text-sm font-semibold hover:bg-violet-900 disabled:opacity-50"
      >
        {loading ? 'Analyzing…' : 'Run investor & in-list sold report'}
      </button>
    </div>
  );
};

export default InvestorSoldWorkspace;
