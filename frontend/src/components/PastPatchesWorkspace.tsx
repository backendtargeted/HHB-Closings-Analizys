import { useRef, useState } from 'react';
import { downloadPatchExport, getAxiosErrorMessage, uploadMonthlyPatches } from '../services/api';
import type { PatchUploadResponse } from '../types/patches';
import LegacyPastPatchesWorkspace from './LegacyPastPatchesWorkspace';

type ExportKind = 'all' | 'property' | 'phone' | 'sf' | 'closings' | 'marketing' | 'review';
const exportNames: Record<ExportKind, string> = {
  all: 'reisift_monthly_bundle.zip', property: 'property_status_updates.csv',
  phone: 'phone_status_tags_updates.csv', sf: 'salesforce_status_tags.csv',
  closings: 'closings_status_tags.csv', marketing: 'marketing_activity_tags.csv', review: 'ingestion_review.csv',
};
const readable = (value: string) => value.replace(/_/g, ' ');
const prettyValue = (value: unknown) => value == null || value === '' ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value);

function SampleTable({ title, rows }: { title: string; rows?: Record<string, unknown>[] }) {
  if (!rows?.length) return null;
  const preferred = ['address', 'city', 'phone', 'tag', 'salesforce_tag', 'status', 'phone_status', 'phone_tag', 'event_date', 'event_month', 'date_source', 'source_status', 'reason', 'source_file', 'source_row', 'source_row_id'];
  const columns = preferred.filter(column => rows.some(row => column in row && row[column] !== ''))
    .filter(column => column !== 'salesforce_tag' || !rows.some(row => 'tag' in row));
  return <div className="overflow-hidden rounded-lg border border-stone-200">
    <h4 className="bg-stone-50 px-3 py-2 text-sm font-semibold text-stone-800">{title} <span className="font-normal text-stone-500">· sample</span></h4>
    <div className="max-h-72 overflow-auto"><table className="w-full text-left text-xs">
      <thead className="sticky top-0 bg-stone-100"><tr>{columns.map((column) => <th key={column} className="px-3 py-2 whitespace-nowrap font-semibold capitalize">{readable(column)}</th>)}</tr></thead>
      <tbody>{rows.map((row, index) => <tr key={index} className="border-t border-stone-100">{columns.map((column) => <td key={column} className="min-w-32 max-w-lg break-words px-3 py-2">{prettyValue(row[column])}</td>)}</tr>)}</tbody>
    </table></div>
  </div>;
}

function MonthlyPatchesWorkspace({ onBusyChange }: { onBusyChange: (busy: boolean) => void }) {
  const [reportMonth, setReportMonth] = useState('');
  const [coldFile, setColdFile] = useState<File | null>(null);
  const [smsFiles, setSmsFiles] = useState<File[]>([]);
  const [qlFile, setQlFile] = useState<File | null>(null);
  const [oppsFile, setOppsFile] = useState<File | null>(null);
  const [transactionsFile, setTransactionsFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PatchUploadResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState('');
  const [uploadKey, setUploadKey] = useState(0);
  const folderInput = useRef<HTMLInputElement>(null);
  const sfCount = [qlFile, oppsFile, transactionsFile].filter(Boolean).length;
  const completeSf = sfCount === 3;
  const validMonth = /^\d{4}-(0[1-9]|1[0-2])$/.test(reportMonth);
  const hasSource = Boolean(coldFile || smsFiles.length || completeSf);
  const busy = loading || exporting;
  const canPreview = validMonth && hasSource && (sfCount === 0 || completeSf);
  const invalidate = () => { setPreview(null); setError(''); };
  const addSms = (files: FileList | null) => {
    if (!files) return;
    const incoming = Array.from(files).filter((file) => file.name.toLowerCase().endsWith('.csv'));
    setSmsFiles((previous) => {
      const byName = new Map(previous.map((file) => [file.name, file]));
      incoming.forEach((file) => byName.set(file.name, file));
      return [...byName.values()];
    });
    invalidate();
  };
  const runPreview = async () => {
    if (!canPreview) return;
    setLoading(true); onBusyChange(true); setError(''); setPreview(null);
    try {
      const form = new FormData();
      form.append('report_month', reportMonth);
      if (coldFile) form.append('cold_csv', coldFile);
      smsFiles.forEach((file) => form.append('sms_files', file, file.name));
      if (qlFile) form.append('qualified_leads', qlFile);
      if (oppsFile) form.append('opportunities', oppsFile);
      if (transactionsFile) form.append('transactions', transactionsFile);
      setPreview(await uploadMonthlyPatches(form));
    } catch (err) { setError(getAxiosErrorMessage(err, 'Monthly preview failed')); }
    finally { setLoading(false); onBusyChange(false); }
  };
  const download = async (kind: ExportKind) => {
    if (!preview) return;
    setExporting(true); onBusyChange(true); setError('');
    try {
      const blob = await downloadPatchExport(preview.job_id, kind, false);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${preview.monthly?.report_month || reportMonth}_${exportNames[kind]}`;
      link.click(); URL.revokeObjectURL(url);
    } catch (err) { setError(getAxiosErrorMessage(err, 'Download failed')); }
    finally { setExporting(false); onBusyChange(false); }
  };
  const reset = () => {
    setReportMonth(''); setColdFile(null); setSmsFiles([]); setQlFile(null); setOppsFile(null); setTransactionsFile(null);
    setUploadKey((value) => value + 1); invalidate();
  };
  const monthly = preview?.monthly;
  const unmapped = preview ? [
    ...preview.metrics.cold_unmapped.map((value) => `Calling: ${value}`),
    ...preview.metrics.sms_unmapped.map((value) => `SMS: ${value}`),
    ...preview.metrics.crm_unmapped.map((value) => `Salesforce: ${value}`),
  ] : [];

  return <div className="space-y-6">
    <div><h2 className="text-2xl font-bold text-amber-950">Gate 1 — Monthly ingestion</h2>
      <p className="mt-2 max-w-3xl text-sm text-stone-600">Choose a reporting month, then upload calling/SMS activity, Salesforce reports, or both. Preview the resulting tags and review excluded rows before downloading REISift import files. No legacy CRM export is required.</p>
    </div>
    <fieldset disabled={busy} className="space-y-5">
      <label className="block max-w-xs text-sm font-semibold text-stone-800">Reporting month — required
        <input aria-label="Reporting month" type="month" value={reportMonth} onInput={(event) => { setReportMonth(event.currentTarget.value); invalidate(); }} onChange={(event) => { setReportMonth(event.target.value); invalidate(); }} className="mt-2 block w-full rounded-lg border border-stone-300 bg-white px-3 py-2 font-normal" />
      </label>
      <p className="text-xs text-stone-600">Event dates determine the month. Calling/SMS rows without a date use the selected month and are counted for review; invalid dates are excluded. Salesforce events require dates and never use a month fallback.</p>
      <div key={uploadKey} className="grid gap-5 lg:grid-cols-2">
        <section className="rounded-xl border border-stone-200 p-4 space-y-4">
          <div><h3 className="font-semibold text-stone-800">Calling and SMS</h3><p className="mt-1 text-xs text-stone-500">Upload either source or both. You can run these independently of Salesforce.</p></div>
          <label className="block text-sm font-medium text-stone-700">Cold calling (.csv)
            <input aria-label="Cold calling CSV" type="file" accept=".csv" onChange={(event) => { setColdFile(event.target.files?.[0] ?? null); invalidate(); }} className="mt-2 block w-full text-xs" />
          </label>
          {coldFile && <div className="text-xs text-stone-600"><p className="mb-1 break-all">Selected: {coldFile.name}</p><button type="button" className="underline" onClick={() => { setColdFile(null); setUploadKey((key) => key + 1); invalidate(); }}>Remove calling file</button></div>}
          <label className="block text-sm font-medium text-stone-700">SMS labels or status files (.csv, multiple)
            <input aria-label="SMS CSV files" type="file" multiple accept=".csv" onChange={(event) => { addSms(event.target.files); event.target.value = ''; }} className="mt-2 block w-full text-xs" />
          </label>
          <p className="text-xs text-stone-500">Labels on each row take priority. Older exports without a labels column use their status filenames. Selecting the same filename replaces its previous copy.</p>
          <input ref={folderInput} aria-label="SMS folder" type="file" multiple {...({ webkitdirectory: '' } as Record<string, string>)} className="hidden" onChange={(event) => { addSms(event.target.files); event.target.value = ''; }} />
          <button type="button" onClick={() => folderInput.current?.click()} className="text-xs font-semibold text-amber-900 underline">Choose SMS folder</button>
          {!!smsFiles.length && <ul className="max-h-36 overflow-auto space-y-1 text-xs text-stone-600">{smsFiles.map((file) => <li key={file.name} className="flex items-center justify-between gap-2"><span className="break-all">{file.name}</span><button aria-label={`Remove SMS file ${file.name}`} type="button" onClick={() => { setSmsFiles((files) => files.filter((item) => item.name !== file.name)); invalidate(); }} className="font-semibold text-stone-700">Remove</button></li>)}</ul>}
        </section>
        <section className="rounded-xl border border-stone-200 p-4 space-y-4">
          <div><h3 className="font-semibold text-stone-800">Salesforce</h3><p className="mt-1 text-xs text-stone-500">Upload all three report roles together, or leave this section empty. Salesforce can run without calling or SMS.</p></div>
          {([
            ['Qualified Leads', qlFile, setQlFile], ['Opportunities', oppsFile, setOppsFile], ['Transactions', transactionsFile, setTransactionsFile],
          ] as const).map(([label, file, setFile]) => <label key={label} className="block text-sm font-medium text-stone-700">{label} (.xlsx / .csv)
            <input aria-label={`Salesforce ${label} report`} type="file" accept=".xlsx,.csv" onChange={(event) => { setFile(event.target.files?.[0] ?? null); invalidate(); }} className="mt-2 block w-full text-xs" />
            {file && <span className="mt-1 block text-xs text-stone-500 break-all">Selected: {file.name}</span>}
          </label>)}
          {sfCount > 0 && <button type="button" onClick={() => { setQlFile(null); setOppsFile(null); setTransactionsFile(null); setUploadKey((key) => key + 1); invalidate(); }} className="text-xs text-stone-600 underline">Remove Salesforce reports</button>}
          {sfCount > 0 && !completeSf && <p role="status" className="text-xs text-amber-900">{sfCount} of 3 selected. Add all three Salesforce reports to preview, or remove them to run calling/SMS only.</p>}
        </section>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" disabled={!canPreview || busy} onClick={runPreview} className="rounded-lg bg-amber-800 px-5 py-2.5 text-sm font-semibold text-white hover:bg-amber-900 disabled:opacity-40">{loading ? 'Preparing monthly preview…' : 'Preview monthly tags'}</button>
        <button type="button" onClick={reset} className="rounded-lg border border-stone-300 px-4 py-2 text-sm text-stone-700">New monthly run</button>
        {!reportMonth && <p className="text-xs text-stone-500">Select a month to begin.</p>}
        {validMonth && !hasSource && sfCount === 0 && <p className="text-xs text-stone-500">Add at least one source.</p>}
      </div>
    </fieldset>
    {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    {preview && <section className="space-y-5 border-t border-amber-200 pt-5">
      <div><h3 className="text-lg font-bold text-amber-950">Preview · {monthly?.report_month || reportMonth}</h3><p className="mt-1 text-xs text-stone-500">Files are prepared for download. Nothing has been imported into REISift.</p></div>
      {!!monthly?.warnings?.length && <ul className="rounded-lg bg-amber-50 p-4 text-xs text-amber-950 space-y-1">{monthly.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
      {!!monthly?.sources?.length && <div className="overflow-x-auto rounded-lg border border-stone-200"><table className="w-full text-left text-xs"><caption className="p-3 text-left text-sm font-semibold text-stone-800">Source and date review</caption>
        <thead className="bg-stone-50"><tr>{['Source', 'Input rows', 'Included', 'Outside month', 'Missing date', 'Invalid date', 'Duplicates', 'Unusable identity', 'Unverified closing'].map((label) => <th key={label} className="px-3 py-2 whitespace-nowrap">{label}</th>)}</tr></thead>
        <tbody>{monthly.sources.map((source, index) => <tr key={`${source.source}-${index}`} className="border-t border-stone-100"><td className="px-3 py-2 capitalize">{readable(source.source)}</td>{[source.input_rows, source.included_rows, source.outside_month_rows, source.missing_date_rows, source.invalid_date_rows, source.duplicate_rows, source.unusable_identity_rows, source.unverified_closing_rows].map((value, i) => <td key={i} className="px-3 py-2">{value == null ? '—' : value.toLocaleString()}</td>)}</tr>)}</tbody>
      </table><p className="px-3 pb-3 text-xs text-stone-500">Missing campaign dates may be included using the selected month; missing Salesforce dates are excluded. Review counts can overlap and do not necessarily sum to input rows.</p></div>}
      {!!monthly?.tag_counts && <div><h4 className="mb-2 text-sm font-semibold text-stone-800">Generated tags</h4>{Object.keys(monthly.tag_counts).length ? <ul className="grid gap-2 sm:grid-cols-2">{Object.entries(monthly.tag_counts).map(([tag, count]) => <li key={tag} className="flex justify-between gap-3 rounded-lg border border-stone-200 p-3 text-xs"><span className="break-words font-mono text-stone-700">{tag}</span><span className="font-semibold text-stone-900">{count.toLocaleString()}</span></li>)}</ul> : <p className="text-xs text-stone-500">No tags generated for this month.</p>}</div>}
      {!!unmapped.length && <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-950"><h4 className="font-semibold mb-1">Unmapped statuses</h4><p className="mb-2">Omitted from status updates and retained in the review CSV. Valid marketing tags remain available for export.</p><ul className="list-disc pl-4">{unmapped.map((status, index) => <li key={index}>{status}</li>)}</ul></div>}
      <div className="space-y-4">
        <SampleTable title="Marketing activity tags" rows={preview.samples.marketing_tags} />
        <SampleTable title="Salesforce lifecycle tags" rows={preview.samples.salesforce_tags} />
        <SampleTable title="Closing tags" rows={preview.samples.closings_tags} />
        <SampleTable title="Calling property status updates" rows={preview.samples.cold_calling} />
        <SampleTable title="SMS phone status updates" rows={preview.samples.sms} />
        <SampleTable title="Rows requiring review" rows={preview.samples.review_rows} />
      </div>
      <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-4 space-y-3">
        <p className="text-xs text-amber-950">For historical backfills, import dated tags. Importing status snapshots may overwrite a property's or phone's current REISift status.</p>
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={busy} onClick={() => download('all')} className="rounded-lg bg-amber-800 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">{exporting ? 'Preparing download…' : `Download ${monthly?.report_month || reportMonth} bundle (.zip)`}</button>
          {([['marketing', 'Marketing tags'], ['sf', 'Salesforce tags'], ['property', 'Property updates'], ['phone', 'Phone updates'], ['review', 'Review CSV']] as const).filter(([kind]) => monthly?.available_exports.includes(exportNames[kind])).map(([kind, label]) => <button key={kind} type="button" disabled={busy} onClick={() => download(kind)} className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs font-medium text-stone-700 disabled:opacity-40">{label}</button>)}
        </div>
      </div>
    </section>}
  </div>;
}

export default function PastPatchesWorkspace() {
  const [mode, setMode] = useState<'monthly' | 'legacy'>('monthly');
  const [busy, setBusy] = useState(false);
  return <div className="rounded-2xl border border-amber-200 bg-white p-5 shadow-sm sm:p-8">
    <div className="mb-6 flex flex-wrap gap-2" role="group" aria-label="Gate 1 workflow">
      {(['monthly', 'legacy'] as const).map((value) => <button key={value} type="button" disabled={busy} aria-pressed={mode === value} onClick={() => setMode(value)} className={`rounded-lg px-3 py-2 text-sm font-semibold disabled:opacity-40 ${mode === value ? 'bg-amber-100 text-amber-950' : 'text-stone-500 hover:bg-stone-50'}`}>{value === 'monthly' ? 'Monthly reports' : 'Legacy CRM workflow'}</button>)}
    </div>
    {mode === 'monthly' ? <MonthlyPatchesWorkspace onBusyChange={setBusy} /> : <LegacyPastPatchesWorkspace />}
  </div>;
}
