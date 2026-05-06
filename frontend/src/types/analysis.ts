export interface LifecycleStageState {
  reached: boolean;
  date?: string | null;
}

export interface LifecycleEvent {
  type: string;
  label: string;
  date: string;
  precision: string;
  tag: string;
}

export interface AnalysisResult {
  Address: string;
  Date_Closed: string;
  Lead_Source: string;
  Total_Contacts: number;
  CC_Count: number;
  SMS_Count: number;
  DM_Count: number;
  First_Contact_Date: string | null;
  Last_Contact_Date: string | null;
  Days_to_Close: number | null;
  Days_Since_Last_Contact: number | null;
  Contact_Timeline: string;
  Match_Found: boolean;
  /** Lead lifecycle (missing on older saved reports) */
  Stages_Reached?: Record<string, LifecycleStageState> | null;
  Highest_Stage?: string | null;
  Stage_Dates?: Record<string, string | null | undefined> | null;
  Path_Sequence?: string | null;
  First_Touch_Channel?: string | null;
  Days_To_First_Touch?: number | null;
  Days_To_Engagement?: number | null;
  SF_Status_Trail?: Array<Record<string, string>> | null;
  List_Purchased_Date?: string | null;
  Skip_Traced_Date?: string | null;
  Closed_Marker_Date?: string | null;
  Lifecycle_Events?: LifecycleEvent[] | null;
}

export interface TopPathRow {
  path: string;
  count: number;
  median_days_to_close: number | null;
}

export interface FirstTouchRow {
  channel: string;
  count: number;
  median_days_to_close: number | null;
}

export interface SummaryStats {
  Total_Deals: number;
  Matched_Deals: number;
  Unmatched_Deals: number;
  Match_Rate: string;
  Average_Contacts_per_Deal: number;
  Median_Contacts_per_Deal: number;
  Max_Contacts: number;
  Min_Contacts: number;
  Total_CC_Contacts: number;
  Total_SMS_Contacts: number;
  Total_DM_Contacts: number;
  Average_Days_to_Close: number | null;
  Median_Days_to_Close: number | null;
  Funnel_Acquired_Count?: number | null;
  Funnel_Researched_Count?: number | null;
  Funnel_First_Contacted_Count?: number | null;
  Funnel_Engaged_Count?: number | null;
  Funnel_Converted_Count?: number | null;
  Funnel_Acquired_Rate_Pct?: number | null;
  Funnel_Researched_Rate_Pct?: number | null;
  Funnel_First_Contact_Rate_Pct?: number | null;
  Funnel_Engaged_Rate_Pct?: number | null;
  Funnel_Converted_Rate_Pct?: number | null;
  Engaged_To_Converted_Rate_Pct?: number | null;
  Top_Paths_Json?: string | null;
  First_Touch_Breakdown_Json?: string | null;
}

export interface AnalysisCompleteResponse {
  job_id: string;
  status: string;
  results: AnalysisResult[];
  stats: SummaryStats;
  matched_count: number;
  total_deals: number;
  /** YYYY-MM-DD when analysis used as-of deal filter */
  as_of?: string | null;
}

export interface ProgressUpdate {
  job_id: string;
  progress: number;
  message: string;
  step: string;
}

export interface AnalysisStatus {
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  message: string;
}

export interface UploadResponse {
  excel_path: string;
  csv_path: string;
  message: string;
}
