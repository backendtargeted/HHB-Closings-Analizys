import axios from 'axios';
import type {
  AnalysisCompleteResponse,
  AnalysisStatus,
  UploadCapabilitiesResponse,
  ResumableUploadInitResponse,
  ResumableUploadStatusResponse,
  ResumableUploadCompleteResponse,
  StartAnalysisParams,
} from '../types/analysis';
import type { PatchUploadResponse } from '../types/patches';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

/** User-facing message when nginx/Flask rejects body size or returns an HTML error page. */
const UPLOAD_TOO_LARGE_MSG =
  'Upload too large for the server limit. Try fewer/smaller files or contact admin.';

export function getAxiosErrorMessage(err: unknown, fallback: string): string {
  if (!axios.isAxiosError(err)) {
    if (err instanceof Error) return err.message;
    return fallback;
  }
  const status = err.response?.status;
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
  kind: 'csv' | 'closings',
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
