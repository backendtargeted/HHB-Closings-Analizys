import { useState, useEffect } from 'react';
import { listAnalyses, getAnalysisResults, deleteAnalysis } from '../services/api';
import type { AnalysisCompleteResponse } from '../types/analysis';

export interface SavedAnalysisItem {
  job_id: string;
  status: string;
  created_at: string;
  matched_count: number;
  total_deals: number;
}

interface SavedReportsProps {
  onOpenReport: (data: AnalysisCompleteResponse) => void;
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

const SavedReports = ({ onOpenReport }: SavedReportsProps) => {
  const [analyses, setAnalyses] = useState<SavedAnalysisItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await listAnalyses();
      setAnalyses(res.analyses ?? []);
    } catch {
      setAnalyses([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleOpen = async (jobId: string) => {
    try {
      const data = await getAnalysisResults(jobId);
      onOpenReport(data);
    } catch {
      alert('Failed to load report');
    }
  };

  const handleDelete = async (jobId: string) => {
    if (!confirm('Delete this saved report?')) return;
    setDeletingId(jobId);
    try {
      await deleteAnalysis(jobId);
      await load();
    } catch {
      alert('Failed to delete report');
    } finally {
      setDeletingId(null);
    }
  };

  if (loading) {
    return (
      <div className="text-stone-500 text-sm">Loading saved reports…</div>
    );
  }

  if (analyses.length === 0) {
    return (
      <div className="text-stone-500 text-sm">No saved reports yet. Run an analysis to save one.</div>
    );
  }

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-stone-700">Saved reports</h3>
      <ul className="space-y-1 max-h-48 overflow-y-auto">
        {analyses.map((a) => (
          <li
            key={a.job_id}
            className="flex items-center justify-between gap-2 py-2 px-3 rounded-lg border border-stone-200 bg-surface hover:bg-stone-100/50"
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm text-stone-700 truncate">{formatDate(a.created_at)}</p>
              <p className="text-xs text-stone-500">
                {a.matched_count} / {a.total_deals} matched
              </p>
            </div>
            <div className="flex gap-1 shrink-0">
              <button
                type="button"
                onClick={() => handleOpen(a.job_id)}
                className="px-2 py-1 text-xs font-medium text-navy hover:bg-navy/10 rounded"
              >
                Open
              </button>
              <button
                type="button"
                onClick={() => handleDelete(a.job_id)}
                disabled={deletingId === a.job_id}
                className="px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50 rounded disabled:opacity-50"
              >
                {deletingId === a.job_id ? '…' : 'Delete'}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
};

export default SavedReports;
