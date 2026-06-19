import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  listReports,
  getAnalysisResults,
  getQualifiedLeadsJob,
  getMonthlyConsolidatedJob,
  getMarketingRampJob,
  getWebLeadsJob,
  deleteAnalysis,
  deleteQualifiedLeadsJob,
  deleteMonthlyConsolidatedJob,
  deleteMarketingRampJob,
  deleteWebLeadsJob,
} from '../services/api';
import type { AnalysisCompleteResponse } from '../types/analysis';
import type { QualifiedLeadsAnalyzeResponse } from '../types/qualifiedLeads';
import type { MonthlyConsolidatedCompletedResponse } from '../types/monthlyConsolidated';
import { asMonthlyConsolidatedCompleted } from '../types/monthlyConsolidated';
import type { MarketingRampCompletedResponse } from '../types/marketingRamp';
import { asMarketingRampCompleted } from '../types/marketingRamp';
import type { WebLeadsCompletedResponse } from '../types/webLeads';
import { asWebLeadsCompleted } from '../types/webLeads';
import type { SavedReportItem } from '../types/reports';

interface SavedReportsProps {
  onOpenAttributionReport: (data: AnalysisCompleteResponse) => void;
  onOpenQualifiedLeadsReport: (data: QualifiedLeadsAnalyzeResponse) => void;
  onOpenMonthlyConsolidatedReport?: (data: MonthlyConsolidatedCompletedResponse) => void;
  onOpenMarketingRampReport?: (data: MarketingRampCompletedResponse) => void;
  onOpenWebLeadsReport?: (data: WebLeadsCompletedResponse) => void;
  refreshKey?: number;
}

type ReportFilter = 'monthly' | 'legacy' | 'all';

const formatDate = (iso: string) => {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { dateStyle: 'medium' });
  } catch {
    return iso;
  }
};

const typeLabel = (t: SavedReportItem['report_type']) => {
  if (t === 'qualified_leads') return 'Qualified leads (legacy)';
  if (t === 'monthly_consolidated') return 'Monthly report';
  if (t === 'marketing_ramp') return 'Marketing ramp';
  if (t === 'web_leads') return 'Web leads';
  return 'Attribution (legacy)';
};

const SavedReports = ({
  onOpenAttributionReport,
  onOpenQualifiedLeadsReport,
  onOpenMonthlyConsolidatedReport,
  onOpenMarketingRampReport,
  onOpenWebLeadsReport,
  refreshKey = 0,
}: SavedReportsProps) => {
  const [reports, setReports] = useState<SavedReportItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [filter, setFilter] = useState<ReportFilter>('monthly');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listReports();
      setReports(res.reports ?? []);
    } catch {
      setReports([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const filteredReports = useMemo(() => {
    if (filter === 'all') return reports;
    if (filter === 'monthly') {
      return reports.filter(
        (r) =>
          r.report_type === 'monthly_consolidated' ||
          r.report_type === 'marketing_ramp' ||
          r.report_type === 'web_leads'
      );
    }
    return reports.filter(
      (r) =>
        r.report_type !== 'monthly_consolidated' &&
        r.report_type !== 'marketing_ramp' &&
        r.report_type !== 'web_leads'
    );
  }, [reports, filter]);

  const handleOpen = async (item: SavedReportItem) => {
    try {
      if (item.report_type === 'qualified_leads') {
        const data = await getQualifiedLeadsJob(item.job_id);
        onOpenQualifiedLeadsReport(data);
      } else if (item.report_type === 'marketing_ramp' && onOpenMarketingRampReport) {
        const data = asMarketingRampCompleted(await getMarketingRampJob(item.job_id));
        onOpenMarketingRampReport(data);
      } else if (item.report_type === 'marketing_ramp') {
        alert('Marketing ramp report handler not configured');
      } else if (item.report_type === 'web_leads' && onOpenWebLeadsReport) {
        const data = asWebLeadsCompleted(await getWebLeadsJob(item.job_id));
        onOpenWebLeadsReport(data);
      } else if (item.report_type === 'web_leads') {
        alert('Web leads report handler not configured');
      } else if (item.report_type === 'monthly_consolidated' && onOpenMonthlyConsolidatedReport) {
        const data = asMonthlyConsolidatedCompleted(await getMonthlyConsolidatedJob(item.job_id));
        onOpenMonthlyConsolidatedReport(data);
      } else if (item.report_type === 'monthly_consolidated') {
        alert('Monthly report handler not configured');
      } else {
        const data = await getAnalysisResults(item.job_id);
        onOpenAttributionReport(data);
      }
    } catch {
      alert('Failed to load report');
    }
  };

  const handleDelete = async (item: SavedReportItem) => {
    if (!confirm('Delete this saved report?')) return;
    setDeletingId(item.job_id);
    try {
      if (item.report_type === 'qualified_leads') {
        await deleteQualifiedLeadsJob(item.job_id);
      } else if (item.report_type === 'marketing_ramp') {
        await deleteMarketingRampJob(item.job_id);
      } else if (item.report_type === 'web_leads') {
        await deleteWebLeadsJob(item.job_id);
      } else if (item.report_type === 'monthly_consolidated') {
        await deleteMonthlyConsolidatedJob(item.job_id);
      } else {
        await deleteAnalysis(item.job_id);
      }
      await load();
    } catch {
      alert('Failed to delete report');
    } finally {
      setDeletingId(null);
    }
  };

  if (loading) {
    return <div className="text-stone-500 text-sm">Loading saved reports…</div>;
  }

  return (
    <div className="space-y-2">
      <div>
        <h3 className="text-sm font-semibold text-navy">Saved reports</h3>
        <p className="text-xs text-stone-500 mt-0.5 leading-snug">
          Stored under <code className="text-[10px]">data/reports</code> — kept across Docker rebuilds.
        </p>
      </div>
      <div className="flex gap-1 text-[10px] uppercase tracking-wide">
        {(['monthly', 'legacy', 'all'] as ReportFilter[]).map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => setFilter(f)}
            className={`px-2 py-1 rounded-md font-semibold ${
              filter === f ? 'bg-indigo-100 text-indigo-900' : 'text-stone-500 hover:bg-stone-100'
            }`}
          >
            {f === 'monthly' ? 'Monthly' : f === 'legacy' ? 'Legacy' : 'All'}
          </button>
        ))}
      </div>
      {filteredReports.length === 0 ? (
        <div className="text-stone-500 text-sm">
          {filter === 'monthly'
            ? 'No monthly workflow reports yet. Run Gate 2, Gate 3, or Gate 4 to save one.'
            : 'No reports in this filter.'}
        </div>
      ) : (
        <ul className="space-y-1 max-h-64 overflow-y-auto">
          {filteredReports.map((r) => (
            <li
              key={`${r.report_type}-${r.job_id}`}
              className="flex items-center justify-between gap-2 py-2 px-3 rounded-lg border border-stone-200 bg-surface hover:bg-stone-100/50"
            >
              <div className="min-w-0 flex-1">
                <p className="text-sm text-stone-700 truncate">{formatDate(r.created_at)}</p>
                <p className="text-xs font-medium text-stone-600 truncate">{r.summary}</p>
                <p className="text-[10px] text-stone-500 uppercase tracking-wide">
                  {typeLabel(r.report_type)}
                  {r.report_type === 'qualified_leads' && r.date_window_start
                    ? ` · ${r.date_window_start} – ${r.date_window_end}`
                    : ''}
                  {r.report_type === 'marketing_ramp' && r.date_window_start
                    ? ` · ${r.date_window_start} – ${r.date_window_end}`
                    : ''}
                  {r.report_type === 'web_leads' && r.date_window_start
                    ? ` · ${r.date_window_start} – ${r.date_window_end}`
                    : ''}
                  {r.report_type === 'attribution' && r.as_of ? ` · as-of ${r.as_of}` : ''}
                </p>
              </div>
              <div className="flex gap-1 shrink-0">
                <button
                  type="button"
                  onClick={() => handleOpen(r)}
                  className="px-2 py-1 text-xs font-medium text-navy hover:bg-navy/10 rounded"
                >
                  Open
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(r)}
                  disabled={deletingId === r.job_id}
                  className="px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50 rounded disabled:opacity-50"
                >
                  {deletingId === r.job_id ? '…' : 'Delete'}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default SavedReports;

type SavedReportsPanelProps = SavedReportsProps;

export function SavedReportsPanel(props: SavedReportsPanelProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-2xl border border-stone-200 bg-white shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-stone-50 rounded-2xl"
      >
        <span className="font-semibold text-stone-800">Saved reports</span>
        <span className="text-sm text-stone-500">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open ? (
        <div className="px-5 pb-5 border-t border-stone-100">
          <SavedReports {...props} />
        </div>
      ) : null}
    </div>
  );
}
