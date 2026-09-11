import axios from 'axios';
import type {
  AnalysisCompleteResponse,
  AnalysisStatus,
  UploadCapabilitiesResponse,
  ResumableUploadInitResponse,
  ResumableUploadStatusResponse,
  ResumableUploadCompleteResponse,
  ResumableUploadKind,
  StartAnalysisParams,
} from '../types/analysis';
import type { PatchUploadResponse } from '../types/patches';
import type { QualifiedLeadsAnalyzeResponse } from '../types/qualifiedLeads';
import type {
  MonthlyConsolidatedAnalyzeResponse,
  MonthlyConsolidatedCompletedResponse,
  MonthlyConsolidatedJobStatus,
} from '../types/monthlyConsolidated';
import { asMonthlyConsolidatedCompleted } from '../types/monthlyConsolidated';
import type { SavedReportsListResponse } from '../types/reports';
import type {
  MarketingRampAnalyzeResponse,
  MarketingRampCompletedResponse,
  MarketingRampJobStatus,
} from '../types/marketingRamp';
import { asMarketingRampCompleted } from '../types/marketingRamp';
import type {
  WebLeadsAnalyzeResponse,
  WebLeadsCompletedResponse,
  WebLeadsJobStatus,
} from '../types/webLeads';
import { asWebLeadsCompleted } from '../types/webLeads';
import type {
  ProbateAnalyzeResponse,
  ProbateCompletedResponse,
  ProbateJobStatus,
} from '../types/probate';
import { asProbateCompleted } from '../types/probate';
import type {
  CourtAlertsAnalyzeResponse,
  CourtAlertsCompletedResponse,
  CourtAlertsJobStatus,
} from '../types/courtAlerts';
import { asCourtAlertsCompleted } from '../types/courtAlerts';
import type {
  SoldPropertiesAnalyzeResponse,
  SoldPropertiesCompletedResponse,
  SoldPropertiesJobStatus,
} from '../types/soldProperties';
import { asSoldPropertiesCompleted } from '../types/soldProperties';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

/** User-facing message when nginx/Flask rejects body size or returns an HTML error page. */
const UPLOAD_TOO_LARGE_MSG =
  'Upload too large for the server limit. Try fewer/smaller files or contact admin.';

const GATEWAY_TIMEOUT_MSG =
  'The server stopped responding (502). Wait a moment and try again — large files upload and analyze in the background.';

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const CHUNK_UPLOAD_TIMEOUT_MS = 10 * 60 * 1000;
const CHUNK_UPLOAD_MAX_ATTEMPTS = 8;

function isRetryableUploadError(err: unknown): boolean {
  if (!axios.isAxiosError(err)) {
    return false;
  }
  const status = err.response?.status;
  if (status === 502 || status === 504 || status === 503) {
    return true;
  }
  const code = err.code;
  return code === 'ECONNABORTED' || code === 'ERR_NETWORK' || code === 'ETIMEDOUT';
}

async function waitForResumableUploadComplete(
  uploadId: string,
  onProgress?: (message: string) => void
): Promise<string> {
  const deadline = Date.now() + 30 * 60 * 1000;
  while (Date.now() < deadline) {
    const status = await getResumableUploadStatus(uploadId);
    if (status.status === 'completed' && status.final_path) {
      return status.final_path;
    }
    if (status.status === 'failed') {
      throw new Error(status.finalize_error || 'Upload assembly failed');
    }
    onProgress?.(
      status.status === 'assembling' ? 'Assembling uploaded file…' : 'Waiting for upload…'
    );
    await sleep(1000);
  }
  throw new Error('Upload assembly timed out');
}

function pathFromCompleteResponse(
  kind: ResumableUploadKind,
  finalized: ResumableUploadCompleteResponse
): string | undefined {
  if (kind === 'csv') return finalized.csv_path ?? finalized.path;
  if (kind === 'closings') return finalized.closings_path ?? finalized.excel_path ?? finalized.path;
  if (kind === 'reisift') return finalized.reisift_path ?? finalized.path;
  if (kind === 'qualified_leads') return finalized.qualified_leads_path ?? finalized.path;
  return finalized.path;
}

async function pollMonthlyConsolidatedJob(
  jobId: string,
  onProgress?: (pct: number, message: string) => void
): Promise<MonthlyConsolidatedCompletedResponse> {
  const deadline = Date.now() + 30 * 60 * 1000;
  while (Date.now() < deadline) {
    const status = await getMonthlyConsolidatedJobStatus(jobId);
    const serverPct = status.progress ?? 0;
    const uiPct =
      serverPct >= 10 ? 90 + Math.round(((serverPct - 10) / 80) * 9) : 90;
    onProgress?.(Math.min(99, uiPct), status.message);
    if (status.status === 'completed') {
      return asMonthlyConsolidatedCompleted(await getMonthlyConsolidatedJob(jobId));
    }
    if (status.status === 'failed') {
      throw new Error(status.message || 'Analysis failed');
    }
    await sleep(1000);
  }
  throw new Error('Analysis timed out after 30 minutes');
}

export function getAxiosErrorMessage(err: unknown, fallback: string): string {
  if (!axios.isAxiosError(err)) {
    if (err instanceof Error) return err.message;
    return fallback;
  }
  const status = err.response?.status;
  if (status === 502 || status === 504) {
    return GATEWAY_TIMEOUT_MSG;
  }
  const d = err.response?.data;
  if (d && typeof d === 'object' && 'detail' in d) {
    return String((d as { detail: string }).detail);
  }
  if (typeof d === 'string') {
    const trimmed = d.trimStart();
    if (status === 413 || trimmed.startsWith('<')) {
      return UPLOAD_TOO_LARGE_MSG;
    }
    return d;
  }
  if (status === 413) {
    return UPLOAD_TOO_LARGE_MSG;
  }
  if (err.message) {
    return err.message;
  }
  return fallback;
}

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const getUploadCapabilities = async (): Promise<UploadCapabilitiesResponse> => {
  const response = await api.get<UploadCapabilitiesResponse>('/upload/capabilities');
  return response.data;
};

export const initResumableUpload = async (
  kind: ResumableUploadKind,
  filename: string,
  totalSize: number,
  chunkSize: number
): Promise<ResumableUploadInitResponse> => {
  const response = await api.post<ResumableUploadInitResponse>('/upload/resumable/init', {
    kind,
    filename,
    total_size: totalSize,
    chunk_size: chunkSize,
  });
  return response.data;
};

export const getResumableUploadStatus = async (
  uploadId: string
): Promise<ResumableUploadStatusResponse> => {
  const response = await api.get<ResumableUploadStatusResponse>(`/upload/resumable/${uploadId}/status`);
  return response.data;
};

export async function uploadResumableChunk(
  uploadId: string,
  chunkIndex: number,
  chunkBlob: Blob
): Promise<void> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= CHUNK_UPLOAD_MAX_ATTEMPTS; attempt += 1) {
    try {
      await api.put(`/upload/resumable/${uploadId}/chunk/${chunkIndex}`, chunkBlob, {
        headers: { 'Content-Type': 'application/octet-stream' },
        timeout: CHUNK_UPLOAD_TIMEOUT_MS,
      });
      return;
    } catch (err) {
      lastError = err;
      if (!isRetryableUploadError(err) || attempt >= CHUNK_UPLOAD_MAX_ATTEMPTS) {
        throw err;
      }
      await sleep(Math.min(30_000, 1000 * 2 ** (attempt - 1)));
    }
  }
  throw lastError;
}

export const completeResumableUpload = async (
  uploadId: string
): Promise<ResumableUploadCompleteResponse> => {
  const response = await api.post<ResumableUploadCompleteResponse>(`/upload/resumable/${uploadId}/complete`);
  return response.data;
};

export const startAnalysis = async (
  params: StartAnalysisParams
): Promise<{ job_id: string; status: string; message: string }> => {
  const body: Record<string, string> = {};
  body.csv_path = params.csvPath;
  if (params.closingsPath) {
    body.closings_path = params.closingsPath;
  }
  const trimmed = params.asOf?.trim();
  if (trimmed) {
    body.as_of = trimmed;
  }
  const response = await api.post('/analyze', body);

  return response.data;
};

export const getAnalysisStatus = async (jobId: string): Promise<AnalysisStatus> => {
  const response = await api.get<AnalysisStatus>(`/analysis/${jobId}/status`);
  return response.data;
};

export const getAnalysisResults = async (
  jobId: string
): Promise<AnalysisCompleteResponse> => {
  const response = await api.get<AnalysisCompleteResponse>(`/analysis/${jobId}`);
  return response.data;
};

export const exportResults = async (
  jobId: string,
  format: 'excel' | 'csv' | 'json' = 'excel'
): Promise<Blob> => {
  const response = await api.get(`/analysis/${jobId}/export`, {
    params: { format },
    responseType: 'blob',
  });

  return response.data;
};

export const compareAnalyses = async (jobIds: string[]) => {
  const response = await api.post('/compare', { job_ids: jobIds });
  return response.data;
};

export const listAnalyses = async () => {
  const response = await api.get('/analyses');
  return response.data;
};

export const listReports = async (): Promise<SavedReportsListResponse> => {
  const response = await api.get<SavedReportsListResponse>('/reports');
  return response.data;
};

export const deleteAnalysis = async (jobId: string): Promise<void> => {
  await api.delete(`/analysis/${jobId}`);
};

export const uploadPatches = async (formData: FormData): Promise<PatchUploadResponse> => {
  const response = await api.post<PatchUploadResponse>('/patches/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

export const downloadPatchExport = async (
  jobId: string,
  file: 'all' | 'property' | 'phone' | 'sf' | 'closings',
  allowUnmapped: boolean
): Promise<Blob> => {
  const response = await api.get(`/patches/${jobId}/export`, {
    params: { file, allow_unmapped: allowUnmapped ? 'true' : 'false' },
    responseType: 'blob',
  });
  return response.data;
};

export const deletePatchJob = async (jobId: string): Promise<void> => {
  await api.delete(`/patches/${jobId}`);
};

export const analyzeQualifiedLeads = async (
  file: File,
  options: {
    useFullFileSpan: boolean;
    startDate?: string;
    endDate?: string;
  }
): Promise<QualifiedLeadsAnalyzeResponse> => {
  const form = new FormData();
  form.append('qualified_leads_file', file);
  form.append('use_full_file_span', options.useFullFileSpan ? 'true' : 'false');
  if (!options.useFullFileSpan) {
    if (options.startDate) form.append('start_date', options.startDate);
    if (options.endDate) form.append('end_date', options.endDate);
  }
  const response = await api.post<QualifiedLeadsAnalyzeResponse>(
    '/qualified-leads/analyze',
    form,
    { headers: { 'Content-Type': 'multipart/form-data' } }
  );
  return response.data;
};

export const getQualifiedLeadsJob = async (
  jobId: string
): Promise<QualifiedLeadsAnalyzeResponse> => {
  const response = await api.get<QualifiedLeadsAnalyzeResponse>(`/qualified-leads/${jobId}`);
  return response.data;
};

export const downloadQualifiedLeadsExport = async (jobId: string): Promise<Blob> => {
  const response = await api.get(`/qualified-leads/${jobId}/export`, {
    responseType: 'blob',
  });
  return response.data;
};

export const deleteQualifiedLeadsJob = async (jobId: string): Promise<void> => {
  await api.delete(`/qualified-leads/${jobId}`);
};

export async function uploadFileResumable(
  kind: ResumableUploadKind,
  file: File,
  onProgress?: (pct: number, message: string) => void
): Promise<string> {
  const caps = await getUploadCapabilities();
  if (caps.resumable_upload !== true) {
    throw new Error('Resumable uploads are not available. Check /api/upload/capabilities.');
  }
  const maxChunkBytes = caps.limits?.max_chunk_bytes ?? 2 * 1024 * 1024;
  const chunkSize = maxChunkBytes;
  const init = await initResumableUpload(kind, file.name, file.size, chunkSize);
  onProgress?.(0, `Uploading ${file.name}…`);

  const status = await getResumableUploadStatus(init.upload_id);
  const uploaded = new Set<number>(status.uploaded_chunks ?? []);
  for (let idx = 0; idx < init.total_chunks; idx += 1) {
    if (uploaded.has(idx)) {
      continue;
    }
    const start = idx * init.chunk_size;
    const end = Math.min(start + init.chunk_size, file.size);
    const chunk = file.slice(start, end);
    await uploadResumableChunk(init.upload_id, idx, chunk);
    uploaded.add(idx);
    const pct = Math.round((uploaded.size / init.total_chunks) * 100);
    onProgress?.(pct, `Uploading ${file.name}…`);
  }

  const completeResponse = await completeResumableUpload(init.upload_id);
  let filePath = pathFromCompleteResponse(kind, completeResponse);
  if (!filePath) {
    filePath = await waitForResumableUploadComplete(init.upload_id, (msg) =>
      onProgress?.(100, msg)
    );
  }
  return filePath;
}

const DIRECT_UPLOAD_TIMEOUT_MS = 30 * 60 * 1000;

function shouldFallbackToResumableUpload(err: unknown): boolean {
  if (!axios.isAxiosError(err)) {
    return false;
  }
  const status = err.response?.status;
  if (status === 413 || status === 502 || status === 503 || status === 504) {
    return true;
  }
  const code = err.code;
  return code === 'ECONNABORTED' || code === 'ERR_NETWORK' || code === 'ETIMEDOUT';
}

/** One multipart request: both files sent whole; backend saves and starts analysis. */
async function analyzeMonthlyConsolidatedDirect(
  reisiftFile: File,
  qualifiedLeadsFile: File,
  onProgress?: (pct: number, message: string) => void
): Promise<MonthlyConsolidatedCompletedResponse> {
  const form = new FormData();
  form.append('reisift_file', reisiftFile);
  form.append('qualified_leads_file', qualifiedLeadsFile);

  const totalBytes = reisiftFile.size + qualifiedLeadsFile.size;
  onProgress?.(0, 'Uploading report files…');

  const response = await api.post<{ job_id: string; status: string; message: string }>(
    '/monthly-consolidated/analyze',
    form,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: DIRECT_UPLOAD_TIMEOUT_MS,
      onUploadProgress: (evt) => {
        if (!evt.total && !totalBytes) {
          return;
        }
        const loaded = evt.loaded ?? 0;
        const total = evt.total && evt.total > 0 ? evt.total : totalBytes;
        const pct = Math.min(85, Math.round((loaded / total) * 85));
        onProgress?.(pct, 'Uploading report files…');
      },
    }
  );

  onProgress?.(88, 'Files received — analyzing…');
  const result = await pollMonthlyConsolidatedJob(response.data.job_id, onProgress);
  onProgress?.(100, 'Done');
  return result;
}

/** Fallback: split large files into binary chunks when the proxy drops a single long upload. */
async function analyzeMonthlyConsolidatedResumable(
  reisiftFile: File,
  qualifiedLeadsFile: File,
  onProgress?: (pct: number, message: string) => void
): Promise<MonthlyConsolidatedCompletedResponse> {
  onProgress?.(0, `Uploading ${reisiftFile.name} (chunked fallback)…`);
  const reisiftPath = await uploadFileResumable('reisift', reisiftFile, (pct, msg) => {
    onProgress?.(Math.round(pct * 0.45), msg);
  });
  onProgress?.(45, `Uploading ${qualifiedLeadsFile.name}…`);
  const qlPath = await uploadFileResumable('qualified_leads', qualifiedLeadsFile, (pct, msg) => {
    onProgress?.(45 + Math.round(pct * 0.45), msg);
  });
  onProgress?.(90, 'Starting analysis…');
  const started = await analyzeMonthlyConsolidatedFromPaths(reisiftPath, qlPath);
  const result = await pollMonthlyConsolidatedJob(started.job_id, onProgress);
  onProgress?.(100, 'Done');
  return result;
}

export const analyzeMonthlyConsolidated = async (
  reisiftFile: File,
  qualifiedLeadsFile: File,
  onProgress?: (pct: number, message: string) => void
): Promise<MonthlyConsolidatedCompletedResponse> => {
  try {
    return await analyzeMonthlyConsolidatedDirect(reisiftFile, qualifiedLeadsFile, onProgress);
  } catch (err) {
    if (!shouldFallbackToResumableUpload(err)) {
      throw err;
    }
    onProgress?.(
      0,
      'Direct upload interrupted — retrying in smaller pieces (proxy timeout)…'
    );
    return analyzeMonthlyConsolidatedResumable(reisiftFile, qualifiedLeadsFile, onProgress);
  }
};

export const analyzeMonthlyConsolidatedFromPaths = async (
  reisiftPath: string,
  qualifiedLeadsPath: string
): Promise<{ job_id: string; status: string; message: string }> => {
  const response = await api.post<{ job_id: string; status: string; message: string }>(
    '/monthly-consolidated/analyze',
    {
      reisift_path: reisiftPath,
      qualified_leads_path: qualifiedLeadsPath,
    }
  );
  return response.data;
};

export const getMonthlyConsolidatedJobStatus = async (
  jobId: string
): Promise<MonthlyConsolidatedJobStatus> => {
  const response = await api.get<MonthlyConsolidatedJobStatus>(
    `/monthly-consolidated/${jobId}/status`
  );
  return response.data;
};

export const getMonthlyConsolidatedJob = async (
  jobId: string
): Promise<MonthlyConsolidatedAnalyzeResponse> => {
  const response = await api.get<MonthlyConsolidatedAnalyzeResponse>(
    `/monthly-consolidated/${jobId}`
  );
  return response.data;
};

export const downloadMonthlyConsolidatedExport = async (jobId: string): Promise<Blob> => {
  const response = await api.get(`/monthly-consolidated/${jobId}/export`, {
    responseType: 'blob',
  });
  return response.data;
};

export const deleteMonthlyConsolidatedJob = async (jobId: string): Promise<void> => {
  await api.delete(`/monthly-consolidated/${jobId}`);
};

export async function pollMarketingRampJob(
  jobId: string,
  onProgress?: (pct: number, message: string) => void
): Promise<MarketingRampCompletedResponse> {
  const deadline = Date.now() + 30 * 60 * 1000;
  while (Date.now() < deadline) {
    const status = await getMarketingRampJobStatus(jobId);
    const serverPct = status.progress ?? 0;
    const uiPct =
      serverPct >= 10 ? 90 + Math.round(((serverPct - 10) / 90) * 9) : 90;
    onProgress?.(Math.min(99, uiPct), status.message || 'Analyzing…');
    if (status.status === 'completed') {
      return asMarketingRampCompleted(await getMarketingRampJob(jobId));
    }
    if (status.status === 'failed') {
      throw new Error(status.message || 'Analysis failed');
    }
    await sleep(1000);
  }
  throw new Error('Analysis timed out after 30 minutes');
}

export const analyzeMarketingRamp = async (
  qualifiedLeadsFile: File,
  reisiftFile: File,
  closingsFile: File,
  options: {
    useFullFileSpan: boolean;
    startDate?: string;
    endDate?: string;
  },
  onProgress?: (pct: number, message: string) => void
): Promise<MarketingRampCompletedResponse> => {
  const form = new FormData();
  form.append('qualified_leads_file', qualifiedLeadsFile);
  form.append('reisift_file', reisiftFile);
  form.append('closings_file', closingsFile);
  form.append('use_full_file_span', options.useFullFileSpan ? 'true' : 'false');
  if (!options.useFullFileSpan) {
    if (options.startDate) form.append('start_date', options.startDate);
    if (options.endDate) form.append('end_date', options.endDate);
  }

  const totalBytes = qualifiedLeadsFile.size + reisiftFile.size + closingsFile.size;
  onProgress?.(0, 'Uploading report files…');

  const response = await api.post<MarketingRampAnalyzeResponse>(
    '/marketing-ramp/analyze',
    form,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: DIRECT_UPLOAD_TIMEOUT_MS,
      onUploadProgress: (evt) => {
        if (!evt.total && !totalBytes) {
          return;
        }
        const loaded = evt.loaded ?? 0;
        const total = evt.total && evt.total > 0 ? evt.total : totalBytes;
        const pct = Math.min(85, Math.round((loaded / total) * 85));
        onProgress?.(pct, 'Uploading report files…');
      },
    }
  );

  onProgress?.(88, 'Files received — analyzing…');
  const result = await pollMarketingRampJob(response.data.job_id, onProgress);
  onProgress?.(100, 'Done');
  return result;
};

export const getMarketingRampJobStatus = async (
  jobId: string
): Promise<MarketingRampJobStatus> => {
  const response = await api.get<MarketingRampJobStatus>(`/marketing-ramp/${jobId}/status`);
  return response.data;
};

export const getMarketingRampJob = async (
  jobId: string
): Promise<MarketingRampAnalyzeResponse> => {
  const response = await api.get<MarketingRampAnalyzeResponse>(`/marketing-ramp/${jobId}`);
  return response.data;
};

export const downloadMarketingRampExport = async (
  jobId: string,
  options?: { format?: 'xlsx' | 'csv' }
): Promise<Blob> => {
  const format = options?.format ?? 'xlsx';
  const response = await api.get(`/marketing-ramp/${jobId}/export`, {
    params: { format },
    responseType: 'blob',
  });
  return response.data;
};

export const deleteMarketingRampJob = async (jobId: string): Promise<void> => {
  await api.delete(`/marketing-ramp/${jobId}`);
};

export async function pollWebLeadsJob(
  jobId: string,
  onProgress?: (pct: number, message: string) => void
): Promise<WebLeadsCompletedResponse> {
  const deadline = Date.now() + 30 * 60 * 1000;
  while (Date.now() < deadline) {
    const status = await getWebLeadsJobStatus(jobId);
    const serverPct = status.progress ?? 0;
    const uiPct =
      serverPct >= 10 ? 90 + Math.round(((serverPct - 10) / 90) * 9) : 90;
    onProgress?.(Math.min(99, uiPct), status.message || 'Analyzing…');
    if (status.status === 'completed') {
      return asWebLeadsCompleted(await getWebLeadsJob(jobId));
    }
    if (status.status === 'failed') {
      throw new Error(status.message || 'Analysis failed');
    }
    await sleep(1000);
  }
  throw new Error('Analysis timed out after 30 minutes');
}

async function analyzeWebLeadsDirect(
  reisiftFile: File,
  closingsFile?: File,
  cohortSource?: string,
  onProgress?: (pct: number, message: string) => void
): Promise<WebLeadsCompletedResponse> {
  const form = new FormData();
  form.append('reisift_file', reisiftFile);
  if (closingsFile) {
    form.append('closings_file', closingsFile);
  }
  if (cohortSource) {
    form.append('cohort_source', cohortSource);
  }

  const totalBytes = reisiftFile.size + (closingsFile?.size ?? 0);
  onProgress?.(0, 'Uploading report files…');

  const response = await api.post<{ job_id: string; status: string; message: string }>(
    '/web-leads/analyze',
    form,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: DIRECT_UPLOAD_TIMEOUT_MS,
      onUploadProgress: (evt) => {
        if (!evt.total && !totalBytes) {
          return;
        }
        const loaded = evt.loaded ?? 0;
        const total = evt.total && evt.total > 0 ? evt.total : totalBytes;
        const pct = Math.min(85, Math.round((loaded / total) * 85));
        onProgress?.(pct, 'Uploading report files…');
      },
    }
  );

  onProgress?.(88, 'Files received — analyzing…');
  const result = await pollWebLeadsJob(response.data.job_id, onProgress);
  onProgress?.(100, 'Done');
  return result;
}

async function analyzeWebLeadsResumable(
  reisiftFile: File,
  closingsFile?: File,
  cohortSource?: string,
  onProgress?: (pct: number, message: string) => void
): Promise<WebLeadsCompletedResponse> {
  onProgress?.(0, `Uploading ${reisiftFile.name} (chunked fallback)…`);
  const reisiftPath = await uploadFileResumable('reisift', reisiftFile, (pct, msg) => {
    onProgress?.(Math.round(pct * (closingsFile ? 0.65 : 0.9)), msg);
  });
  let closingsPath: string | undefined;
  if (closingsFile) {
    onProgress?.(65, `Uploading ${closingsFile.name}…`);
    closingsPath = await uploadFileResumable('closings', closingsFile, (pct, msg) => {
      onProgress?.(65 + Math.round(pct * 0.25), msg);
    });
  }
  onProgress?.(90, 'Starting analysis…');
  const started = await analyzeWebLeadsFromPaths(reisiftPath, closingsPath, cohortSource);
  const result = await pollWebLeadsJob(started.job_id, onProgress);
  onProgress?.(100, 'Done');
  return result;
}

export const analyzeWebLeads = async (
  reisiftFile: File,
  closingsFile?: File,
  cohortSource?: string,
  onProgress?: (pct: number, message: string) => void
): Promise<WebLeadsCompletedResponse> => {
  try {
    return await analyzeWebLeadsDirect(reisiftFile, closingsFile, cohortSource, onProgress);
  } catch (err) {
    if (!shouldFallbackToResumableUpload(err)) {
      throw err;
    }
    onProgress?.(
      0,
      'Direct upload interrupted — retrying in smaller pieces (proxy timeout)…'
    );
    return analyzeWebLeadsResumable(reisiftFile, closingsFile, cohortSource, onProgress);
  }
};

export const analyzeWebLeadsFromPaths = async (
  reisiftPath: string,
  closingsPath?: string,
  cohortSource?: string
): Promise<{ job_id: string; status: string; message: string }> => {
  const body: Record<string, unknown> = {
    reisift_path: reisiftPath,
  };
  if (closingsPath) {
    body.closings_path = closingsPath;
  }
  if (cohortSource) {
    body.cohort_source = cohortSource;
  }
  const response = await api.post<{ job_id: string; status: string; message: string }>(
    '/web-leads/analyze',
    body
  );
  return response.data;
};

export const getWebLeadsJobStatus = async (jobId: string): Promise<WebLeadsJobStatus> => {
  const response = await api.get<WebLeadsJobStatus>(`/web-leads/${jobId}/status`);
  return response.data;
};

export const getWebLeadsJob = async (jobId: string): Promise<WebLeadsAnalyzeResponse> => {
  const response = await api.get<WebLeadsAnalyzeResponse>(`/web-leads/${jobId}`);
  return response.data;
};

export const downloadWebLeadsExport = async (jobId: string): Promise<Blob> => {
  const response = await api.get(`/web-leads/${jobId}/export`, {
    responseType: 'blob',
  });
  return response.data;
};

export const deleteWebLeadsJob = async (jobId: string): Promise<void> => {
  await api.delete(`/web-leads/${jobId}`);
};

export async function pollProbateJob(
  jobId: string,
  onProgress?: (pct: number, message: string) => void
): Promise<ProbateCompletedResponse> {
  const deadline = Date.now() + 30 * 60 * 1000;
  while (Date.now() < deadline) {
    const status = await getProbateJobStatus(jobId);
    const serverPct = status.progress ?? 0;
    const uiPct =
      serverPct >= 10 ? 90 + Math.round(((serverPct - 10) / 90) * 9) : 90;
    onProgress?.(Math.min(99, uiPct), status.message || 'Analyzing…');
    if (status.status === 'completed') {
      return asProbateCompleted(await getProbateJob(jobId));
    }
    if (status.status === 'failed') {
      throw new Error(status.message || 'Analysis failed');
    }
    await sleep(1000);
  }
  throw new Error('Analysis timed out after 30 minutes');
}

async function analyzeProbateDirect(
  reisiftFile: File,
  qlFile: File,
  oppsFile?: File,
  txnFile?: File,
  onProgress?: (pct: number, message: string) => void
): Promise<ProbateCompletedResponse> {
  const form = new FormData();
  form.append('reisift_file', reisiftFile);
  form.append('qualified_leads_file', qlFile);
  if (oppsFile) form.append('opportunities_file', oppsFile);
  if (txnFile) form.append('transactions_file', txnFile);

  const totalBytes =
    reisiftFile.size + qlFile.size + (oppsFile?.size ?? 0) + (txnFile?.size ?? 0);
  onProgress?.(0, 'Uploading report files…');

  const response = await api.post<{ job_id: string; status: string; message: string }>(
    '/probate/analyze',
    form,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: DIRECT_UPLOAD_TIMEOUT_MS,
      onUploadProgress: (evt) => {
        if (!evt.total && !totalBytes) {
          return;
        }
        const loaded = evt.loaded ?? 0;
        const total = evt.total && evt.total > 0 ? evt.total : totalBytes;
        const pct = Math.min(85, Math.round((loaded / total) * 85));
        onProgress?.(pct, 'Uploading report files…');
      },
    }
  );
  onProgress?.(88, 'Files received — analyzing…');
  const result = await pollProbateJob(response.data.job_id, onProgress);
  onProgress?.(100, 'Done');
  return result;
}

async function analyzeProbateResumable(
  reisiftFile: File,
  qlFile: File,
  oppsFile?: File,
  txnFile?: File,
  onProgress?: (pct: number, message: string) => void
): Promise<ProbateCompletedResponse> {
  onProgress?.(0, `Uploading ${reisiftFile.name} (chunked fallback)…`);
  const reisiftPath = await uploadFileResumable('reisift', reisiftFile, (pct, msg) => {
    onProgress?.(Math.round(pct * 0.4), msg);
  });
  onProgress?.(40, `Uploading ${qlFile.name}…`);
  const qlPath = await uploadFileResumable('qualified_leads', qlFile, (pct, msg) => {
    onProgress?.(40 + Math.round(pct * 0.3), msg);
  });
  let oppsPath: string | undefined;
  if (oppsFile) {
    onProgress?.(70, `Uploading ${oppsFile.name}…`);
    oppsPath = await uploadFileResumable('closings', oppsFile, (pct, msg) => {
      onProgress?.(70 + Math.round(pct * 0.1), msg);
    });
  }
  let txnPath: string | undefined;
  if (txnFile) {
    onProgress?.(80, `Uploading ${txnFile.name}…`);
    txnPath = await uploadFileResumable('closings', txnFile, (pct, msg) => {
      onProgress?.(80 + Math.round(pct * 0.1), msg);
    });
  }
  onProgress?.(90, 'Starting analysis…');
  const started = await analyzeProbateFromPaths(reisiftPath, qlPath, oppsPath, txnPath);
  const result = await pollProbateJob(started.job_id, onProgress);
  onProgress?.(100, 'Done');
  return result;
}

export const analyzeProbate = async (
  reisiftFile: File,
  qlFile: File,
  oppsFile?: File,
  txnFile?: File,
  onProgress?: (pct: number, message: string) => void
): Promise<ProbateCompletedResponse> => {
  try {
    return await analyzeProbateDirect(reisiftFile, qlFile, oppsFile, txnFile, onProgress);
  } catch (err) {
    if (!shouldFallbackToResumableUpload(err)) {
      throw err;
    }
    onProgress?.(
      0,
      'Direct upload interrupted — retrying in smaller pieces (proxy timeout)…'
    );
    return analyzeProbateResumable(reisiftFile, qlFile, oppsFile, txnFile, onProgress);
  }
};

export const analyzeProbateFromPaths = async (
  reisiftPath: string,
  qlPath: string,
  oppsPath?: string,
  txnPath?: string
): Promise<{ job_id: string; status: string; message: string }> => {
  const body: Record<string, unknown> = {
    reisift_path: reisiftPath,
    qualified_leads_path: qlPath,
  };
  if (oppsPath) body.opportunities_path = oppsPath;
  if (txnPath) body.transactions_path = txnPath;
  const response = await api.post<{ job_id: string; status: string; message: string }>(
    '/probate/analyze',
    body
  );
  return response.data;
};

export const getProbateJobStatus = async (jobId: string): Promise<ProbateJobStatus> => {
  const response = await api.get<ProbateJobStatus>(`/probate/${jobId}/status`);
  return response.data;
};

export const getProbateJob = async (jobId: string): Promise<ProbateAnalyzeResponse> => {
  const response = await api.get<ProbateAnalyzeResponse>(`/probate/${jobId}`);
  return response.data;
};

export const downloadProbateExport = async (jobId: string): Promise<Blob> => {
  const response = await api.get(`/probate/${jobId}/export`, { responseType: 'blob' });
  return response.data;
};

export const deleteProbateJob = async (jobId: string): Promise<void> => {
  await api.delete(`/probate/${jobId}`);
};

export async function pollSoldPropertiesJob(
  jobId: string,
  onProgress?: (pct: number, message: string) => void
): Promise<SoldPropertiesCompletedResponse> {
  const deadline = Date.now() + 30 * 60 * 1000;
  while (Date.now() < deadline) {
    const status = await getSoldPropertiesJobStatus(jobId);
    const serverPct = status.progress ?? 0;
    const uiPct =
      serverPct >= 10 ? 90 + Math.round(((serverPct - 10) / 90) * 9) : 90;
    onProgress?.(Math.min(99, uiPct), status.message || 'Analyzing…');
    if (status.status === 'completed') {
      return asSoldPropertiesCompleted(await getSoldPropertiesJob(jobId));
    }
    if (status.status === 'failed') {
      throw new Error(status.message || 'Analysis failed');
    }
    await sleep(1000);
  }
  throw new Error('Analysis timed out after 30 minutes');
}

async function analyzeSoldPropertiesDirect(
  reisiftFile: File,
  qlFile: File,
  oppsFile?: File,
  onProgress?: (pct: number, message: string) => void
): Promise<SoldPropertiesCompletedResponse> {
  const form = new FormData();
  form.append('reisift_file', reisiftFile);
  form.append('qualified_leads_file', qlFile);
  if (oppsFile) form.append('opportunities_file', oppsFile);

  const totalBytes = reisiftFile.size + qlFile.size + (oppsFile?.size ?? 0);
  onProgress?.(0, 'Uploading report files…');

  const response = await api.post<{ job_id: string; status: string; message: string }>(
    '/sold-properties/analyze',
    form,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: DIRECT_UPLOAD_TIMEOUT_MS,
      onUploadProgress: (evt) => {
        if (!evt.total && !totalBytes) {
          return;
        }
        const loaded = evt.loaded ?? 0;
        const total = evt.total && evt.total > 0 ? evt.total : totalBytes;
        const pct = Math.min(85, Math.round((loaded / total) * 85));
        onProgress?.(pct, 'Uploading report files…');
      },
    }
  );
  onProgress?.(88, 'Files received — analyzing…');
  const result = await pollSoldPropertiesJob(response.data.job_id, onProgress);
  onProgress?.(100, 'Done');
  return result;
}

async function analyzeSoldPropertiesResumable(
  reisiftFile: File,
  qlFile: File,
  oppsFile?: File,
  onProgress?: (pct: number, message: string) => void
): Promise<SoldPropertiesCompletedResponse> {
  onProgress?.(0, `Uploading ${reisiftFile.name} (chunked fallback)…`);
  const reisiftPath = await uploadFileResumable('reisift', reisiftFile, (pct, msg) => {
    onProgress?.(Math.round(pct * 0.45), msg);
  });
  onProgress?.(45, `Uploading ${qlFile.name}…`);
  const qlPath = await uploadFileResumable('qualified_leads', qlFile, (pct, msg) => {
    onProgress?.(45 + Math.round(pct * 0.35), msg);
  });
  let oppsPath: string | undefined;
  if (oppsFile) {
    onProgress?.(80, `Uploading ${oppsFile.name}…`);
    oppsPath = await uploadFileResumable('closings', oppsFile, (pct, msg) => {
      onProgress?.(80 + Math.round(pct * 0.1), msg);
    });
  }
  onProgress?.(90, 'Starting analysis…');
  const started = await analyzeSoldPropertiesFromPaths(reisiftPath, qlPath, oppsPath);
  const result = await pollSoldPropertiesJob(started.job_id, onProgress);
  onProgress?.(100, 'Done');
  return result;
}

export const analyzeSoldProperties = async (
  reisiftFile: File,
  qlFile: File,
  oppsFile?: File,
  onProgress?: (pct: number, message: string) => void
): Promise<SoldPropertiesCompletedResponse> => {
  try {
    return await analyzeSoldPropertiesDirect(reisiftFile, qlFile, oppsFile, onProgress);
  } catch (err) {
    if (!shouldFallbackToResumableUpload(err)) {
      throw err;
    }
    return analyzeSoldPropertiesResumable(reisiftFile, qlFile, oppsFile, onProgress);
  }
};

export const analyzeSoldPropertiesFromPaths = async (
  reisiftPath: string,
  qlPath: string,
  oppsPath?: string
): Promise<{ job_id: string; status: string; message: string }> => {
  const body: Record<string, unknown> = {
    reisift_path: reisiftPath,
    qualified_leads_path: qlPath,
  };
  if (oppsPath) body.opportunities_path = oppsPath;
  const response = await api.post<{ job_id: string; status: string; message: string }>(
    '/sold-properties/analyze',
    body
  );
  return response.data;
};

export const getSoldPropertiesJobStatus = async (
  jobId: string
): Promise<SoldPropertiesJobStatus> => {
  const response = await api.get<SoldPropertiesJobStatus>(
    `/sold-properties/${jobId}/status`
  );
  return response.data;
};

export const getSoldPropertiesJob = async (
  jobId: string
): Promise<SoldPropertiesAnalyzeResponse> => {
  const response = await api.get<SoldPropertiesAnalyzeResponse>(`/sold-properties/${jobId}`);
  return response.data;
};

export const downloadSoldPropertiesExport = async (jobId: string): Promise<Blob> => {
  const response = await api.get(`/sold-properties/${jobId}/export`, {
    responseType: 'blob',
  });
  return response.data;
};

export const deleteSoldPropertiesJob = async (jobId: string): Promise<void> => {
  await api.delete(`/sold-properties/${jobId}`);
};

export async function pollCourtAlertsJob(
  jobId: string,
  onProgress?: (pct: number, message: string) => void
): Promise<CourtAlertsCompletedResponse> {
  const deadline = Date.now() + 30 * 60 * 1000;
  while (Date.now() < deadline) {
    const status = await getCourtAlertsJobStatus(jobId);
    const serverPct = status.progress ?? 0;
    const uiPct =
      serverPct >= 10 ? 90 + Math.round(((serverPct - 10) / 90) * 9) : 90;
    onProgress?.(Math.min(99, uiPct), status.message || 'Analyzing…');
    if (status.status === 'completed') {
      return asCourtAlertsCompleted(await getCourtAlertsJob(jobId));
    }
    if (status.status === 'failed') {
      throw new Error(status.message || 'Analysis failed');
    }
    await sleep(1000);
  }
  throw new Error('Analysis timed out after 30 minutes');
}

async function analyzeCourtAlertsDirect(
  courtAlertsFile: File,
  reisiftFile: File,
  qlFile: File,
  oppsFile?: File,
  txnFile?: File,
  onProgress?: (pct: number, message: string) => void
): Promise<CourtAlertsCompletedResponse> {
  const form = new FormData();
  form.append('court_alerts_file', courtAlertsFile);
  form.append('reisift_file', reisiftFile);
  form.append('qualified_leads_file', qlFile);
  if (oppsFile) form.append('opportunities_file', oppsFile);
  if (txnFile) form.append('transactions_file', txnFile);

  const totalBytes =
    courtAlertsFile.size +
    reisiftFile.size +
    qlFile.size +
    (oppsFile?.size ?? 0) +
    (txnFile?.size ?? 0);
  onProgress?.(0, 'Uploading report files…');

  const response = await api.post<{ job_id: string; status: string; message: string }>(
    '/court-alerts/analyze',
    form,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: DIRECT_UPLOAD_TIMEOUT_MS,
      onUploadProgress: (evt) => {
        if (!evt.total && !totalBytes) {
          return;
        }
        const loaded = evt.loaded ?? 0;
        const total = evt.total && evt.total > 0 ? evt.total : totalBytes;
        const pct = Math.min(85, Math.round((loaded / total) * 85));
        onProgress?.(pct, 'Uploading report files…');
      },
    }
  );
  onProgress?.(88, 'Files received — analyzing…');
  const result = await pollCourtAlertsJob(response.data.job_id, onProgress);
  onProgress?.(100, 'Done');
  return result;
}

async function analyzeCourtAlertsResumable(
  courtAlertsFile: File,
  reisiftFile: File,
  qlFile: File,
  oppsFile?: File,
  txnFile?: File,
  onProgress?: (pct: number, message: string) => void
): Promise<CourtAlertsCompletedResponse> {
  onProgress?.(0, `Uploading ${courtAlertsFile.name} (chunked fallback)…`);
  const caPath = await uploadFileResumable('closings', courtAlertsFile, (pct, msg) => {
    onProgress?.(Math.round(pct * 0.25), msg);
  });
  onProgress?.(25, `Uploading ${reisiftFile.name}…`);
  const reisiftPath = await uploadFileResumable('reisift', reisiftFile, (pct, msg) => {
    onProgress?.(25 + Math.round(pct * 0.3), msg);
  });
  onProgress?.(55, `Uploading ${qlFile.name}…`);
  const qlPath = await uploadFileResumable('qualified_leads', qlFile, (pct, msg) => {
    onProgress?.(55 + Math.round(pct * 0.2), msg);
  });
  let oppsPath: string | undefined;
  if (oppsFile) {
    onProgress?.(75, `Uploading ${oppsFile.name}…`);
    oppsPath = await uploadFileResumable('closings', oppsFile, (pct, msg) => {
      onProgress?.(75 + Math.round(pct * 0.08), msg);
    });
  }
  let txnPath: string | undefined;
  if (txnFile) {
    onProgress?.(83, `Uploading ${txnFile.name}…`);
    txnPath = await uploadFileResumable('closings', txnFile, (pct, msg) => {
      onProgress?.(83 + Math.round(pct * 0.07), msg);
    });
  }
  onProgress?.(90, 'Starting analysis…');
  const started = await analyzeCourtAlertsFromPaths(caPath, reisiftPath, qlPath, oppsPath, txnPath);
  const result = await pollCourtAlertsJob(started.job_id, onProgress);
  onProgress?.(100, 'Done');
  return result;
}

export const analyzeCourtAlerts = async (
  courtAlertsFile: File,
  reisiftFile: File,
  qlFile: File,
  oppsFile?: File,
  txnFile?: File,
  onProgress?: (pct: number, message: string) => void
): Promise<CourtAlertsCompletedResponse> => {
  try {
    return await analyzeCourtAlertsDirect(
      courtAlertsFile,
      reisiftFile,
      qlFile,
      oppsFile,
      txnFile,
      onProgress
    );
  } catch (err) {
    if (!shouldFallbackToResumableUpload(err)) {
      throw err;
    }
    onProgress?.(
      0,
      'Direct upload interrupted — retrying in smaller pieces (proxy timeout)…'
    );
    return analyzeCourtAlertsResumable(
      courtAlertsFile,
      reisiftFile,
      qlFile,
      oppsFile,
      txnFile,
      onProgress
    );
  }
};

export const analyzeCourtAlertsFromPaths = async (
  courtAlertsPath: string,
  reisiftPath: string,
  qlPath: string,
  oppsPath?: string,
  txnPath?: string
): Promise<{ job_id: string; status: string; message: string }> => {
  const body: Record<string, unknown> = {
    court_alerts_path: courtAlertsPath,
    reisift_path: reisiftPath,
    qualified_leads_path: qlPath,
  };
  if (oppsPath) body.opportunities_path = oppsPath;
  if (txnPath) body.transactions_path = txnPath;
  const response = await api.post<{ job_id: string; status: string; message: string }>(
    '/court-alerts/analyze',
    body
  );
  return response.data;
};

export const getCourtAlertsJobStatus = async (jobId: string): Promise<CourtAlertsJobStatus> => {
  const response = await api.get<CourtAlertsJobStatus>(`/court-alerts/${jobId}/status`);
  return response.data;
};

export const getCourtAlertsJob = async (jobId: string): Promise<CourtAlertsAnalyzeResponse> => {
  const response = await api.get<CourtAlertsAnalyzeResponse>(`/court-alerts/${jobId}`);
  return response.data;
};

export const downloadCourtAlertsExport = async (jobId: string): Promise<Blob> => {
  const response = await api.get(`/court-alerts/${jobId}/export`, { responseType: 'blob' });
  return response.data;
};

export const deleteCourtAlertsJob = async (jobId: string): Promise<void> => {
  await api.delete(`/court-alerts/${jobId}`);
};
