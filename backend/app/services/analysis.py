"""
Core analysis logic extracted from contact_attribution_gui.py
"""

import pandas as pd
import numpy as np
import re
from datetime import datetime, date
import os
from typing import Dict, List, Any, Optional
import json

from .lifecycle import (
    CONVERTED_LABELS,
    aggregate_lifecycle_stats,
    build_events,
    compute_first_touch,
    compute_ordered_path,
    compute_stage_funnel,
    events_before_close,
    events_to_jsonable,
    first_dates_for_markers,
    get_highest_stage,
    sf_status_trail,
)
from .marketing_mapper import normalize_status


def normalize_address(address):
    """
    Normalize address for matching by:
    - Converting to lowercase
    - Removing punctuation
    - Standardizing common abbreviations
    - Removing extra spaces
    """
    if pd.isna(address):
        return ""
    
    # Convert to string and lowercase
    addr = str(address).lower().strip()
    
    # Standardize common street abbreviations
    abbreviations = {
        r'\bstreet\b': 'st',
        r'\bavenue\b': 'ave',
        r'\broad\b': 'rd',
        r'\bdrive\b': 'dr',
        r'\blane\b': 'ln',
        r'\bcourt\b': 'ct',
        r'\bcircle\b': 'cir',
        r'\bplace\b': 'pl',
        r'\bboulevard\b': 'blvd',
        r'\bparkway\b': 'pkwy',
        r'\bterrace\b': 'ter',
        r'\bway\b': 'wy',
    }
    
    for pattern, replacement in abbreviations.items():
        addr = re.sub(pattern, replacement, addr)
    
    # Remove punctuation and extra spaces
    addr = re.sub(r'[^\w\s]', '', addr)
    addr = re.sub(r'\s+', ' ', addr).strip()
    
    return addr


def filter_closed_deals_by_as_of(closed_deals: pd.DataFrame, as_of_date: str) -> pd.DataFrame:
    """
    Keep deals whose Date Closed is on or before as_of_date (calendar day, UTC-normalized).
    Rows with invalid/missing Date Closed are dropped when filtering.
    """
    cutoff = pd.Timestamp(date.fromisoformat(as_of_date.strip()))
    closed_dt = pd.to_datetime(closed_deals["Date Closed"], errors="coerce")
    mask = closed_dt.notna() & (closed_dt.normalize() <= cutoff.normalize())
    return closed_deals.loc[mask].copy().reset_index(drop=True)


def _dedupe_parsed_tag_events(parsed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    One row per logical event: duplicate tokens in Tags (e.g. double REISift import)
    share the same (type, month-level date, channel, label) and are counted once.
    """
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for p in parsed:
        key = (
            str(p.get("type", "")),
            str(p.get("date", "")),
            str(p.get("channel") or ""),
            str(p.get("label") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def parse_tags(tags_str):
    """
    Parse the Tags column to extract contact information.
    Returns a list of dictionaries with contact details.
    Identical logical events (same type, date, channel, label) are returned once
    so duplicate comma-separated tokens do not inflate counts.
    """
    if pd.isna(tags_str) or tags_str == '':
        return []
    
    contacts = []
    tags = str(tags_str).split(',')
    
    for tag in tags:
        tag = tag.strip()
        
        # Skip empty tags
        if not tag:
            continue
        
        # Parse contact tags: (8020) CC - 12-2025, (8020) SMS - 11-2025, (8020) DM - 10-2025
        contact_match = re.match(r'\(8020\)\s*(CC|SMS|DM)\s*-\s*(\d{1,2})[-\/](\d{4})', tag)
        if contact_match:
            channel = contact_match.group(1)
            month = int(contact_match.group(2))
            year = int(contact_match.group(3))
            
            # Create date (using first day of month since we don't have exact day)
            try:
                contact_date = datetime(year, month, 1)
                contacts.append({
                    'type': 'contact',
                    'channel': channel,
                    'label': channel,
                    'precision': 'month',
                    'date': contact_date.isoformat(),
                    'month': month,
                    'year': year,
                    'tag': tag
                })
            except ValueError:
                continue
        
        # Parse list purchase dates: List Purchased 8020 11/2025
        list_match = re.match(r'List Purchased\s+8020\s+(\d{1,2})[-\/](\d{4})', tag)
        if list_match:
            month = int(list_match.group(1))
            year = int(list_match.group(2))
            try:
                list_date = datetime(year, month, 1)
                contacts.append({
                    'type': 'list_purchase',
                    'channel': None,
                    'label': '',
                    'precision': 'month',
                    'date': list_date.isoformat(),
                    'month': month,
                    'year': year,
                    'tag': tag
                })
            except ValueError:
                continue
        
        # Parse skip trace dates: Skip Traced Versium 10/2025
        skip_match = re.match(r'Skip Traced\s+(?:Versium\s+)?(\d{1,2})[-\/](\d{4})', tag)
        if skip_match:
            month = int(skip_match.group(1))
            year = int(skip_match.group(2))
            try:
                skip_date = datetime(year, month, 1)
                contacts.append({
                    'type': 'skip_trace',
                    'channel': None,
                    'label': '',
                    'precision': 'month',
                    'date': skip_date.isoformat(),
                    'month': month,
                    'year': year,
                    'tag': tag
                })
            except ValueError:
                continue

        # Closing marker (REISift backfill): (CLOSED) 8020 - 03/2025
        closed_match = re.match(r'\(CLOSED\)\s*8020\s*-\s*(\d{1,2})[-\/](\d{4})', tag)
        if closed_match:
            month = int(closed_match.group(1))
            year = int(closed_match.group(2))
            try:
                closing_date = datetime(year, month, 1)
                contacts.append({
                    'type': 'closing',
                    'channel': None,
                    'label': '',
                    'precision': 'month',
                    'date': closing_date.isoformat(),
                    'month': month,
                    'year': year,
                    'tag': tag
                })
            except ValueError:
                continue

        # Salesforce-style tags from mapper: (SF) UPDATED - <status> - YYYY-MM-DD
        if re.match(r'^\(SF\)\s*UPDATED\s*-', tag, re.I):
            m = re.search(r'\s-\s*(\d{4}-\d{2}-\d{2})\s*$', tag)
            if m:
                date_str = m.group(1)
                head = tag[: m.start()].strip()
                label = re.sub(r'^\(SF\)\s*UPDATED\s*-\s*', '', head, flags=re.I).strip()
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    contacts.append({
                        'type': 'sf_updated',
                        'channel': None,
                        'label': label,
                        'precision': 'day',
                        'date': dt.isoformat(),
                        'month': dt.month,
                        'year': dt.year,
                        'tag': tag,
                    })
                except ValueError:
                    pass

        # (SF) STATUS - <status> - YYYY-MM-DD
        if re.match(r'^\(SF\)\s*STATUS\s*-', tag, re.I):
            m = re.search(r'\s-\s*(\d{4}-\d{2}-\d{2})\s*$', tag)
            if m:
                date_str = m.group(1)
                head = tag[: m.start()].strip()
                label = re.sub(r'^\(SF\)\s*STATUS\s*-\s*', '', head, flags=re.I).strip()
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    contacts.append({
                        'type': 'sf_status',
                        'channel': None,
                        'label': label,
                        'precision': 'day',
                        'date': dt.isoformat(),
                        'month': dt.month,
                        'year': dt.year,
                        'tag': tag,
                    })
                except ValueError:
                    pass
    
    return _dedupe_parsed_tag_events(contacts)


def parse_closings_address(full_address):
    """
    Parse closings address format (e.g., "248 E. Shore Rd Lindenhurst") into street and city.
    """
    if pd.isna(full_address):
        return None, None
    
    addr_str = str(full_address).strip()
    parts = addr_str.split()
    
    # Try to identify city (usually last 1-2 words)
    street_types = ['rd', 'st', 'dr', 'ave', 'ln', 'ct', 'cir', 'pl', 'blvd', 'pkwy', 'ter', 'wy', 'way']
    
    # Find where street type ends (likely end of street address)
    street_end_idx = len(parts)
    for i, part in enumerate(parts):
        # Remove punctuation for comparison
        part_clean = re.sub(r'[^\w]', '', part.lower())
        if part_clean in street_types or part_clean.endswith('street') or part_clean.endswith('road'):
            street_end_idx = i + 1
            break
    
    # Street address is everything up to street_end_idx
    street_parts = parts[:street_end_idx]
    city_parts = parts[street_end_idx:]
    
    street_address = ' '.join(street_parts)
    city = ' '.join(city_parts) if city_parts else None
    
    return street_address, city


def normalize_city(city):
    """Normalize city name for matching."""
    if pd.isna(city) or city == '':
        return ''
    
    city_str = str(city).lower().strip()
    
    # Handle common variations
    city_variations = {
        'ronkokama': 'ronkonkoma',
        'mastic beach': 'mastic',
        'massapequa park': 'massapequa',
        'new hyde park': 'new hyde park',
        'mount sinai': 'mount sinai',
    }
    
    for variant, standard in city_variations.items():
        if variant in city_str:
            return standard
    
    return city_str


def match_deals_to_csv(closed_deals: pd.DataFrame, csv_data: pd.DataFrame) -> List[Dict]:
    """
    Match closed deals to CSV records by normalized address and city.
    """
    matches = []
    
    # Normalize addresses in CSV
    csv_data['normalized_address'] = csv_data['Property address'].apply(normalize_address)
    csv_data['normalized_city'] = csv_data['Property city'].apply(normalize_city)
    
    for idx, deal in closed_deals.iterrows():
        # Parse closings address into street and city
        street_addr, city = parse_closings_address(deal['Address'])
        
        if street_addr is None:
            matches.append({
                'deal_index': int(idx),
                'csv_index': None,
                'closed_date': str(deal['Date Closed']),
                'address': str(deal['Address']),
                'lead_source': str(deal['Lead Source']),
                'csv_record': None
            })
            continue
        
        # Normalize street address
        normalized_street = normalize_address(street_addr)
        normalized_city_deal = normalize_city(city) if city else ''
        
        # Find matches in CSV
        # Strategy 1: Exact match on normalized street address
        matches_found = csv_data[csv_data['normalized_address'] == normalized_street]
        
        # Strategy 2: If city is available, filter by city too
        if len(matches_found) > 1 and normalized_city_deal:
            city_matches = matches_found[matches_found['normalized_city'] == normalized_city_deal]
            if len(city_matches) > 0:
                matches_found = city_matches
        
        # Strategy 3: If no exact match, try partial match on street address
        if len(matches_found) == 0:
            deal_parts = normalized_street.split()
            if len(deal_parts) >= 2:
                # Match on street number and first part of street name
                street_num = deal_parts[0]
                street_name_part = deal_parts[1] if len(deal_parts) > 1 else ''
                
                # Find addresses that start with same number and contain street name
                partial_match = csv_data[
                    csv_data['normalized_address'].str.startswith(street_num + ' ', na=False) &
                    csv_data['normalized_address'].str.contains(street_name_part, na=False, regex=False)
                ]
                
                # If city available, also filter by city
                if normalized_city_deal and len(partial_match) > 0:
                    city_filtered = partial_match[partial_match['normalized_city'] == normalized_city_deal]
                    if len(city_filtered) > 0:
                        matches_found = city_filtered
                    else:
                        matches_found = partial_match
                else:
                    matches_found = partial_match
        
        # Strategy 4: Try matching just the street number and city
        if len(matches_found) == 0 and normalized_city_deal:
            deal_parts = normalized_street.split()
            if len(deal_parts) >= 1:
                street_num = deal_parts[0]
                matches_found = csv_data[
                    csv_data['normalized_address'].str.startswith(street_num + ' ', na=False) &
                    (csv_data['normalized_city'] == normalized_city_deal)
                ]
        
        if len(matches_found) > 0:
            # Use the first match (or could aggregate if multiple)
            match = matches_found.iloc[0]
            matches.append({
                'deal_index': int(idx),
                'csv_index': int(match.name),
                'closed_date': str(deal['Date Closed']),
                'address': str(deal['Address']),
                'lead_source': str(deal['Lead Source']),
                'csv_record': match.to_dict()
            })
        else:
            # No match found
            matches.append({
                'deal_index': int(idx),
                'csv_index': None,
                'closed_date': str(deal['Date Closed']),
                'address': str(deal['Address']),
                'lead_source': str(deal['Lead Source']),
                'csv_record': None
            })
    
    return matches


def derive_closed_deals_from_csv(csv_data: pd.DataFrame, as_of_date: Optional[str] = None) -> pd.DataFrame:
    """
    Build closed-deal rows directly from contact-history tags.
    Prefers explicit (CLOSED) markers; falls back to converted SF statuses.
    """
    cutoff: Optional[pd.Timestamp] = None
    if as_of_date:
        cutoff = pd.Timestamp(date.fromisoformat(as_of_date.strip())).normalize()

    rows: List[Dict[str, Any]] = []
    for idx, rec in csv_data.iterrows():
        tags_str = rec.get("Tags", "")
        parsed = parse_tags(tags_str)
        close_candidates: List[datetime] = []

        for p in parsed:
            ptype = str(p.get("type", ""))
            if ptype == "closing":
                try:
                    close_candidates.append(datetime.fromisoformat(str(p.get("date"))))
                except ValueError:
                    continue
            elif ptype in ("sf_updated", "sf_status"):
                label = normalize_status(str(p.get("label", "")))
                if label in CONVERTED_LABELS:
                    try:
                        close_candidates.append(datetime.fromisoformat(str(p.get("date"))))
                    except ValueError:
                        continue

        if not close_candidates:
            continue

        closed_dt = min(close_candidates)
        if cutoff is not None and pd.Timestamp(closed_dt).normalize() > cutoff:
            continue

        addr = str(rec.get("Property address", "")).strip()
        city = str(rec.get("Property city", "")).strip()
        if not addr:
            addr = str(rec.get("Address", "")).strip()
        address = f"{addr} {city}".strip()
        if not address:
            continue

        lead_source = (
            rec.get("Lead Source")
            or rec.get("Lead source")
            or rec.get("LeadSource")
            or "Contact History Tags"
        )
        rows.append(
            {
                "Address": address,
                "Date Closed": closed_dt.date().isoformat(),
                "Lead Source": str(lead_source),
                "csv_index": int(idx),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["Address", "Date Closed", "Lead Source", "csv_index"])
    return pd.DataFrame(rows)


def match_closed_rows_to_csv(closed_deals: pd.DataFrame, csv_data: pd.DataFrame) -> List[Dict]:
    """
    Build match list from close rows that already reference source CSV rows.
    """
    matches: List[Dict] = []
    for idx, deal in closed_deals.iterrows():
        csv_index = deal.get("csv_index")
        csv_record = None
        if csv_index is not None and pd.notna(csv_index):
            try:
                csv_record = csv_data.iloc[int(csv_index)].to_dict()
            except (IndexError, ValueError, TypeError):
                csv_record = None

        matches.append(
            {
                "deal_index": int(idx),
                "csv_index": int(csv_index) if csv_index is not None and pd.notna(csv_index) else None,
                "closed_date": str(deal.get("Date Closed", "")),
                "address": str(deal.get("Address", "")),
                "lead_source": str(deal.get("Lead Source", "")),
                "csv_record": csv_record,
            }
        )
    return matches


def analyze_contacts(matches: List[Dict]) -> pd.DataFrame:
    """
    Analyze contact history for matched deals.
    """
    results = []
    
    for match in matches:
        if match['csv_record'] is None:
            # No match found
            results.append({
                'Address': match['address'],
                'Date Closed': match['closed_date'],
                'Lead Source': match['lead_source'],
                'Total Contacts': 0,
                'CC Count': 0,
                'SMS Count': 0,
                'DM Count': 0,
                'First Contact Date': None,
                'Last Contact Date': None,
                'Days to Close': None,
                'Days Since Last Contact': None,
                'Contact Timeline': '',
                'Match Found': False,
                'Stages Reached': None,
                'Highest Stage': None,
                'Stage Dates': None,
                'Path Sequence': '',
                'First Touch Channel': None,
                'Days To First Touch': None,
                'Days To Engagement': None,
                'SF Status Trail': None,
                'List Purchased Date': None,
                'Skip Traced Date': None,
                'Closed Marker Date': None,
                'Lifecycle Events': None,
            })
            continue
        
        closed_date = pd.to_datetime(match['closed_date'])
        csv_record = match['csv_record']
        
        # Parse tags
        tags_str = csv_record.get('Tags', '')
        contacts = parse_tags(tags_str)
        
        # Filter contacts that occurred before closing date
        contacts_before = []
        for c in contacts:
            if c['type'] == 'contact':
                contact_date = datetime.fromisoformat(c['date'])
                if contact_date < closed_date:
                    contacts_before.append(c)
        
        # Count contacts by channel
        cc_count = len([c for c in contacts_before if c['channel'] == 'CC'])
        sms_count = len([c for c in contacts_before if c['channel'] == 'SMS'])
        dm_count = len([c for c in contacts_before if c['channel'] == 'DM'])
        total_contacts = len(contacts_before)
        
        # Get first and last contact dates
        if contacts_before:
            contact_dates = [datetime.fromisoformat(c['date']) for c in contacts_before]
            first_contact = min(contact_dates)
            last_contact = max(contact_dates)
            
            # Calculate days (approximate since we only have month/year)
            days_to_close = (closed_date - first_contact).days
            days_since_last = (closed_date - last_contact).days
            
            # Create contact timeline
            timeline = []
            sorted_contacts = sorted(contacts_before, key=lambda x: datetime.fromisoformat(x['date']))
            for c in sorted_contacts:
                contact_date = datetime.fromisoformat(c['date'])
                timeline.append(f"{c['channel']} ({contact_date.strftime('%b %Y')})")
            contact_timeline = ' → '.join(timeline)
        else:
            first_contact = None
            last_contact = None
            days_to_close = None
            days_since_last = None
            contact_timeline = 'No contacts before closing'

        events = build_events(contacts)
        stages = compute_stage_funnel(events, closed_date)

        stage_dates = {k: (v.get("date") if isinstance(v, dict) else None) for k, v in stages.items()}
        path_seq = compute_ordered_path(events, closed_date)
        ft = compute_first_touch(events, closed_date)
        trail = sf_status_trail(events, closed_date)
        lp_d, sk_d, cl_d = first_dates_for_markers(events, closed_date)
        ev_bc = events_before_close(events, closed_date)
        lifecycle_events_json = json.dumps(events_to_jsonable(ev_bc))

        highest_stage = get_highest_stage(stages)

        results.append({
            'Address': match['address'],
            'Date Closed': closed_date.isoformat() if isinstance(closed_date, pd.Timestamp) else str(closed_date),
            'Lead Source': match['lead_source'],
            'Total Contacts': total_contacts,
            'CC Count': cc_count,
            'SMS Count': sms_count,
            'DM Count': dm_count,
            'First Contact Date': first_contact.isoformat() if first_contact else None,
            'Last Contact Date': last_contact.isoformat() if last_contact else None,
            'Days to Close': int(days_to_close) if days_to_close is not None else None,
            'Days Since Last Contact': int(days_since_last) if days_since_last is not None else None,
            'Contact Timeline': contact_timeline,
            'Match Found': True,
            'Stages Reached': stages,
            'Highest Stage': highest_stage,
            'Stage Dates': json.dumps(stage_dates),
            'Path Sequence': path_seq,
            'First Touch Channel': ft.get('channel'),
            'Days To First Touch': ft.get('days_list_to_first_touch'),
            'Days To Engagement': ft.get('days_to_engagement'),
            'SF Status Trail': json.dumps(trail),
            'List Purchased Date': lp_d,
            'Skip Traced Date': sk_d,
            'Closed Marker Date': cl_d,
            'Lifecycle Events': lifecycle_events_json,
        })
    
    if not results:
        return pd.DataFrame(
            columns=[
                "Address",
                "Date Closed",
                "Lead Source",
                "Total Contacts",
                "CC Count",
                "SMS Count",
                "DM Count",
                "First Contact Date",
                "Last Contact Date",
                "Days to Close",
                "Days Since Last Contact",
                "Contact Timeline",
                "Match Found",
                "Stages Reached",
                "Highest Stage",
                "Stage Dates",
                "Path Sequence",
                "First Touch Channel",
                "Days To First Touch",
                "Days To Engagement",
                "SF Status Trail",
                "List Purchased Date",
                "Skip Traced Date",
                "Closed Marker Date",
                "Lifecycle Events",
            ]
        )
    return pd.DataFrame(results)


def generate_summary_stats(results_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Generate summary statistics from results.
    """
    matched_results = results_df[results_df['Match Found'] == True]
    
    if len(matched_results) == 0:
        return {}
    
    stats = {
        'Total Deals': int(len(results_df)),
        'Matched Deals': int(len(matched_results)),
        'Unmatched Deals': int(len(results_df) - len(matched_results)),
        'Match Rate': f"{(len(matched_results) / len(results_df) * 100):.1f}%",
        'Average Contacts per Deal': float(matched_results['Total Contacts'].mean()),
        'Median Contacts per Deal': float(matched_results['Total Contacts'].median()),
        'Max Contacts': int(matched_results['Total Contacts'].max()),
        'Min Contacts': int(matched_results['Total Contacts'].min()),
        'Total CC Contacts': int(matched_results['CC Count'].sum()),
        'Total SMS Contacts': int(matched_results['SMS Count'].sum()),
        'Total DM Contacts': int(matched_results['DM Count'].sum()),
        'Average Days to Close': float(matched_results['Days to Close'].mean()) if matched_results['Days to Close'].notna().any() else None,
        'Median Days to Close': float(matched_results['Days to Close'].median()) if matched_results['Days to Close'].notna().any() else None,
    }

    records = results_df.replace({np.nan: None}).to_dict("records")
    lifecycle_agg = aggregate_lifecycle_stats(records)
    if lifecycle_agg:
        stats.update(lifecycle_agg)

    return stats


def perform_analysis(
    closings_file_path: Optional[str],
    csv_file_path: str,
    progress_callback=None,
    as_of_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main analysis function that orchestrates the entire process.
    
    Args:
        closings_file_path: Optional path to legacy closings workbook
        csv_file_path: Path to CSV file with contact history
        progress_callback: Optional callback function for progress updates
        as_of_date: Optional YYYY-MM-DD; only deals with Date Closed on or before this day are analyzed
    
    Returns:
        Dictionary containing results_df and stats
    """
    if progress_callback:
        progress_callback("Loading data...", 10)
    
    as_of_clean = (as_of_date or "").strip() or None
    csv_data = pd.read_csv(csv_file_path, low_memory=False)

    if closings_file_path:
        closed_deals = pd.read_excel(closings_file_path)
        if as_of_clean:
            original_n = len(closed_deals)
            try:
                closed_deals = filter_closed_deals_by_as_of(closed_deals, as_of_clean)
            except ValueError as exc:
                raise ValueError("as_of must be a valid calendar date in YYYY-MM-DD format") from exc
            if progress_callback:
                progress_callback(
                    f"As-of {as_of_clean}: using {len(closed_deals)} of {original_n} deals (Date Closed <= as-of)",
                    15,
                )
    else:
        try:
            closed_deals = derive_closed_deals_from_csv(csv_data, as_of_clean)
        except ValueError as exc:
            raise ValueError("as_of must be a valid calendar date in YYYY-MM-DD format") from exc
        if progress_callback:
            progress_callback(
                f"Derived {len(closed_deals)} closed deals from contact-history tags",
                15,
            )
    
    if progress_callback:
        source_label = "Closings workbook + CSV" if closings_file_path else "CSV tags only"
        progress_callback(f"Loaded {len(closed_deals)} closed deals and {len(csv_data)} CSV records ({source_label})", 20)
    
    # Match deals
    if progress_callback:
        progress_callback("Matching deals to CSV records...", 30)
    
    if closings_file_path:
        matches = match_deals_to_csv(closed_deals, csv_data)
    else:
        matches = match_closed_rows_to_csv(closed_deals, csv_data)
    matched_count = sum(1 for m in matches if m['csv_record'] is not None)
    
    if progress_callback:
        progress_callback(f"Matched {matched_count} out of {len(matches)} deals", 50)
    
    # Analyze contacts
    if progress_callback:
        progress_callback("Parsing contact tags and analyzing...", 60)
    
    results_df = analyze_contacts(matches)
    
    # Generate statistics
    if progress_callback:
        progress_callback("Generating summary statistics...", 80)
    
    stats = generate_summary_stats(results_df)
    
    if progress_callback:
        progress_callback("Analysis complete!", 100)
    
    # Convert DataFrame to dict for JSON serialization
    results_dict = results_df.to_dict('records')
    
    return {
        'results': results_dict,
        'stats': stats,
        'matched_count': matched_count,
        'total_deals': len(closed_deals),
        'as_of': as_of_clean,
    }
