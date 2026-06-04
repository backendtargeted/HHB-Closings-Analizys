export interface QualifiedLeadsMetrics {
  rows_ingested: number;
  qualified_total_file: number;
  posted_in_window: number;
  posted_excluded_bad_date: number;
  posted_outside_window: number;
  date_window_start: string;
  date_window_end: string;
  create_date_min: string | null;
  create_date_max: string | null;
  channel_counts: Record<string, number>;
  channel_shares_pct: Record<string, number>;
  in_scope_subtotal: number;
  in_scope_share_pct: number;
  lead_source_unmapped: Record<string, number>;
  lead_source_blank: number;
  qualified_rate_window_note: string;
}

export interface QualifiedLeadsAnalyzeResponse {
  job_id: string;
  metrics: QualifiedLeadsMetrics;
  use_full_file_span: boolean;
}
