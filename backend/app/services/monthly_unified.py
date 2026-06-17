"""
Unified monthly report: Gate 3 marketing ramp + Gate 2 consolidated in one run.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

from .marketing_ramp import MarketingRampResult, analyze as analyze_marketing_ramp
from .monthly_consolidated import (
    MonthlyConsolidatedResult,
    analyze as analyze_monthly_consolidated,
    build_export_workbook,
)


@dataclass
class UnifiedMonthlyResult:
    marketing_ramp: MarketingRampResult
    consolidated: MonthlyConsolidatedResult

    def to_api_dict(self) -> Dict[str, Any]:
        return {
            "metrics": self.marketing_ramp.metrics,
            "rows": self.marketing_ramp.rows,
            "consolidated": {
                "metrics": self.consolidated.to_dict(),
                "warnings": self.consolidated.warnings,
            },
        }


def analyze_unified(
    qualified_leads_path: str,
    reisift_path: str,
    closings_path: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    use_full_file_span: bool = False,
) -> UnifiedMonthlyResult:
    """Run marketing ramp and consolidated list report in parallel on shared uploads."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        ramp_future = pool.submit(
            analyze_marketing_ramp,
            qualified_leads_path,
            reisift_path,
            closings_path,
            start_date=start_date,
            end_date=end_date,
            use_full_file_span=use_full_file_span,
        )
        consolidated_future = pool.submit(
            analyze_monthly_consolidated,
            reisift_path,
            qualified_leads_path,
            report_month=None,
        )
        ramp_result = ramp_future.result()
        consolidated_result = consolidated_future.result()

    return UnifiedMonthlyResult(
        marketing_ramp=ramp_result,
        consolidated=consolidated_result,
    )


def build_unified_export_workbook(
    consolidated: MonthlyConsolidatedResult,
    ramp_rows: List[Dict[str, Any]],
) -> bytes:
    """XLSX with Gate 2 sheets plus Marketing Ramp journey rows."""
    return build_export_workbook(consolidated, ramp_rows=ramp_rows)
