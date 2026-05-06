export interface PatchUploadResponse {
  job_id: string;
  metrics: PatchMetrics;
  samples: PatchSamples;
}

export interface PatchMetrics {
  crm_total_rows?: number;
  crm_matched_by_phone?: number;
  crm_matched_by_address?: number;
  cold_overrides_applied?: number;
  sms_overrides_applied?: number;
  crm_unmatched_rows?: number;
  sf_tags_created_total?: number;
  sf_tags_created_status?: number;
  sf_tags_created_updated?: number;
  sf_skipped_updated_on?: number;
  sf_skipped_created_date?: number;
  cold_unmapped: string[];
  sms_unmapped: string[];
  crm_unmapped: string[];
  cold_input_counts: Record<string, number>;
  cold_output_counts: Record<string, number>;
  sms_input_counts: Record<string, number>;
  sms_output_counts: Record<string, number>;
  closings_rows: number;
}

export interface PatchSamples {
  cold_calling: Record<string, unknown>[];
  sms: Record<string, unknown>[];
  salesforce_tags: Record<string, unknown>[];
  closings_tags: Record<string, unknown>[];
}
