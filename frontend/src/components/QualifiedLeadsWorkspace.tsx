import { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import {
  analyzeQualifiedLeads,
  deleteQualifiedLeadsJob,
  downloadQualifiedLeadsExport,
  getAxiosErrorMessage,
} from '../services/api';
import type { QualifiedLeadsAnalyzeResponse } from '../types/qualifiedLeads';
import QualifiedLeadsResults from './QualifiedLeadsResults';

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const CHANNEL_LABELS: Record<string, string> = {
  CC: 'Cold Calling',
  SMS: 'SMS (incl. RES-VA SMS)',
  DM: 'Direct Mail',
  Website: 'Website',
  PPC: 'PPC',
  SEO: 'SEO',
  Other: 'Other',
};

interface QualifiedLeadsWorkspaceProps {
  onRunComplete?: () => void;
  onOpenResult?: (data: QualifiedLeadsAnalyzeResponse) => void;
}

const QualifiedLeadsWorkspace = ({ onRunComplete, onOpenResult }: QualifiedLeadsWorkspaceProps) => {
  const [file, setFile] = useState<File | null>(null);
  const [useFullSpan, setUseFullSpan] = useState(true);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QualifiedLeadsAnalyzeResponse | null>(null);
  const [exporting, setExporting] = useState(false);

  const onDrop = useCallback((files: File[]) => {
    if (files[0]) {
      setFile(files[0]);
      setError(null);
      setResult(null);
    }
  }, []);

  const dropzone = useDropzone({
    onDrop,
    accept: {
      'text/csv': ['.csv'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
    },
    maxFiles: 1,
  });

  const handleAnalyze = async () => {
    if (!file) {
      setError('Upload a Salesforce Total Qualified Leads export (.csv or .xlsx).');
      return;
    }
    if (!useFullSpan && (!startDate.trim() || !endDate.trim())) {
      setError('Enter start and end dates, or enable “Use full file date span”.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await analyzeQualifiedLeads(file, {
        useFullFileSpan: useFullSpan,
        startDate: startDate.trim() || undefined,
        endDate: endDate.trim() || undefined,
      });
      onRunComplete?.();
      if (onOpenResult) {
        onOpenResult(data);
      } else {
        setResult(data);
      }
    } catch (err) {
      setError(getAxiosErrorMessage(err, 'Analysis failed'));
    } finally {
      setLoading(false);
    }
  };

  const handleReset = async () => {
    if (result?.job_id) {
      try {
        await deleteQualifiedLeadsJob(result.job_id);
      } catch {
        /* ignore */
      }
    }
    setResult(null);
    setFile(null);
    setError(null);
  };

  const handleExportRows = async () => {
    if (!result?.job_id) return;
    setExporting(true);
    try {
      const blob = await downloadQualifiedLeadsExport(result.job_id);
      downloadBlob(blob, `qualified_leads_rows_${result.job_id}.csv`);
    } catch (err) {
      setError(getAxiosErrorMessage(err, 'Export failed'));
    } finally {
      setExporting(false);
    }
  };

  if (result) {
    return (
      <QualifiedLeadsResults
        result={result}
        channelLabels={CHANNEL_LABELS}
        onNewRun={handleReset}
        onExportRows={handleExportRows}
        exporting={exporting}
      />
    );
  }

  return (
    <div className="rounded-2xl border border-teal-200/90 bg-white shadow-sm overflow-hidden">
      <div className="bg-teal-50/80 border-b border-teal-200/80 px-6 py-4">
        <h2 className="text-xl font-bold text-teal-950">Qualified leads consolidation</h2>
        <p className="text-sm text-teal-900/80 mt-1 leading-relaxed max-w-2xl">
          One-time snapshot from Salesforce <strong>Total Qualified Leads</strong>. Every row in the
          export counts as qualified. Rates show each channel&apos;s share of posted leads in your
          chosen <strong>Create Date</strong> window — not conversion rate.
        </p>
      </div>

      <div className="p-6 space-y-6">
        <div
          {...dropzone.getRootProps()}
          className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
            dropzone.isDragActive
              ? 'border-teal-500 bg-teal-50'
              : 'border-stone-300 hover:border-teal-400'
          }`}
        >
          <input {...dropzone.getInputProps()} />
          {file ? (
            <p className="text-sm font-medium text-stone-800">{file.name}</p>
          ) : (
            <p className="text-sm text-stone-600">
              Drop SF export here, or click to select (.csv / .xlsx)
            </p>
          )}
        </div>

        <fieldset className="rounded-xl border border-stone-200 bg-stone-50/60 p-4 space-y-3">
          <legend className="text-xs font-semibold uppercase tracking-wide text-stone-600 px-1">
            Create Date window
          </legend>
          <label className="flex items-start gap-3 text-sm text-stone-700 cursor-pointer">
            <input
              type="checkbox"
              checked={useFullSpan}
              onChange={(e) => setUseFullSpan(e.target.checked)}
              className="mt-1"
            />
            <span>
              Use full file date span (min–max <code className="text-xs">Create Date</code> in
              upload)
            </span>
          </label>
          {!useFullSpan && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <label className="text-sm">
                <span className="block text-stone-600 mb-1">Start date</span>
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="w-full rounded-lg border border-stone-300 px-3 py-2"
                />
              </label>
              <label className="text-sm">
                <span className="block text-stone-600 mb-1">End date</span>
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
          <p className="text-sm text-red-800 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
            {error}
          </p>
        )}

        <button
          type="button"
          onClick={handleAnalyze}
          disabled={loading || !file}
          className="w-full sm:w-auto px-6 py-3 rounded-xl bg-teal-800 text-white font-semibold hover:bg-teal-900 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? 'Analyzing…' : 'Run consolidation'}
        </button>
      </div>
    </div>
  );
};

export default QualifiedLeadsWorkspace;
