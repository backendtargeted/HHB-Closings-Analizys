"""
Contact Attribution Analysis
Analyzes contact history for closed deals to identify trends and patterns.
"""

import pandas as pd
import numpy as np
import re
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns
from collections import Counter
import warnings
warnings.filterwarnings('ignore')

# Set style for plots
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (12, 6)

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
                    'date': contact_date,
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
                    'date': list_date,
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
                    'date': skip_date,
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
    
    # Common city names in the area (to help identify where address ends and city begins)
    # This is a heuristic - city names are typically at the end
    parts = addr_str.split()
    
    # Try to identify city (usually last 1-2 words)
    # Common patterns: "Street City" or "Street St City" or "Street Ave City"
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

def match_deals_to_csv(closed_deals, csv_data):
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
                'deal_index': idx,
                'csv_index': None,
                'closed_date': deal['Date Closed'],
                'address': deal['Address'],
                'lead_source': deal['Lead Source'],
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
                'deal_index': idx,
                'csv_index': match.name,
                'closed_date': deal['Date Closed'],
                'address': deal['Address'],
                'lead_source': deal['Lead Source'],
                'csv_record': match
            })
        else:
            # No match found
            matches.append({
                'deal_index': idx,
                'csv_index': None,
                'closed_date': deal['Date Closed'],
                'address': deal['Address'],
                'lead_source': deal['Lead Source'],
                'csv_record': None
            })
    
    return matches

def analyze_contacts(matches):
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
        contacts = parse_tags(csv_record.get('Tags', ''))
        
        # Filter contacts that occurred before closing date
        # Since we only have month/year, we'll consider a contact as "before" if its date is before the closing month
        contacts_before = [
            c for c in contacts 
            if c['type'] == 'contact' and c['date'] < closed_date
        ]
        
        # Count contacts by channel
        cc_count = len([c for c in contacts_before if c['channel'] == 'CC'])
        sms_count = len([c for c in contacts_before if c['channel'] == 'SMS'])
        dm_count = len([c for c in contacts_before if c['channel'] == 'DM'])
        total_contacts = len(contacts_before)
        
        # Get first and last contact dates
        if contacts_before:
            first_contact = min(c['date'] for c in contacts_before)
            last_contact = max(c['date'] for c in contacts_before)
            
            # Calculate days (approximate since we only have month/year)
            days_to_close = (closed_date - first_contact).days
            days_since_last = (closed_date - last_contact).days
            
            # Create contact timeline
            timeline = []
            for c in sorted(contacts_before, key=lambda x: x['date']):
                timeline.append(f"{c['channel']} ({c['date'].strftime('%b %Y')})")
            contact_timeline = ' → '.join(timeline)
        else:
            first_contact = None
            last_contact = None
            days_to_close = None
            days_since_last = None
            contact_timeline = 'No contacts before closing'
        
        results.append({
            'Address': match['address'],
            'Date Closed': closed_date,
            'Lead Source': match['lead_source'],
            'Total Contacts': total_contacts,
            'CC Count': cc_count,
            'SMS Count': sms_count,
            'DM Count': dm_count,
            'First Contact Date': first_contact,
            'Last Contact Date': last_contact,
            'Days to Close': days_to_close,
            'Days Since Last Contact': days_since_last,
            'Contact Timeline': contact_timeline,
            'Match Found': True
        })
    
    return pd.DataFrame(results)

def generate_summary_stats(results_df):
    """
    Generate summary statistics from results.
    """
    matched_results = results_df[results_df['Match Found'] == True]
    
    if len(matched_results) == 0:
        return {}
    
    stats = {
        'Total Deals': len(results_df),
        'Matched Deals': len(matched_results),
        'Unmatched Deals': len(results_df) - len(matched_results),
        'Match Rate': f"{(len(matched_results) / len(results_df) * 100):.1f}%",
        'Average Contacts per Deal': matched_results['Total Contacts'].mean(),
        'Median Contacts per Deal': matched_results['Total Contacts'].median(),
        'Max Contacts': matched_results['Total Contacts'].max(),
        'Min Contacts': matched_results['Total Contacts'].min(),
        'Total CC Contacts': matched_results['CC Count'].sum(),
        'Total SMS Contacts': matched_results['SMS Count'].sum(),
        'Total DM Contacts': matched_results['DM Count'].sum(),
        'Average Days to Close': matched_results['Days to Close'].mean() if matched_results['Days to Close'].notna().any() else None,
        'Median Days to Close': matched_results['Days to Close'].median() if matched_results['Days to Close'].notna().any() else None,
    }
    
    return stats

def create_visualizations(results_df, output_dir='.'):
    """
    Create visualizations for the analysis.
    """
    matched_results = results_df[results_df['Match Found'] == True]
    
    if len(matched_results) == 0:
        print("No matched deals found for visualization.")
        return
    
    # Create figure with subplots
    fig = plt.figure(figsize=(16, 12))
    
    # 1. Contact Count Distribution
    ax1 = plt.subplot(2, 3, 1)
    contact_counts = matched_results['Total Contacts'].value_counts().sort_index()
    ax1.bar(contact_counts.index, contact_counts.values, color='steelblue', alpha=0.7)
    ax1.set_xlabel('Number of Contacts Before Closing')
    ax1.set_ylabel('Number of Deals')
    ax1.set_title('Distribution of Contact Counts')
    ax1.grid(axis='y', alpha=0.3)
    
    # 2. Channel Usage Breakdown
    ax2 = plt.subplot(2, 3, 2)
    channel_totals = {
        'CC': matched_results['CC Count'].sum(),
        'SMS': matched_results['SMS Count'].sum(),
        'DM': matched_results['DM Count'].sum()
    }
    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1']
    ax2.pie(channel_totals.values(), labels=channel_totals.keys(), autopct='%1.1f%%', 
            colors=colors, startangle=90)
    ax2.set_title('Total Contacts by Channel')
    
    # 3. Average Contacts by Channel
    ax3 = plt.subplot(2, 3, 3)
    avg_by_channel = {
        'CC': matched_results['CC Count'].mean(),
        'SMS': matched_results['SMS Count'].mean(),
        'DM': matched_results['DM Count'].mean()
    }
    ax3.bar(avg_by_channel.keys(), avg_by_channel.values(), color=colors, alpha=0.7)
    ax3.set_ylabel('Average Contacts per Deal')
    ax3.set_title('Average Contacts by Channel')
    ax3.grid(axis='y', alpha=0.3)
    
    # 4. Contact Count vs Days to Close
    ax4 = plt.subplot(2, 3, 4)
    valid_data = matched_results[matched_results['Days to Close'].notna()]
    if len(valid_data) > 0:
        ax4.scatter(valid_data['Total Contacts'], valid_data['Days to Close'], 
                   alpha=0.6, color='steelblue')
        ax4.set_xlabel('Number of Contacts')
        ax4.set_ylabel('Days to Close')
        ax4.set_title('Contact Count vs Days to Close')
        ax4.grid(alpha=0.3)
    
    # 5. Lead Source Distribution
    ax5 = plt.subplot(2, 3, 5)
    lead_source_counts = matched_results['Lead Source'].value_counts()
    ax5.barh(lead_source_counts.index, lead_source_counts.values, color='coral', alpha=0.7)
    ax5.set_xlabel('Number of Deals')
    ax5.set_title('Deals by Lead Source')
    ax5.grid(axis='x', alpha=0.3)
    
    # 6. Contacts by Lead Source
    ax6 = plt.subplot(2, 3, 6)
    lead_source_contacts = matched_results.groupby('Lead Source')['Total Contacts'].mean().sort_values(ascending=False)
    ax6.barh(lead_source_contacts.index, lead_source_contacts.values, color='mediumseagreen', alpha=0.7)
    ax6.set_xlabel('Average Contacts')
    ax6.set_title('Average Contacts by Lead Source')
    ax6.grid(axis='x', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(f'{output_dir}/contact_analysis_charts.png', dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"Visualizations saved to {output_dir}/contact_analysis_charts.png")

def create_html_report(results_df, stats, output_file='contact_analysis_report.html'):
    """
    Create an HTML report with results and visualizations.
    """
    matched_results = results_df[results_df['Match Found'] == True]
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Contact Attribution Analysis Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
            .container {{ max-width: 1200px; margin: 0 auto; background-color: white; padding: 30px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }}
            h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
            h2 {{ color: #34495e; margin-top: 30px; }}
            .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
            .stat-box {{ background-color: #ecf0f1; padding: 15px; border-radius: 5px; border-left: 4px solid #3498db; }}
            .stat-label {{ font-size: 12px; color: #7f8c8d; text-transform: uppercase; }}
            .stat-value {{ font-size: 24px; font-weight: bold; color: #2c3e50; margin-top: 5px; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #3498db; color: white; }}
            tr:hover {{ background-color: #f5f5f5; }}
            .chart {{ text-align: center; margin: 30px 0; }}
            .insights {{ background-color: #e8f5e9; padding: 20px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #4caf50; }}
            .insights h3 {{ margin-top: 0; color: #2e7d32; }}
            .insights ul {{ margin: 10px 0; padding-left: 20px; }}
            .insights li {{ margin: 8px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Contact Attribution Analysis Report</h1>
            <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            
            <h2>Summary Statistics</h2>
            <div class="stats">
    """
    
    for key, value in stats.items():
        html_content += f"""
                <div class="stat-box">
                    <div class="stat-label">{key}</div>
                    <div class="stat-value">{value}</div>
                </div>
        """
    
    html_content += """
            </div>
            
            <div class="chart">
                <img src="contact_analysis_charts.png" alt="Analysis Charts" style="max-width: 100%; height: auto;">
            </div>
            
            <h2>Key Insights</h2>
            <div class="insights">
    """
    
    # Generate insights
    insights = []
    
    if stats.get('Average Contacts per Deal'):
        avg_contacts = stats['Average Contacts per Deal']
        insights.append(f"Average of {avg_contacts:.1f} contacts were made before closing")
    
    if stats.get('Total CC Contacts') and stats.get('Total SMS Contacts') and stats.get('Total DM Contacts'):
        total_all = stats['Total CC Contacts'] + stats['Total SMS Contacts'] + stats['Total DM Contacts']
        if total_all > 0:
            cc_pct = (stats['Total CC Contacts'] / total_all) * 100
            sms_pct = (stats['Total SMS Contacts'] / total_all) * 100
            dm_pct = (stats['Total DM Contacts'] / total_all) * 100
            insights.append(f"Channel distribution: CC ({cc_pct:.1f}%), SMS ({sms_pct:.1f}%), DM ({dm_pct:.1f}%)")
    
    if stats.get('Average Days to Close'):
        insights.append(f"Average time from first contact to closing: {stats['Average Days to Close']:.0f} days")
    
    # Contact count distribution insights
    contact_dist = matched_results['Total Contacts'].value_counts().sort_index()
    most_common_count = contact_dist.idxmax()
    insights.append(f"Most common contact count before closing: {most_common_count} contacts ({contact_dist[most_common_count]} deals)")
    
    for insight in insights:
        html_content += f"<li>{insight}</li>"
    
    html_content += """
            </div>
            
            <h2>Detailed Results</h2>
            <p>Showing first 50 matched deals. Full data available in Excel export.</p>
    """
    
    # Create table of results (first 50)
    display_df = matched_results.head(50)[['Address', 'Date Closed', 'Lead Source', 'Total Contacts', 
                                           'CC Count', 'SMS Count', 'DM Count', 'Days to Close']]
    html_content += "<table><tr>"
    for col in display_df.columns:
        html_content += f"<th>{col}</th>"
    html_content += "</tr>"
    
    for _, row in display_df.iterrows():
        html_content += "<tr>"
        for col in display_df.columns:
            value = row[col]
            if pd.isna(value):
                value = '-'
            elif isinstance(value, datetime):
                value = value.strftime('%Y-%m-%d')
            else:
                value = str(value)
            html_content += f"<td>{value}</td>"
        html_content += "</tr>"
    
    html_content += """
            </table>
        </div>
    </body>
    </html>
    """
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"HTML report saved to {output_file}")

def main():
    """
    Main analysis function.
    """
    print("=" * 60)
    print("Contact Attribution Analysis")
    print("=" * 60)
    
    # File paths
    excel_file = r'c:\Users\USER\Desktop\HHB 2024 Closings Analizys\2025 Closed Attribution.xlsx'
    csv_file = r'c:\Users\USER\Desktop\HHB 2024 Closings Analizys\reisift_sample.csv'
    output_dir = r'c:\Users\USER\Desktop\HHB 2024 Closings Analizys'
    
    # Step 1: Load data
    print("\n1. Loading data...")
    closed_deals = pd.read_excel(excel_file)
    print(f"   Loaded {len(closed_deals)} closed deals")
    
    csv_data = pd.read_csv(csv_file, low_memory=False)
    print(f"   Loaded {len(csv_data)} CSV records")
    
    # Step 2: Match deals
    print("\n2. Matching deals to CSV records...")
    matches = match_deals_to_csv(closed_deals, csv_data)
    matched_count = sum(1 for m in matches if m['csv_record'] is not None)
    print(f"   Matched {matched_count} out of {len(matches)} deals")
    
    # Step 3: Parse tags and analyze contacts
    print("\n3. Parsing contact tags and analyzing...")
    results_df = analyze_contacts(matches)
    
    # Step 4: Generate summary statistics
    print("\n4. Generating summary statistics...")
    stats = generate_summary_stats(results_df)
    for key, value in stats.items():
        print(f"   {key}: {value}")
    
    # Step 5: Create visualizations
    print("\n5. Creating visualizations...")
    create_visualizations(results_df, output_dir)
    
    # Step 6: Export results
    print("\n6. Exporting results...")
    
    # Export detailed results to Excel
    results_excel = f'{output_dir}/contact_analysis_results.xlsx'
    with pd.ExcelWriter(results_excel, engine='openpyxl') as writer:
        results_df.to_excel(writer, sheet_name='Detailed Results', index=False)
        
        # Create summary sheet
        summary_data = []
        for key, value in stats.items():
            summary_data.append({'Metric': key, 'Value': value})
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name='Summary Statistics', index=False)
        
        # Contact count distribution
        contact_dist = results_df[results_df['Match Found'] == True]['Total Contacts'].value_counts().sort_index()
        dist_df = pd.DataFrame({
            'Contact Count': contact_dist.index,
            'Number of Deals': contact_dist.values
        })
        dist_df.to_excel(writer, sheet_name='Contact Distribution', index=False)
    
    print(f"   Detailed results saved to {results_excel}")
    
    # Create HTML report
    html_report = f'{output_dir}/contact_analysis_report.html'
    create_html_report(results_df, stats, html_report)
    
    print("\n" + "=" * 60)
    print("Analysis Complete!")
    print("=" * 60)
    print(f"\nOutput files:")
    print(f"  - {results_excel}")
    print(f"  - {html_report}")
    print(f"  - {output_dir}/contact_analysis_charts.png")

if __name__ == '__main__':
    main()
