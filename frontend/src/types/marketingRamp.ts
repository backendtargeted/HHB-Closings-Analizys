export interface MarketingRampPopulationCounts {
  qualified_leads_in_window?: number;
  qualified_leads_total?: number;
  reisift_rows?: number;
  reisift_in_window?: number;
  closings_in_window?: number;
  closings_total?: number;
  [key: string]: number | undefined;
}

export interface MarketingRampReisiftMatch {
  matched: number;
  unmatched: number;
  match_rate_pct: number;
}

export interface MarketingRampMetrics {
  report_type: string;
  date_window_start: string;
  date_window_end: string;
  population_counts: MarketingRampPopulationCounts;
  reisift_match: MarketingRampReisiftMatch;
  channel_counts: Record<string, number>;
  touch_counts: Record<string, number>;
  opportunity_counts: Record<string, number>;
  warnings: string[];
  methodology_note: string;
}

export type MarketingRampRow = Record<string, string | number | boolean | null | undefined>;

export interface MarketingRampAnalyzeResponse {
  job_id: string;
  status: string;
  metrics?: MarketingRampMetrics;
  rows?: MarketingRampRow[];
  message?: string;
  created_at?: string;
}

export type MarketingRampCompletedResponse = MarketingRampAnalyzeResponse & {
  metrics: MarketingRampMetrics;
};

export function asMarketingRampCompleted(
  response: MarketingRampAnalyzeResponse
): MarketingRampCompletedResponse {
  if (!response.metrics) {
    throw new Error(response.message || 'Report metrics are not available');
  }
  return { ...response, metrics: response.metrics };
}
