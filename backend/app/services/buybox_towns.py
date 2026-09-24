"""Gate 7 Nassau/Suffolk geography, with authoritative ZIP exclusions.

Executable exclusion lists and provenance live in buybox_policy.json. Historical
positive town labels below are retained only for old report metadata consumers;
they have no role in deciding membership.
"""

from __future__ import annotations

import re
from typing import FrozenSet, Optional

from dataclasses import dataclass

from .buybox_zips import BUYBOX_POLICY, EXCLUDED_ZIPS, normalize_zip, zip_is_missing

# Display spellings (including known scrape typos / aliases). Matching uses normalize_town().
_BUYBOX_TOWN_LABELS: tuple[str, ...] = (
    'Centereach',
    'Coram',
    'East Meadow',
    'Freeport',
    'Hempstead',
    'Hicksville',
    'Huntington Station',
    'Levittown',
    'Lindenhurst',
    'Massapequa Park',
    'Mastic Beach',
    'West Babylon',
    'Westbury',
    'East Setauket',
    'Setauket',
    'Amityville',
    'Baldwin',
    'Bethpage',
    'East Northport',
    'Farmingdale',
    'Huntington',
    'Massapequa',
    'Mastic',
    'Medford',
    'Merrick',
    'North Amityville',
    'North Babylon',
    'North Patchogue',
    'Northport',
    'Patchogue',
    'Port Jefferson',
    'Port Jefferson Station',
    'Roosevelt',
    'Seaford',
    'Selden',
    'Shirley',
    'Uniondale',
    'Wantagh',
    'Bayshore',
    'Bellmore',
    'Bellport',
    'Brentwood',
    'Central Islip',
    'Commack',
    'Copiague',
    'Deer Park',
    'East Patchogue',
    'East Rockaway',
    'Elmont',
    'Elwood',
    'Farmingville',
    'Hauppauge',
    'Holbrook',
    'Holtsville',
    'Islip Terrace',
    'Kings Park',
    'Lake Grove',
    'Lynbrook',
    'Malverne',
    'Middle Island',
    'Miller Place',
    'Nesconset',
    'North Lynbrook',
    'Oceanside',
    'Old Bethpage',
    'Oyster Bay',
    'Plainview',
    'Riverhead',
    'Rockville Centre',
    'Rocky Point',
    'Ronkonkoma',
    'Smithtown',
    'Sound Beach',
    'Syosset',
    'Valley Stream',
    'West Hempstead',
    'West Islip',
    'Yaphank',
    'Babylon',
    'Bayport',
    'Bellerose Terrace',
    'Blue Point',
    'Bohemia',
    'Brightwaters',
    'Brookhaven',
    'Calverton',
    'Carle Place',
    'Center Moriches',
    'Centerport',
    'Cold Spring Harbor',
    'Dix Hills',
    'East Islip',
    'Floral Park',
    'Franklin Square',
    'Greenlawn',
    'Island Park',
    'Islandia',
    'Islip',
    'Manorville',
    'Mineola',
    'Mount Sinai',
    'New Hyde Park',
    'North New Hyde Park',
    'North Valley Stream',
    'Oakdale',
    'Port Washington',
    'Ridge',
    'Saint James',
    'Sayville',
    'South Hempstead',
    'Stony Brook',
    'Wading River',
    'West Sayville',
    'North Bellmore',
    'Amity Harbor',
    'E Farmingdale',
    'Flanders',
    'Garden City',
    'Glen Cove',
    'Lake Ronkonkoma',
    'Lido Beach',
    'Long Beach',
    'Melville',
    'Moriches',
    'Mt Sinai',
    'North Baldwin',
    'South Floral Park',
    'South Huntington',
    'South Setauket',
    'St James',
    'Wheatley Heights',
    'Wyandanch',
    'Albertson',
    'Alden Manor',
    'Astoria',
    'Bay Shore',
    'Bayside',
    'Bayville',
    'Beechhurst',
    'Belle Harbor',
    'Bellerose',
    'Bellerose Village',
    'Blue Poin',
    'Breezy Point',
    'Broad Channel',
    'Brooklyn',
    'Cambria Heights',
    'Corona',
    'E Northport',
    'East Elmhurst',
    'East Massapequa',
    'East Northport,',
    'East Williston',
    'Elmhurst',
    'Far Rockaway',
    'Flushing',
    'Fort Salonga',
    'FRANKLIN SQUAR',
    'Garden City Park',
    'Garden City South',
    'GardenCity',
    'Glen Oaks',
    'Great River',
    'Greenvale',
    'Hauppaüge',
    'Hicksvill',
    'Hollis',
    'Howard Beach',
    'Huntington Bay',
    'Huntington,',
    'Inwood',
    'Jamaica',
    'Jericho',
    'Kew Gardens',
    'Latham',
    'Little Neck',
    'Malba',
    'Manhasset',
    'Manhasset Hills',
    'Maspeth',
    'Matinecock',
    'Middle Village',
    'North Massapequa',
    'North Merrick',
    'North Sea',
    'Oakland Gardens',
    'Ocean Bay Park',
    'Ocean Beach',
    'Old Westbury',
    'Ozone Park',
    'Patchog',
    'Queens Village',
    'Ridgewood',
    'Rosedale',
    'Saint Albans',
    'Seiden',
    'Setauket- East Setauket',
    'South Farmingdale',
    'South Ozone Park',
    'South Richmond Hill',
    'Springfield Gardens',
    'Stewart Manor',
    'StIslip',
    'Sunnyside',
    'Woodside',
    'N babylon',
    'W babylon',
    'Richmond Hill',
    # Added 2026-09-23: evidenced by nonzero 8020REI buybox score in
    # docs/BUYBOX_8020REI.md S4 (zip table), not suppressed, previously missing.
    'Captree Island',
    'Port Washington North',
    'Davis Park',
    'Oyster Bay Cove',
)

_TRAILING_PUNCT_RE = re.compile(r"[,;.]+$")
_WS_RE = re.compile(r"\s+")


def normalize_town(city: Optional[str]) -> str:
    """Normalize city for buybox membership (casefold, strip, collapse spaces)."""
    if city is None:
        return ""
    text = str(city).strip()
    text = _TRAILING_PUNCT_RE.sub("", text).strip()
    text = _WS_RE.sub(" ", text)
    return text.casefold()


BUYBOX_TOWNS: FrozenSet[str] = frozenset(normalize_town(t) for t in _BUYBOX_TOWN_LABELS)
BUYBOX_TOWN_COUNT: int = len(BUYBOX_TOWNS)


EXCLUDED_CITIES: frozenset[str] = frozenset(BUYBOX_POLICY["excluded_cities"])
EXCLUDED_CITY_COUNT = len(EXCLUDED_CITIES)


@dataclass(frozen=True)
class BuyboxDecision:
    included: bool
    reason: str
    normalized_zip: Optional[str] = None


def evaluate_buybox(
    city: Optional[str], zip_code: object = None,
    county: Optional[str] = None, state: Optional[str] = None,
) -> BuyboxDecision:
    """Apply state/county scope, then ZIP exclusions, or city when ZIP is absent.

    Scores and the historical positive town list do not participate. A present
    invalid ZIP is excluded rather than silently becoming a city fallback.
    """
    z = normalize_zip(zip_code)
    if normalize_town(state) not in {"ny", "new york"}:
        return BuyboxDecision(False, "excluded_state", z)
    county_key = normalize_town(county)
    county_key = re.sub(r"\s+county$", "", county_key)
    if county_key not in {"nassau", "suffolk"}:
        return BuyboxDecision(False, "excluded_county", z)
    if not zip_is_missing(zip_code):
        if z is None:
            return BuyboxDecision(False, "invalid_zip")
        if z in EXCLUDED_ZIPS:
            return BuyboxDecision(False, "excluded_zip", z)
        return BuyboxDecision(True, "included_zip", z)
    key = normalize_town(city)
    if not key:
        return BuyboxDecision(False, "missing_city")
    if key in EXCLUDED_CITIES:
        return BuyboxDecision(False, "excluded_city")
    return BuyboxDecision(True, "included_city_fallback")


def in_buybox(
    city: Optional[str], zip_code: object = None,
    county: Optional[str] = None, state: Optional[str] = None,
) -> bool:
    return evaluate_buybox(city, zip_code, county, state).included
