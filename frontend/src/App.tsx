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
import WebLeadsWorkspace from './components/WebLeadsWorkspace';
import WebLeadsResults from './components/WebLeadsResults';
import ProbateWorkspace from './components/ProbateWorkspace';
import ProbateResults from './components/ProbateResults';
import SoldPropertiesWorkspace from './components/SoldPropertiesWorkspace';
import SoldPropertiesResults from './components/SoldPropertiesResults';
import CourtAlertsWorkspace from './components/CourtAlertsWorkspace';
import CourtAlertsResults from './components/CourtAlertsResults';
import SavedReports, { SavedReportsPanel } from './components/SavedReports';
import {
  downloadQualifiedLeadsExport,
  downloadMonthlyConsolidatedExport,
  downloadMarketingRampExport,
  downloadWebLeadsExport,
  downloadProbateExport,
  downloadSoldPropertiesExport,
  downloadCourtAlertsExport,
  getAnalysisResults,
  getQualifiedLeadsJob,
  getMonthlyConsolidatedJob,
  getMarketingRampJob,
  getWebLeadsJob,
  getProbateJob,
  getSoldPropertiesJob,
  getCourtAlertsJob,
  listReports,
} from './services/api';
import type { AnalysisCompleteResponse } from './types/analysis';
import type { QualifiedLeadsAnalyzeResponse } from './types/qualifiedLeads';
import type { MonthlyConsolidatedCompletedResponse } from './types/monthlyConsolidated';
import { asMonthlyConsolidatedCompleted } from './types/monthlyConsolidated';
import type { MarketingRampCompletedResponse } from './types/marketingRamp';
import { asMarketingRampCompleted } from './types/marketingRamp';
import type { WebLeadsCompletedResponse } from './types/webLeads';
import { asWebLeadsCompleted } from './types/webLeads';
import type { ProbateCompletedResponse } from './types/probate';
import { asProbateCompleted } from './types/probate';
import type { SoldPropertiesCompletedResponse } from './types/soldProperties';
import { asSoldPropertiesCompleted } from './types/soldProperties';
import type { CourtAlertsCompletedResponse } from './types/courtAlerts';
import { asCourtAlertsCompleted } from './types/courtAlerts';

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
    reportType?: 'attribution' | 'qualified_leads' | 'monthly_consolidated' | 'marketing_ramp' | 'web_leads' | 'probate' | 'sold_properties' | 'court_alerts'
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

  const [gate, setGate] = useState<GateMode>('probate');
  const [loadedSavedReport, setLoadedSavedReport] = useState<AnalysisCompleteResponse | null>(null);
  const [loadedQualifiedReport, setLoadedQualifiedReport] =
    useState<QualifiedLeadsAnalyzeResponse | null>(null);
  const [loadedMonthlyReport, setLoadedMonthlyReport] =
    useState<MonthlyConsolidatedCompletedResponse | null>(null);
  const [loadedMarketingReport, setLoadedMarketingReport] =
    useState<MarketingRampCompletedResponse | null>(null);
  const [loadedWebLeadsReport, setLoadedWebLeadsReport] =
    useState<WebLeadsCompletedResponse | null>(null);
  const [loadedProbateReport, setLoadedProbateReport] =
    useState<ProbateCompletedResponse | null>(null);
  const [loadedSoldPropertiesReport, setLoadedSoldPropertiesReport] =
    useState<SoldPropertiesCompletedResponse | null>(null);
  const [loadedCourtAlertsReport, setLoadedCourtAlertsReport] =
    useState<CourtAlertsCompletedResponse | null>(null);
  const [savedReportsRefresh, setSavedReportsRefresh] = useState(0);
  const [qlExporting, setQlExporting] = useState(false);
  const [mcrExporting, setMcrExporting] = useState(false);
  const [mrExporting, setMrExporting] = useState(false);
  const [wlExporting, setWlExporting] = useState(false);
  const [pbExporting, setPbExporting] = useState(false);
  const [spExporting, setSpExporting] = useState(false);
  const [caExporting, setCaExporting] = useState(false);

  const showQualifiedResults = loadedQualifiedReport !== null;
  const showMonthlyResults = loadedMonthlyReport !== null;
  const showMarketingResults = loadedMarketingReport !== null;
  const showWebLeadsResults = loadedWebLeadsReport !== null;
  const showProbateResults = loadedProbateReport !== null;
  const showSoldPropertiesResults = loadedSoldPropertiesReport !== null;
  const showCourtAlertsResults = loadedCourtAlertsReport !== null;
  const showLegacyAttribution = loadedSavedReport !== null;

  const handleNewRun = () => {
    setLoadedSavedReport(null);
    setLoadedQualifiedReport(null);
    setLoadedMonthlyReport(null);
    setLoadedMarketingReport(null);
    setLoadedWebLeadsReport(null);
    setLoadedProbateReport(null);
    setLoadedSoldPropertiesReport(null);
    setLoadedCourtAlertsReport(null);
    setReportQueryParam(null);
  };

  const handleOpenSavedReport = (data: AnalysisCompleteResponse) => {
    setLoadedSavedReport(data);
    setLoadedQualifiedReport(null);
    setLoadedMonthlyReport(null);
    setLoadedMarketingReport(null);
    setLoadedWebLeadsReport(null);
    setLoadedProbateReport(null);
    setLoadedSoldPropertiesReport(null);
    setLoadedCourtAlertsReport(null);
    setReportQueryParam(data.job_id, 'attribution');
  };

  const handleOpenQualifiedReport = (data: QualifiedLeadsAnalyzeResponse) => {
    setLoadedQualifiedReport(data);
    setLoadedSavedReport(null);
    setLoadedMonthlyReport(null);
    setLoadedMarketingReport(null);
    setLoadedWebLeadsReport(null);
    setLoadedProbateReport(null);
    setLoadedSoldPropertiesReport(null);
    setLoadedCourtAlertsReport(null);
    setReportQueryParam(data.job_id, 'qualified_leads');
  };

  const handleOpenMonthlyReport = (data: MonthlyConsolidatedCompletedResponse) => {
    setLoadedMonthlyReport(data);
    setLoadedSavedReport(null);
    setLoadedQualifiedReport(null);
    setLoadedMarketingReport(null);
    setLoadedWebLeadsReport(null);
    setLoadedProbateReport(null);
    setLoadedSoldPropertiesReport(null);
    setLoadedCourtAlertsReport(null);
    setGate('monthlyConsolidated');
    setReportQueryParam(data.job_id, 'monthly_consolidated');
  };

  const handleOpenMarketingReport = (data: MarketingRampCompletedResponse) => {
    setLoadedMarketingReport(data);
    setLoadedSavedReport(null);
    setLoadedQualifiedReport(null);
    setLoadedMonthlyReport(null);
    setLoadedWebLeadsReport(null);
    setLoadedProbateReport(null);
    setLoadedSoldPropertiesReport(null);
    setLoadedCourtAlertsReport(null);
    setGate('marketingRamp');
    setReportQueryParam(data.job_id, 'marketing_ramp');
  };

  const handleOpenWebLeadsReport = (data: WebLeadsCompletedResponse) => {
    setLoadedWebLeadsReport(data);
    setLoadedSavedReport(null);
    setLoadedQualifiedReport(null);
    setLoadedMonthlyReport(null);
    setLoadedMarketingReport(null);
    setLoadedProbateReport(null);
    setLoadedSoldPropertiesReport(null);
    setLoadedCourtAlertsReport(null);
    setGate('webLeads');
    setReportQueryParam(data.job_id, 'web_leads');
  };

  const handleOpenProbateReport = (data: ProbateCompletedResponse) => {
    setLoadedProbateReport(data);
    setLoadedSavedReport(null);
    setLoadedQualifiedReport(null);
    setLoadedMonthlyReport(null);
    setLoadedMarketingReport(null);
    setLoadedWebLeadsReport(null);
    setLoadedSoldPropertiesReport(null);
    setLoadedCourtAlertsReport(null);
    setGate('probate');
    setReportQueryParam(data.job_id, 'probate');
  };

  const handleOpenSoldPropertiesReport = (data: SoldPropertiesCompletedResponse) => {
    setLoadedSoldPropertiesReport(data);
    setLoadedSavedReport(null);
    setLoadedQualifiedReport(null);
    setLoadedMonthlyReport(null);
    setLoadedMarketingReport(null);
    setLoadedWebLeadsReport(null);
    setLoadedProbateReport(null);
    setLoadedCourtAlertsReport(null);
    setGate('soldProperties');
    setReportQueryParam(data.job_id, 'sold_properties');
  };

  const handleOpenCourtAlertsReport = (data: CourtAlertsCompletedResponse) => {
    setLoadedCourtAlertsReport(data);
    setLoadedSavedReport(null);
    setLoadedQualifiedReport(null);
    setLoadedMonthlyReport(null);
    setLoadedMarketingReport(null);
    setLoadedWebLeadsReport(null);
    setLoadedProbateReport(null);
    setLoadedSoldPropertiesReport(null);
    setGate('courtAlerts');
    setReportQueryParam(data.job_id, 'court_alerts');
  };

  const handleProbateRunComplete = () => {
    setSavedReportsRefresh((k) => k + 1);
  };

  const handleSoldPropertiesRunComplete = () => {
    setSavedReportsRefresh((k) => k + 1);
  };

  const handleCourtAlertsRunComplete = () => {
    setSavedReportsRefresh((k) => k + 1);
  };

  const handleWebLeadsRunComplete = () => {
    setSavedReportsRefresh((k) => k + 1);
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

  const handleExportWebLeads = async (jobId: string) => {
    setWlExporting(true);
    try {
      const blob = await downloadWebLeadsExport(jobId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `web_leads_${jobId}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert('Export failed');
    } finally {
      setWlExporting(false);
    }
  };

  const handleExportProbate = async (jobId: string) => {
    setPbExporting(true);
    try {
      const blob = await downloadProbateExport(jobId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `probate_${jobId}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert('Export failed');
    } finally {
      setPbExporting(false);
    }
  };

  const handleExportSoldProperties = async (jobId: string) => {
    setSpExporting(true);
    try {
      const blob = await downloadSoldPropertiesExport(jobId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `sold_properties_${jobId}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert('Export failed');
    } finally {
      setSpExporting(false);
    }
  };

  const handleExportCourtAlerts = async (jobId: string) => {
    setCaExporting(true);
    try {
      const blob = await downloadCourtAlertsExport(jobId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `court_alerts_${jobId}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert('Export failed');
    } finally {
      setCaExporting(false);
    }
  };

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const reportId = params.get('report');
    const reportType = params.get('type');
    let isCancelled = false;

    const applyLoaded = (loaded: {
      kind:
        | 'qualified_leads'
        | 'monthly_consolidated'
        | 'marketing_ramp'
        | 'web_leads'
        | 'probate'
        | 'sold_properties'
        | 'court_alerts'
        | 'attribution';
      data: unknown;
    }) => {
      if (loaded.kind === 'qualified_leads') {
        setLoadedQualifiedReport(loaded.data as QualifiedLeadsAnalyzeResponse);
      } else if (loaded.kind === 'monthly_consolidated') {
        setLoadedMonthlyReport(loaded.data as MonthlyConsolidatedCompletedResponse);
        setGate('monthlyConsolidated');
      } else if (loaded.kind === 'marketing_ramp') {
        setLoadedMarketingReport(loaded.data as MarketingRampCompletedResponse);
        setGate('marketingRamp');
      } else if (loaded.kind === 'web_leads') {
        setLoadedWebLeadsReport(loaded.data as WebLeadsCompletedResponse);
        setGate('webLeads');
      } else if (loaded.kind === 'probate') {
        setLoadedProbateReport(loaded.data as ProbateCompletedResponse);
        setGate('probate');
      } else if (loaded.kind === 'sold_properties') {
        setLoadedSoldPropertiesReport(loaded.data as SoldPropertiesCompletedResponse);
        setGate('soldProperties');
      } else if (loaded.kind === 'court_alerts') {
        setLoadedCourtAlertsReport(loaded.data as CourtAlertsCompletedResponse);
        setGate('courtAlerts');
      } else {
        setLoadedSavedReport(loaded.data as AnalysisCompleteResponse);
      }
    };

    const tryLoad = async (id: string, type: string | null) => {
      if (type === 'qualified_leads') {
        return { kind: 'qualified_leads' as const, data: await getQualifiedLeadsJob(id) };
      }
      if (type === 'monthly_consolidated') {
        return {
          kind: 'monthly_consolidated' as const,
          data: asMonthlyConsolidatedCompleted(await getMonthlyConsolidatedJob(id)),
        };
      }
      if (type === 'marketing_ramp') {
        return {
          kind: 'marketing_ramp' as const,
          data: asMarketingRampCompleted(await getMarketingRampJob(id)),
        };
      }
      if (type === 'web_leads') {
        return {
          kind: 'web_leads' as const,
          data: asWebLeadsCompleted(await getWebLeadsJob(id)),
        };
      }
      if (type === 'probate') {
        return {
          kind: 'probate' as const,
          data: asProbateCompleted(await getProbateJob(id)),
        };
      }
      if (type === 'sold_properties') {
        return {
          kind: 'sold_properties' as const,
          data: asSoldPropertiesCompleted(await getSoldPropertiesJob(id)),
        };
      }
      if (type === 'court_alerts') {
        return {
          kind: 'court_alerts' as const,
          data: asCourtAlertsCompleted(await getCourtAlertsJob(id)),
        };
      }
      if (type === 'attribution') {
        return { kind: 'attribution' as const, data: await getAnalysisResults(id) };
      }
      try {
        return {
          kind: 'marketing_ramp' as const,
          data: asMarketingRampCompleted(await getMarketingRampJob(id)),
        };
      } catch {
        try {
          return {
            kind: 'monthly_consolidated' as const,
            data: asMonthlyConsolidatedCompleted(await getMonthlyConsolidatedJob(id)),
          };
        } catch {
          try {
            return { kind: 'qualified_leads' as const, data: await getQualifiedLeadsJob(id) };
          } catch {
            try {
              return {
                kind: 'probate' as const,
                data: asProbateCompleted(await getProbateJob(id)),
              };
            } catch {
              try {
                return {
                  kind: 'sold_properties' as const,
                  data: asSoldPropertiesCompleted(await getSoldPropertiesJob(id)),
                };
              } catch {
                try {
                  return {
                    kind: 'court_alerts' as const,
                    data: asCourtAlertsCompleted(await getCourtAlertsJob(id)),
                  };
                } catch {
                  return { kind: 'attribution' as const, data: await getAnalysisResults(id) };
                }
              }
            }
          }
        }
      }
    };

    const loadSharedReport = async () => {
      try {
        if (reportId) {
          const loaded = await tryLoad(reportId, reportType);
          if (isCancelled) return;
          applyLoaded(loaded);
          return;
        }
        const res = await listReports();
        const latest = (res.reports ?? []).find((r) => r.report_type === 'probate');
        if (!latest || isCancelled) return;
        const data = asProbateCompleted(await getProbateJob(latest.job_id));
        if (isCancelled) return;
        setLoadedProbateReport(data);
        setGate('probate');
        setReportQueryParam(data.job_id, 'probate');
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
    !showMonthlyResults &&
    !showQualifiedResults &&
    !showLegacyAttribution &&
    !showMarketingResults &&
    !showWebLeadsResults &&
    !showProbateResults &&
    !showSoldPropertiesResults &&
    !showCourtAlertsResults;

  const showAnyReport =
    showMarketingResults ||
    showMonthlyResults ||
    showQualifiedResults ||
    showLegacyAttribution ||
    showWebLeadsResults ||
    showProbateResults ||
    showSoldPropertiesResults ||
    showCourtAlertsResults;

  const workspaceTabId =
    gate === 'pastPatches'
      ? 'tab-gate1'
      : gate === 'marketingRamp'
        ? 'tab-gate3'
        : gate === 'webLeads'
          ? 'tab-gate4'
          : gate === 'probate'
            ? 'tab-gate5'
            : gate === 'soldProperties'
              ? 'tab-gate6'
              : gate === 'courtAlerts'
                ? 'tab-gate7'
                : 'tab-gate2';

  const savedReportsSidebar = (
    <aside className="rounded-2xl border border-stone-200/90 bg-white shadow-sm p-5 h-fit lg:sticky lg:top-6">
      <SavedReports
        onOpenAttributionReport={handleOpenSavedReport}
        onOpenQualifiedLeadsReport={handleOpenQualifiedReport}
        onOpenMonthlyConsolidatedReport={handleOpenMonthlyReport}
        onOpenMarketingRampReport={handleOpenMarketingReport}
        onOpenWebLeadsReport={handleOpenWebLeadsReport}
        onOpenProbateReport={handleOpenProbateReport}
        onOpenSoldPropertiesReport={handleOpenSoldPropertiesReport}
        onOpenCourtAlertsReport={handleOpenCourtAlertsReport}
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
                Gate 1: ingest · Gate 2: consolidated · Gate 3: marketing ramp · Gate 4: web leads ·
                Gate 5: probate · Gate 6: sold properties · Gate 7: court alerts
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
        {showCourtAlertsResults && loadedCourtAlertsReport ? (
          <div className="space-y-6">
            <CourtAlertsResults
              result={loadedCourtAlertsReport}
              onNewRun={handleNewRun}
              onExport={() => handleExportCourtAlerts(loadedCourtAlertsReport.job_id)}
              exporting={caExporting}
            />
            <SavedReportsPanel
              onOpenAttributionReport={handleOpenSavedReport}
              onOpenQualifiedLeadsReport={handleOpenQualifiedReport}
              onOpenMonthlyConsolidatedReport={handleOpenMonthlyReport}
              onOpenMarketingRampReport={handleOpenMarketingReport}
              onOpenWebLeadsReport={handleOpenWebLeadsReport}
              onOpenProbateReport={handleOpenProbateReport}
              onOpenSoldPropertiesReport={handleOpenSoldPropertiesReport}
              onOpenCourtAlertsReport={handleOpenCourtAlertsReport}
              refreshKey={savedReportsRefresh}
            />
          </div>
        ) : showSoldPropertiesResults && loadedSoldPropertiesReport ? (
          <div className="space-y-6">
            <SoldPropertiesResults
              result={loadedSoldPropertiesReport}
              onNewRun={handleNewRun}
              onExport={() => handleExportSoldProperties(loadedSoldPropertiesReport.job_id)}
              exporting={spExporting}
            />
            <SavedReportsPanel
              onOpenAttributionReport={handleOpenSavedReport}
              onOpenQualifiedLeadsReport={handleOpenQualifiedReport}
              onOpenMonthlyConsolidatedReport={handleOpenMonthlyReport}
              onOpenMarketingRampReport={handleOpenMarketingReport}
              onOpenWebLeadsReport={handleOpenWebLeadsReport}
              onOpenProbateReport={handleOpenProbateReport}
              onOpenSoldPropertiesReport={handleOpenSoldPropertiesReport}
              onOpenCourtAlertsReport={handleOpenCourtAlertsReport}
              refreshKey={savedReportsRefresh}
            />
          </div>
        ) : showProbateResults && loadedProbateReport ? (
          <div className="space-y-6">
            <ProbateResults
              result={loadedProbateReport}
              onNewRun={handleNewRun}
              onExport={() => handleExportProbate(loadedProbateReport.job_id)}
              exporting={pbExporting}
            />
            <SavedReportsPanel
              onOpenAttributionReport={handleOpenSavedReport}
              onOpenQualifiedLeadsReport={handleOpenQualifiedReport}
              onOpenMonthlyConsolidatedReport={handleOpenMonthlyReport}
              onOpenMarketingRampReport={handleOpenMarketingReport}
              onOpenWebLeadsReport={handleOpenWebLeadsReport}
              onOpenProbateReport={handleOpenProbateReport}
              onOpenSoldPropertiesReport={handleOpenSoldPropertiesReport}
              onOpenCourtAlertsReport={handleOpenCourtAlertsReport}
              refreshKey={savedReportsRefresh}
            />
          </div>
        ) : showWebLeadsResults && loadedWebLeadsReport ? (
          <div className="space-y-6">
            <WebLeadsResults
              result={loadedWebLeadsReport}
              onNewRun={handleNewRun}
              onExport={() => handleExportWebLeads(loadedWebLeadsReport.job_id)}
              exporting={wlExporting}
            />
            <SavedReportsPanel
              onOpenAttributionReport={handleOpenSavedReport}
              onOpenQualifiedLeadsReport={handleOpenQualifiedReport}
              onOpenMonthlyConsolidatedReport={handleOpenMonthlyReport}
              onOpenMarketingRampReport={handleOpenMarketingReport}
              onOpenWebLeadsReport={handleOpenWebLeadsReport}
              onOpenProbateReport={handleOpenProbateReport}
              onOpenSoldPropertiesReport={handleOpenSoldPropertiesReport}
              onOpenCourtAlertsReport={handleOpenCourtAlertsReport}
              refreshKey={savedReportsRefresh}
            />
          </div>
        ) : showMarketingResults && loadedMarketingReport ? (
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
              onOpenWebLeadsReport={handleOpenWebLeadsReport}
              onOpenProbateReport={handleOpenProbateReport}
              onOpenSoldPropertiesReport={handleOpenSoldPropertiesReport}
              onOpenCourtAlertsReport={handleOpenCourtAlertsReport}
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
              onOpenWebLeadsReport={handleOpenWebLeadsReport}
              onOpenProbateReport={handleOpenProbateReport}
              onOpenSoldPropertiesReport={handleOpenSoldPropertiesReport}
              onOpenCourtAlertsReport={handleOpenCourtAlertsReport}
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
              onOpenWebLeadsReport={handleOpenWebLeadsReport}
              onOpenProbateReport={handleOpenProbateReport}
              onOpenSoldPropertiesReport={handleOpenSoldPropertiesReport}
              onOpenCourtAlertsReport={handleOpenCourtAlertsReport}
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
              onOpenWebLeadsReport={handleOpenWebLeadsReport}
              onOpenProbateReport={handleOpenProbateReport}
              onOpenSoldPropertiesReport={handleOpenSoldPropertiesReport}
              onOpenCourtAlertsReport={handleOpenCourtAlertsReport}
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
              ) : gate === 'webLeads' ? (
                <WebLeadsWorkspace
                  onRunComplete={handleWebLeadsRunComplete}
                  onOpenResult={handleOpenWebLeadsReport}
                />
              ) : gate === 'probate' ? (
                <ProbateWorkspace
                  onRunComplete={handleProbateRunComplete}
                  onOpenResult={handleOpenProbateReport}
                />
              ) : gate === 'soldProperties' ? (
                <SoldPropertiesWorkspace
                  onRunComplete={handleSoldPropertiesRunComplete}
                  onOpenResult={handleOpenSoldPropertiesReport}
                />
              ) : gate === 'courtAlerts' ? (
                <CourtAlertsWorkspace
                  onRunComplete={handleCourtAlertsRunComplete}
                  onOpenResult={handleOpenCourtAlertsReport}
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
