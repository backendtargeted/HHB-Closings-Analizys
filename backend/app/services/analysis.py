"""
Core analysis logic extracted from contact_attribution_gui.py
"""

import pandas as pd
import numpy as np
import re
from datetime import datetime
import os
from typing import Dict, List, Any, Optional
import json


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


def parse_tags(tags_str):
    """
    Parse the Tags column to extract contact information.
    Returns a list of dictionaries with contact details.
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
                    'date': skip_date.isoformat(),
                    'month': month,
                    'year': year,
                    'tag': tag
                })
            except ValueError:
                continue
    
    return contacts


def parse_excel_address(full_address):
    """
    Parse Excel address format (e.g., "248 E. Shore Rd Lindenhurst") into street and city.
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
        # Parse Excel address into street and city
        street_addr, city = parse_excel_address(deal['Address'])
        
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
                'Match Found': False
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
            'Match Found': True
        })
    
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
    
    return stats


def perform_analysis(excel_file_path: str, csv_file_path: str, progress_callback=None) -> Dict[str, Any]:
    """
    Main analysis function that orchestrates the entire process.
    
    Args:
        excel_file_path: Path to Excel file with closed deals
        csv_file_path: Path to CSV file with contact history
        progress_callback: Optional callback function for progress updates
    
    Returns:
        Dictionary containing results_df and stats
    """
    if progress_callback:
        progress_callback("Loading data...", 10)
    
    # Load data
    closed_deals = pd.read_excel(excel_file_path)
    csv_data = pd.read_csv(csv_file_path, low_memory=False)
    
    if progress_callback:
        progress_callback(f"Loaded {len(closed_deals)} closed deals and {len(csv_data)} CSV records", 20)
    
    # Match deals
    if progress_callback:
        progress_callback("Matching deals to CSV records...", 30)
    
    matches = match_deals_to_csv(closed_deals, csv_data)
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
        'total_deals': len(closed_deals)
    }
