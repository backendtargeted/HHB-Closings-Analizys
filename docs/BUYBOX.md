# Gate 7 buybox — active report contract

Gate 7 evaluates provider coverage among eligible properties in **Nassau and Suffolk counties, New York**. Geography is filtered from the raw sold report before property rows, REISift/CRM enrichment, or KPIs are built.

## Source of truth

[buybox_policy.json](../backend/app/services/buybox_policy.json) is the single executable policy: **72 excluded ZIPs and 84 excluded city keys**, with source provenance. It consolidates the union of DM-Sept, Tina, and the 8020 ZIP list in [BUYBOX_8020REI.md §13](BUYBOX_8020REI.md#13-suppressed-towns--source-list). Any source's suppression is sufficient. Source-specific “only” annotations are respected; other sources can still supply the remaining ZIPs.

No scores determine membership. Neither the 8020 compound score/count column nor the sold CSV's investor classification score supplies an exclusion. The raw source document preserves evidence, while the JSON supplies runtime decisions.

## Decision order

1. Require state NY/New York and county Nassau/Suffolk. Missing or other state/county is excluded.
2. When ZIP is present, normalize it and check the excluded ZIP list. An excluded ZIP is outside the universe regardless of city. A valid ZIP absent from the exclusions passes geography.
3. A malformed nonblank ZIP is excluded; it does not activate city fallback.
4. Only when ZIP is absent, normalize the city and check the excluded-city list. Missing city or an excluded city is excluded; another nonblank city passes.

ZIP normalization accepts five digits, ZIP+4, nine-digit ZIP+4, numeric CSV artifacts such as `11550.0`, and four digits with a lost leading zero. It does not extract digits from arbitrary text. City normalization trims whitespace and trailing punctuation, collapses internal spaces, and ignores case.

Shared ZIPs are excluded in full: for example, 11743 is excluded even when a row says Huntington. Conversely, an excluded city name with a valid nonexcluded ZIP passes because city is only a fallback. This precedence is intentional.

Implementation: [evaluate_buybox](../backend/app/services/buybox_towns.py), [ZIP normalization](../backend/app/services/buybox_zips.py), and sold ingest in [investor_sold.py](../backend/app/services/investor_sold.py). Exclusion reasons and counts make the universe auditable.

## Scope and limits

With `sold_property_details.jsonl`, Gate 7 streams details only for geographically admitted properties, after collapsing repeat transactions. The returned property's APN and county must match the original sold evidence: the JSONL's copied sold IDs alone do not prove a correct property lookup. Unverified identities and missing details remain unresolved, outside the screened KPI universe, with an audit row.

Supported property screening uses the documented SFH/2–9-unit, property age, estimated value, living area and lot-size criteria. Only properties passing these supported rules enter pipeline enrichment. Unknown values pass only where the source buybox explicitly permits unknowns. This is a screen using the retrieved property snapshot, not certification of every characteristic as of the sale. Ownership duration, LTV, and non-seller/religious-owner exclusion remain unevaluated and are disclosed in the report. Individual-file uploads without details retain the geographic-only workflow, clearly labeled.

Seller categories are **Trust / Company / Individual**, with **Unclassified** for insufficient evidence. These are name-based inferences from historical sellers, only after validating the property and uniquely matching a transaction to the earliest sold month, original buyer and sale amount. Current-owner names never substitute for the seller. The earliest month is the precision of the sold source; the report does not invent transaction order within that month.

The UI and Excel export expose screening counts and a property screening audit, including excluded and unresolved properties. Seller category totals describe the eligible KPI universe.

The report view presents coverage/loss KPIs, a cumulative pipeline funnel, seller ownership composition, and the property table. Selecting a chart focuses that table; table filters do not recalculate the full-report summaries. A property's row shows its furthest stage, while the funnel includes it in every earlier stage it reached. Data review contains geographic counts, screening exceptions, and methodology. Monthly and source-list breakdowns remain available under supporting breakdowns.

The raw scrape can remain statewide. Closings defines the analysis universe; matching REISift records never readmits a geographically excluded sold row.

## Upload bundle

Upload a ZIP containing these exact names at its root or inside one shared folder:

| File | Required |
|---|---|
| `sold_properties_full.csv` | Yes |
| `reisift_export.csv` | Yes |
| `qualified_leads.xlsx` or `qualified_leads.csv` | Yes, exactly one |
| `sold_property_details.jsonl` | Yes |
| `opportunities.xlsx` or `opportunities.csv` | Optional, at most one |
| `transactions.xlsx` or `transactions.csv` | Optional, at most one |

Rename copies of Salesforce exports to these canonical bundle names. The backend validates and streams extraction in a background worker, then applies geography → earliest-property collapse → validated details → REISift/CRM → KPIs. Extra substantive files, ambiguous duplicates, nested folders, and unsafe ZIP entries fail with an explanation. The default uncompressed limit is 4 GiB, configurable with `INVESTOR_SOLD_BUNDLE_MAX_UNCOMPRESSED_BYTES`. Large uploads use the existing resumable upload mechanism. Original individual-file uploads remain available.

## Property grain and timing

Each property appears once across the report, anchored to its earliest observed sold month. All distinct transaction IDs remain counted. Later-month investor/In My Records flags and buyers do not change the earlier snapshot. Distinct buyers observed within the earliest month are displayed together; the source does not establish their exact within-month order.

Enrichment is evaluated relative to that anchored sold month. Headline pipeline cards are cumulative “reached at least” counts, divided by eligible unique properties. “Never prospected” evaluates investor properties without qualifying pre-sale Prospect-list history; “Lost” evaluates investor properties we had before the sale that were not HHB-closed.

## Historical provenance — not active policy

Earlier versions used a town allowlist, then a permissive town-OR-ZIP allowlist. The ZIP list was derived from any marketed name appearing in a source ZIP row, admitting suppressed ZIPs again. Town deletions alone could not prevent readmission by ZIP.

Those historical positive town labels remain in code only for compatibility with old metadata consumers. They do not decide membership. Old marketed-town counts, statewide proportions, and property-by-month totals are not current report denominators.

The source's 8020 table includes incomplete city captures and mixed city/ZIP associations. It is retained as evidence, not interpreted as a new postal map or score-based rule.

## Known source limitations

The historical production audit found the scraper's In My Records API returning zero for Mar–Jul 2026. That observation is a source-data caveat, not a reason to change geography. REISift list-purchase tags independently provide Prospect evidence. Recheck the source before treating missing scrape presence as complete coverage.

Salesforce Transaction Pipeline exports may lack a separate city field, requiring street-plus-ZIP matching. Its candidate window is bounded by first Prospect month when available, otherwise the configured lookback, and by sold month end; see [REPORT_METHODOLOGY.md §21](REPORT_METHODOLOGY.md#21-gate-7-investor--in-list-sold).

## Maintaining the policy

Edit the single JSON policy and its provenance, update regression tests, refresh the appendix with `python backend/scripts/gen_buybox_doc.py`, and rerun Gate 7. The generator updates only the marked appendix and preserves this operator contract.

<!-- BUYBOX_POLICY_APPENDIX_START -->

## Exclusion-policy appendix

Generated from `buybox_policy.json`: 72 ZIPs and 84 city keys.

### Excluded ZIPs

`06390`, `10591`, `10598`, `11020`, `11021`, `11023`, `11024`, `11030`, `11050`, `11375`, `11421`, `11507`, `11509`, `11516`, `11545`, `11547`, `11548`, `11557`, `11559`, `11560`, `11569`, `11576`, `11577`, `11579`, `11581`, `11596`, `11598`, `11702`, `11732`, `11743`, `11771`, `11777`, `11780`, `11782`, `11786`, `11791`, `11797`, `11901`, `11930`, `11931`, `11932`, `11933`, `11935`, `11937`, `11939`, `11940`, `11941`, `11942`, `11944`, `11946`, `11947`, `11948`, `11952`, `11954`, `11956`, `11957`, `11958`, `11959`, `11962`, `11963`, `11964`, `11965`, `11968`, `11970`, `11971`, `11972`, `11975`, `11976`, `11977`, `11978`, `12601`, `12603`

### Excluded city keys

- albany
- amagansett
- aquebogue
- atlantic beach
- baiting hollow
- bridgehampton
- buffalo
- cedarhurst
- cherry grove
- cutchogue
- e moriches
- east atlantic beach
- east hampton
- east hills
- east marion
- east moriches
- east norwich
- east quogue
- eastport
- fishers island
- forest hills
- gilgo beach
- glen head
- glenwood landing
- great neck
- greenport
- halesite
- hampton bays
- henderson
- hewlett
- hewlett harbor
- james
- jamesport
- kings point
- laurel
- laurel hollow
- lawrence
- lloyd harbor
- locust valley
- mattituck
- montauk
- muttontown
- new suffolk
- north haven
- north hills
- north woodmere
- oak beach
- oak island
- old brookville
- orient
- peconic
- plandome
- point lookout
- poughkeepsie
- quogue
- roslyn
- roslyn estates
- roslyn harbor
- roslyn heights
- sag harbor
- sagaponack
- sands point
- sea cliff
- searingtown
- shelter island
- shelter island heights
- shoreham
- south jamesport
- southampton
- southold
- speonk
- tarrytown
- upper brookville
- wainscott
- water mill
- west hampton
- west hampton beach
- westhampton
- westhampton beach
- williston park
- woodbury
- woodhaven
- woodmere
- yorktown heights

<!-- BUYBOX_POLICY_APPENDIX_END -->

## Related

- [SOP.md](SOP.md) — operator workflow
- [REPORT_METHODOLOGY.md](REPORT_METHODOLOGY.md) — report methods
- [BUYBOX_8020REI.md](BUYBOX_8020REI.md) — captured source evidence
