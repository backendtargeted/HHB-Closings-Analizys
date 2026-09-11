export interface CourtAlertsRow {
  address: string;
  address_key: string;
  county: string;
  ca_month: string;
  eight_month: string;
  first_source: string;
  first_source_label: string;
  prospect_date: string;
  prospect_matched: boolean;
  prospect_match_via: string;
  months_ca_to_prospect: number | null;
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
  index_number?: string;
  action_type?: string;
  current_status?: string;
}

export interface CrmBeforeFirstListRow {
  address: string;
  address_key?: string;
  county: string;
  ca_month: string;
  eight_month: string;
  prospect_date: string;
  prospect_match_via: string;
  ql_campaign: string;
  first_source_label: string;
}

export interface CountShareRow {
  label?: string;
  key?: string;
  county?: string;
  bucket?: string;
  ca_month?: string;
  count?: number;
  listed?: number;
  prospects?: number;
  txns?: number;
  share_pct: number;
  prospect_rate_pct?: number;
  mean_months_ca_to_prospect?: number | null;
  median_months_ca_to_prospect?: number | null;
  ca?: number;
  eight?: number;
  same?: number;
}

export interface LagBySourceRow {
  prospects: number;
  mean: number | null;
  median: number | null;
}

export interface CourtAlertsMetrics {
  report_type: string;
  date_window_start: string;
  date_window_end: string;
  inputs: {
    court_alerts_rows_ingested: number;
    reisift_rows_ingested: number;
    ca_universe: number;
  };
  match: {
    prospect_matched: number;
    prospect_rate_pct: number;
    opp_matched: number;
    opp_rate_pct: number;
    txn_matched: number;
    txn_rate_pct: number;
    crm_before_first_list?: number;
  };
  lag: {
    mean_months_ca_to_prospect: number | null;
    median_months_ca_to_prospect: number | null;
    by_source?: {
      ca?: LagBySourceRow;
      eight?: LagBySourceRow;
      same?: LagBySourceRow;
    };
  };
  first_source: CountShareRow[];
  campaigns?: CountShareRow[];
  other_campaigns?: CountShareRow[];
  counties: CountShareRow[];
  cohorts: CountShareRow[];
  lag_buckets: CountShareRow[];
  funnel: {
    court_alerts: number;
    prospect: number;
    opportunity: number;
    transaction: number;
  };
  primary_reasons: CountShareRow[];
  secondary_reasons: CountShareRow[];
  crm_before_first_list?: CrmBeforeFirstListRow[];
  rows: CourtAlertsRow[];
  warnings: string[];
  methodology_note: string;
}

export interface CourtAlertsAnalyzeResponse {
  job_id: string;
  status: string;
  metrics?: CourtAlertsMetrics;
  warnings?: string[];
  created_at?: string;
  message?: string;
}

export type CourtAlertsCompletedResponse = CourtAlertsAnalyzeResponse & {
  metrics: CourtAlertsMetrics;
};

export interface CourtAlertsJobStatus {
  job_id: string;
  status: string;
  progress?: number;
  message?: string;
}

export function asCourtAlertsCompleted(
  response: CourtAlertsAnalyzeResponse
): CourtAlertsCompletedResponse {
  if (!response.metrics) {
    throw new Error(response.message || 'Report metrics are not available');
  }
  return { ...response, metrics: response.metrics };
}
