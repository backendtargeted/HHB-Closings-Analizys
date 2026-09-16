export interface SoldPropertyRow {
  address: string;
  address_key: string;
  street: string;
  city: string;
  state: string;
  zip: string;
  sold_month: string;
  sold_month_raw: string;
  created: string;
  lists: string;
  list_purchase_date: string;
  marketed: boolean;
  cc_touch_count: number;
  sms_touch_count: number;
  dm_touch_count: number;
  first_touch_channel: string;
  first_touch_date: string;
  lead_matched: boolean;
  lead_date: string;
  lead_source: string;
  qualified_lead_matched: boolean;
  qualified_lead_date: string;
  qualified_lead_match_via: string;
  prospect_matched: boolean;
  prospect_date: string;
  prospect_match_via: string;
  prospect_source: string;
  opp_matched: boolean;
  opp_created_date: string;
  under_contract_date: string;
  hhb_closed_date: string;
  highest_lifecycle_stage: string;
  pipeline_stage: string;
  pipeline_stage_label: string;
  days_list_to_sold: number | null;
  months_list_to_sold: number | null;
  days_list_to_qualified_lead: number | null;
  months_list_to_qualified_lead: number | null;
  days_list_to_prospect: number | null;
  months_list_to_prospect: number | null;
  tags: string;
}

export interface PipelineFunnelRow {
  stage: string;
  label: string;
  count: number;
  share_pct: number;
}

export interface SoldMonthRollupRow {
  sold_month: string;
  count: number;
  marketed: number;
  leads?: number;
  qualified_leads?: number;
  prospects: number;
  opportunities: number;
  under_contract: number;
  hhb_closed: number;
}

export interface SoldPropertiesMetrics {
  report_type: string;
  date_window_start: string;
  date_window_end: string;
  inputs: {
    reisift_rows_ingested: number;
    cohort_rows: number;
    sold_month_unparseable: number;
  };
  marketing: {
    marketed_count: number;
    marketed_pct: number;
    total_touch_counts: Record<string, number>;
    avg_touches_per_marketed: number | null;
  };
  match: {
    lead_matched?: number;
    lead_rate_pct?: number;
    qualified_lead_matched?: number;
    qualified_lead_rate_pct?: number;
    prospect_matched: number;
    prospect_rate_pct: number;
    opp_matched: number;
    opp_rate_pct: number;
    under_contract_count: number;
    hhb_closed_count: number;
  };
  lag: {
    mean_months_list_to_sold: number | null;
    median_months_list_to_sold: number | null;
    mean_months_list_to_qualified_lead?: number | null;
    median_months_list_to_qualified_lead?: number | null;
    mean_months_list_to_prospect: number | null;
    median_months_list_to_prospect: number | null;
  };
  pipeline_funnel: PipelineFunnelRow[];
  lifecycle_funnel: Array<{ stage: string; count: number; share_pct: number }>;
  by_sold_month: SoldMonthRollupRow[];
  rows: SoldPropertyRow[];
  warnings: string[];
  methodology_note: string;
}

export interface SoldPropertiesJobStatus {
  job_id: string;
  status: string;
  progress?: number;
  message?: string;
}

export interface SoldPropertiesAnalyzeResponse {
  job_id: string;
  status: string;
  message?: string;
  metrics?: SoldPropertiesMetrics;
  warnings?: string[];
  created_at?: string;
}

export interface SoldPropertiesCompletedResponse {
  job_id: string;
  status: 'completed';
  metrics: SoldPropertiesMetrics;
  warnings: string[];
  created_at?: string;
}

export function asSoldPropertiesCompleted(
  data: SoldPropertiesAnalyzeResponse
): SoldPropertiesCompletedResponse {
  if (data.status !== 'completed' || !data.metrics) {
    throw new Error(data.message || 'Sold properties analysis not complete');
  }
  return {
    job_id: data.job_id,
    status: 'completed',
    metrics: data.metrics,
    warnings: data.warnings ?? data.metrics.warnings ?? [],
    created_at: data.created_at,
  };
}
