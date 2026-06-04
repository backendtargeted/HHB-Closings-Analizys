import { useState, useEffect } from 'react';
import FileUpload from './components/FileUpload';
import AnalysisResults from './components/AnalysisResults';
import MethodologySection from './components/MethodologySection';
import ModeSwitcher, { type WorkspaceMode } from './components/ModeSwitcher';
import PastPatchesGuide from './components/PastPatchesGuide';
import PastPatchesWorkspace from './components/PastPatchesWorkspace';
import QualifiedLeadsWorkspace from './components/QualifiedLeadsWorkspace';
import QualifiedLeadsResults from './components/QualifiedLeadsResults';
import MonthlyConsolidatedWorkspace from './components/MonthlyConsolidatedWorkspace';
import MonthlyConsolidatedResults from './components/MonthlyConsolidatedResults';
import SavedReports from './components/SavedReports';
import {
  downloadQualifiedLeadsExport,
  downloadMonthlyConsolidatedExport,
  getAnalysisResults,
  getQualifiedLeadsJob,
  getMonthlyConsolidatedJob,
} from './services/api';
import { useAnalysis } from './hooks/useAnalysis';
import type { AnalysisCompleteResponse } from './types/analysis';
import type { QualifiedLeadsAnalyzeResponse } from './types/qualifiedLeads';
import type { MonthlyConsolidatedCompletedResponse } from './types/monthlyConsolidated';
import { asMonthlyConsolidatedCompleted } from './types/monthlyConsolidated';

const QL_CHANNEL_LABELS: Record<string, string> = {
  CC: 'Cold Calling',
  SMS: 'SMS (incl. RES-VA SMS)',
  DM: 'Direct Mail',
  Website: 'Website',
  PPC: 'PPC',
  SEO: 'SEO',
  Other: 'Other',
};

function App() {
  const setReportQueryParam = (
    jobId: string | null,
    reportType?: 'attribution' | 'qualified_leads' | 'monthly_consolidated'
  ) => {
    const url = new URL(window.location.href);
    if (jobId) {
      url.searchParams.set('report', jobId);
      if (reportType) {
        url.searchParams.set('type', reportType);
      }
    } else {
      url.searchParams.delete('report');
      url.searchParams.delete('type');
    }
    window.history.replaceState({}, '', url.toString());
  };

  const [workspace, setWorkspace] = useState<WorkspaceMode>('regular');
  const [analysisComplete, setAnalysisComplete] = useState(false);
  const [loadedSavedReport, setLoadedSavedReport] = useState<AnalysisCompleteResponse | null>(null);
  const [loadedQualifiedReport, setLoadedQualifiedReport] =
    useState<QualifiedLeadsAnalyzeResponse | null>(null);
  const [loadedMonthlyReport, setLoadedMonthlyReport] =
    useState<MonthlyConsolidatedCompletedResponse | null>(null);
  const [savedReportsRefresh, setSavedReportsRefresh] = useState(0);
  const [qlExporting, setQlExporting] = useState(false);
  const [mcrExporting, setMcrExporting] = useState(false);
  const {
    runAnalysis,
    progress,
    statusMessage,
    analysisResults,
    analysisStatus,
    resumableUpload,
    isLoading,
    isError,
    error,
  } = useAnalysis();

  const resultsWithStatus = analysisResults as AnalysisCompleteResponse | undefined;
  const analysisStatusProp = analysisStatus?.status ?? resultsWithStatus?.status;
  const displayResults = analysisResults ?? loadedSavedReport ?? null;
  const showQualifiedResults = loadedQualifiedReport !== null;
  const showMonthlyResults = loadedMonthlyReport !== null;

  const handleAnalysisComplete = () => {
    setAnalysisComplete(true);
    setLoadedSavedReport(null);
    if (analysisResults?.job_id) {
      setReportQueryParam(analysisResults.job_id);
    }
  };

  const handleNewAnalysis = () => {
    setAnalysisComplete(false);
    setLoadedSavedReport(null);
    setLoadedQualifiedReport(null);
    setLoadedMonthlyReport(null);
    setWorkspace('regular');
    setReportQueryParam(null);
  };

  const handleOpenSavedReport = (data: AnalysisCompleteResponse) => {
    setLoadedSavedReport(data);
    setLoadedQualifiedReport(null);
    setLoadedMonthlyReport(null);
    setAnalysisComplete(true);
    setReportQueryParam(data.job_id, 'attribution');
  };

  const handleOpenQualifiedReport = (data: QualifiedLeadsAnalyzeResponse) => {
    setLoadedQualifiedReport(data);
    setLoadedSavedReport(null);
    setLoadedMonthlyReport(null);
    setAnalysisComplete(false);
    setWorkspace('qualifiedLeads');
    setReportQueryParam(data.job_id, 'qualified_leads');
  };

  const handleOpenMonthlyReport = (data: MonthlyConsolidatedCompletedResponse) => {
    setLoadedMonthlyReport(data);
    setLoadedSavedReport(null);
    setLoadedQualifiedReport(null);
    setAnalysisComplete(false);
    setWorkspace('monthlyConsolidated');
    setReportQueryParam(data.job_id, 'monthly_consolidated');
  };

  const handleMonthlyRunComplete = () => {
    setSavedReportsRefresh((k) => k + 1);
  };

  const handleExportMonthly = async (jobId: string) => {
    setMcrExporting(true);
    try {
      const blob = await downloadMonthlyConsolidatedExport(jobId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `monthly_consolidated_${jobId}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert('Export failed');
    } finally {
      setMcrExporting(false);
    }
  };

  const handleQualifiedRunComplete = () => {
    setSavedReportsRefresh((k) => k + 1);
  };

  const handleExportQualifiedRows = async (jobId: string) => {
    setQlExporting(true);
    try {
      const blob = await downloadQualifiedLeadsExport(jobId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `qualified_leads_rows_${jobId}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert('Export failed');
    } finally {
      setQlExporting(false);
    }
  };

  // Auto-show results when analysis completes
  useEffect(() => {
    if (analysisResults?.status === 'completed') {
      setAnalysisComplete(true);
      setLoadedSavedReport(null);
      setReportQueryParam(analysisResults.job_id);
    }
  }, [analysisResults]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const reportId = params.get('report');
    if (!reportId) return;

    const reportType = params.get('type');
    let isCancelled = false;
    const loadSharedReport = async () => {
      try {
        if (reportType === 'qualified_leads') {
          const data = await getQualifiedLeadsJob(reportId);
          if (!isCancelled) {
            setLoadedQualifiedReport(data);
            setWorkspace('qualifiedLeads');
          }
        } else if (reportType === 'monthly_consolidated') {
          const data = asMonthlyConsolidatedCompleted(await getMonthlyConsolidatedJob(reportId));
          if (!isCancelled) {
            setLoadedMonthlyReport(data);
            setWorkspace('monthlyConsolidated');
          }
        } else {
          const data = await getAnalysisResults(reportId);
          if (!isCancelled) {
            setLoadedSavedReport(data);
            setAnalysisComplete(true);
          }
        }
      } catch {
        // Invalid/missing report IDs are ignored so the regular landing flow still works.
      }
    };
    loadSharedReport();

    return () => {
      isCancelled = true;
    };
  }, []);

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
        {!analysisComplete && !displayResults && !showQualifiedResults && !showMonthlyResults && (
          <>
            <ModeSwitcher mode={workspace} onChange={setWorkspace} />
            {workspace === 'pastPatches' ? (
              <PastPatchesGuide />
            ) : workspace === 'qualifiedLeads' ? (
              <p className="text-sm text-stone-500 -mt-4 mb-6 leading-relaxed max-w-3xl">
                Upload your Salesforce <strong>Total Qualified Leads</strong> export for channel counts
                and mix by <strong>Create Date</strong>. This does not replace{' '}
                <button
                  type="button"
                  onClick={() => setWorkspace('regular')}
                  className="font-semibold text-navy underline decoration-navy/30 underline-offset-2"
                >
                  regular analysis
                </button>{' '}
                or{' '}
                <button
                  type="button"
                  onClick={() => setWorkspace('pastPatches')}
                  className="font-semibold text-amber-900 underline underline-offset-2"
                >
                  Past patches
                </button>
                .
              </p>
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
                —or{' '}
                <button
                  type="button"
                  onClick={() => setWorkspace('qualifiedLeads')}
                  className="font-semibold text-teal-800 underline underline-offset-2"
                >
                  Qualified leads
                </button>{' '}
                for a one-time SF channel mix report.
              </p>
            )}
          </>
        )}
        <div className="mb-6">
          <MethodologySection />
        </div>
        {showMonthlyResults && loadedMonthlyReport ? (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 lg:gap-8">
            <div className="lg:col-span-2 min-w-0">
              <MonthlyConsolidatedResults
                result={loadedMonthlyReport}
                channelLabels={QL_CHANNEL_LABELS}
                onNewRun={() => {
                  setLoadedMonthlyReport(null);
                  setReportQueryParam(null);
                }}
                onExport={() => handleExportMonthly(loadedMonthlyReport.job_id)}
                exporting={mcrExporting}
              />
            </div>
            <aside className="rounded-2xl border border-stone-200/90 bg-white shadow-sm p-5 h-fit lg:sticky lg:top-6">
              <SavedReports
                onOpenAttributionReport={handleOpenSavedReport}
                onOpenQualifiedLeadsReport={handleOpenQualifiedReport}
                onOpenMonthlyConsolidatedReport={handleOpenMonthlyReport}
                refreshKey={savedReportsRefresh}
              />
            </aside>
          </div>
        ) : showQualifiedResults && loadedQualifiedReport ? (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 lg:gap-8">
            <div className="lg:col-span-2 min-w-0">
              <QualifiedLeadsResults
                result={loadedQualifiedReport}
                channelLabels={QL_CHANNEL_LABELS}
                onNewRun={() => {
                  setLoadedQualifiedReport(null);
                  setReportQueryParam(null);
                }}
                onExportRows={() => handleExportQualifiedRows(loadedQualifiedReport.job_id)}
                exporting={qlExporting}
              />
            </div>
            <aside className="rounded-2xl border border-stone-200/90 bg-white shadow-sm p-5 h-fit lg:sticky lg:top-6">
              <SavedReports
                onOpenAttributionReport={handleOpenSavedReport}
                onOpenQualifiedLeadsReport={handleOpenQualifiedReport}
                onOpenMonthlyConsolidatedReport={handleOpenMonthlyReport}
                refreshKey={savedReportsRefresh}
              />
            </aside>
          </div>
        ) : !analysisComplete && !displayResults ? (
          <div
            id="panel-workspace"
            role="tabpanel"
            aria-labelledby={
              workspace === 'regular'
                ? 'tab-regular'
                : workspace === 'pastPatches'
                  ? 'tab-past'
                  : workspace === 'qualifiedLeads'
                    ? 'tab-qualified'
                    : 'tab-monthly'
            }
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
                  resumableUpload={resumableUpload}
                />
              ) : workspace === 'pastPatches' ? (
                <PastPatchesWorkspace />
              ) : workspace === 'qualifiedLeads' ? (
                <QualifiedLeadsWorkspace
                  onRunComplete={handleQualifiedRunComplete}
                  onOpenResult={handleOpenQualifiedReport}
                />
              ) : (
                <MonthlyConsolidatedWorkspace
                  channelLabels={QL_CHANNEL_LABELS}
                  onRunComplete={handleMonthlyRunComplete}
                  onOpenResult={handleOpenMonthlyReport}
                />
              )}
            </div>
            <aside className="rounded-2xl border border-stone-200/90 bg-white shadow-sm p-5 h-fit lg:sticky lg:top-6">
              <SavedReports
                onOpenAttributionReport={handleOpenSavedReport}
                onOpenQualifiedLeadsReport={handleOpenQualifiedReport}
                onOpenMonthlyConsolidatedReport={handleOpenMonthlyReport}
                refreshKey={savedReportsRefresh}
              />
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
                resumableUpload={resumableUpload}
              />
            </div>
            <aside className="rounded-2xl border border-stone-200/90 bg-white shadow-sm p-5 h-fit">
              <SavedReports
                onOpenAttributionReport={handleOpenSavedReport}
                onOpenQualifiedLeadsReport={handleOpenQualifiedReport}
                onOpenMonthlyConsolidatedReport={handleOpenMonthlyReport}
                refreshKey={savedReportsRefresh}
              />
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
