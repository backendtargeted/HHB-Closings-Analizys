export type WebLeadsCohortSource = 'web_leads' | 'court_alerts' | 'long_island_profiles';

export interface WebLeadRow {
  address: string;
  address_key: string;
  cohort_track_date: string;
  ql_create_date: string;
  reisift_created_on: string;
  anchor_date: string;
  lists: string[];
  combo_key: string;
  had_prior_history: boolean;
  earliest_list_date: string;
  days_list_to_web: number | null;
  prior_8020_channels: string[];
  has_8020_tag: boolean;
  journey_path: string;
  journey_path_compact: string;
  matched: boolean;
  closings_matched: boolean;
  closings_date_closed: string;
  closings_stage: string;
}

export interface WebLeadsMetrics {
  report_type: string;
  date_window_start: string;
  date_window_end: string;
  cohort_source: string;
  inputs: {
    cohort_rows: number;
    cohort_source: string;
    reisift_reference_rows: number;
    reisift_rows_ingested: number;
    website_ql_total: number;
  };
  match: {
    matched: number;
    unmatched: number;
    match_rate_pct: number;
  };
  prior_history: {
    count: number;
    share_pct: number;
    new_to_db_count: number;
    new_to_db_pct: number;
  };
  top_lists: Array<{ list: string; count: number; share_pct: number }>;
  combinations: Array<{
    lists_key: string;
    lists: string[];
    row_count: number;
    share_pct: number;
  }>;
  top_paths: Array<{ path: string; count: number; share_pct: number }>;
  age_buckets: Array<{ bucket: string; count: number; share_pct: number }>;
  rows: WebLeadRow[];
  warnings: string[];
  methodology_note: string;
}

export interface WebLeadsAnalyzeResponse {
  job_id: string;
  status: string;
  metrics?: WebLeadsMetrics;
  warnings?: string[];
  created_at?: string;
  message?: string;
}

export type WebLeadsCompletedResponse = WebLeadsAnalyzeResponse & {
  metrics: WebLeadsMetrics;
};

export function asWebLeadsCompleted(response: WebLeadsAnalyzeResponse): WebLeadsCompletedResponse {
  if (!response.metrics) {
    throw new Error(response.message || 'Report metrics are not available');
  }
  return { ...response, metrics: response.metrics };
}

export interface WebLeadsJobStatus {
  job_id: string;
  status: string;
  progress?: number;
  message?: string;
}
