import { useState, useEffect, useCallback } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  uploadFiles,
  startAnalysis,
  getAnalysisStatus,
  getAnalysisResults,
  getUploadCapabilities,
  presignUpload,
  putFileToPresignedUrl,
} from '../services/api';
import type { AnalysisCompleteResponse, AnalysisStatus } from '../types/analysis';

export const useAnalysis = () => {
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');
  const [s3UploadPending, setS3UploadPending] = useState(false);

  const { data: uploadCaps, refetch: refetchUploadCaps } = useQuery({
    queryKey: ['upload-capabilities'],
    queryFn: getUploadCapabilities,
    staleTime: 60_000,
  });

  const uploadMutation = useMutation({
    mutationFn: ({ closingsFile, csvFile }: { closingsFile: File | null; csvFile: File }) =>
      uploadFiles(closingsFile, csvFile),
  });

  const startAnalysisMutation = useMutation({
    mutationFn: (params: {
      closingsPath?: string | null;
      csvPath?: string;
      csvObjectKey?: string;
      closingsObjectKey?: string | null;
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
      try {
        const { data: caps } = await refetchUploadCaps();
        const usePresigned = caps?.presigned_upload === true;

        if (usePresigned) {
          setS3UploadPending(true);
          try {
            const csvPresign = await presignUpload('csv', csvFile.name);
            await putFileToPresignedUrl(csvFile, csvPresign.upload);
            let closingsObjectKey: string | undefined;
            if (closingsFile) {
              const cPresign = await presignUpload('closings', closingsFile.name);
              await putFileToPresignedUrl(closingsFile, cPresign.upload);
              closingsObjectKey = cPresign.object_key;
            }
            await startAnalysisMutation.mutateAsync({
              csvObjectKey: csvPresign.object_key,
              closingsObjectKey: closingsObjectKey ?? undefined,
              asOf: asOf?.trim() || undefined,
            });
          } finally {
            setS3UploadPending(false);
          }
        } else {
          const uploadResult = await uploadMutation.mutateAsync({
            closingsFile,
            csvFile,
          });
          await startAnalysisMutation.mutateAsync({
            closingsPath: uploadResult.closings_path ?? uploadResult.excel_path ?? undefined,
            csvPath: uploadResult.csv_path,
            asOf: asOf?.trim() || undefined,
          });
        }
      } catch (error) {
        console.error('Analysis error:', error);
        throw error;
      }
    },
    [refetchUploadCaps, uploadMutation, startAnalysisMutation]
  );

  return {
    runAnalysis,
    currentJobId,
    progress,
    statusMessage,
    analysisStatus,
    analysisResults,
    presignedUpload: uploadCaps?.presigned_upload === true,
    isLoading:
      s3UploadPending ||
      uploadMutation.isPending ||
      startAnalysisMutation.isPending ||
      analysisStatus?.status === 'running' ||
      analysisStatus?.status === 'pending',
    isError: uploadMutation.isError || startAnalysisMutation.isError,
    error: uploadMutation.error || startAnalysisMutation.error,
  };
};
