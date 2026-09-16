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
  list_purchase_date: string;
  reisift_matched: boolean;
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
  prospect_matched: boolean;
  prospect_date: string;
  prospect_source: string;
  opp_matched: boolean;
  opp_created_date: string;
  under_contract_date: string;
  hhb_closed_date: string;
  pipeline_stage: string;
  pipeline_stage_label: string;
  months_list_to_sold: number | null;
  months_list_to_qualified_lead: number | null;
  months_list_to_prospect: number | null;
}

export interface InvestorSoldRollupRow {
  sold_month?: string;
  county?: string;
  count: number;
  investor: number;
  in_our_list: number;
  both: number;
  neither: number;
  marketed?: number;
  leads?: number;
  qualified_leads?: number;
  prospects?: number;
  lost_to_investor?: number;
}

export interface InvestorSoldSegmentRow {
  segment: string;
  count: number;
  marketed: number;
  never_marketed: number;
  leads?: number;
  qualified_leads?: number;
  prospects: number;
  prospects_podio: number;
  prospects_ql: number;
  prospects_sf: number;
  opportunities: number;
  under_contract: number;
  hhb_closed: number;
  median_months_list_to_sold: number | null;
  marketed_pct?: number;
  lead_pct?: number;
  qualified_lead_pct?: number;
  prospect_pct?: number;
}

export interface InvestorSoldPipelineFunnelRow {
  stage: string;
  label: string;
  count: number;
  share_pct: number;
}

export interface InvestorSoldLostBlock {
  lost_to_investor_count: number;
  lost_to_investor_pct: number;
  in_list_investor_count: number;
  in_list_non_investor_count: number;
  lost_by_stage: InvestorSoldPipelineFunnelRow[];
  in_list_exits_by_buyer: Record<string, number>;
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
  lost?: InvestorSoldLostBlock;
  marketing: {
    marketed_count: number;
    marketed_pct: number;
    never_marketed_count: number;
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
    reisift_matched_count: number;
  };
  lag: {
    mean_months_list_to_sold: number | null;
    median_months_list_to_sold: number | null;
    mean_months_list_to_qualified_lead?: number | null;
    median_months_list_to_qualified_lead?: number | null;
    mean_months_list_to_prospect: number | null;
    median_months_list_to_prospect: number | null;
  };
  pipeline_funnel: InvestorSoldPipelineFunnelRow[];
  prospect_sources: {
    ql: number;
    sf_tag: number;
    podio: number;
    unmatched: number;
  };
  lead_sources?: {
    sf_tag: number;
    podio: number;
  };
  by_segment: InvestorSoldSegmentRow[];
  enrichment?: {
    reisift_matched_count: number;
    marketed_count: number;
    lead_matched?: number;
    qualified_lead_matched?: number;
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

function emptyMarketing(): InvestorSoldMetrics['marketing'] {
  return {
    marketed_count: 0,
    marketed_pct: 0,
    never_marketed_count: 0,
    total_touch_counts: {},
    avg_touches_per_marketed: null,
  };
}

function emptyMatch(enrichment?: InvestorSoldMetrics['enrichment']): InvestorSoldMetrics['match'] {
  return {
    lead_matched: enrichment?.lead_matched ?? 0,
    lead_rate_pct: 0,
    qualified_lead_matched: enrichment?.qualified_lead_matched ?? 0,
    qualified_lead_rate_pct: 0,
    prospect_matched: enrichment?.prospect_matched ?? 0,
    prospect_rate_pct: 0,
    opp_matched: enrichment?.opp_matched ?? 0,
    opp_rate_pct: 0,
    under_contract_count: 0,
    hhb_closed_count: 0,
    reisift_matched_count: enrichment?.reisift_matched_count ?? 0,
  };
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
  if (!metrics.marketing) {
    metrics.marketing = {
      ...emptyMarketing(),
      marketed_count: metrics.enrichment?.marketed_count ?? 0,
    };
  }
  if (!metrics.match) {
    metrics.match = emptyMatch(metrics.enrichment);
  }
  if (!metrics.lag) {
    metrics.lag = {
      mean_months_list_to_sold: null,
      median_months_list_to_sold: null,
      mean_months_list_to_qualified_lead: null,
      median_months_list_to_qualified_lead: null,
      mean_months_list_to_prospect: null,
      median_months_list_to_prospect: null,
    };
  }
  if (!metrics.lost) {
    metrics.lost = {
      lost_to_investor_count: 0,
      lost_to_investor_pct: 0,
      in_list_investor_count: 0,
      in_list_non_investor_count: 0,
      lost_by_stage: [],
      in_list_exits_by_buyer: {},
    };
  }
  if (!metrics.pipeline_funnel) metrics.pipeline_funnel = [];
  if (!metrics.prospect_sources) {
    metrics.prospect_sources = { ql: 0, sf_tag: 0, podio: 0, unmatched: 0 };
  }
  if (!metrics.lead_sources) {
    metrics.lead_sources = { sf_tag: 0, podio: 0 };
  }
  if (!metrics.by_segment) metrics.by_segment = [];
  return {
    job_id: data.job_id,
    status: 'completed',
    metrics,
    warnings: data.warnings ?? data.metrics.warnings ?? [],
    created_at: data.created_at,
  };
}
