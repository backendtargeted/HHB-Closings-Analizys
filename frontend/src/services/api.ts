import axios from 'axios';
import type {
  AnalysisCompleteResponse,
  AnalysisStatus,
  UploadResponse,
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

export const uploadFiles = async (
  closingsFile: File | null,
  csvFile: File
): Promise<UploadResponse> => {
  const formData = new FormData();
  if (closingsFile) {
    formData.append('closings_file', closingsFile);
  }
  formData.append('csv_file', csvFile);

  const response = await api.post<UploadResponse>('/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });

  return response.data;
};

export const startAnalysis = async (
  closingsPath: string | null | undefined,
  csvPath: string,
  asOf?: string | null
): Promise<{ job_id: string; status: string; message: string }> => {
  const body: Record<string, string> = {
    csv_path: csvPath,
  };
  if (closingsPath) {
    body.closings_path = closingsPath;
  }
  const trimmed = asOf?.trim();
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
