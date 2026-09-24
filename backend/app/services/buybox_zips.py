"""Flat zip-code allowlist for the Gate 7 marketed-zip buybox check.

BUYBOX_ZIPS is a plain list of zip codes HHB services, sourced from
docs/BUYBOX_8020REI.md S4 (zip -> city map): a zip is on this list if at least
one of its listed cities is already on buybox_towns.BUYBOX_TOWNS. This is a
flat allowlist, same idea as buybox_towns._BUYBOX_TOWN_LABELS - no per-row
classification, no contamination scanning, no overrides. `in_buybox()` in
buybox_towns.py checks this list OR the town-name list; either match is
enough.
"""
from __future__ import annotations

import re
from typing import FrozenSet, Optional

_BUYBOX_ZIP_LABELS: tuple[str, ...] = (
    '11001', '11003', '11010', '11030', '11040', '11050', '11096', '11501',
    '11507', '11510', '11514', '11518', '11520', '11530', '11542', '11548',
    '11550', '11575', '11580', '11581', '11590', '11596', '11701', '11702',
    '11703', '11704', '11705', '11706', '11709', '11710', '11713', '11714',
    '11715', '11716', '11717', '11718', '11719', '11720', '11721', '11722',
    '11724', '11725', '11726', '11727', '11729', '11730', '11731', '11732',
    '11733', '11735', '11738', '11739', '11740', '11741', '11742', '11743',
    '11746', '11747', '11749', '11751', '11752', '11754', '11755', '11756',
    '11757', '11758', '11762', '11763', '11764', '11766', '11767', '11768',
    '11769', '11770', '11771', '11772', '11776', '11777', '11778', '11779',
    '11780', '11782', '11783', '11784', '11786', '11787', '11788', '11789',
    '11790', '11791', '11792', '11793', '11795', '11796', '11798', '11801',
    '11803', '11804', '11901', '11930', '11932', '11933', '11934', '11937',
    '11940', '11946', '11949', '11950', '11951', '11953', '11954', '11955',
    '11959', '11960', '11961', '11963', '11967', '11968', '11971', '11972',
    '11975', '11976', '11977', '11978', '11980',
)

BUYBOX_ZIPS: FrozenSet[str] = frozenset(_BUYBOX_ZIP_LABELS)
BUYBOX_ZIP_COUNT: int = len(BUYBOX_ZIPS)

_ZIP_DIGITS_RE = re.compile(r"\d+")


def normalize_zip(raw: object) -> Optional[str]:
    """Normalize a sold-CSV zip value to a clean 5-digit string, or None if unusable.

    Handles ZIP+4 ("11550-1234"), float-read CSV artifacts ("11550.0", and the
    leading-zero-loss case "6390.0" -> "06390"), blank/NaN/None.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() == "nan":
        return None
    text = re.sub(r"\.0+$", "", text)  # "11550.0" -> "11550"
    text = text.split("-", 1)[0].strip()  # ZIP+4 -> base 5
    if not text.isdigit():
        m = _ZIP_DIGITS_RE.search(text)
        if not m:
            return None
        text = m.group(0)
    if len(text) > 5:
        text = text[:5]
    elif len(text) < 5:
        text = text.zfill(5)
    return text if len(text) == 5 else None


def in_buybox_zip(zip_code: Optional[str]) -> bool:
    """True when zip_code matches a marketed-zip allowlist entry."""
    z = normalize_zip(zip_code)
    return bool(z) and z in BUYBOX_ZIPS
