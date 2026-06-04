import type { SummaryStats } from './analysis';
import type { QualifiedLeadsMetrics } from './qualifiedLeads';

export interface ListMetric {
  token: string;
  row_count: number;
  crm_lead_count: number;
  qualified_lead_count: number;
  closing_count: number;
  closing_rate: number;
  stacked_row_count: number;
}

export interface ComboMetric {
  lists: string[];
  lists_key: string;
  row_count: number;
  closing_count: number;
  closing_rate: number;
}

export interface MonthlyConsolidatedMetrics {
  report_type: string;
  report_month: string;
  cohort_scope: 'full_file' | 'calendar_month';
  period: { start: string; end: string };
  inputs: { reisift_rows_ingested: number; cohort_rows: number };
  cohort: {
    total_rows: number;
    crm_lead_rows: number;
    closing_rows: number;
    stacked_rows: number;
    stacked_pct: number;
  };
  lists: ListMetric[];
  combinations: ComboMetric[];
  qualified_leads: QualifiedLeadsMetrics;
  list_attribution: {
    matched_to_reisift: number;
    unmatched: number;
    by_list_token: Record<string, number>;
    match_rate_pct: number;
  };
  lifecycle_stats: SummaryStats;
  open_pipeline_lifecycle?: {
    open_rows: number;
    stuck_at_stage: Array<{ stage: string; count: number; share_pct: number }>;
  };
  tag_lead_source_counts?: Array<{ source: string; count: number; share_pct: number }>;
  warnings: string[];
  methodology_note: string;
}

export interface MonthlyConsolidatedAnalyzeResponse {
  job_id: string;
  status: string;
  metrics?: MonthlyConsolidatedMetrics;
  warnings?: string[];
  created_at?: string;
  message?: string;
}

/** Completed report with metrics — used when rendering results UI. */
export type MonthlyConsolidatedCompletedResponse = MonthlyConsolidatedAnalyzeResponse & {
  metrics: MonthlyConsolidatedMetrics;
};

export function asMonthlyConsolidatedCompleted(
  response: MonthlyConsolidatedAnalyzeResponse
): MonthlyConsolidatedCompletedResponse {
  if (!response.metrics) {
    throw new Error(response.message || 'Report metrics are not available');
  }
  return { ...response, metrics: response.metrics };
}

export interface MonthlyConsolidatedJobStatus {
  job_id: string;
  status: 'pending' | 'running' | 'started' | 'completed' | 'failed';
  progress: number;
  message: string;
}
