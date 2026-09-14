"""
Gate 7 — Court Alerts lifecycle.

Universe is a Court Alerts CSV/XLSX (pgweb export). REISift supplies competing
8020 list-purchase tags (and phones) by address. First list is the QL credit.
Salesforce Create Date is when marketing pushed the lead into CRM (a clock,
not a source). Transactions supply Primary/Secondary Reason for Selling.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from .marketing_mapper import find_column_name, read_csv_header, resolve_usecols, sanitize_phone, smart_read_csv
from .monthly_consolidated import (
    REISIFT_ADDR,
    REISIFT_INDEX_COLUMN_GROUPS,
    TAGS_CANDIDATES,
    iter_reisift_chunks,
)
from .probate import (
    CREATE_DATE_CANDIDATES,
    LAG_BUCKETS,
    OPP_ADDR,
    OPP_DATE_CANDIDATES,
    PRIMARY_REASON_CANDIDATES,
    QL_ADDR,
    QL_CAMPAIGN_CANDIDATES,
    QL_PHONE_CANDIDATES,
    REISIFT_PHONE_CANDIDATES,
    SECONDARY_REASON_CANDIDATES,
    TXN_ADDR,
    TXN_DATE_CANDIDATES,
    MatchIndex,
    _address_key_from_parts,
    _best_hit,
    _build_match_index,
    _counter_table,
    _iso_day,
    _load_crm_file,
    _mean_median,
    _parse_ts,
    _pct,
    _ym_label,
    lag_bucket_label,
    months_between,
    parse_8020_list_purchase_date,
)

REPORT_TYPE = "court_alerts"

ProgressCallback = Callable[[int, str], None]

FIRST_SOURCE_CA_ONLY = "ca_only"
FIRST_SOURCE_CA_FIRST = "ca_first"
FIRST_SOURCE_8020_FIRST = "eight_first"
FIRST_SOURCE_SAME = "same_month"

FIRST_SOURCE_LABELS: Dict[str, str] = {
    FIRST_SOURCE_CA_ONLY: "Court Alerts only",
    FIRST_SOURCE_CA_FIRST: "Court Alerts first",
    FIRST_SOURCE_8020_FIRST: "8020 first",
    FIRST_SOURCE_SAME: "Same month",
}

LAG_CREDIT_CA = "ca"
LAG_CREDIT_EIGHT = "eight"
LAG_CREDIT_SAME = "same"
LAG_CREDIT_GROUPS: Tuple[str, ...] = (LAG_CREDIT_CA, LAG_CREDIT_EIGHT, LAG_CREDIT_SAME)

CA_ADDR = {
    "street": ["address", "Address", "Property address", "street"],
    "city": ["city", "City"],
    "state": ["state", "State"],
    "zip": ["zip_code", "Zip", "Zip Code", "zip", "postal_code"],
}
CA_CREATED_CANDIDATES = ["created_on", "Created On", "created_at", "Created At", "Created"]
CA_COUNTY_CANDIDATES = ["county_name", "County", "county", "County Name"]


def classify_first_source(
    ca_date: Optional[pd.Timestamp],
    eight_date: Optional[pd.Timestamp],
) -> str:
    if ca_date is None or pd.isna(ca_date):
        raise ValueError("Court Alerts date is required to classify first source")
    if eight_date is None or pd.isna(eight_date):
        return FIRST_SOURCE_CA_ONLY
    ca = pd.Timestamp(ca_date)
    eight = pd.Timestamp(eight_date)
    ca_ym = (ca.year, ca.month)
    eight_ym = (eight.year, eight.month)
    if ca_ym < eight_ym:
        return FIRST_SOURCE_CA_FIRST
    if eight_ym < ca_ym:
        return FIRST_SOURCE_8020_FIRST
    return FIRST_SOURCE_SAME


def lag_credit_group(first_source: str) -> str:
    if first_source in (FIRST_SOURCE_CA_ONLY, FIRST_SOURCE_CA_FIRST):
        return LAG_CREDIT_CA
    if first_source == FIRST_SOURCE_8020_FIRST:
        return LAG_CREDIT_EIGHT
    return LAG_CREDIT_SAME


def _first_list_date(
    ca_date: Optional[pd.Timestamp], eight_date: Optional[pd.Timestamp]
) -> Optional[pd.Timestamp]:
    if ca_date is None or pd.isna(ca_date):
        return None
    if eight_date is None or pd.isna(eight_date):
        return pd.Timestamp(ca_date)
    ca = pd.Timestamp(ca_date)
    eight = pd.Timestamp(eight_date)
    return eight if eight < ca else ca


def _month_start_from_ts(ts: Optional[pd.Timestamp]) -> Optional[pd.Timestamp]:
    if ts is None or pd.isna(ts):
        return None
    stamp = pd.Timestamp(ts)
    return pd.Timestamp(year=stamp.year, month=stamp.month, day=1)


def _normalize_county(raw: object) -> str:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return ""
    text = str(raw).strip()
    if not text or text.lower() == "nan":
        return ""
    lowered = text.lower()
    if lowered.endswith(" county"):
        text = text[: -len(" county")].strip()
    return text.title() if text else ""


def load_court_alerts_file(file_path: str) -> pd.DataFrame:
    path = Path(file_path)
    suffix = path.suffix.lower()
    ca_groups: List[List[str]] = [
        CA_ADDR["street"],
        CA_ADDR["city"],
        CA_ADDR["state"],
        CA_ADDR["zip"],
        CA_CREATED_CANDIDATES,
        CA_COUNTY_CANDIDATES,
        ["index_number", "Index Number", "index"],
        ["action_type", "Action Type", "action"],
        ["current_status", "Current Status", "status"],
    ]
    if suffix in (".xlsx", ".xls"):
        try:
            header = [str(c) for c in pd.read_excel(file_path, engine="openpyxl", nrows=0).columns]
            usecols = resolve_usecols(header, ca_groups)
            if usecols:
                return pd.read_excel(file_path, engine="openpyxl", usecols=usecols, dtype=str)
            return pd.read_excel(file_path, engine="openpyxl")
        except ImportError as exc:
            raise ValueError("Reading Excel requires openpyxl: pip install openpyxl") from exc
    if suffix == ".csv" or suffix == "":
        usecols = resolve_usecols(read_csv_header(file_path), ca_groups)
        if usecols:
            return smart_read_csv(file_path, usecols=usecols)
        return smart_read_csv(file_path)
    raise ValueError(f"Unsupported file type: {suffix or '(none)'}. Use .csv or .xlsx")


def _merge_reisift_chunk_into_index(index: Dict[str, Dict[str, Any]], df: pd.DataFrame) -> None:
    """Merge one REISift chunk into address → tags/phones index (no iterrows)."""
    tags_col = find_column_name(df, TAGS_CANDIDATES)
    if not tags_col:
        raise ValueError("Missing required column: Tags")
    street_col = find_column_name(df, REISIFT_ADDR["street"])
    city_col = find_column_name(df, REISIFT_ADDR["city"])
    state_col = find_column_name(df, REISIFT_ADDR["state"])
    zip_col = find_column_name(df, REISIFT_ADDR["zip"])
    phone_cols: List[str] = []
    seen_phone_cols: set[str] = set()
    for name in REISIFT_PHONE_CANDIDATES:
        col = find_column_name(df, [name])
        if col and col not in seen_phone_cols:
            seen_phone_cols.add(col)
            phone_cols.append(col)

    def _col_series(col: Optional[str]) -> List[str]:
        if not col or col not in df.columns:
            return [""] * len(df)
        return [str(v).strip() if v is not None else "" for v in df[col].tolist()]

    streets = _col_series(street_col)
    cities = _col_series(city_col)
    states = _col_series(state_col)
    zips = _col_series(zip_col)
    tags_list = _col_series(tags_col)
    phone_lists = [_col_series(c) for c in phone_cols]
    n = len(df)
    for i in range(n):
        street = streets[i]
        city = cities[i]
        state = states[i]
        zip_code = zips[i]
        if street.lower() == "nan":
            street = ""
        if city.lower() == "nan":
            city = ""
        if state.lower() == "nan":
            state = ""
        if zip_code.lower() == "nan":
            zip_code = ""
        key = _address_key_from_parts(street, city, state, zip_code)
        if not key or key == "|||":
            continue
        tags_part = tags_list[i]
        if tags_part.lower() == "nan":
            tags_part = ""
        phones: List[str] = []
        seen_phones: set[str] = set()
        for phone_vals in phone_lists:
            phone = sanitize_phone(phone_vals[i])
            if len(phone) >= 10 and phone not in seen_phones:
                seen_phones.add(phone)
                phones.append(phone)
        entry = index.get(key)
        if entry is None:
            index[key] = {
                "tags": tags_part,
                "phones": phones,
                "street": street,
                "city": city,
                "state": state,
                "zip": zip_code,
            }
        else:
            if tags_part:
                existing = entry["tags"]
                entry["tags"] = f"{existing},{tags_part}" if existing else tags_part
            seen = set(entry["phones"])
            for phone in phones:
                if phone not in seen:
                    seen.add(phone)
                    entry["phones"].append(phone)
            for fld, val in (("street", street), ("city", city), ("state", state), ("zip", zip_code)):
                if not entry.get(fld) and val:
                    entry[fld] = val


def _build_reisift_index(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """Address key → merged Tags + phones (full-file REISift)."""
    index: Dict[str, Dict[str, Any]] = {}
    _merge_reisift_chunk_into_index(index, df)
    return index


def build_reisift_index_from_path(file_path: str) -> Tuple[Dict[str, Dict[str, Any]], int]:
    """Chunked/pruned REISift load → address index + row count."""
    index: Dict[str, Dict[str, Any]] = {}
    rows = 0
    for chunk in iter_reisift_chunks(file_path, column_groups=REISIFT_INDEX_COLUMN_GROUPS):
        rows += len(chunk)
        _merge_reisift_chunk_into_index(index, chunk)
    return index, rows


def _lag_buckets_have_split(lag_buckets: List[Dict[str, Any]]) -> bool:
    return any("ca" in row and "eight" in row for row in lag_buckets)


def _lag_by_source_complete(by_source: Dict[str, Any]) -> bool:
    return all(group in by_source for group in LAG_CREDIT_GROUPS)


def _lag_split_from_rows(
    rows: List["CourtAlertsRow"],
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], Optional[float], Optional[float]]:
    prospect_n = sum(1 for row in rows if row.prospect_matched)
    bucket_counts: Dict[str, Counter[str]] = {label: Counter() for label, _lo, _hi in LAG_BUCKETS}
    values_by_group: Dict[str, List[int]] = {group: [] for group in LAG_CREDIT_GROUPS}
    all_values: List[int] = []
    for row in rows:
        if not row.prospect_matched or row.months_winner_to_prospect is None:
            continue
        months = row.months_winner_to_prospect
        bucket = row.lag_bucket or lag_bucket_label(months)
        group = lag_credit_group(row.first_source)
        if bucket in bucket_counts:
            bucket_counts[bucket][group] += 1
        values_by_group[group].append(months)
        all_values.append(months)
    lag_table: List[Dict[str, Any]] = []
    for label, _lo, _hi in LAG_BUCKETS:
        counts = bucket_counts[label]
        count = sum(counts.values())
        lag_table.append(
            {
                "bucket": label,
                "count": count,
                "share_pct": _pct(count, prospect_n),
                LAG_CREDIT_CA: counts.get(LAG_CREDIT_CA, 0),
                LAG_CREDIT_EIGHT: counts.get(LAG_CREDIT_EIGHT, 0),
                LAG_CREDIT_SAME: counts.get(LAG_CREDIT_SAME, 0),
            }
        )
    by_source: Dict[str, Dict[str, Any]] = {}
    for group in LAG_CREDIT_GROUPS:
        vals = values_by_group[group]
        mean, median = _mean_median(vals)
        by_source[group] = {"prospects": len(vals), "mean": mean, "median": median}
    mean_lag, median_lag = _mean_median(all_values)
    return lag_table, by_source, mean_lag, median_lag


@dataclass
class CourtAlertsRow:
    address: str
    address_key: str
    county: str
    ca_month: str
    eight_month: str
    first_source: str
    first_source_label: str
    prospect_date: str
    prospect_matched: bool
    prospect_match_via: str
    months_ca_to_prospect: Optional[int]
    months_eight_to_prospect: Optional[int]
    months_winner_to_prospect: Optional[int]
    lag_bucket: str
    opp_matched: bool
    opp_created_date: str
    txn_matched: bool
    txn_closed_date: str
    txn_primary_reason: str
    txn_secondary_reason: str
    prospect_source: str = ""
    prospect_source_label: str = ""
    ql_campaign: str = ""
    tags: str = ""
    index_number: str = ""
    action_type: str = ""
    current_status: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "address_key": self.address_key,
            "county": self.county,
            "ca_month": self.ca_month,
            "eight_month": self.eight_month,
            "first_source": self.first_source,
            "first_source_label": self.first_source_label,
            "prospect_date": self.prospect_date,
            "prospect_matched": self.prospect_matched,
            "prospect_match_via": self.prospect_match_via,
            "months_ca_to_prospect": self.months_ca_to_prospect,
            "months_eight_to_prospect": self.months_eight_to_prospect,
            "months_winner_to_prospect": self.months_winner_to_prospect,
            "lag_bucket": self.lag_bucket,
            "prospect_source": self.prospect_source,
            "prospect_source_label": self.prospect_source_label,
            "ql_campaign": self.ql_campaign,
            "opp_matched": self.opp_matched,
            "opp_created_date": self.opp_created_date,
            "txn_matched": self.txn_matched,
            "txn_closed_date": self.txn_closed_date,
            "txn_primary_reason": self.txn_primary_reason if self.txn_matched else "",
            "txn_secondary_reason": self.txn_secondary_reason if self.txn_matched else "",
            "tags": self.tags,
            "index_number": self.index_number,
            "action_type": self.action_type,
            "current_status": self.current_status,
        }


@dataclass
class CourtAlertsResult:
    date_window_start: str
    date_window_end: str
    court_alerts_rows_ingested: int
    reisift_rows_ingested: int
    ca_universe: int
    prospect_matched: int
    prospect_rate_pct: float
    opp_matched: int
    opp_rate_pct: float
    txn_matched: int
    txn_rate_pct: float
    mean_months_ca_to_prospect: Optional[float]
    median_months_ca_to_prospect: Optional[float]
    first_source: List[Dict[str, Any]]
    campaigns: List[Dict[str, Any]]
    counties: List[Dict[str, Any]]
    cohorts: List[Dict[str, Any]]
    lag_buckets: List[Dict[str, Any]]
    funnel: Dict[str, int]
    primary_reasons: List[Dict[str, Any]]
    secondary_reasons: List[Dict[str, Any]]
    crm_before_first_list_count: int = 0
    crm_before_first_list: List[Dict[str, Any]] = field(default_factory=list)
    lag_by_source: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    rows: List[CourtAlertsRow] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    methodology_note: str = ""

    def to_api_dict(self) -> Dict[str, Any]:
        return {
            "report_type": REPORT_TYPE,
            "date_window_start": self.date_window_start,
            "date_window_end": self.date_window_end,
            "inputs": {
                "court_alerts_rows_ingested": self.court_alerts_rows_ingested,
                "reisift_rows_ingested": self.reisift_rows_ingested,
                "ca_universe": self.ca_universe,
            },
            "match": {
                "prospect_matched": self.prospect_matched,
                "prospect_rate_pct": self.prospect_rate_pct,
                "opp_matched": self.opp_matched,
                "opp_rate_pct": self.opp_rate_pct,
                "txn_matched": self.txn_matched,
                "txn_rate_pct": self.txn_rate_pct,
                "crm_before_first_list": self.crm_before_first_list_count,
            },
            "lag": {
                "mean_months_ca_to_prospect": self.mean_months_ca_to_prospect,
                "median_months_ca_to_prospect": self.median_months_ca_to_prospect,
                "by_source": self.lag_by_source,
            },
            "first_source": self.first_source,
            "campaigns": self.campaigns,
            "counties": self.counties,
            "cohorts": self.cohorts,
            "lag_buckets": self.lag_buckets,
            "funnel": self.funnel,
            "primary_reasons": self.primary_reasons,
            "secondary_reasons": self.secondary_reasons,
            "crm_before_first_list": self.crm_before_first_list,
            "rows": [r.to_dict() for r in self.rows],
            "warnings": self.warnings,
            "methodology_note": self.methodology_note,
        }


def result_from_metrics_dict(metrics: Dict[str, Any]) -> CourtAlertsResult:
    rows = [CourtAlertsRow(**_row_kwargs(item)) for item in metrics.get("rows") or []]
    match = metrics.get("match") or {}
    lag = metrics.get("lag") or {}
    inputs = metrics.get("inputs") or {}
    lag_buckets = list(metrics.get("lag_buckets") or [])
    lag_by_source = dict(lag.get("by_source") or {})
    mean_lag = lag.get("mean_months_ca_to_prospect")
    median_lag = lag.get("median_months_ca_to_prospect")
    if rows and (
        not _lag_buckets_have_split(lag_buckets) or not _lag_by_source_complete(lag_by_source)
    ):
        derived_buckets, derived_source, derived_mean, derived_median = _lag_split_from_rows(rows)
        if not _lag_buckets_have_split(lag_buckets):
            lag_buckets = derived_buckets
        if not _lag_by_source_complete(lag_by_source):
            lag_by_source = derived_source
        if mean_lag is None:
            mean_lag = derived_mean
        if median_lag is None:
            median_lag = derived_median
    return CourtAlertsResult(
        date_window_start=str(metrics.get("date_window_start") or ""),
        date_window_end=str(metrics.get("date_window_end") or ""),
        court_alerts_rows_ingested=int(inputs.get("court_alerts_rows_ingested") or 0),
        reisift_rows_ingested=int(inputs.get("reisift_rows_ingested") or 0),
        ca_universe=int(inputs.get("ca_universe") or 0),
        prospect_matched=int(match.get("prospect_matched") or 0),
        prospect_rate_pct=float(match.get("prospect_rate_pct") or 0),
        opp_matched=int(match.get("opp_matched") or 0),
        opp_rate_pct=float(match.get("opp_rate_pct") or 0),
        txn_matched=int(match.get("txn_matched") or 0),
        txn_rate_pct=float(match.get("txn_rate_pct") or 0),
        mean_months_ca_to_prospect=mean_lag,
        median_months_ca_to_prospect=median_lag,
        first_source=list(metrics.get("first_source") or []),
        campaigns=list(metrics.get("campaigns") or metrics.get("other_campaigns") or []),
        counties=list(metrics.get("counties") or []),
        cohorts=list(metrics.get("cohorts") or []),
        lag_buckets=lag_buckets,
        funnel=dict(metrics.get("funnel") or {}),
        primary_reasons=list(metrics.get("primary_reasons") or []),
        secondary_reasons=list(metrics.get("secondary_reasons") or []),
        crm_before_first_list_count=int(match.get("crm_before_first_list") or 0),
        crm_before_first_list=list(metrics.get("crm_before_first_list") or []),
        lag_by_source=lag_by_source,
        rows=rows,
        warnings=list(metrics.get("warnings") or []),
        methodology_note=str(metrics.get("methodology_note") or ""),
    )


def _row_kwargs(item: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {
        "address",
        "address_key",
        "county",
        "ca_month",
        "eight_month",
        "first_source",
        "first_source_label",
        "prospect_date",
        "prospect_matched",
        "prospect_match_via",
        "months_ca_to_prospect",
        "months_eight_to_prospect",
        "months_winner_to_prospect",
        "lag_bucket",
        "prospect_source",
        "prospect_source_label",
        "ql_campaign",
        "opp_matched",
        "opp_created_date",
        "txn_matched",
        "txn_closed_date",
        "txn_primary_reason",
        "txn_secondary_reason",
        "tags",
        "index_number",
        "action_type",
        "current_status",
    }
    out = {k: item.get(k) for k in allowed}
    out["prospect_matched"] = bool(out.get("prospect_matched"))
    out["opp_matched"] = bool(out.get("opp_matched"))
    out["txn_matched"] = bool(out.get("txn_matched"))
    for key in (
        "address",
        "address_key",
        "county",
        "ca_month",
        "eight_month",
        "first_source",
        "first_source_label",
        "prospect_date",
        "prospect_match_via",
        "lag_bucket",
        "prospect_source",
        "prospect_source_label",
        "ql_campaign",
        "opp_created_date",
        "txn_closed_date",
        "txn_primary_reason",
        "txn_secondary_reason",
        "tags",
        "index_number",
        "action_type",
        "current_status",
    ):
        out[key] = str(out.get(key) or "")
    return out


def analyze(
    court_alerts_path: str,
    reisift_path: str,
    ql_path: str,
    opportunities_path: Optional[str] = None,
    transactions_path: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> CourtAlertsResult:
    def report(pct: int, message: str) -> None:
        if on_progress:
            on_progress(pct, message)

    warnings: List[str] = []
    report(6, "Loading Court Alerts file…")
    ca_df = load_court_alerts_file(court_alerts_path)
    street_col = find_column_name(ca_df, CA_ADDR["street"])
    city_col = find_column_name(ca_df, CA_ADDR["city"])
    state_col = find_column_name(ca_df, CA_ADDR["state"])
    zip_col = find_column_name(ca_df, CA_ADDR["zip"])
    created_col = find_column_name(ca_df, CA_CREATED_CANDIDATES)
    county_col = find_column_name(ca_df, CA_COUNTY_CANDIDATES)
    if not street_col:
        raise ValueError("Missing required column: address")
    if not created_col:
        raise ValueError("Missing required column: created_on")

    index_col = find_column_name(ca_df, ["index_number", "Index Number", "index"])
    action_col = find_column_name(ca_df, ["action_type", "Action Type", "action"])
    status_col = find_column_name(ca_df, ["current_status", "Current Status", "status"])

    report(14, "Loading REISift export…")
    reisift_index, reisift_rows_ingested = build_reisift_index_from_path(reisift_path)

    report(22, "Loading Salesforce qualified leads…")
    ql_df = _load_crm_file(ql_path)
    if not find_column_name(ql_df, QL_CAMPAIGN_CANDIDATES):
        warnings.append(
            "Qualified Leads file has no Campaign column — Campaign table will be blank."
        )
    ql_index = _build_match_index(
        ql_df,
        QL_ADDR,
        CREATE_DATE_CANDIDATES,
        QL_PHONE_CANDIDATES,
        campaign_candidates=QL_CAMPAIGN_CANDIDATES,
    )

    opp_index: Optional[MatchIndex] = None
    if opportunities_path:
        report(28, "Loading opportunities…")
        opp_index = _build_match_index(
            _load_crm_file(opportunities_path), OPP_ADDR, OPP_DATE_CANDIDATES
        )
    else:
        warnings.append("Opportunities file not uploaded — Opp funnel counts will be zero.")

    txn_index: Optional[MatchIndex] = None
    if transactions_path:
        report(34, "Loading transactions…")
        txn_df = _load_crm_file(transactions_path)
        txn_index = _build_match_index(
            txn_df,
            TXN_ADDR,
            TXN_DATE_CANDIDATES,
            primary_reason_candidates=PRIMARY_REASON_CANDIDATES,
            secondary_reason_candidates=SECONDARY_REASON_CANDIDATES,
        )
        if not find_column_name(txn_df, PRIMARY_REASON_CANDIDATES):
            warnings.append("Transactions file has no Primary Reason for Selling column.")
    else:
        warnings.append(
            "Transactions file not uploaded — reason-to-sell tables will be empty."
        )

    rows: List[CourtAlertsRow] = []
    crm_before_rows: List[Dict[str, Any]] = []
    ca_dates: List[pd.Timestamp] = []
    first_source_counter: Counter[str] = Counter()
    campaign_counter: Counter[str] = Counter()
    county_counter: Counter[str] = Counter()
    cohort_stats: Dict[str, Dict[str, Any]] = {}
    primary_counter: Counter[str] = Counter()
    secondary_counter: Counter[str] = Counter()
    skipped_no_address = 0
    skipped_no_date = 0

    report(42, "Matching Court Alerts to REISift and CRM…")
    total = len(ca_df)
    for i, (_, row) in enumerate(ca_df.iterrows()):
        street = str(row.get(street_col, "") or "").strip() if street_col else ""
        city = str(row.get(city_col, "") or "").strip() if city_col else ""
        state = str(row.get(state_col, "") or "").strip() if state_col else ""
        zip_code = str(row.get(zip_col, "") or "").strip() if zip_col else ""
        key = _address_key_from_parts(street, city, state, zip_code)
        if not key or key == "|||" or not street:
            skipped_no_address += 1
            continue

        created_raw = row.get(created_col, "") if created_col else ""
        created_ts = _parse_ts(created_raw)
        ca_date = _month_start_from_ts(created_ts)
        if ca_date is None:
            skipped_no_date += 1
            continue

        ca_dates.append(ca_date)
        reisift_hit = reisift_index.get(key) or {}
        tags_val = reisift_hit.get("tags") or ""
        phones = list(reisift_hit.get("phones") or [])
        eight_date = parse_8020_list_purchase_date(tags_val) if tags_val else None
        source = classify_first_source(ca_date, eight_date)
        first_source_counter[source] += 1

        county = _normalize_county(row.get(county_col, "")) if county_col else ""
        if county:
            county_counter[county] += 1
        else:
            county_counter["(blank)"] += 1
            county = "(blank)"

        display = " ".join(p for p in (street, city) if p) or key
        winner_date = _first_list_date(ca_date, eight_date)
        ql_hit = _best_hit(ql_index, key, phones, on_or_after=winner_date)
        early_hit = None
        if ql_hit is None:
            early_hit = _best_hit(ql_index, key, phones, before=winner_date)
        opp_hit = _best_hit(opp_index, key, [])
        txn_hit = _best_hit(txn_index, key, [])

        prospect_date = ql_hit.date if ql_hit else None
        months_ca = months_between(ca_date, prospect_date)
        months_eight = months_between(eight_date, prospect_date)
        months_winner = months_between(winner_date, prospect_date)
        prospect_source = source if ql_hit else ""
        prospect_source_label = FIRST_SOURCE_LABELS[source] if ql_hit else ""
        ql_campaign = ql_hit.campaign if ql_hit else ""
        bucket = ""
        if ql_hit:
            campaign_counter[ql_campaign] += 1
            if months_winner is not None:
                bucket = lag_bucket_label(months_winner)
        elif early_hit:
            crm_before_rows.append(
                {
                    "address": display,
                    "address_key": key,
                    "county": county,
                    "ca_month": _ym_label(ca_date),
                    "eight_month": _ym_label(eight_date),
                    "prospect_date": _iso_day(early_hit.date),
                    "prospect_match_via": early_hit.via,
                    "ql_campaign": early_hit.campaign or "",
                    "first_source_label": FIRST_SOURCE_LABELS[source],
                }
            )

        if txn_hit:
            primary_counter[txn_hit.primary_reason] += 1
            secondary_counter[txn_hit.secondary_reason] += 1

        cohort_key = _ym_label(ca_date)
        stats = cohort_stats.setdefault(
            cohort_key,
            {"ca_month": cohort_key, "listed": 0, "prospects": 0, "txns": 0, "lags": []},
        )
        stats["listed"] += 1
        if ql_hit:
            stats["prospects"] += 1
        if txn_hit:
            stats["txns"] += 1
        if ql_hit and months_winner is not None:
            stats["lags"].append(months_winner)

        index_number = (
            str(row.get(index_col, "") or "").strip() if index_col else ""
        )
        action_type = str(row.get(action_col, "") or "").strip() if action_col else ""
        current_status = str(row.get(status_col, "") or "").strip() if status_col else ""

        rows.append(
            CourtAlertsRow(
                address=display,
                address_key=key,
                county=county,
                ca_month=_ym_label(ca_date),
                eight_month=_ym_label(eight_date),
                first_source=source,
                first_source_label=FIRST_SOURCE_LABELS[source],
                prospect_date=_iso_day(prospect_date),
                prospect_matched=ql_hit is not None,
                prospect_match_via=ql_hit.via if ql_hit else "",
                months_ca_to_prospect=months_ca,
                months_eight_to_prospect=months_eight,
                months_winner_to_prospect=months_winner,
                lag_bucket=bucket,
                prospect_source=prospect_source,
                prospect_source_label=prospect_source_label,
                ql_campaign=ql_campaign if ql_hit else "",
                opp_matched=opp_hit is not None,
                opp_created_date=_iso_day(opp_hit.date if opp_hit else None),
                txn_matched=txn_hit is not None,
                txn_closed_date=_iso_day(txn_hit.date if txn_hit else None),
                txn_primary_reason=txn_hit.primary_reason if txn_hit else "",
                txn_secondary_reason=txn_hit.secondary_reason if txn_hit else "",
                tags=str(tags_val or ""),
                index_number=index_number if index_number.lower() != "nan" else "",
                action_type=action_type if action_type.lower() != "nan" else "",
                current_status=current_status if current_status.lower() != "nan" else "",
            )
        )
        if on_progress and i > 0 and i % 200 == 0:
            report(42 + int(45 * i / max(total, 1)), f"Row {i:,} / {total:,}…")

    universe = len(rows)
    if skipped_no_address:
        warnings.append(
            f"Skipped {skipped_no_address:,} Court Alerts row(s) with no parseable address."
        )
    if skipped_no_date:
        warnings.append(
            f"Skipped {skipped_no_date:,} Court Alerts row(s) with no parseable created_on."
        )
    if universe == 0:
        warnings.append(
            "No Court Alerts rows had both a parseable address and created_on date."
        )

    prospect_n = sum(1 for r in rows if r.prospect_matched)
    opp_n = sum(1 for r in rows if r.opp_matched)
    txn_n = sum(1 for r in rows if r.txn_matched)
    lag_table, lag_by_source, mean_lag, median_lag = _lag_split_from_rows(rows)

    first_source_table = [
        {
            "key": key,
            "label": FIRST_SOURCE_LABELS[key],
            "count": first_source_counter.get(key, 0),
            "share_pct": _pct(first_source_counter.get(key, 0), universe),
            "prospects": sum(1 for r in rows if r.first_source == key and r.prospect_matched),
            "prospect_rate_pct": _pct(
                sum(1 for r in rows if r.first_source == key and r.prospect_matched),
                first_source_counter.get(key, 0),
            ),
        }
        for key in (
            FIRST_SOURCE_CA_ONLY,
            FIRST_SOURCE_CA_FIRST,
            FIRST_SOURCE_8020_FIRST,
            FIRST_SOURCE_SAME,
        )
    ]

    county_table = [
        {
            "county": county,
            "count": county_counter.get(county, 0),
            "share_pct": _pct(county_counter.get(county, 0), universe),
            "prospects": sum(1 for r in rows if r.county == county and r.prospect_matched),
            "prospect_rate_pct": _pct(
                sum(1 for r in rows if r.county == county and r.prospect_matched),
                county_counter.get(county, 0),
            ),
        }
        for county in sorted(county_counter.keys())
    ]

    cohorts: List[Dict[str, Any]] = []
    for key in sorted(cohort_stats):
        stats = cohort_stats[key]
        listed = int(stats["listed"])
        prospects = int(stats["prospects"])
        mean_c, med_c = _mean_median(list(stats["lags"]))
        cohorts.append(
            {
                "ca_month": key,
                "listed": listed,
                "prospects": prospects,
                "prospect_rate_pct": _pct(prospects, listed),
                "txns": int(stats["txns"]),
                "mean_months_ca_to_prospect": mean_c,
                "median_months_ca_to_prospect": med_c,
            }
        )

    window_start = min(ca_dates).date().isoformat() if ca_dates else ""
    window_end = max(ca_dates).date().isoformat() if ca_dates else ""

    methodology = (
        "Universe = Court Alerts export rows with a parseable address and created_on "
        "(list month = first of that month). REISift is joined by address for Tags / phones; "
        "8020 list purchase = List Purchased 8020 MM/YYYY, or List Purchased MM/YYYY when a "
        "standalone (8020) token is on the same row. First list on the property is the QL credit "
        "(Court Alerts only / Court Alerts first / 8020 first / Same month). A Prospect is a Total "
        "Qualified Leads match whose Create Date is on or after that first-list month (earliest "
        "such hit). An earlier CRM row is not this list's conversion. Campaign is how the team "
        "worked a counted Prospect. Lag is calendar months from the first-list month to that "
        "Create Date, split by first-list source (Court Alerts / 8020 / Same month). Reason for "
        "selling is read only from the Transactions pipeline Primary/Secondary columns after "
        "address match. County comes from county_name on the Court Alerts row."
    )

    report(96, "Finishing summary…")
    return CourtAlertsResult(
        date_window_start=window_start,
        date_window_end=window_end,
        court_alerts_rows_ingested=total,
        reisift_rows_ingested=reisift_rows_ingested,
        ca_universe=universe,
        prospect_matched=prospect_n,
        prospect_rate_pct=_pct(prospect_n, universe),
        opp_matched=opp_n,
        opp_rate_pct=_pct(opp_n, universe),
        txn_matched=txn_n,
        txn_rate_pct=_pct(txn_n, universe),
        mean_months_ca_to_prospect=mean_lag,
        median_months_ca_to_prospect=median_lag,
        first_source=first_source_table,
        campaigns=_counter_table(campaign_counter, prospect_n),
        counties=county_table,
        cohorts=cohorts,
        lag_buckets=lag_table,
        funnel={
            "court_alerts": universe,
            "prospect": prospect_n,
            "opportunity": opp_n,
            "transaction": txn_n,
        },
        primary_reasons=_counter_table(primary_counter, txn_n),
        secondary_reasons=_counter_table(secondary_counter, txn_n),
        crm_before_first_list_count=len(crm_before_rows),
        crm_before_first_list=crm_before_rows,
        lag_by_source=lag_by_source,
        rows=rows,
        warnings=warnings,
        methodology_note=methodology,
    )


def build_export_workbook(result: CourtAlertsResult) -> bytes:
    try:
        import openpyxl  # noqa: F401
    except ImportError as exc:
        raise ValueError("XLSX export requires openpyxl") from exc

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        summary = [
            {"metric": "Date window start", "value": result.date_window_start},
            {"metric": "Date window end", "value": result.date_window_end},
            {
                "metric": "Court Alerts rows ingested",
                "value": result.court_alerts_rows_ingested,
            },
            {"metric": "REISift rows ingested", "value": result.reisift_rows_ingested},
            {"metric": "Court Alerts universe", "value": result.ca_universe},
            {"metric": "Prospect matched", "value": result.prospect_matched},
            {
                "metric": "Prospect % of Court Alerts list",
                "value": result.prospect_rate_pct,
            },
            {
                "metric": "In CRM before first list",
                "value": result.crm_before_first_list_count,
            },
            {"metric": "Opportunities matched", "value": result.opp_matched},
            {"metric": "Transactions matched", "value": result.txn_matched},
            {
                "metric": "Mean months first list to CRM push",
                "value": result.mean_months_ca_to_prospect,
            },
            {
                "metric": "Median months first list to CRM push",
                "value": result.median_months_ca_to_prospect,
            },
            {
                "metric": "Mean months Court Alerts to CRM push",
                "value": (result.lag_by_source.get(LAG_CREDIT_CA) or {}).get("mean"),
            },
            {
                "metric": "Median months Court Alerts to CRM push",
                "value": (result.lag_by_source.get(LAG_CREDIT_CA) or {}).get("median"),
            },
            {
                "metric": "Mean months 8020 to CRM push",
                "value": (result.lag_by_source.get(LAG_CREDIT_EIGHT) or {}).get("mean"),
            },
            {
                "metric": "Median months 8020 to CRM push",
                "value": (result.lag_by_source.get(LAG_CREDIT_EIGHT) or {}).get("median"),
            },
            {
                "metric": "Mean months same-month list to CRM push",
                "value": (result.lag_by_source.get(LAG_CREDIT_SAME) or {}).get("mean"),
            },
            {
                "metric": "Median months same-month list to CRM push",
                "value": (result.lag_by_source.get(LAG_CREDIT_SAME) or {}).get("median"),
            },
            {"metric": "Methodology", "value": result.methodology_note},
        ]
        pd.DataFrame(summary).to_excel(writer, sheet_name="Summary", index=False)
        pd.DataFrame([r.to_dict() for r in result.rows]).to_excel(
            writer, sheet_name="Court Alerts Rows", index=False
        )
        if result.first_source:
            pd.DataFrame(result.first_source).to_excel(
                writer, sheet_name="First Source", index=False
            )
        if result.campaigns:
            pd.DataFrame(result.campaigns).to_excel(
                writer, sheet_name="Campaign", index=False
            )
        if result.counties:
            pd.DataFrame(result.counties).to_excel(writer, sheet_name="County", index=False)
        if result.cohorts:
            pd.DataFrame(result.cohorts).to_excel(writer, sheet_name="List Month", index=False)
        if result.lag_buckets:
            pd.DataFrame(result.lag_buckets).to_excel(
                writer, sheet_name="Lag Buckets", index=False
            )
        if result.crm_before_first_list:
            pd.DataFrame(result.crm_before_first_list).to_excel(
                writer, sheet_name="CRM Before First List", index=False
            )
        if result.primary_reasons:
            pd.DataFrame(result.primary_reasons).to_excel(
                writer, sheet_name="Txn Primary Reason", index=False
            )
        if result.secondary_reasons:
            pd.DataFrame(result.secondary_reasons).to_excel(
                writer, sheet_name="Txn Secondary Reason", index=False
            )
    return buf.getvalue()
