import { useState, useEffect } from 'react';
import FileUpload from './components/FileUpload';
import AnalysisResults from './components/AnalysisResults';
import MethodologySection from './components/MethodologySection';
import SavedReports from './components/SavedReports';
import { useAnalysis } from './hooks/useAnalysis';
import type { AnalysisCompleteResponse } from './types/analysis';

function App() {
  const [analysisComplete, setAnalysisComplete] = useState(false);
  const [loadedSavedReport, setLoadedSavedReport] = useState<AnalysisCompleteResponse | null>(null);
  const {
    runAnalysis,
    progress,
    statusMessage,
    analysisResults,
    isLoading,
    isError,
    error,
  } = useAnalysis();

  const resultsWithStatus = analysisResults as AnalysisCompleteResponse | undefined;
  const analysisStatusProp = resultsWithStatus?.status;
  const displayResults = analysisResults ?? loadedSavedReport ?? null;

  const handleAnalysisComplete = () => {
    setAnalysisComplete(true);
    setLoadedSavedReport(null);
  };

  const handleNewAnalysis = () => {
    setAnalysisComplete(false);
    setLoadedSavedReport(null);
  };

  const handleOpenSavedReport = (data: AnalysisCompleteResponse) => {
    setLoadedSavedReport(data);
    setAnalysisComplete(true);
  };

  // Auto-show results when analysis completes
  useEffect(() => {
    if (analysisResults?.status === 'completed') {
      setAnalysisComplete(true);
      setLoadedSavedReport(null);
    }
  }, [analysisResults]);

  return (
    <div className="min-h-screen bg-surface">
      <header className="bg-gradient-to-r from-surface to-navy text-white shadow-md">
        <div className="container mx-auto px-4 py-6">
          <div className="flex items-center gap-4">
            <div className="flex items-center shrink-0 bg-surface/95 rounded-r-lg pr-2 py-1 -ml-4 pl-4">
              <img
                src="/HHB-Logo-600x143.webp"
                alt="HHB Logo"
                className="h-12 object-contain"
              />
            </div>
            <div className="min-w-0">
              <h1 className="text-3xl font-bold text-white drop-shadow-sm">Contact Attribution Analysis</h1>
              <p className="text-gray-200 mt-1">Analyze contact history for closed deals</p>
            </div>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8">
        <div className="mb-6">
          <MethodologySection />
        </div>
        {!analysisComplete && !displayResults ? (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2">
              <FileUpload
                onUpload={runAnalysis}
                isLoading={isLoading}
                progress={progress}
                statusMessage={statusMessage}
                isError={isError}
                error={error}
                onComplete={handleAnalysisComplete}
                analysisStatus={analysisStatusProp}
              />
            </div>
            <div className="rounded-lg border border-stone-200 bg-surface shadow-sm p-4">
              <SavedReports onOpenReport={handleOpenSavedReport} />
            </div>
          </div>
        ) : displayResults ? (
          <AnalysisResults
            results={displayResults}
            onNewAnalysis={handleNewAnalysis}
          />
        ) : (
          <FileUpload
            onUpload={runAnalysis}
            isLoading={isLoading}
            progress={progress}
            statusMessage={statusMessage}
            isError={isError}
            error={error}
            onComplete={handleAnalysisComplete}
            analysisStatus={analysisStatusProp}
          />
        )}
      </main>
    </div>
  );
}

export default App;
