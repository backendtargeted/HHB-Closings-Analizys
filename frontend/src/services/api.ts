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
  MonthlyConsolidatedJobStatus,
} from '../types/monthlyConsolidated';
import type { SavedReportsListResponse } from '../types/reports';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

/** User-facing message when nginx/Flask rejects body size or returns an HTML error page. */
const UPLOAD_TOO_LARGE_MSG =
  'Upload too large for the server limit. Try fewer/smaller files or contact admin.';

const GATEWAY_TIMEOUT_MSG =
  'The server stopped responding (502). Try again — uploads use short requests and analysis runs in the background.';

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function pollMonthlyConsolidatedJob(
  jobId: string,
  onProgress?: (pct: number, message: string) => void
): Promise<MonthlyConsolidatedAnalyzeResponse> {
  const deadline = Date.now() + 30 * 60 * 1000;
  while (Date.now() < deadline) {
    const status = await getMonthlyConsolidatedJobStatus(jobId);
    onProgress?.(90 + Math.round((status.progress ?? 0) * 0.1), status.message);
    if (status.status === 'completed') {
      return getMonthlyConsolidatedJob(jobId);
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
  await api.put(`/upload/resumable/${uploadId}/chunk/${chunkIndex}`, chunkBlob, {
    headers: { 'Content-Type': 'application/octet-stream' },
  });
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
  const maxChunkBytes = caps.limits?.max_chunk_bytes ?? 8 * 1024 * 1024;
  const chunkSize = Math.min(maxChunkBytes, 8 * 1024 * 1024);
  const init = await initResumableUpload(kind, file.name, file.size, chunkSize);
  onProgress?.(0, `Uploading ${file.name}…`);

  const status = await getResumableUploadStatus(init.upload_id);
  const uploaded = new Set<number>(status.uploaded_chunks ?? []);
  const retryLimit = 3;

  for (let idx = 0; idx < init.total_chunks; idx += 1) {
    if (uploaded.has(idx)) {
      continue;
    }
    const start = idx * init.chunk_size;
    const end = Math.min(start + init.chunk_size, file.size);
    const chunk = file.slice(start, end);

    let attempts = 0;
    while (attempts < retryLimit) {
      try {
        await uploadResumableChunk(init.upload_id, idx, chunk);
        uploaded.add(idx);
        const pct = Math.round((uploaded.size / init.total_chunks) * 100);
        onProgress?.(pct, `Uploading ${file.name}…`);
        break;
      } catch (err) {
        attempts += 1;
        if (attempts >= retryLimit) {
          throw err;
        }
        await new Promise((resolve) => setTimeout(resolve, 400 * attempts));
      }
    }
  }

  const finalized = await completeResumableUpload(init.upload_id);
  if (kind === 'csv' && finalized.csv_path) {
    return finalized.csv_path;
  }
  if (kind === 'closings') {
    const closingsPath = finalized.closings_path ?? finalized.excel_path;
    if (closingsPath) return closingsPath;
  }
  if (kind === 'reisift' && finalized.reisift_path) {
    return finalized.reisift_path;
  }
  if (kind === 'qualified_leads' && finalized.qualified_leads_path) {
    return finalized.qualified_leads_path;
  }
  throw new Error(`${kind} upload did not return a file path`);
}

export const analyzeMonthlyConsolidated = async (
  reisiftFile: File,
  qualifiedLeadsFile: File,
  onProgress?: (pct: number, message: string) => void
): Promise<MonthlyConsolidatedAnalyzeResponse> => {
  onProgress?.(0, `Uploading ${reisiftFile.name}…`);
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
