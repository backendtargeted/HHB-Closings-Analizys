"""
Pydantic models for API requests and responses
"""

from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime


class AnalysisRequest(BaseModel):
    excel_file_path: str
    csv_file_path: str


class AnalysisResponse(BaseModel):
    job_id: str
    status: str
    message: str


class LifecycleStageState(BaseModel):
    reached: bool
    date: Optional[str] = None


class LifecycleEvent(BaseModel):
    type: str
    label: str
    date: str
    precision: str
    tag: str


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    Address: str
    Date_Closed: str
    Lead_Source: str
    Total_Contacts: int
    CC_Count: int
    SMS_Count: int
    DM_Count: int
    First_Contact_Date: Optional[str]
    Last_Contact_Date: Optional[str]
    Days_to_Close: Optional[int]
    Days_Since_Last_Contact: Optional[int]
    Contact_Timeline: str
    Match_Found: bool
    # Lead lifecycle (optional for older saved reports)
    Stages_Reached: Optional[Dict[str, LifecycleStageState]] = None
    Highest_Stage: Optional[str] = None
    Stage_Dates: Optional[Dict[str, Optional[str]]] = None
    Path_Sequence: Optional[str] = None
    First_Touch_Channel: Optional[str] = None
    Days_To_First_Touch: Optional[int] = None
    Days_To_Engagement: Optional[int] = None
    SF_Status_Trail: Optional[List[Dict[str, str]]] = None
    List_Purchased_Date: Optional[str] = None
    Skip_Traced_Date: Optional[str] = None
    Closed_Marker_Date: Optional[str] = None
    Lifecycle_Events: Optional[List[LifecycleEvent]] = None


class SummaryStats(BaseModel):
    model_config = ConfigDict(extra="ignore")

    Total_Deals: int
    Matched_Deals: int
    Unmatched_Deals: int
    Match_Rate: str
    Average_Contacts_per_Deal: float
    Median_Contacts_per_Deal: float
    Max_Contacts: int
    Min_Contacts: int
    Total_CC_Contacts: int
    Total_SMS_Contacts: int
    Total_DM_Contacts: int
    Average_Days_to_Close: Optional[float]
    Median_Days_to_Close: Optional[float]
    # Lifecycle aggregates (optional)
    Funnel_Acquired_Count: Optional[int] = None
    Funnel_Researched_Count: Optional[int] = None
    Funnel_First_Contacted_Count: Optional[int] = None
    Funnel_Engaged_Count: Optional[int] = None
    Funnel_Converted_Count: Optional[int] = None
    Funnel_Acquired_Rate_Pct: Optional[float] = None
    Funnel_Researched_Rate_Pct: Optional[float] = None
    Funnel_First_Contact_Rate_Pct: Optional[float] = None
    Funnel_Engaged_Rate_Pct: Optional[float] = None
    Funnel_Converted_Rate_Pct: Optional[float] = None
    Engaged_To_Converted_Rate_Pct: Optional[float] = None
    Top_Paths_Json: Optional[str] = None
    First_Touch_Breakdown_Json: Optional[str] = None


class AnalysisCompleteResponse(BaseModel):
    job_id: str
    status: str
    results: List[AnalysisResult]
    stats: SummaryStats
    matched_count: int
    total_deals: int
    as_of: Optional[str] = None


class ProgressUpdate(BaseModel):
    job_id: str
    progress: int
    message: str
    step: str


class ComparisonRequest(BaseModel):
    job_ids: List[str]


class ComparisonResponse(BaseModel):
    comparisons: Dict[str, Any]
    differences: Dict[str, Any]
