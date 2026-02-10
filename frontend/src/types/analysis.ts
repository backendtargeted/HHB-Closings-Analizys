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
}

export interface AnalysisCompleteResponse {
  job_id: string;
  status: string;
  results: AnalysisResult[];
  stats: SummaryStats;
  matched_count: number;
  total_deals: number;
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
