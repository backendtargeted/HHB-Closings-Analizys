export interface InvestorSoldRow {
  address: string;
  address_key: string;
  street: string;
  city: string;
  state: string;
  zip: string;
  county: string;
  period_date: string;
  period_label: string;
  sold_month: string;
  buyer_full_name: string;
  sale_amount: string;
  investor: boolean;
  in_my_records: boolean;
  segment: 'investor' | 'in_our_list' | 'both' | 'neither' | string;
  investor_score: string;
  distressors: string;
  dataflik_id: string;
  transaction_id: string;
  transaction_count: number;
  reisift_matched: boolean;
  marketed: boolean;
  cc_touch_count: number;
  sms_touch_count: number;
  dm_touch_count: number;
  prospect_matched: boolean;
  prospect_date: string;
  prospect_source: string;
  opp_matched: boolean;
  opp_created_date: string;
  under_contract_date: string;
  hhb_closed_date: string;
  pipeline_stage: string;
  pipeline_stage_label: string;
}

export interface InvestorSoldRollupRow {
  sold_month?: string;
  county?: string;
  count: number;
  investor: number;
  in_our_list: number;
  both: number;
  neither: number;
}

export interface InvestorSoldMetrics {
  report_type: string;
  date_window_start: string;
  date_window_end: string;
  inputs: {
    sold_rows_ingested: number;
    property_rows: number;
    unique_addresses: number;
    enrichment_enabled: boolean;
  };
  segments: {
    investor_count: number;
    investor_pct: number;
    in_our_list_count: number;
    in_our_list_pct: number;
    both_count: number;
    both_pct: number;
    neither_count: number;
    neither_pct: number;
  };
  enrichment: {
    reisift_matched_count: number;
    marketed_count: number;
    prospect_matched: number;
    opp_matched: number;
  };
  by_sold_month: InvestorSoldRollupRow[];
  by_county: InvestorSoldRollupRow[];
  rows: InvestorSoldRow[];
  warnings: string[];
  methodology_note: string;
}

export interface InvestorSoldJobStatus {
  job_id: string;
  status: string;
  progress?: number;
  message?: string;
}

export interface InvestorSoldAnalyzeResponse {
  job_id: string;
  status: string;
  message?: string;
  metrics?: InvestorSoldMetrics;
  warnings?: string[];
  created_at?: string;
}

export interface InvestorSoldCompletedResponse {
  job_id: string;
  status: 'completed';
  metrics: InvestorSoldMetrics;
  warnings: string[];
  created_at?: string;
}

export function asInvestorSoldCompleted(
  data: InvestorSoldAnalyzeResponse
): InvestorSoldCompletedResponse {
  if (data.status !== 'completed' || !data.metrics) {
    throw new Error(data.message || 'Investor sold analysis not complete');
  }
  const metrics = data.metrics;
  if (metrics.inputs.property_rows == null) {
    metrics.inputs.property_rows = metrics.rows?.length ?? metrics.inputs.sold_rows_ingested ?? 0;
  }
  return {
    job_id: data.job_id,
    status: 'completed',
    metrics,
    warnings: data.warnings ?? data.metrics.warnings ?? [],
    created_at: data.created_at,
  };
}
