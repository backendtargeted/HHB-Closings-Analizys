import { useCallback, useRef, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import {
  deletePatchJob,
  downloadPatchExport,
  getAxiosErrorMessage,
  uploadPatches,
} from '../services/api';
import type { PatchUploadResponse } from '../types/patches';

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function CountBlock({
  title,
  counts,
}: {
  title: string;
  counts: Record<string, number> | undefined;
}) {
  const entries = Object.entries(counts || {}).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) {
    return null;
  }
  return (
    <div className="rounded-lg border border-stone-200 bg-stone-50/80 p-3">
      <p className="text-xs font-semibold text-stone-700 uppercase tracking-wide mb-2">{title}</p>
      <ul className="text-xs text-stone-600 space-y-0.5 max-h-32 overflow-y-auto">
        {entries.map(([k, v]) => (
          <li key={k}>
            <span className="font-mono text-stone-800">{k || '<empty>'}</span>: {v}
          </li>
        ))}
      </ul>
    </div>
  );
}

function UnmappedList({ title, items }: { title: string; items: string[] }) {
  if (!items?.length) {
    return (
      <p className="text-xs text-emerald-800 bg-emerald-50 border border-emerald-200 rounded-md px-2 py-1.5">
        {title}: none
      </p>
    );
  }
  return (
    <div>
      <p className="text-xs font-semibold text-amber-900 mb-1">{title}</p>
      <ul className="text-xs text-amber-950/90 list-disc list-inside space-y-0.5">
        {items.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ul>
    </div>
  );
}

const PastPatchesWorkspace = () => {
  const folderInputRef = useRef<HTMLInputElement>(null);
  const [coldFile, setColdFile] = useState<File | null>(null);
  const [crmFile, setCrmFile] = useState<File | null>(null);
  const [closingsFile, setClosingsFile] = useState<File | null>(null);
  const [smsFiles, setSmsFiles] = useState<File[]>([]);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [jobId, setJobId] = useState<string | null>(null);
  const [preview, setPreview] = useState<PatchUploadResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [allowUnmapped, setAllowUnmapped] = useState(false);
  const [exporting, setExporting] = useState(false);

  const mergeSms = useCallback((incoming: File[]) => {
    const csvs = incoming.filter((f) => f.name.toLowerCase().endsWith('.csv'));
    setSmsFiles((prev) => {
      const map = new Map<string, File>();
      prev.forEach((f) => map.set(f.name, f));
      csvs.forEach((f) => map.set(f.name, f));
      return Array.from(map.values());
    });
  }, []);

  const onDropCold = useCallback((files: File[]) => {
    if (files[0]) setColdFile(files[0]);
  }, []);
  const onDropCrm = useCallback((files: File[]) => {
    if (files[0]) setCrmFile(files[0]);
  }, []);
  const onDropClosings = useCallback((files: File[]) => {
    if (files[0]) setClosingsFile(files[0]);
  }, []);

  const coldDrop = useDropzone({
    onDrop: onDropCold,
    accept: { 'text/csv': ['.csv'] },
    multiple: false,
  });
  const crmDrop = useDropzone({
    onDrop: onDropCrm,
    accept: { 'text/csv': ['.csv'] },
    multiple: false,
  });
  const closingsDrop = useDropzone({
    onDrop: onDropClosings,
    accept: {
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
    },
    multiple: false,
  });
  const smsDrop = useDropzone({
    onDrop: mergeSms,
    accept: { 'text/csv': ['.csv'] },
    multiple: true,
  });

  const handleFolderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const list = Array.from(e.target.files || []).filter((f) =>
      f.name.toLowerCase().endsWith('.csv')
    );
    mergeSms(list);
    e.target.value = '';
  };

  const canPreview = coldFile && crmFile && closingsFile && smsFiles.length > 0;

  const runPreview = async () => {
    if (!canPreview) return;
    setLoading(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append('cold_csv', coldFile);
      fd.append('crm_csv', crmFile);
      fd.append('closings_xlsx', closingsFile);
      smsFiles.forEach((f) => fd.append('sms_files', f, f.name));
      const data = await uploadPatches(fd);
      setJobId(data.job_id);
      setPreview(data);
      setStep(2);
    } catch (err: unknown) {
      setError(getAxiosErrorMessage(err, 'Preview failed'));
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadAll = async () => {
    if (!jobId) return;
    setExporting(true);
    setError(null);
    try {
      const blob = await downloadPatchExport(jobId, 'all', allowUnmapped);
      downloadBlob(blob, `reisift_import_${jobId}.zip`);
      setStep(3);
    } catch (err: unknown) {
      setError(getAxiosErrorMessage(err, 'Export failed'));
    } finally {
      setExporting(false);
    }
  };

  const handleDownloadSingle = async (kind: 'property' | 'phone' | 'sf' | 'closings') => {
    if (!jobId) return;
    setExporting(true);
    setError(null);
    try {
      const blob = await downloadPatchExport(jobId, kind, allowUnmapped);
      const names: Record<string, string> = {
        property: 'property_status_updates.csv',
        phone: 'phone_status_tags_updates.csv',
        sf: 'salesforce_status_tags.csv',
        closings: 'closings_status_tags.csv',
      };
      downloadBlob(blob, names[kind]);
    } catch (err: unknown) {
      setError(getAxiosErrorMessage(err, 'Download failed'));
    } finally {
      setExporting(false);
    }
  };

  const resetWorkspace = async () => {
    if (jobId) {
      try {
        await deletePatchJob(jobId);
      } catch {
        /* ignore */
      }
    }
    setColdFile(null);
    setCrmFile(null);
    setClosingsFile(null);
    setSmsFiles([]);
    setJobId(null);
    setPreview(null);
    setStep(1);
    setError(null);
    setAllowUnmapped(false);
  };

  const m = preview?.metrics;

  return (
    <div className="w-full rounded-2xl border border-amber-200/90 bg-white ring-1 ring-amber-100/40 shadow-sm p-6 sm:p-8">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h2 className="text-2xl font-bold text-amber-950 tracking-tight">Past patches — REISift imports</h2>
          <p className="text-sm text-stone-600 mt-1 max-w-2xl">
            Step 1: attach your four sources. Step 2: review mapping coverage. Step 3: download CSVs
            (or a zip) for bulk import into REISift.
          </p>
        </div>
        <div className="flex gap-2 text-xs font-semibold">
          <span
            className={`px-2 py-1 rounded-md ${step >= 1 ? 'bg-amber-200 text-amber-950' : 'bg-stone-100 text-stone-500'}`}
          >
            1 Inputs
          </span>
          <span
            className={`px-2 py-1 rounded-md ${step >= 2 ? 'bg-amber-200 text-amber-950' : 'bg-stone-100 text-stone-500'}`}
          >
            2 Preview
          </span>
          <span
            className={`px-2 py-1 rounded-md ${step >= 3 ? 'bg-amber-200 text-amber-950' : 'bg-stone-100 text-stone-500'}`}
          >
            3 Export
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <div>
          <label className="block text-sm font-semibold text-stone-700 mb-2">Cold calling CSV</label>
          <div
            {...coldDrop.getRootProps()}
            className={`border-2 border-dashed rounded-xl p-5 text-center cursor-pointer transition-colors ${
              coldDrop.isDragActive ? 'border-amber-600 bg-amber-50' : 'border-stone-200 hover:border-amber-400'
            }`}
          >
            <input {...coldDrop.getInputProps()} />
            {coldFile ? (
              <p className="text-sm text-emerald-700 font-medium">✓ {coldFile.name}</p>
            ) : (
              <p className="text-sm text-stone-600">Drop or click — Log Type + Phone + Address…</p>
            )}
          </div>
        </div>
        <div>
          <label className="block text-sm font-semibold text-stone-700 mb-2">CRM updates CSV</label>
          <div
            {...crmDrop.getRootProps()}
            className={`border-2 border-dashed rounded-xl p-5 text-center cursor-pointer transition-colors ${
              crmDrop.isDragActive ? 'border-amber-600 bg-amber-50' : 'border-stone-200 hover:border-amber-400'
            }`}
          >
            <input {...crmDrop.getInputProps()} />
            {crmFile ? (
              <p className="text-sm text-emerald-700 font-medium">✓ {crmFile.name}</p>
            ) : (
              <p className="text-sm text-stone-600">Drop or click — needs leadstatus</p>
            )}
          </div>
        </div>
        <div>
          <label className="block text-sm font-semibold text-stone-700 mb-2">Closings Excel (.xlsx)</label>
          <div
            {...closingsDrop.getRootProps()}
            className={`border-2 border-dashed rounded-xl p-5 text-center cursor-pointer transition-colors ${
              closingsDrop.isDragActive ? 'border-amber-600 bg-amber-50' : 'border-stone-200 hover:border-amber-400'
            }`}
          >
            <input {...closingsDrop.getInputProps()} />
            {closingsFile ? (
              <p className="text-sm text-emerald-700 font-medium">✓ {closingsFile.name}</p>
            ) : (
              <p className="text-sm text-stone-600">Drop or click — Date Closed + Address</p>
            )}
          </div>
        </div>
        <div>
          <label className="block text-sm font-semibold text-stone-700 mb-2">SMS logs (CSV files)</label>
          <div
            {...smsDrop.getRootProps()}
            className={`border-2 border-dashed rounded-xl p-5 text-center cursor-pointer transition-colors mb-2 ${
              smsDrop.isDragActive ? 'border-amber-600 bg-amber-50' : 'border-stone-200 hover:border-amber-400'
            }`}
          >
            <input {...smsDrop.getInputProps()} />
            <p className="text-sm text-stone-600">
              Drop many CSVs here, or use a folder picker (filename = status bucket).
            </p>
            {smsFiles.length > 0 && (
              <p className="text-xs text-emerald-700 font-medium mt-2">{smsFiles.length} file(s) selected</p>
            )}
          </div>
          <input
            ref={folderInputRef}
            type="file"
            multiple
            {...({ webkitdirectory: '' } as Record<string, string>)}
            className="hidden"
            onChange={handleFolderChange}
          />
          <button
            type="button"
            onClick={() => folderInputRef.current?.click()}
            className="text-sm font-medium text-navy underline underline-offset-2"
          >
            Choose folder…
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-3 mb-6">
        <button
          type="button"
          disabled={!canPreview || loading}
          onClick={runPreview}
          className="px-5 py-2.5 rounded-xl font-semibold text-white bg-amber-800 hover:bg-amber-900 disabled:bg-stone-300 disabled:text-stone-500"
        >
          {loading ? 'Running preview…' : 'Run preview'}
        </button>
        <button
          type="button"
          onClick={resetWorkspace}
          className="px-4 py-2.5 rounded-xl text-sm font-medium border border-stone-300 text-stone-700 hover:bg-stone-50"
        >
          Reset
        </button>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-sm text-red-800">{error}</div>
      )}

      {preview && m && step >= 2 && (
        <div className="space-y-6 border-t border-amber-200/60 pt-6">
          <h3 className="text-lg font-bold text-amber-950">Preview</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <CountBlock title="Cold — input statuses" counts={m.cold_input_counts} />
            <CountBlock title="Cold — mapped property" counts={m.cold_output_counts} />
            <CountBlock title="SMS — input (filename)" counts={m.sms_input_counts} />
            <CountBlock title="SMS — phone status" counts={m.sms_output_counts} />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
            <div className="rounded-lg border border-stone-200 p-3 bg-white">
              <p className="font-semibold text-stone-800 mb-2">CRM overrides</p>
              <ul className="text-xs text-stone-600 space-y-1">
                <li>CRM rows: {m.crm_total_rows ?? 0}</li>
                <li>Matched by phone: {m.crm_matched_by_phone ?? 0}</li>
                <li>Matched by address: {m.crm_matched_by_address ?? 0}</li>
                <li>Cold overrides: {m.cold_overrides_applied ?? 0}</li>
                <li>SMS overrides: {m.sms_overrides_applied ?? 0}</li>
                <li>Unmatched CRM rows: {m.crm_unmatched_rows ?? 0}</li>
              </ul>
            </div>
            <div className="rounded-lg border border-stone-200 p-3 bg-white">
              <p className="font-semibold text-stone-800 mb-2">Salesforce-style tags</p>
              <ul className="text-xs text-stone-600 space-y-1">
                <li>Tags created: {m.sf_tags_created_total ?? 0}</li>
                <li>STATUS tags: {m.sf_tags_created_status ?? 0}</li>
                <li>UPDATED tags: {m.sf_tags_created_updated ?? 0}</li>
                <li>Skipped (bad updated_on): {m.sf_skipped_updated_on ?? 0}</li>
                <li>Skipped (bad lead date): {m.sf_skipped_created_date ?? 0}</li>
              </ul>
            </div>
            <div className="rounded-lg border border-stone-200 p-3 bg-white">
              <p className="font-semibold text-stone-800 mb-2">Closings tags</p>
              <p className="text-xs text-stone-600">Rows with (CLOSED) 8020 tag: {m.closings_rows ?? 0}</p>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <UnmappedList title="Unmapped cold statuses" items={m.cold_unmapped || []} />
            <UnmappedList title="Unmapped SMS statuses" items={m.sms_unmapped || []} />
            <UnmappedList title="Unmapped CRM statuses" items={m.crm_unmapped || []} />
          </div>

          <h4 className="text-sm font-bold text-stone-800">Sample rows</h4>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 text-xs">
            {(['cold_calling', 'sms', 'salesforce_tags', 'closings_tags'] as const).map((key) => (
              <div key={key} className="rounded-lg border border-stone-200 overflow-hidden">
                <div className="bg-stone-100 px-2 py-1 font-semibold text-stone-700">{key}</div>
                <pre className="p-2 max-h-40 overflow-auto text-stone-600 whitespace-pre-wrap">
                  {JSON.stringify(preview.samples[key]?.slice(0, 3) ?? [], null, 2)}
                </pre>
              </div>
            ))}
          </div>

          <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 space-y-4">
            <label className="flex items-center gap-2 text-sm text-amber-950 cursor-pointer">
              <input
                type="checkbox"
                checked={allowUnmapped}
                onChange={(e) => setAllowUnmapped(e.target.checked)}
                className="rounded border-amber-400"
              />
              <span>
                Allow export with unmapped statuses (otherwise fix mappings or leave unchecked)
              </span>
            </label>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={exporting}
                onClick={handleDownloadAll}
                className="px-5 py-2.5 rounded-xl font-semibold text-white bg-navy hover:bg-navy/90 disabled:opacity-50"
              >
                {exporting ? 'Preparing…' : 'Download REISift bundle (.zip)'}
              </button>
              <button
                type="button"
                disabled={exporting}
                onClick={() => handleDownloadSingle('property')}
                className="px-3 py-2 rounded-lg text-xs font-medium border border-stone-300 bg-white"
              >
                property_status…
              </button>
              <button
                type="button"
                disabled={exporting}
                onClick={() => handleDownloadSingle('phone')}
                className="px-3 py-2 rounded-lg text-xs font-medium border border-stone-300 bg-white"
              >
                phone_status…
              </button>
              <button
                type="button"
                disabled={exporting}
                onClick={() => handleDownloadSingle('sf')}
                className="px-3 py-2 rounded-lg text-xs font-medium border border-stone-300 bg-white"
              >
                salesforce_status…
              </button>
              <button
                type="button"
                disabled={exporting}
                onClick={() => handleDownloadSingle('closings')}
                className="px-3 py-2 rounded-lg text-xs font-medium border border-stone-300 bg-white"
              >
                closings_status…
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default PastPatchesWorkspace;
