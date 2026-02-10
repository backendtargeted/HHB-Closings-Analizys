import { useState, useEffect, useCallback } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  uploadFiles,
  startAnalysis,
  getAnalysisStatus,
  getAnalysisResults,
} from '../services/api';
import type { AnalysisCompleteResponse, AnalysisStatus } from '../types/analysis';

export const useAnalysis = () => {
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('');

  const uploadMutation = useMutation({
    mutationFn: ({ excelFile, csvFile }: { excelFile: File; csvFile: File }) =>
      uploadFiles(excelFile, csvFile),
  });

  const startAnalysisMutation = useMutation({
    mutationFn: ({ excelPath, csvPath }: { excelPath: string; csvPath: string }) =>
      startAnalysis(excelPath, csvPath),
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
    async (excelFile: File, csvFile: File) => {
      try {
        // Upload files
        const uploadResult = await uploadMutation.mutateAsync({
          excelFile,
          csvFile,
        });

        // Start analysis
        await startAnalysisMutation.mutateAsync({
          excelPath: uploadResult.excel_path,
          csvPath: uploadResult.csv_path,
        });
      } catch (error) {
        console.error('Analysis error:', error);
        throw error;
      }
    },
    [uploadMutation, startAnalysisMutation]
  );

  return {
    runAnalysis,
    currentJobId,
    progress,
    statusMessage,
    analysisStatus,
    analysisResults,
    isLoading:
      uploadMutation.isPending ||
      startAnalysisMutation.isPending ||
      analysisStatus?.status === 'running' ||
      analysisStatus?.status === 'pending',
    isError: uploadMutation.isError || startAnalysisMutation.isError,
    error: uploadMutation.error || startAnalysisMutation.error,
  };
};
