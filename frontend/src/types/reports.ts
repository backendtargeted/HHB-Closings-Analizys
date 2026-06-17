export type ReportType = 'attribution' | 'qualified_leads' | 'monthly_consolidated' | 'marketing_ramp';

export interface SavedReportItem {
  job_id: string;
  report_type: ReportType;
  status: string;
  created_at: string;
  summary: string;
  matched_count?: number;
  total_deals?: number;
  as_of?: string | null;
  posted_in_window?: number;
  rows_ingested?: number;
  date_window_start?: string;
  date_window_end?: string;
  report_month?: string;
  cohort_rows?: number;
  closing_rows?: number;
}

export interface SavedReportsListResponse {
  reports: SavedReportItem[];
}
