import { useState, useEffect, useCallback } from 'react';
import {
  listReports,
  getAnalysisResults,
  getQualifiedLeadsJob,
  getMonthlyConsolidatedJob,
  deleteAnalysis,
  deleteQualifiedLeadsJob,
  deleteMonthlyConsolidatedJob,
} from '../services/api';
import type { AnalysisCompleteResponse } from '../types/analysis';
import type { QualifiedLeadsAnalyzeResponse } from '../types/qualifiedLeads';
import type { MonthlyConsolidatedCompletedResponse } from '../types/monthlyConsolidated';
import { asMonthlyConsolidatedCompleted } from '../types/monthlyConsolidated';
import type { SavedReportItem } from '../types/reports';

interface SavedReportsProps {
  onOpenAttributionReport: (data: AnalysisCompleteResponse) => void;
  onOpenQualifiedLeadsReport: (data: QualifiedLeadsAnalyzeResponse) => void;
  onOpenMonthlyConsolidatedReport?: (data: MonthlyConsolidatedCompletedResponse) => void;
  refreshKey?: number;
}

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
  if (t === 'qualified_leads') return 'Qualified leads';
  if (t === 'monthly_consolidated') return 'Monthly consolidated';
  return 'Attribution';
};

const SavedReports = ({
  onOpenAttributionReport,
  onOpenQualifiedLeadsReport,
  onOpenMonthlyConsolidatedReport,
  refreshKey = 0,
}: SavedReportsProps) => {
  const [reports, setReports] = useState<SavedReportItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);

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

  const handleOpen = async (item: SavedReportItem) => {
    try {
      if (item.report_type === 'qualified_leads') {
        const data = await getQualifiedLeadsJob(item.job_id);
        onOpenQualifiedLeadsReport(data);
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

  if (reports.length === 0) {
    return (
      <div className="text-stone-500 text-sm">
        No saved reports yet. Run attribution or qualified-leads consolidation to save one.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div>
        <h3 className="text-sm font-semibold text-navy">Saved reports</h3>
        <p className="text-xs text-stone-500 mt-0.5 leading-snug">
          Stored under <code className="text-[10px]">data/reports</code> — kept across Docker rebuilds.
        </p>
      </div>
      <ul className="space-y-1 max-h-64 overflow-y-auto">
        {reports.map((r) => (
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
    </div>
  );
};

export default SavedReports;
