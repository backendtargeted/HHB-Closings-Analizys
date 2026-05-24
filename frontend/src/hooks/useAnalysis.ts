import { useState, useEffect, useCallback } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  startAnalysis,
  getAnalysisStatus,
  getAnalysisResults,
  getUploadCapabilities,
  initResumableUpload,
  getResumableUploadStatus,
  uploadResumableChunk,
  completeResumableUpload,
} from '../services/api';
import type { AnalysisCompleteResponse, AnalysisStatus } from '../types/analysis';

export const useAnalysis = () => {
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');
  const [resumableUploadPending, setResumableUploadPending] = useState(false);
  const [uploadError, setUploadError] = useState<Error | null>(null);

  const { data: uploadCaps, refetch: refetchUploadCaps } = useQuery({
    queryKey: ['upload-capabilities'],
    queryFn: getUploadCapabilities,
    staleTime: 60_000,
  });

  const startAnalysisMutation = useMutation({
    mutationFn: (params: {
      closingsPath?: string | null;
      csvPath: string;
      asOf?: string | null;
    }) => startAnalysis(params),
    onSuccess: (data) => {
      setCurrentJobId(data.job_id);
    },
  });

  const { data: analysisStatus } = useQuery<AnalysisStatus>({
    queryKey: ['analysis-status', currentJobId],
    queryFn: () => getAnalysisStatus(currentJobId!),
    enabled: !!currentJobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'running' || status === 'pending' ? 1000 : false;
    },
  });

  const { data: analysisResults } = useQuery<AnalysisCompleteResponse>({
    queryKey: ['analysis-results', currentJobId],
    queryFn: () => getAnalysisResults(currentJobId!),
    enabled: !!currentJobId && analysisStatus?.status === 'completed',
  });

  useEffect(() => {
    if (analysisStatus) {
      setProgress(analysisStatus.progress);
      setStatusMessage(analysisStatus.message);
    }
  }, [analysisStatus]);

  const runAnalysis = useCallback(
    async (closingsFile: File | null, csvFile: File, asOf?: string | null) => {
      const uploadOneFileResumable = async (kind: 'csv' | 'closings', file: File): Promise<string> => {
        const { data: capsData } = await refetchUploadCaps();
        const maxChunkBytes = capsData?.limits?.max_chunk_bytes ?? 8 * 1024 * 1024;
        const chunkSize = Math.min(maxChunkBytes, 8 * 1024 * 1024);
        const init = await initResumableUpload(kind, file.name, file.size, chunkSize);
        setStatusMessage(`Uploading ${file.name}...`);

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
              setProgress(pct);
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
        if (kind === 'csv') {
          if (!finalized.csv_path) throw new Error('CSV upload did not return csv_path');
          return finalized.csv_path;
        }
        const closingsPath = finalized.closings_path ?? finalized.excel_path;
        if (!closingsPath) throw new Error('Closings upload did not return closings_path');
        return closingsPath;
      };

      try {
        setUploadError(null);
        const { data: caps } = await refetchUploadCaps();
        if (caps?.resumable_upload !== true) {
          throw new Error('Resumable uploads are not available. Check /api/upload/capabilities.');
        }

        setResumableUploadPending(true);
        try {
          setProgress(0);
          const csvPath = await uploadOneFileResumable('csv', csvFile);
          let closingsPath: string | undefined;
          if (closingsFile) {
            closingsPath = await uploadOneFileResumable('closings', closingsFile);
          }
          setStatusMessage('Starting analysis...');
          await startAnalysisMutation.mutateAsync({
            csvPath,
            closingsPath: closingsPath ?? undefined,
            asOf: asOf?.trim() || undefined,
          });
        } finally {
          setResumableUploadPending(false);
        }
      } catch (error) {
        const err = error instanceof Error ? error : new Error(String(error));
        setUploadError(err);
        console.error('Analysis error:', err);
        throw err;
      }
    },
    [refetchUploadCaps, startAnalysisMutation]
  );

  return {
    runAnalysis,
    currentJobId,
    progress,
    statusMessage,
    analysisStatus,
    analysisResults,
    resumableUpload: uploadCaps?.resumable_upload === true,
    isLoading:
      resumableUploadPending ||
      startAnalysisMutation.isPending ||
      analysisStatus?.status === 'running' ||
      analysisStatus?.status === 'pending',
    isError: uploadError !== null || startAnalysisMutation.isError,
    error: uploadError ?? startAnalysisMutation.error,
  };
};
