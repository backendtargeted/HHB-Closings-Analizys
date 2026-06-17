import { useState, useEffect } from 'react';
import AnalysisResults from './components/AnalysisResults';
import MethodologySection from './components/MethodologySection';
import ModeSwitcher, { type GateMode } from './components/ModeSwitcher';
import PastPatchesGuide from './components/PastPatchesGuide';
import PastPatchesWorkspace from './components/PastPatchesWorkspace';
import QualifiedLeadsResults from './components/QualifiedLeadsResults';
import MonthlyConsolidatedWorkspace from './components/MonthlyConsolidatedWorkspace';
import MonthlyConsolidatedResults from './components/MonthlyConsolidatedResults';
import MarketingRampWorkspace from './components/MarketingRampWorkspace';
import MarketingRampResults from './components/MarketingRampResults';
import SavedReports, { SavedReportsPanel } from './components/SavedReports';
import {
  downloadQualifiedLeadsExport,
  downloadMonthlyConsolidatedExport,
  downloadMarketingRampExport,
  getAnalysisResults,
  getQualifiedLeadsJob,
  getMonthlyConsolidatedJob,
  getMarketingRampJob,
} from './services/api';
import type { AnalysisCompleteResponse } from './types/analysis';
import type { QualifiedLeadsAnalyzeResponse } from './types/qualifiedLeads';
import type { MonthlyConsolidatedCompletedResponse } from './types/monthlyConsolidated';
import { asMonthlyConsolidatedCompleted } from './types/monthlyConsolidated';
import type { MarketingRampCompletedResponse } from './types/marketingRamp';
import { asMarketingRampCompleted } from './types/marketingRamp';

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
    reportType?: 'attribution' | 'qualified_leads' | 'monthly_consolidated' | 'marketing_ramp'
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

  const [gate, setGate] = useState<GateMode>('monthlyConsolidated');
  const [loadedSavedReport, setLoadedSavedReport] = useState<AnalysisCompleteResponse | null>(null);
  const [loadedQualifiedReport, setLoadedQualifiedReport] =
    useState<QualifiedLeadsAnalyzeResponse | null>(null);
  const [loadedMonthlyReport, setLoadedMonthlyReport] =
    useState<MonthlyConsolidatedCompletedResponse | null>(null);
  const [loadedMarketingReport, setLoadedMarketingReport] =
    useState<MarketingRampCompletedResponse | null>(null);
  const [savedReportsRefresh, setSavedReportsRefresh] = useState(0);
  const [qlExporting, setQlExporting] = useState(false);
  const [mcrExporting, setMcrExporting] = useState(false);
  const [mrExporting, setMrExporting] = useState(false);

  const showQualifiedResults = loadedQualifiedReport !== null;
  const showMonthlyResults = loadedMonthlyReport !== null;
  const showMarketingResults = loadedMarketingReport !== null;
  const showLegacyAttribution = loadedSavedReport !== null;

  const handleNewRun = () => {
    setLoadedSavedReport(null);
    setLoadedQualifiedReport(null);
    setLoadedMonthlyReport(null);
    setLoadedMarketingReport(null);
    setGate('monthlyConsolidated');
    setReportQueryParam(null);
  };

  const handleOpenSavedReport = (data: AnalysisCompleteResponse) => {
    setLoadedSavedReport(data);
    setLoadedQualifiedReport(null);
    setLoadedMonthlyReport(null);
    setLoadedMarketingReport(null);
    setReportQueryParam(data.job_id, 'attribution');
  };

  const handleOpenQualifiedReport = (data: QualifiedLeadsAnalyzeResponse) => {
    setLoadedQualifiedReport(data);
    setLoadedSavedReport(null);
    setLoadedMonthlyReport(null);
    setLoadedMarketingReport(null);
    setReportQueryParam(data.job_id, 'qualified_leads');
  };

  const handleOpenMonthlyReport = (data: MonthlyConsolidatedCompletedResponse) => {
    setLoadedMonthlyReport(data);
    setLoadedSavedReport(null);
    setLoadedQualifiedReport(null);
    setLoadedMarketingReport(null);
    setGate('monthlyConsolidated');
    setReportQueryParam(data.job_id, 'monthly_consolidated');
  };

  const handleOpenMarketingReport = (data: MarketingRampCompletedResponse) => {
    setLoadedMarketingReport(data);
    setLoadedSavedReport(null);
    setLoadedQualifiedReport(null);
    setLoadedMonthlyReport(null);
    setGate('marketingRamp');
    setReportQueryParam(data.job_id, 'marketing_ramp');
  };

  const handleMonthlyRunComplete = () => {
    setSavedReportsRefresh((k) => k + 1);
  };

  const handleMarketingRunComplete = () => {
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

  const handleExportMarketing = async (jobId: string) => {
    setMrExporting(true);
    try {
      const hasConsolidated = Boolean(loadedMarketingReport?.consolidated);
      const format = hasConsolidated ? 'xlsx' : 'csv';
      const blob = await downloadMarketingRampExport(jobId, { format });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download =
        format === 'xlsx' ? `monthly_report_${jobId}.xlsx` : `marketing_ramp_${jobId}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert('Export failed');
    } finally {
      setMrExporting(false);
    }
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

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const reportId = params.get('report');
    if (!reportId) return;

    const reportType = params.get('type');
    let isCancelled = false;
    const loadSharedReport = async () => {
      const tryLoad = async () => {
        if (reportType === 'qualified_leads') {
          return { kind: 'qualified_leads' as const, data: await getQualifiedLeadsJob(reportId) };
        }
        if (reportType === 'monthly_consolidated') {
          return {
            kind: 'monthly_consolidated' as const,
            data: asMonthlyConsolidatedCompleted(await getMonthlyConsolidatedJob(reportId)),
          };
        }
        if (reportType === 'marketing_ramp') {
          return {
            kind: 'marketing_ramp' as const,
            data: asMarketingRampCompleted(await getMarketingRampJob(reportId)),
          };
        }
        if (reportType === 'attribution') {
          return { kind: 'attribution' as const, data: await getAnalysisResults(reportId) };
        }
        try {
          return {
            kind: 'marketing_ramp' as const,
            data: asMarketingRampCompleted(await getMarketingRampJob(reportId)),
          };
        } catch {
          try {
            return {
              kind: 'monthly_consolidated' as const,
              data: asMonthlyConsolidatedCompleted(await getMonthlyConsolidatedJob(reportId)),
            };
          } catch {
            try {
              return { kind: 'qualified_leads' as const, data: await getQualifiedLeadsJob(reportId) };
            } catch {
              return { kind: 'attribution' as const, data: await getAnalysisResults(reportId) };
            }
          }
        }
      };
      try {
        const loaded = await tryLoad();
        if (isCancelled) return;
        if (loaded.kind === 'qualified_leads') {
          setLoadedQualifiedReport(loaded.data);
        } else if (loaded.kind === 'monthly_consolidated') {
          setLoadedMonthlyReport(loaded.data);
          setGate('monthlyConsolidated');
        } else if (loaded.kind === 'marketing_ramp') {
          setLoadedMarketingReport(loaded.data);
          setGate('marketingRamp');
        } else {
          setLoadedSavedReport(loaded.data);
        }
      } catch {
        // Invalid/missing report IDs are ignored so the landing flow still works.
      }
    };
    loadSharedReport();

    return () => {
      isCancelled = true;
    };
  }, []);

  const showWorkflowPicker =
    !showMonthlyResults && !showQualifiedResults && !showLegacyAttribution && !showMarketingResults;

  const showAnyReport =
    showMarketingResults || showMonthlyResults || showQualifiedResults || showLegacyAttribution;

  const workspaceTabId =
    gate === 'pastPatches' ? 'tab-gate1' : gate === 'marketingRamp' ? 'tab-gate3' : 'tab-gate2';

  const savedReportsSidebar = (
    <aside className="rounded-2xl border border-stone-200/90 bg-white shadow-sm p-5 h-fit lg:sticky lg:top-6">
      <SavedReports
        onOpenAttributionReport={handleOpenSavedReport}
        onOpenQualifiedLeadsReport={handleOpenQualifiedReport}
        onOpenMonthlyConsolidatedReport={handleOpenMonthlyReport}
        onOpenMarketingRampReport={handleOpenMarketingReport}
        refreshKey={savedReportsRefresh}
      />
    </aside>
  );

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
              <h1 className="text-3xl font-bold text-white drop-shadow-sm">HHB Marketing Reports</h1>
              <p className="text-gray-200 mt-1">
                Gate 1: ingest monthly data · Gate 2: consolidated report · Gate 3: marketing ramp
              </p>
            </div>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8 max-w-7xl">
        {showWorkflowPicker && (
          <>
            <ModeSwitcher mode={gate} onChange={setGate} />
            {gate === 'pastPatches' ? <PastPatchesGuide /> : null}
          </>
        )}
        <div className="mb-6">
          {!showAnyReport ? <MethodologySection /> : null}
        </div>
        {showMarketingResults && loadedMarketingReport ? (
          <div className="space-y-6">
            <MarketingRampResults
              result={loadedMarketingReport}
              channelLabels={QL_CHANNEL_LABELS}
              onNewRun={handleNewRun}
              onExport={() => handleExportMarketing(loadedMarketingReport.job_id)}
              exporting={mrExporting}
            />
            <SavedReportsPanel
              onOpenAttributionReport={handleOpenSavedReport}
              onOpenQualifiedLeadsReport={handleOpenQualifiedReport}
              onOpenMonthlyConsolidatedReport={handleOpenMonthlyReport}
              onOpenMarketingRampReport={handleOpenMarketingReport}
              refreshKey={savedReportsRefresh}
            />
          </div>
        ) : showMonthlyResults && loadedMonthlyReport ? (
          <div className="space-y-6">
            <MonthlyConsolidatedResults
              result={loadedMonthlyReport}
              channelLabels={QL_CHANNEL_LABELS}
              onNewRun={handleNewRun}
              onExport={() => handleExportMonthly(loadedMonthlyReport.job_id)}
              exporting={mcrExporting}
            />
            <SavedReportsPanel
              onOpenAttributionReport={handleOpenSavedReport}
              onOpenQualifiedLeadsReport={handleOpenQualifiedReport}
              onOpenMonthlyConsolidatedReport={handleOpenMonthlyReport}
              onOpenMarketingRampReport={handleOpenMarketingReport}
              refreshKey={savedReportsRefresh}
            />
          </div>
        ) : showQualifiedResults && loadedQualifiedReport ? (
          <div className="space-y-6">
            <p className="text-xs text-stone-500 uppercase tracking-wide">Legacy saved report</p>
            <QualifiedLeadsResults
              result={loadedQualifiedReport}
              channelLabels={QL_CHANNEL_LABELS}
              onNewRun={handleNewRun}
              onExportRows={() => handleExportQualifiedRows(loadedQualifiedReport.job_id)}
              exporting={qlExporting}
            />
            <SavedReportsPanel
              onOpenAttributionReport={handleOpenSavedReport}
              onOpenQualifiedLeadsReport={handleOpenQualifiedReport}
              onOpenMonthlyConsolidatedReport={handleOpenMonthlyReport}
              onOpenMarketingRampReport={handleOpenMarketingReport}
              refreshKey={savedReportsRefresh}
            />
          </div>
        ) : showLegacyAttribution && loadedSavedReport ? (
          <div className="space-y-6">
            <p className="text-xs text-stone-500 uppercase tracking-wide">Legacy saved report</p>
            <AnalysisResults results={loadedSavedReport} onNewAnalysis={handleNewRun} />
            <SavedReportsPanel
              onOpenAttributionReport={handleOpenSavedReport}
              onOpenQualifiedLeadsReport={handleOpenQualifiedReport}
              onOpenMonthlyConsolidatedReport={handleOpenMonthlyReport}
              onOpenMarketingRampReport={handleOpenMarketingReport}
              refreshKey={savedReportsRefresh}
            />
          </div>
        ) : (
          <div
            id="panel-workspace"
            role="tabpanel"
            aria-labelledby={workspaceTabId}
            className="grid grid-cols-1 lg:grid-cols-3 gap-6 lg:gap-8"
          >
            <div className="lg:col-span-2 min-w-0">
              {gate === 'pastPatches' ? (
                <PastPatchesWorkspace />
              ) : gate === 'marketingRamp' ? (
                <MarketingRampWorkspace
                  onRunComplete={handleMarketingRunComplete}
                  onOpenResult={handleOpenMarketingReport}
                />
              ) : (
                <MonthlyConsolidatedWorkspace
                  channelLabels={QL_CHANNEL_LABELS}
                  onRunComplete={handleMonthlyRunComplete}
                  onOpenResult={handleOpenMonthlyReport}
                />
              )}
            </div>
            {savedReportsSidebar}
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
