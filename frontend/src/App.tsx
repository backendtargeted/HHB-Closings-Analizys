import { useState, useEffect } from 'react';
import FileUpload from './components/FileUpload';
import AnalysisResults from './components/AnalysisResults';
import MethodologySection from './components/MethodologySection';
import ModeSwitcher, { type WorkspaceMode } from './components/ModeSwitcher';
import PastPatchesGuide from './components/PastPatchesGuide';
import PastPatchesWorkspace from './components/PastPatchesWorkspace';
import SavedReports from './components/SavedReports';
import { useAnalysis } from './hooks/useAnalysis';
import type { AnalysisCompleteResponse } from './types/analysis';

function App() {
  const [workspace, setWorkspace] = useState<WorkspaceMode>('regular');
  const [analysisComplete, setAnalysisComplete] = useState(false);
  const [loadedSavedReport, setLoadedSavedReport] = useState<AnalysisCompleteResponse | null>(null);
  const {
    runAnalysis,
    progress,
    statusMessage,
    analysisResults,
    analysisStatus,
    presignedUpload,
    isLoading,
    isError,
    error,
  } = useAnalysis();

  const resultsWithStatus = analysisResults as AnalysisCompleteResponse | undefined;
  const analysisStatusProp = analysisStatus?.status ?? resultsWithStatus?.status;
  const displayResults = analysisResults ?? loadedSavedReport ?? null;

  const handleAnalysisComplete = () => {
    setAnalysisComplete(true);
    setLoadedSavedReport(null);
  };

  const handleNewAnalysis = () => {
    setAnalysisComplete(false);
    setLoadedSavedReport(null);
    setWorkspace('regular');
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

      <main className="container mx-auto px-4 py-8 max-w-7xl">
        {!analysisComplete && !displayResults && (
          <>
            <ModeSwitcher mode={workspace} onChange={setWorkspace} />
            {workspace === 'pastPatches' ? (
              <PastPatchesGuide />
            ) : (
              <p className="text-sm text-stone-500 -mt-4 mb-6 leading-relaxed max-w-3xl">
                Need to build REISift import CSVs from cold calling + SMS + CRM + closings? Use{' '}
                <button
                  type="button"
                  onClick={() => setWorkspace('pastPatches')}
                  className="font-semibold text-navy underline decoration-navy/30 underline-offset-2 hover:decoration-navy"
                >
                  Past patches
                </button>
                —then import into REISift and come back here for regular analysis.
              </p>
            )}
          </>
        )}
        <div className="mb-6">
          <MethodologySection />
        </div>
        {!analysisComplete && !displayResults ? (
          <div
            id="panel-workspace"
            role="tabpanel"
            aria-labelledby={workspace === 'regular' ? 'tab-regular' : 'tab-past'}
            className="grid grid-cols-1 lg:grid-cols-3 gap-6 lg:gap-8"
          >
            <div className="lg:col-span-2 min-w-0">
              {workspace === 'regular' ? (
                <FileUpload
                  onUpload={runAnalysis}
                  isLoading={isLoading}
                  progress={progress}
                  statusMessage={statusMessage}
                  isError={isError}
                  error={error}
                  onComplete={handleAnalysisComplete}
                  analysisStatus={analysisStatusProp}
                  presignedUpload={presignedUpload}
                />
              ) : (
                <PastPatchesWorkspace />
              )}
            </div>
            <aside className="rounded-2xl border border-stone-200/90 bg-white shadow-sm p-5 h-fit lg:sticky lg:top-6">
              <SavedReports onOpenReport={handleOpenSavedReport} />
            </aside>
          </div>
        ) : displayResults ? (
          <AnalysisResults
            results={displayResults}
            onNewAnalysis={handleNewAnalysis}
          />
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 lg:gap-8">
            <div className="lg:col-span-2 min-w-0">
              <FileUpload
                onUpload={runAnalysis}
                isLoading={isLoading}
                progress={progress}
                statusMessage={statusMessage}
                isError={isError}
                error={error}
                onComplete={handleAnalysisComplete}
                analysisStatus={analysisStatusProp}
                presignedUpload={presignedUpload}
              />
            </div>
            <aside className="rounded-2xl border border-stone-200/90 bg-white shadow-sm p-5 h-fit">
              <SavedReports onOpenReport={handleOpenSavedReport} />
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
