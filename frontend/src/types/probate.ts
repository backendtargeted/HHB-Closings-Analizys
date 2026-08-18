export interface ProbateRow {
  address: string;
  address_key: string;
  county: string;
  counties: string[];
  lip_month: string;
  eight_month: string;
  first_source: string;
  first_source_label: string;
  prospect_date: string;
  prospect_matched: boolean;
  prospect_match_via: string;
  months_lip_to_prospect: number | null;
  months_eight_to_prospect: number | null;
  months_winner_to_prospect: number | null;
  lag_bucket: string;
  prospect_source: string;
  prospect_source_label: string;
  ql_campaign: string;
  opp_matched: boolean;
  opp_created_date: string;
  txn_matched: boolean;
  txn_closed_date: string;
  txn_primary_reason: string;
  txn_secondary_reason: string;
  tags: string;
}

export interface CountShareRow {
  label?: string;
  key?: string;
  county?: string;
  bucket?: string;
  lip_month?: string;
  count?: number;
  listed?: number;
  prospects?: number;
  txns?: number;
  share_pct: number;
  prospect_rate_pct?: number;
  mean_months_lip_to_prospect?: number | null;
  median_months_lip_to_prospect?: number | null;
}

export interface ProbateMetrics {
  report_type: string;
  date_window_start: string;
  date_window_end: string;
  inputs: {
    reisift_rows_ingested: number;
    lip_universe: number;
  };
  match: {
    prospect_matched: number;
    prospect_rate_pct: number;
    opp_matched: number;
    opp_rate_pct: number;
    txn_matched: number;
    txn_rate_pct: number;
  };
  lag: {
    mean_months_lip_to_prospect: number | null;
    median_months_lip_to_prospect: number | null;
  };
  first_source: CountShareRow[];
  campaigns?: CountShareRow[];
  other_campaigns?: CountShareRow[];
  counties: CountShareRow[];
  cohorts: CountShareRow[];
  lag_buckets: CountShareRow[];
  funnel: {
    lip: number;
    prospect: number;
    opportunity: number;
    transaction: number;
  };
  primary_reasons: CountShareRow[];
  secondary_reasons: CountShareRow[];
  rows: ProbateRow[];
  warnings: string[];
  methodology_note: string;
}

export interface ProbateAnalyzeResponse {
  job_id: string;
  status: string;
  metrics?: ProbateMetrics;
  warnings?: string[];
  created_at?: string;
  message?: string;
}

export type ProbateCompletedResponse = ProbateAnalyzeResponse & {
  metrics: ProbateMetrics;
};

export interface ProbateJobStatus {
  job_id: string;
  status: string;
  progress?: number;
  message?: string;
}

export function asProbateCompleted(response: ProbateAnalyzeResponse): ProbateCompletedResponse {
  if (!response.metrics) {
    throw new Error(response.message || 'Report metrics are not available');
  }
  return { ...response, metrics: response.metrics };
}
