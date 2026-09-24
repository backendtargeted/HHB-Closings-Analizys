"""ZIP normalization and exclusion data for the approved Gate 7 geography policy."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Optional

BUYBOX_POLICY = json.loads(Path(__file__).with_name("buybox_policy.json").read_text(encoding="utf-8"))
EXCLUDED_ZIPS: frozenset[str] = frozenset(BUYBOX_POLICY["excluded_zips"])
EXCLUDED_ZIP_COUNT = len(EXCLUDED_ZIPS)


def zip_is_missing(raw: object) -> bool:
    """Only absent/blank values and actual numeric NaN are missing ZIPs."""
    return raw is None or (isinstance(raw, float) and math.isnan(raw)) or str(raw).strip() == ""


def normalize_zip(raw: object) -> Optional[str]:
    """Accept ZIP, ZIP+4, 9 digits, or CSV numeric artifacts; never salvage junk."""
    if zip_is_missing(raw):
        return None
    text = str(raw).strip()
    text = re.sub(r"\.0+$", "", text)
    if re.fullmatch(r"[0-9]{4}", text):
        return text.zfill(5)
    if re.fullmatch(r"[0-9]{5}(?:-?[0-9]{4})?", text):
        return text[:5]
    return None


def in_buybox_zip(zip_code: object) -> bool:
    """ZIP-only exclusion check; callers must separately enforce county/state."""
    z = normalize_zip(zip_code)
    return z is not None and z not in EXCLUDED_ZIPS
