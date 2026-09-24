# 8020REI Buybox — raw scrape (2026-09-23)

Source: `mandalayholdings.8020rei.com/buybox/form/63fcc492c329a14c9847e134`, buybox **"Residential - Nassau & Suffolk"**. Scraped live, step by step, from the 8020REI UI (no export/API available in the tool — `Actions` menu only offers History / Restore last version / Add all / Remove all, none of which were used). This is a data capture, not a report: raw values as shown, in the order the UI returned them. Numbers will drift as 8020REI's data refreshes.

Final result (Summary step): **380K properties** match the full filter stack.

---

## 1. Counties — 2/2 included

| County | Parcels | Residential | Buybox score > 0 | Deals concentration A | Deals concentration B |
|---|---|---|---|---|---|
| Suffolk, NY | 587K | 408K | 215K | 8.5K (0.7×) | 493 (1×) |
| Nassau, NY | 427K | 377K | 157K | 4.5K (1.4×) | 482 (1×) |
| **Total** | **1M** | **785K** | **372K** | 6.2K (1×) | 488 (1×) |

## 2. Property type — 2/12 included

Included (toggle "Include listed properties" = ON for both): **SFH**, **2-9 units**.

| Type | Properties | Buybox score > 0 | Included |
|---|---|---|---|
| SFH | 706K (70%) | 349K | Y (★★★★★, Recommended) |
| Others | 80K (7.9%) | 77 | N |
| Land | 79K (7.8%) | 180 | N |
| Commercial | 52K (5.1%) | 322 | N |
| Condo | 31K (3%) | 222 | N |
| 2-9 units | 39K (3.8%) | 23K | Y (★★☆☆☆) |
| Multi-family | 8.7K (0.85%) | 31 | N |
| Mobile Home | 6K (0.59%) | 24 | N |
| Townhouse | 9.3K (0.92%) | 212 | N |
| Warehouse | 3K (0.29%) | 3 | N |
| Mobile Home Park | 28 (0%) | 2 | N |
| Modular Homes | 25 (0%) | 0 | N |
| **Total** | **1M** | **373K** | |

## 3. Weights — sums to 100% (raw slider/number field values)

| Dimension | Weight |
|---|---|
| Property type | 5 |
| ZIP Code | 30 |
| Owner type | 5 |
| Year of ownership | 20 |
| Years old | 5 |
| LTV | 5 |
| Estimated market value | 20 |
| Living area | 5 |
| Lot size | 5 |
| **Total** | **100** |

## 4. Zip Code — 105/172 included

Rating-bucket distribution shown on this step: 1★ 114K (18%), 2★ 124K (20%), 3★ 169K (27%), 4★ 89K (14%), 5★ 122K (20%). Table total row: 738K properties / 372K buybox score > 0 (visible-rows running total, not all 172 summed — 8020REI recomputes this total live as the table scrolls, it is not a per-page subtotal).

Scraped in sequential scroll windows; consecutive windows overlap by a few rows (shown once, at first appearance) since the UI virtualizes/re-renders on scroll. **Included = Buybox score > 0** in this table (every row with a star rating had a nonzero score; every row showing "Add to buybox" had score = 0 — treated as the inclusion signal since the UI didn't expose an explicit included/excluded flag in the text extraction).

| Zip | Properties | Buybox score > 0 | County | City |
|---|---|---|---|---|
| 11001 | 6.1K (0.83%) | 3.2K | Nassau | Bellerose Terrace, Elmont, Floral Park |
| 11003 | 9.3K (1.3%) | 6.4K | Nassau | Elmont, South Floral Park |
| 11010 | 6.9K (0.93%) | 4.4K | Nassau | Franklin Square |
| 11020 | 1.8K (0.24%) | 0 | Nassau | Great Neck, Lake Success |
| 11021 | 2.8K (0.38%) | 0 | Nassau | Great Neck, Great Neck Estates |
| 11023 | 2.6K (0.35%) | 0 | Nassau | Great Neck, Kings Point |
| 11024 | 2.2K (0.29%) | 0 | Nassau | Great Neck, Kings Point |
| 11030 | 5.2K (0.7%) | 0 | Nassau | Manhasset, Plandome |
| 11040 | 12K (1.6%) | 4.2K | Nassau | Garden City, Garden City Park, Manhasset, New Hyde Park |
| 11050 | 7.8K (1.1%) | 1.2K | Nassau | Port Washington, Port Washington North, Prt Washingtn, Sands Point |
| 11096 | 1.3K (0.17%) | 0 | Nassau | Inwood |
| 11501 | 4.6K (0.62%) | 2.8K | Nassau | Mineola |
| 11507 | 2.3K (0.31%) | 0 | Nassau | Albertson |
| 11509 | 1.1K (0.15%) | 0 | Nassau | Atlantic Beach |
| 11510 | 9.3K (1.3%) | 6.1K | Nassau | Baldwin, North Baldwin |
| 11514 | 1.3K (0.18%) | 662 | Nassau | Carle Place |
| 11516 | 1.7K (0.22%) | 0 | Nassau | Cedarhurst |
| 11518 | 3K (0.41%) | 1.7K | Nassau | East Rockaway |
| 11520 | 8.6K (1.2%) | 5.4K | Nassau | Freeport |
| 11530 | 8K (1.1%) | 0 | Nassau | Garden City, Garden City South, Stewart Manor, Village Of Garden City |
| 11542 | 6.5K (0.88%) | 3.5K | Nassau | Glen Cove |
| 11545 | 3.8K (0.52%) | 427 | Nassau | Glen Head, Muttontown, Old Brookville, Upper Brookville |
| 11547 | 351 (0.05%) | 0 | Nassau | Glenwood Landing |
| 11548 | 387 (0.05%) | 0 | Nassau | Greenvale, Roslyn |
| 11550 | 8.1K (1.1%) | 5K | Nassau | Hempstead, South Hempstead, West Hempstead |
| 11552 | 6.8K (0.93%) | 4.1K | Nassau | *(not captured)* |
| 11553 | 5.2K (0.7%) | 3.8K | Nassau | *(not captured)* |
| 11554 | 10K (1.4%) | 6.3K | Nassau | *(not captured)* |
| 11557 | 2.2K (0.3%) | 537 | Nassau | *(not captured)* |
| 11558 | 2.1K (0.29%) | 0 | Nassau | *(not captured)* |
| 11559 | 1.9K (0.26%) | 0 | Nassau | *(not captured)* |
| 11560 | 2.2K (0.29%) | 0 | Nassau | *(not captured)* |
| 11561 | 7.1K (0.96%) | 2.8K | Nassau | *(not captured)* |
| 11563 | 5.6K (0.76%) | 3.6K | Nassau | *(not captured)* |
| 11565 | 3.1K (0.42%) | 1.9K | Nassau | *(not captured)* |
| 11566 | 11K (1.5%) | 4.8K | Nassau | *(not captured)* |
| 11568 | 1.1K (0.15%) | 0 | Nassau | *(not captured)* |
| 11569 | 828 (0.11%) | 0 | Nassau | *(not captured)* |
| 11570 | 6.7K (0.9%) | 2K | Nassau | *(not captured)* |
| 11575 | 3.7K (0.51%) | 2.5K | Nassau | Roosevelt |
| 11576 | 3.8K (0.52%) | 0 | Nassau | East Hills, Roslyn, Roslyn Harbor, Roslyn Heights |
| 11577 | 3.4K (0.46%) | 0 | Nassau | East Hills, Roslyn, Roslyn Heights |
| 11579 | 1.7K (0.22%) | 0 | Nassau | Sea Cliff |
| 11580 | 10K (1.3%) | 6.6K | Nassau | North Valley Stream, Valley Stream |
| 11581 | 5.8K (0.79%) | 2.7K | Nassau | North Woodmere, Valley Stream, Woodmere |
| 11590 | 11K (1.4%) | 5.9K | Nassau | Westbury |
| 11596 | 3.2K (0.44%) | 0 | Nassau | East Williston, Williston Park |
| 11598 | 3.6K (0.49%) | 0 | Nassau | Hewlett, Woodmere |
| 11701 | 5.8K (0.79%) | 3.9K | Suffolk | Amity Harbor, Amityville, N Amityville |
| 11702 | 4.3K (0.58%) | 2.3K | Suffolk | Babylon, Captree Is, Gilgo Beach, N Babylon, North Babylon, Oak Beach, W Babylon, West Babylon, Westhampton Beach |
| 11703 | 4.5K (0.61%) | 3K | Suffolk | N Babylon, North Babylon, W Babylon |
| 11704 | 9.8K (1.3%) | 6.8K | Suffolk | N Babylon, North Babylon, W Babylon, West Babylon |
| 11705 | 2.3K (0.32%) | 1.2K | Suffolk | Amityville, Bayport |
| 11706 | 14K (1.9%) | 8.8K | Suffolk | Bay Shore, East Hampton, Melville |
| 11709 | 2.4K (0.32%) | 0 | Nassau | Bayville |
| 11710 | 11K (1.5%) | 6.2K | Nassau | Bellmore, North Bellmore |
| 11713 | 3K (0.4%) | 1.6K | Suffolk | Bellport, Northport |
| 11714 | 6.6K (0.89%) | 4.2K | Nassau | Bethpage |
| 11715 | 1.6K (0.22%) | 974 | Suffolk | Blue Point, Wyandanch |
| 11716 | 2.6K (0.35%) | 1.7K | Suffolk | Bohemia, Greenport |
| 11717 | 11K (1.4%) | 7.3K | Suffolk | Brentwood |
| 11718 | 1.1K (0.15%) | 0 | Suffolk | Brightwaters |
| 11719 | 1.2K (0.16%) | 578 | Suffolk | Brookhaven |
| 11720 | 8.3K (1.1%) | 5.5K | Suffolk | Centereach, East Setauket, S Setauket, Setauket, South Setauket |
| 11721 | 882 (0.12%) | 0 | Suffolk | Centerport |
| 11722 | 6.8K (0.93%) | 4.4K | Suffolk | Central Islip, Hauppauge, Islip, Lindenhurst |
| 11724 | 802 (0.11%) | 0 | Suffolk | Cold Spring Harbor, East Hampton, Huntington |
| 11725 | 6.3K (0.85%) | 5K | Suffolk | Commack |
| 11726 | 4.4K (0.6%) | 2.9K | Suffolk | Copiague, Manorville |
| 11727 | 5.7K (0.77%) | 3.6K | Suffolk | Amityville, Coram |
| 11729 | 7.5K (1%) | 5.1K | Suffolk | Commack, Deer Park, East Hampton |
| 11730 | 4.2K (0.57%) | 2.6K | Suffolk | East Islip, Islip, Sag Harbor |
| 11731 | 2.7K (0.36%) | 5.5K | Suffolk | Amityville, Central Islip, East Northport |
| 11732 | 1.1K (0.14%) | 0 | Nassau | East Norwich, Syosset |
| 11733 | 5.6K (0.75%) | 2.2K | Suffolk | East Hampton, East Setauket, Huntington, Mastic Beach, Setauket |
| 11735 | 8.5K (1.2%) | 5.7K | Nassau, Suffolk | E Farmingdale, Farmingdale |
| 11738 | 4.6K (0.62%) | 3K | Suffolk | Farmingville |
| 11739 | 364 (0.05%) | 0 | Suffolk | Great River |
| 11740 | 863 (0.12%) | 0 | Suffolk | Greenlawn |
| 11741 | 7.2K (0.97%) | 5.1K | Suffolk | Holbrook |
| 11742 | 3.2K (0.43%) | 2.1K | Suffolk | Holtsville |
| 11743 | 6.2K (0.83%) | 4.3K | Suffolk | Cold Spring Harbor, Halesite, Huntingtn Sta, Huntington, Huntington Station, Lloyd Harbor, Montauk |
| 11746 | 7.2K (0.98%) | 7.6K | Suffolk | Bohemia, Calverton, Coram, Dix Hills, Hampton Bays, Huntingtn Sta, Huntington, Huntington Station, Islip, South Huntington |
| 11747 | 2.1K (0.29%) | 2K | Suffolk | Melville |
| 11749 | 830 (0.11%) | 519 | Suffolk | Hauppauge, Islandia, Ronkonkoma |
| 11751 | 4K (0.54%) | 2.3K | Suffolk | Huntington, Islip |
| 11752 | 2.8K (0.38%) | 2K | Suffolk | Islip Terrace |
| 11753 | 3.1K (0.42%) | 0 | Nassau | Jericho, Muttontown |
| 11754 | 4.4K (0.59%) | 3.5K | Suffolk | Kings Park |
| 11755 | 3.4K (0.46%) | 2.1K | Suffolk | Lake Grove |
| 11756 | 13K (1.8%) | 8.6K | Nassau | Islandia, Levittown |
| 11757 | 13K (1.7%) | 8.7K | Suffolk | Lindenhurst, Melville |
| 11758 | 17K (2.3%) | 9.2K | Nassau | Massapequa, Massapequa Park, Massapequa Pk |
| 11762 | 7K (0.95%) | 4.3K | Nassau | Massapequa, Massapequa Park |
| 11763 | 7.3K (0.99%) | 4.7K | Suffolk | Medford |
| 11764 | 4K (0.54%) | 2.3K | Suffolk | Miller Place |
| 11765 | 273 (0.04%) | 0 | Nassau | Mill Neck |
| 11766 | 3.5K (0.47%) | 1.8K | Suffolk | Mount Sinai, Mt Sinai |
| 11767 | 3.6K (0.49%) | 2.8K | Suffolk | Nesconset |
| 11768 | 3.8K (0.52%) | 2K | Suffolk | Fort Salonga, Islip, Nesconset, Northport |
| 11769 | 2.7K (0.36%) | 1.6K | Suffolk | Oakdale |
| 11770 | 685 (0.09%) | 0 | Suffolk | Ocean Beach |
| 11771 | 2.9K (0.39%) | 0 | Nassau | Centre Island, Glen Head, Muttontown, Oyster Bay, Oyster Bay Cove, Upper Brookville |
| 11772 | 12K (1.6%) | 7.5K | Suffolk | Blue Point, Davis Park, E Patchogue, East Patchogue, Patchogue, Saint James, Sayville, Wainscott |
| 11776 | 6.1K (0.83%) | 4K | Suffolk | Port Jefferson, Port Jefferson Station |
| 11777 | 1.7K (0.23%) | 1.3K | Suffolk | Port Jefferson, Port Jefferson Station, Shoreham |
| 11778 | 4.6K (0.62%) | 2.9K | Suffolk | Rocky Point |
| 11779 | 11K (1.5%) | 7.3K | Suffolk | Islandia, Lake Ronkonkoma, Patchogue, Ronkonkoma |
| 11780 | 4.2K (0.57%) | 1.9K | Suffolk | Saint James, St James |
| 11782 | 5.5K (0.74%) | 0 | Suffolk | Fire Island, Huntington, Sayville, West Sayville |
| 11783 | 6.8K (0.92%) | 4.4K | Nassau | Seaford |
| 11784 | 6.8K (0.92%) | 4.5K | Suffolk | Selden |
| 11786 | 2K (0.27%) | 1.1K | Suffolk | Port Jefferson, Shoreham |
| 11787 | 9.4K (1.3%) | 5.9K | Suffolk | Hauppauge, Lindenhurst, Smithtown |
| 11788 | 4.2K (0.58%) | 2.8K | Suffolk | Hauppauge, Smithtown |
| 11789 | 2.9K (0.39%) | 1.8K | Suffolk | Sound Beach |
| 11790 | 4.6K (0.63%) | 2.8K | Suffolk | Stony Brook |
| 11791 | 7.8K (1.1%) | 798 | Nassau | Jericho, Laurel Hollow, Muttontown, Oyster Bay, Oyster Bay Cove, Syosset |
| 11792 | 3.2K (0.43%) | 1.8K | Suffolk | Huntington, Huntington Station, Sayville, Wading River |
| 11793 | 9.9K (1.3%) | 5.8K | Nassau | Wantagh |
| 11795 | 8K (1.1%) | 4.7K | Suffolk | Sayville, West Islip |
| 11796 | 1.1K (0.15%) | 0 | Suffolk | West Sayville |
| 11797 | 1.7K (0.23%) | 0 | Nassau | Woodbury |
| 11798 | 3.7K (0.5%) | 2.5K | Suffolk | Huntington Station, Islip, Mount Sinai, Wheatley Heights, Wyandanch |
| 11801 | 12K (1.6%) | 7.7K | Nassau | Hicksville, Plainview |
| 11803 | 8.8K (1.2%) | 3.1K | Nassau | Hicksville, Plainview |
| 11804 | 1.6K (0.21%) | 441 | Nassau | Bethpage, Hicksville, Old Bethpage, Plainview |
| 11901 | 8K (1.1%) | 4.6K | Suffolk | Flanders, Glen Head, Lake Grove, Medford, Riverhead |
| 11930 | 876 (0.12%) | 0 | Suffolk | Amagansett, Sound Beach, Westhampton Beach |
| 11931 | 393 (0.05%) | 0 | Suffolk | Aquebogue |
| 11932 | 1.3K (0.17%) | 0 | Suffolk | Bridgehampton, Ocean Beach, Saint James |
| 11933 | 2.3K (0.31%) | 1.4K | Suffolk | Baiting Hollow, Calverton, Oakdale, Wading River |
| 11934 | 2.7K (0.37%) | 1.6K | Suffolk | Center Moriches, Huntington |
| 11935 | 1.5K (0.2%) | 0 | Suffolk | Cutchogue, Laurel |
| 11937 | 5.6K (0.76%) | 0 | Suffolk | East Hampton, Huntington, Lindenhurst, Nesconset |
| 11939 | 544 (0.07%) | 0 | Suffolk | East Marion |
| 11940 | 1.7K (0.23%) | 932 | Suffolk | E Moriches, East Moriches, Moriches |
| 11941 | 650 (0.09%) | 0 | Suffolk | Eastport |
| 11942 | 2.2K (0.3%) | 0 | Suffolk | East Hampton, East Quogue, Quogue |
| 11944 | 1.1K (0.15%) | 673 | Suffolk | Greenport |
| 11946 | 5.6K (0.76%) | 2.2K | Suffolk | Hampton Bays, Manorville |
| 11947 | 214 (0.03%) | 0 | Suffolk | Jamesport |
| 11948 | 604 (0.08%) | 0 | Suffolk | Laurel |
| 11949 | 3.4K (0.46%) | 2.1K | Suffolk | Manorville |
| 11950 | 4.7K (0.64%) | 2.8K | Suffolk | Mastic, Mastic Beach |
| 11951 | 2.3K (0.31%) | 2.3K | Suffolk | Mastic, Mastic Beach |
| 11952 | 1.6K (0.21%) | 0 | Suffolk | Mattituck |
| 11953 | 2.6K (0.35%) | 1.7K | Suffolk | Middle Island |
| 11954 | 1.6K (0.22%) | 0 | Suffolk | Lindenhurst, Montauk, Saint James, Sound Beach |
| 11955 | 439 (0.06%) | 265 | Suffolk | Moriches |
| 11956 | 183 (0.02%) | 0 | Suffolk | New Suffolk |
| 11957 | 638 (0.09%) | 0 | Suffolk | Orient |
| 11958 | 348 (0.05%) | 0 | Suffolk | Peconic |
| 11959 | 888 (0.12%) | 0 | Suffolk | East Hampton, East Quogue, Quogue, Saint James |
| 11960 | 576 (0.08%) | 0 | Suffolk | Hauppauge, Huntington, Islip, Kings Park, Remsenburg |
| 11961 | 3.9K (0.52%) | 2.5K | Suffolk | Ridge |
| 11962 | 690 (0.09%) | 0 | Suffolk | East Hampton, Sagaponack |
| 11963 | 4K (0.54%) | 0 | Suffolk | East Quogue, Hampton Bays, Hauppauge, Huntington, Mastic, Melville, Sag Harbor, Saint James, Smithtown, Sound Beach, Stony Brook |
| 11964 | 1.4K (0.19%) | 0 | Suffolk | Shelter Island |
| 11965 | 1.2K (0.16%) | 0 | Suffolk | Shelter Island, Shelter Island Heights |
| 11967 | 8K (1.1%) | 5K | Suffolk | Melville, Montauk, Shirley, Smithtown, Yaphank |
| 11968 | 7.4K (1%) | 0 | Suffolk | Babylon, Brentwood, Bridgehampton, Centereach, Central Islip, Coram, East Hampton, East Quogue, Hampton Bays, Huntington, Manorville, Mastic Beach, Medford, Middle Island, Quogue, Sag Harbor, Sagaponack, Shoreham, Southampton, Stony Brook |
| 11970 | 168 (0.02%) | 0 | Suffolk | Jamesport, South Jamesport |
| 11971 | 2.3K (0.31%) | 0 | Suffolk | Sound Beach, Southold |
| 11972 | 213 (0.03%) | 0 | Suffolk | Kings Park, Remsenburg, Remsenburg Speonk, Speonk |
| 11975 | 382 (0.05%) | 0 | Suffolk | Deer Park, Lake Grove, Medford, Quogue, Wainscott |
| 11976 | 2.1K (0.29%) | 0 | Suffolk | Bridgehampton, Cutchogue, East Hampton, Lake Grove, Moriches, Quogue, Southampton, Water Mill, Watermill |
| 11977 | 1.1K (0.15%) | 0 | Suffolk | Deer Park, Islandia, Kings Park, Medford, Westhampton, Westhampton Beach |
| 11978 | 1.6K (0.21%) | 0 | Suffolk | Amagansett, Greenport, Hampton Bays, Huntington, Westhampton, Westhampton Beach |
| 11980 | 993 (0.13%) | 0 | Suffolk | Riverhead, Southampton, Yaphank |
| 06390 | 444 (0.06%) | 0 | Suffolk | Fishers Island |

That's 172 rows (11552–11570 block of 14 rows captured via screenshot only — county confirmed Nassau from context/screenshot, city column was cut off-screen and not re-captured; everything else has full City data).

## 5. Owner type — 5/7 included

| Type | Properties | Buybox score > 0 | Deals concentration A | Deals concentration B | Client Deals | Included |
|---|---|---|---|---|---|---|
| Individual | 631K (85%) | 318K | 4.6K (1×) | 427 (0.9×) | 138 (85%) | Y |
| Trust | 59K (7.9%) | 35K | 8.4K (0.5×) | 386 (1×) | 7 (4.3%) | Y |
| Company | 52K (7%) | 18K | 3.2K (1.4×) | 256 (1.5×) | 16 (9.9%) | Y |
| Non Sellers | 1.4K (0.18%) | 0 | 0 (0×) | 40 (9.8×) | 0 | N |
| Estate | 592 (0.08%) | 415 | 0 (0×) | 59 (6.6×) | 0 | Y |
| Religious Organization | 235 (0.03%) | 0 | 0 | 0 | 0 | N |
| Unknown | 120 (0.02%) | 13 | 120 (*) | 8 (*) | 1 (0.62%) | Y |
| **Total** | **744K** | **372K** | 4.6K (1×) | 393 (1×) | 54/162 | |

## 6. Years of ownership — 10/14 included (full range list, editable numeric bounds)

| Range (years) | Properties | Included |
|---|---|---|
| Unknown | 206K (28%) | Y |
| 0–1 | 40K (5.4%) | N |
| 2–4 | 77K (10%) | N |
| 5–7 | 75K (10%) | N |
| 8–9 | 47K (6.3%) | N |
| 10–14 | 76K (10%) | Y |
| 15–19 | 57K (7.7%) | Y |
| 20–24 | 71K (9.6%) | Y |
| 25–29 | 70K (9.4%) | Y |
| 30–39 | 25K (3.3%) | Y |
| 40–49 | 0 | Y |
| 50–74 | 0 | Y |
| 75–99 | 0 | Y |
| 100–100000000000 | 0 | Y |
| **Total** | **744K** | |

## 7. Years old (property age) — 10/14 included

| Range (years old) | Properties | Buybox score > 0 | Included |
|---|---|---|---|
| Unknown | 116K (16%) | 81K | Y |
| 0–1 | 1.4K (0.19%) | 0 | N |
| 2–4 | 3.5K (0.47%) | 0 | N |
| 5–7 | 4.2K (0.56%) | 0 | N |
| 8–9 | 3K (0.41%) | 0 | N |
| 10–14 | 7.5K (1%) | 745 | Y |
| 15–19 | 10K (1.3%) | 1.4K | Y |
| 20–24 | 18K (2.4%) | 4.5K | Y |
| 25–29 | 20K (2.7%) | 6.8K | Y |
| 30–39 | 40K (5.4%) | 14K | Y |
| 40–49 | 27K (3.6%) | 12K | Y |
| 50–74 | 295K (40%) | 139K | Y |
| 75–99 | 155K (21%) | 91K | Y |
| 100–100000000000 | 42K (5.7%) | 22K | Y |
| **Total** | **744K** | **372K** | |

## 8. LTV — 3/6 included

Gated by a one-time acknowledgement modal (operator clicked through, not the tool).

| Range | Properties | Buybox score > 0 | Deals concentration | Included |
|---|---|---|---|---|
| Unknown | 282K (38%) | 165K | 1.9K (2.3×) | Y |
| 0–50% | 344K (47%) | 191K | 26K (0.2×) | Y |
| 51–84% | 98K (13%) | 16K | 49K (0.1×) | Y |
| 85–99% | 8.4K (1.1%) | 0 | 0 | N |
| 100–998% | 4.8K (0.66%) | 0 | 4.8K (0.9×) | N |
| 999–100000% | 145 (0.02%) | 0 | 0 | N |
| **Total** | **737K** | **372K** | 4.5K (1×) | |

## 9. Estimated market value — per property type (sub-tabbed)

### SFH — 15/18 included

| Range ($) | Properties | Buybox score > 0 | Included |
|---|---|---|---|
| Unknown | *(row present, not individually re-verified this pass — see step 9 capture)* | | |
| 200,000–249,999 | 262 (0.04%) | 59 | Y |
| 250,000–299,999 | 553 (0.08%) | 165 | Y |
| 300,000–349,999 | 1.2K (0.16%) | 471 | Y |
| 350,000–399,999 | 2K (0.28%) | 1K | Y |
| 400,000–499,999 | 16K (2.2%) | 11K | Y |
| 500,000–599,999 | 50K (7.1%) | 33K | Y |
| 600,000–749,999 | 197K (28%) | 141K | Y |
| 750,000–999,999 | 230K (33%) | 161K | Y |
| 1,000,000–1,499,999 | 105K (15%) | 0 | N |
| 1,500,000–1,999,999 | 39K (5.5%) | 0 | N |
| 2,000,000–500,000,000 | 63K (9%) | 0 | N |
| **Total** | **705K** | **349K** | |

Lower SFH buckets (Unknown, $0, $1–24,999, $25,000–49,999, $50,000–99,999, $100,000–149,999, $150,000–199,999 — 7 rows) were seen on-screen in an earlier pass with near-zero counts (single/double-digit properties) but not re-transcribed exactly this pass; 15/18 total included confirms only the top 3 brackets above are excluded.

### 2-9 units — 7/18 included

| Range ($) | Properties | Buybox score > 0 | Included |
|---|---|---|---|
| Unknown | 0 | 0 | Y |
| 0 | 0 | 0 | Y |
| 1–24,999 | 4 (0.01%) | 0 | N |
| 25,000–49,999 | 5 (0.01%) | 0 | N |
| 50,000–99,999 | 1 (0%) | 0 | N |
| 100,000–149,999 | 14 (0.04%) | 0 | N |
| 150,000–199,999 | 9 (0.02%) | 0 | N |
| 200,000–249,999 | 7 (0.02%) | 0 | N |
| 250,000–299,999 | 15 (0.04%) | 1 | N |
| 300,000–349,999 | 23 (0.06%) | 1 | N |
| 350,000–399,999 | 39 (0.1%) | 0 | N |
| 400,000–449,999 | 60 (0.16%) | 37 | Y |
| 450,000–499,999 | 292 (0.76%) | 162 | Y |
| 500,000–749,999 | 8.6K (22%) | 5.6K | Y |
| 750,000–999,999 | 20K (51%) | 13K | Y |
| 1,000,000–1,499,999 | 8.2K (21%) | 4.7K | Y |
| 1,500,000–1,999,999 | 844 (2.2%) | 0 | N |
| 2,000,000–100,000,000 | 705 (1.8%) | 0 | N |
| **Total** | **38K** | **23K** | |

## 10. Living area (sq ft) — per property type

### SFH — 8/9 included

| Range | Properties | Buybox score > 0 | Included |
|---|---|---|---|
| Unknown | 153K (22%) | 0 | Y |
| 0 | 2 (0%) | 108K | Y |
| 1–199 | 33 (0%) | 0 | N |
| 200–799 | 9.3K (1.3%) | 4.7K | Y |
| 800–1499 | 190K (27%) | 110K | Y |
| 1500–2499 | 253K (36%) | 115K | Y |
| 2500–3499 | 66K (9.4%) | 11K | Y |
| 3500–4499 | 18K (2.5%) | 638 | Y |
| 4500–100000000 | 15K (2.1%) | 116 | Y |
| **Total** | **705K** | **349K** | |

### 2-9 units — 3/3 included (all)

| Range | Properties | Buybox score > 0 |
|---|---|---|
| Unknown | 8.3K (22%) | 0 |
| 0 | 0 | 5.6K |
| 1–100000000000 | 30K (78%) | 18K |
| **Total** | **38K** | **23K** |

## 11. Lot size (sq ft) — per property type

### SFH — 8/9 included

| Range | Properties | Buybox score > 0 | Included |
|---|---|---|---|
| Unknown | 756 (0.11%) | 0 | Y |
| 0 | 21 (0%) | 380 | Y |
| 1–100 | 6 (0%) | 0 | N |
| 101–999 | 751 (0.11%) | 924 | Y |
| 1000–3599 | 10K (1.4%) | 5.4K | Y |
| 3600–14999 | 507K (72%) | 277K | Y |
| 15000–29999 | 109K (15%) | 51K | Y |
| 30000–44999 | 41K (5.7%) | 10K | Y |
| 45000–100000000000 | 37K (5.2%) | 4.3K | Y |
| **Total** | **705K** | **349K** | |

### 2-9 units — 3/3 included (all)

| Range | Properties | Buybox score > 0 |
|---|---|---|
| Unknown | 4 (0.01%) | 0 |
| 0 | 6 (0.02%) | 1 |
| 1–100000000000 | 38K (100%) | 23K |
| **Total** | **38K** | **23K** |

## 12. Summary

> **380K Properties** match the full buybox.
> Counties: Suffolk, Nassau
> Property types: SFH, 2-9 units
> Owner types: Individual, Trust, Company, Estate, Unknown
> "You have no warnings in the Buybox settings."

---

## 13. Suppressed towns — source list

| Town | ZIP(s) | DM-Sept | Tina | 8020 zip list |
|---|---|---|---|---|
| East Norwich | 11732 | ✓ | ✓ | ✓ |
| Glen Head | 11545, 11901 | ✓ | ✓ | |
| Glenwood Landing | 11547 | ✓ | ✓ | ✓ |
| Great Neck | 11020, 11021, 11023, 11024 | ✓ | ✓ | ✓ |
| Greenport | 11944 | ✓ | ✓ | |
| Hampton Bays | 11946 | ✓ | ✓ | |
| Kings Point | 11024 | ✓ | ✓ | ✓ |
| Locust Valley | 11560 | ✓ | ✓ | ✓ |
| New Suffolk | 11956 | ✓ | ✓ | ✓ |
| Point Lookout | 11569 | ✓ | ✓ | ✓ |
| Southampton | 11968 | ✓ | ✓ | ✓ |
| Atlantic Beach | 11509 | ✓ | ✓ | ✓ |
| Baiting Hollow | 11933 | ✓ | ✓ | |
| East Atlantic Beach | 11509 | ✓ | ✓ | ✓ |
| Gilgo Beach | 11702 | ✓ | ✓ | |
| Halesite | 11743 | ✓ | ✓ | |
| Hewlett | 11557, 11598 | ✓ | ✓ | 11598 only |
| Laurel Hollow | 11791 | ✓ | ✓ | |
| Muttontown | 11545, 11791 | ✓ | ✓ | |
| North Woodmere | 11581 | ✓ | ✓ | |
| Oak Beach | 11702 | ✓ | ✓ | |
| Oak Island | 11702 | ✓ | ✓ | |
| Roslyn | 11576 | ✓ | ✓ | ✓ |
| Sands Point | 11050 | ✓ | ✓ | |
| Shoreham | 11786, 11777 | ✓ | ✓ | |
| Woodmere | 11598 | ✓ | ✓ | ✓ |
| Albany | — | ✓ | ✓ | |
| Amagansett | 11930 | ✓ | ✓ | ✓ |
| Aquebogue | 11931 | ✓ | ✓ | ✓ |
| Bridgehampton | 11932 | ✓ | ✓ | ✓ |
| Buffalo | — | ✓ | ✓ | |
| Cedarhurst | 11516 | ✓ | ✓ | ✓ |
| Cherry Grove | 11782 | ✓ | ✓ | ✓ |
| Cutchogue | 11935 | ✓ | ✓ | ✓ |
| East Hampton | 11937 | ✓ | ✓ | ✓ |
| East Hills | 11548, 11576, 11577 | ✓ | ✓ | ✓ |
| East Quogue | 11942 | ✓ | ✓ | ✓ |
| Forest Hills | 11375 | ✓ | ✓ | |
| Henderson | | ✓ | | |
| Hewlett Harbor | 11557 | ✓ | ✓ | |
| James | 11780 | ✓ | | |
| Jamesport | 11947 | ✓ | ✓ | ✓ |
| Laurel | 11948 | ✓ | ✓ | ✓ |
| Lawrence | 11559 | ✓ | ✓ | ✓ |
| Mattituck | 11952 | ✓ | ✓ | ✓ |
| Montauk | 11954 | ✓ | ✓ | ✓ |
| North Haven | 11963 | ✓ | ✓ | ✓ |
| North Hills | 11030, 11576 | ✓ | ✓ | ✓ |
| Old Brookville | 11545 | ✓ | ✓ | |
| Orient | 11957 | ✓ | ✓ | ✓ |
| Peconic | 11958 | ✓ | ✓ | ✓ |
| Plandome | 11030 | ✓ | ✓ | ✓ |
| Poughkeepsie | 12601, 12603 | ✓ | ✓ | |
| Quogue | 11959 | ✓ | ✓ | ✓ |
| Roslyn Estates | 11576 | ✓ | ✓ | ✓ |
| Roslyn Harbor | 11545, 11576 | ✓ | ✓ | 11576 only |
| Roslyn Heights | 11577 | ✓ | ✓ | ✓ |
| Sag Harbor | 11963 | ✓ | ✓ | ✓ |
| Sagaponack | 11962 | ✓ | ✓ | ✓ |
| Sea Cliff | 11579 | ✓ | ✓ | ✓ |
| Searingtown | 11507 | ✓ | ✓ | ✓ |
| Shelter Island | 11964 | ✓ | ✓ | ✓ |
| Shelter Island Heights | 11965 | ✓ | ✓ | ✓ |
| Speonk | 11972 | ✓ | ✓ | ✓ |
| Tarrytown | 10591 | ✓ | ✓ | |
| Upper Brookville | 11545, 11771 | ✓ | ✓ | 11771 only |
| Wainscott | 11975 | ✓ | ✓ | ✓ |
| Water Mill | 11976 | ✓ | ✓ | ✓ |
| Westhampton / West Hampton | 11977 | ✓ | ✓ | ✓ |
| Williston Park | 11596 | ✓ | ✓ | ✓ |
| Woodbury | 11797 | ✓ | ✓ | ✓ |
| Woodhaven | 11421 | ✓ | | |
| Yorktown Heights | 10598 | ✓ | ✓ | |
| East Marion | 11939 | | ✓ | ✓ |
| East Moriches | 11940 | | ✓ | |
| Eastport | 11941 | | ✓ | ✓ |
| Fishers Island | 06390 | | ✓ | ✓ |
| Lloyd Harbor | 11743 | | ✓ | |
| Southold | 11971 | | ✓ | ✓ |
| South Jamesport | 11970 | | ✓ | ✓ |
| West Hampton Beach | 11978 | | ✓ | ✓ |

---

## Gaps in this scrape (honest accounting)

- Zip Code table: 14 rows (11552–11570) have County but not City — screenshot-only capture, text extraction wasn't re-run for that exact scroll window.
- Estimated market value / SFH: the 7 lowest-value buckets (Unknown through $150,000–199,999) were viewed but not re-transcribed with exact figures in this pass (all near-zero property counts; the 15/18-included total is confirmed).
- Deals concentration (2 columns) and Client Deals were not captured for the Zip Code table (only Properties / Buybox score / County / City were — the Zip step's columns extended further right than transcribed).
- 2-9 units sub-tab was not captured for Counties, Property type, Owner type, Years of ownership, Years old, or LTV steps — those steps did not appear to be sub-tabbed by property type (only Estimated market value / Living area / Lot size were).

## Relationship to Closings (this repo)

`backend/app/services/buybox_towns.py` is a flat town-name allowlist used to filter `sold_properties_full.csv` at Gate 7 ingest. As of 2026-09-23, this document IS used as a source: `backend/app/services/buybox_zips.py` is a flat zip-code allowlist built from this document's §4 (zip table) — a zip was added if one of its listed cities was already a marketed town — and the town allowlist above was separately reconciled against §13 (suppressed-town list). See [BUYBOX.md](BUYBOX.md)'s "Buybox reconciliation against 8020REI (2026-09-23)" and "Zip matching" sections for the mechanism and specific changes made. This document remains the raw-scrape record; it is not itself re-derived or re-synced automatically when `buybox_zips.py`/`buybox_towns.py` change.
