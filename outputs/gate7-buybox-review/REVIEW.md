# Gate 7 buybox review

Review scope: the current working tree and all five reports supplied in `C:/Users/USER/Downloads/reproject (1)`. Sold and REISift CSVs were fully scanned. The three Salesforce workbooks were inspected for schemas and worksheet dimensions. Application code and input reports were not modified during this buybox review.

## Confirmed intended geography

- Source: `docs/BUYBOX_8020REI.md`. Combine its DM-Sept, Tina, and 8020 exclusions into one policy.
- Outer geography: Nassau and Suffolk, New York.
- One excluded-ZIP list. A listed ZIP excludes the entire record, regardless of city.
- One excluded-city list, consulted only when ZIP is missing.
- Scores do not determine exclusions.
- The rest of the buybox remains relevant, but source fields must exist before those criteria can be evaluated.

The compiled review candidate is `candidate_exclusions.json`: 72 ZIPs, 81 original city labels, 82 city names after splitting the explicit Westhampton / West Hampton entry, and 84 normalized city keys after retaining the known Westhampton Beach and E Moriches aliases. Source provenance is attached to entries. The 8020 column's ZIP-specific “only” qualifiers are preserved.

## Current code walkthrough

1. `backend/app/services/buybox_zips.py:16` contains 125 **included** ZIPs. There is no runtime excluded-ZIP list. The list was derived from city associations, not directly from the consolidated suppression list.
2. `backend/app/services/buybox_zips.py:41` normalizes ZIP values. It supports ZIP+4 and spreadsheet numeric artifacts, but also salvages arbitrary digit substrings. Malformed nonblank values should be distinguished from missing ZIPs before implementing the new rule. The supplied sold CSV has no nonblank unusable ZIPs under this helper.
3. `backend/app/services/buybox_towns.py:255` accepts a ZIP match immediately, then tries the city even if a ZIP was supplied and rejected. Thus either match is sufficient. This is the opposite of an authoritative ZIP decision with city fallback only for missing ZIP.
4. `backend/app/services/investor_sold.py:979` loads the raw sold file. Lines 1006–1040 load enrichment indexes. Loading these indexes does not add properties to the report.
5. `backend/app/services/investor_sold.py:1062` applies the geography helper to each raw sold row. Excluded rows are skipped before constructing report rows.
6. `backend/app/services/investor_sold.py:1116` collapses surviving transactions to property × sold month. Lines 1119–1136 enrich those surviving properties with REISift, QL, Opportunities, and Transaction Pipeline evidence. Lines 1138 onward calculate KPIs. Enrichment cannot resurrect geographically excluded rows.

The filtering position is correct. Membership rules and source lists are incorrect for the confirmed intent. The county boundary is currently absent.

## Measured impact on the supplied sold report

All figures below count source transaction rows, before property-month deduplication.

| Step | Rows |
|---|---:|
| Raw sold file | 72,918 |
| Current ZIP-or-city rule admits | 17,944 |
| Raw Nassau/Suffolk NY rows | 6,335 |
| Rejected by the 72-ZIP exclusion union within Nassau/Suffolk | 1,497 |
| Proposed geography survivors | 4,838 |

The current included rows comprise Kings 6,378; Queens 5,565; Suffolk 3,469; Nassau 2,404; Albany 128. Therefore 12,071 currently admitted rows are outside the confirmed Nassau/Suffolk boundary.

Simply making the old 125-ZIP inclusion list authoritative would produce 5,326 rows, but that is not the intended policy. It omits marketed ZIPs such as East Meadow 11554, Merrick 11566, Oceanside 11572, West Hempstead 11552, and Lynbrook 11563. In the full 751,250-row REISift export, 77,428 records currently qualify by city despite having ZIPs outside that old list.

Conversely, current code admits source-documented suppressed places: Southampton 11968 (64 sold rows), Montauk 11954 (26), Southold 11971 (26), Westhampton Beach 11978 (19), East Moriches 11940 (14), and Lloyd Harbor 11743 (2).

ZIP-wide exclusions also remove other cities sharing those ZIPs. Examples in the supplied file: Huntington 11743 (104 rows), Riverhead 11901 (77), Syosset 11791 (68), and Port Washington 11050 (67). This is a direct consequence of compiling all listed ZIP associations into hard exclusions. These are counts under the documented mapping, not an independent postal-geography validation.

## Other buybox requirements

The confirmed document also specifies property types (SFH and 2–9 units), owner types, ownership duration, property age, LTV, estimated value, living area, and lot size. The raw sold CSV has geography, transaction identifiers, buyer, sale amount, investor flags/score, and distressor labels. It does not provide the structured attributes needed to enforce those remaining requirements.

Sale amount cannot silently substitute for estimated market value. Investor score cannot substitute for buybox eligibility. REISift membership cannot substitute for those attributes across all sold properties: doing so would eliminate properties never acquired into REISift and bias the coverage KPI.

Accordingly, 4,838 is a **geography-only** preview, not a count proven eligible under the full property buybox. Complete enforcement requires property attributes for the sold universe, with a defined policy for unknown values and an appropriate pre-sale clock for ownership-related fields.

## Upstream coverage observation

Before any exclusions, Nassau/Suffolk counts in the supplied sold CSV fall from 1,536 in February, 1,642 in March, and 1,570 in April to 1,144 in May, 350 in June, and 93 in July 2026. This is present in the source file. It is not caused by Gate 7 filtering. No conclusion about the reason or completeness of those months was established in this review.

## Next implementation scope

Replace the derived positive ZIP/town combination with the consolidated exclusion policy and county boundary. Preserve the raw suppression evidence and maintain one executable policy source. Add tests for excluded ZIP plus otherwise eligible city, missing ZIP city fallback, shared ZIP exclusions, unknown geography, and exclusion before all KPI computation. Report raw count, outside-county exclusions, excluded-ZIP count, excluded-city fallback count, unresolved geography, and surviving properties separately. Update report wording to distinguish geographic coverage from full-property buybox coverage until the missing attributes are available.
