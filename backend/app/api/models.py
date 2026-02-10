"""
Pydantic models for API requests and responses
"""

from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class AnalysisRequest(BaseModel):
    excel_file_path: str
    csv_file_path: str


class AnalysisResponse(BaseModel):
    job_id: str
    status: str
    message: str


class AnalysisResult(BaseModel):
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


class SummaryStats(BaseModel):
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


class AnalysisCompleteResponse(BaseModel):
    job_id: str
    status: str
    results: List[AnalysisResult]
    stats: SummaryStats
    matched_count: int
    total_deals: int


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
