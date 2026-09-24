"""Bounded, read-only screening of SiftMap snapshots for admitted sold properties.

Snapshot eligibility is not historical eligibility. Seller names are used only
from a sale-history event reconciled to the source sale, never from owner_info.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Any

MAX_LINE_BYTES = 4 * 1024 * 1024
_PREFIX_ID = re.compile(rb'^\s*\{\s*"dataflik_id"\s*:\s*("(?:[^"\\]|\\.)*"|[0-9]+)\s*[,}]')
_MISSING = {"", "none", "null", "nan", "unknown", "n/a", "na", "-"}
_ENTITY = re.compile(r"\b(llc|llp|pllc|lp|pc|inc|incorporated|corp|corporation|company|co|ltd|limited|bank|association|foundation|estate|est|fsb|church|temple|synagogue|mosque|ministries|ministry|government|authority|department|county|municipality|partnership|partners|holdings|housing|university|school|hospital|credit union)\b", re.I)
_TRUST = re.compile(r"\b(trust|trustee|trustees|trstee|trst|revocable|irrevocable)\b", re.I)


def _text(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split())


def _norm(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", _text(value).upper())


def _county(value: Any) -> str:
    return _norm(re.sub(r"\s+county\s*$", "", _text(value), flags=re.I))


def _state(value: Any) -> str:
    normalized = _norm(value)
    return {"NEWYORK": "NY", "NEWJERSEY": "NJ", "CONNECTICUT": "CT"}.get(normalized, normalized)


def _number(value: Any) -> Decimal | None:
    text = _text(value).lower()
    if text in _MISSING:
        return None
    try:
        result = Decimal(text.replace(",", "").replace("$", ""))
    except InvalidOperation as exc:
        raise ValueError("invalid_numeric_value") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("invalid_numeric_value")
    return result


def _category(name: str) -> str:
    """Name-based estimate, not a verified legal entity classification."""
    if name.lower() in _MISSING:
        return "Unclassified"
    name = re.sub(r"\b(?:[A-Za-z]\.){2,}", lambda m: m[0].replace(".", ""), name)
    if _TRUST.search(name):
        return "Company" if re.search(r"\bbank\b", name, re.I) else "Trust"
    if _ENTITY.search(name):
        return "Company"
    if re.search(r"\d|[/:]", name):
        return "Unclassified"
    tokens = re.findall(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", name, re.UNICODE)
    stop = {"unknown", "owner", "owners", "occupant", "heirs", "et", "al", "and"}
    substantive = [t for t in tokens if t.lower() != "and"]
    if (2 <= len(substantive) <= 10
            and tokens[-1].lower() != "and"
            and not (set(t.lower() for t in tokens) & (stop - {"and"}))):
        return "Individual"
    return "Unclassified"


def _decision(reason: str, status: str = "unresolved", property_type: str = "") -> dict:
    return dict(status=status, reason=reason, seller_name="", seller_category="Unclassified",
                seller_match_status="not_matched", property_type=property_type)


def _month(value: Any) -> str:
    match = re.match(r"^(\d{4})-(\d{2})(?:-|$|T)", _text(value))
    if match and 1 <= int(match[2]) <= 12:
        return f"{match[1]}-{match[2]}"
    return ""


def _seller(record: dict, target: dict) -> tuple[str, str, str]:
    history = record.get("history") or {}
    events = history.get("transactions") if isinstance(history, dict) else None
    if not isinstance(events, list):
        return "", "Unclassified", "history_missing"
    expected = set()
    for event in target.get("sale_events", []):
        try:
            price = _number(event.get("sale_amount"))
        except ValueError:
            continue
        buyer = _norm(event.get("buyer_full_name"))
        if buyer and price is not None:
            expected.add((buyer, price))
    if not expected:
        return "", "Unclassified", "source_sale_incomplete"
    matches = {}
    for event in events:
        if not isinstance(event, dict) or _month(event.get("sale_date")) != target.get("sold_month"):
            continue
        try:
            price = _number(event.get("sale_price", event.get("sale_amount")))
        except ValueError:
            continue
        if (_norm(event.get("buyer_name")), price) in expected:
            name = _text(event.get("seller_name"))
            event_key = (_text(event.get("sale_date")), _norm(event.get("buyer_name")), str(price), _norm(name))
            matches[event_key] = name
    if not matches:
        return "", "Unclassified", "sale_event_not_matched"
    if len(matches) != 1:
        return "", "Unclassified", "ambiguous_seller_events"
    name = next(iter(matches.values()))
    if not name or name.lower() in _MISSING:
        return "", "Unclassified", "seller_missing"
    return name, _category(name), "matched_sale_history"


def _evaluate(record: dict, target: dict) -> tuple[dict, str]:
    prop = record.get("property")
    raw = record.get("raw") or {}
    detail = raw.get("detail", {}) if isinstance(raw, dict) else {}
    if record.get("error") or not isinstance(prop, dict) or not isinstance(detail, dict) or detail.get("error"):
        return _decision("unusable_details"), "unusable_details"
    parcels = {_norm(p) for p in target.get("parcels", []) if _norm(p)}
    if not parcels or not _norm(prop.get("apn")) or not _county(prop.get("county")) or not _county(target.get("county")):
        return _decision("identity_missing"), "identity_missing"
    if _norm(prop.get("apn")) not in parcels or _county(prop.get("county")) != _county(target.get("county")):
        return _decision("identity_mismatch"), "identity_mismatch"
    if prop.get("state") and target.get("state") and _state(prop["state"]) != _state(target["state"]):
        return _decision("identity_mismatch"), "identity_mismatch"
    values = {**detail, **prop}
    label = _text(values.get("property_type"))
    typ = re.sub(r"[^a-z0-9]", "", label.lower())
    sfh = typ in {"sfh", "singlefamily", "singlefamilyresidence", "singlefamilyresidential", "singlefamilyhome", "sfr"}
    multi = typ in {"29units", "multifamily", "multifamilyresidence", "multifamilyresidential", "multifamilycommercial", "duplex", "triplex", "fourplex", "2family", "3family", "4family"}
    try:
        units = _number(values.get("units_count"))
        year = _number(values.get("years_built", values.get("year_built")))
        value = _number(values.get("total_market_value"))
        living = _number(values.get("living_square_feet"))
        lot = _number(values.get("lot_sqrf", values.get("lot_square_feet")))
        if not _month(target.get("sold_month")):
            raise ValueError("invalid_sold_month")
        if year and year != year.to_integral_value():
            raise ValueError("invalid_year_built")
    except ValueError as exc:
        return _decision(str(exc), property_type=label), str(exc)
    reason, status = "supported_rules_pass", "eligible"
    if not label:
        reason, status = "property_type_missing", "unresolved"
    elif not sfh and not multi:
        reason, status = "property_type_outside_buybox", "excluded"
    elif multi and typ != "29units" and units is None:
        reason, status = "unit_count_missing", "unresolved"
    elif multi and units is not None and (units < 2 or units > 9 or units != units.to_integral_value()):
        reason, status = "unit_count_outside_buybox", "excluded"
    elif sfh and units is not None and units > 1:
        reason, status = "conflicting_property_type_units", "unresolved"
    elif year and int(target["sold_month"][:4]) - year < 10:
        reason, status = "property_age_under_10", "excluded"
    elif sfh and value is not None and value >= 1000000:
        reason, status = "sfh_market_value_outside_buybox", "excluded"
    elif multi and value and not 400000 <= value < 1500000:
        reason, status = "multi_market_value_outside_buybox", "excluded"
    elif sfh and living and living < 200:
        reason, status = "sfh_living_area_outside_buybox", "excluded"
    elif sfh and lot and lot < 101:
        reason, status = "sfh_lot_area_outside_buybox", "excluded"
    decision = _decision(reason, status, label)
    decision["seller_name"], decision["seller_category"], decision["seller_match_status"] = _seller(record, target)
    fingerprint = json.dumps([_norm(prop["apn"]), _county(prop["county"]), typ,
                              units, year, value, living, lot, decision], sort_keys=True, default=str)
    return decision, fingerprint


def screen_property_details(path: str, targets: list[dict]) -> tuple[dict[str, dict], dict]:
    """Stream JSONL, admitting no new properties; unresolved records never pass."""
    routed: dict[str, list[dict]] = defaultdict(list)
    decisions = {t["key"]: _decision("details_not_found") for t in targets}
    for target in targets:
        identity = _text(target.get("dataflik_id"))
        if identity:
            routed[identity].append(target)
        else:
            decisions[target["key"]] = _decision("routing_id_missing")
    fingerprints: dict[str, str] = {}
    conflicts = set()
    scanned = malformed = oversized = matched = 0
    with open(path, "rb") as stream:
        while True:
            line = stream.readline(MAX_LINE_BYTES + 1)
            if not line:
                break
            scanned += 1
            prefix = _PREFIX_ID.match(line)
            prefix_id = None
            if prefix:
                try:
                    prefix_id = _text(json.loads(prefix[1]))
                except (ValueError, UnicodeDecodeError):
                    pass
            if len(line) > MAX_LINE_BYTES:
                oversized += 1
                for target in routed.get(prefix_id, []):
                    decisions[target["key"]] = _decision("oversized_details")
                    conflicts.add(target["key"])
                while line and not line.endswith(b"\n"):
                    line = stream.readline(MAX_LINE_BYTES + 1)
                continue
            if prefix_id is not None and prefix_id not in routed:
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("not_object")
            except (ValueError, UnicodeDecodeError, RecursionError):
                malformed += 1
                for target in routed.get(prefix_id, []):
                    decisions[target["key"]] = _decision("malformed_details")
                    conflicts.add(target["key"])
                continue
            target_rows = routed.get(_text(record.get("dataflik_id")), [])
            if not target_rows:
                continue
            matched += 1
            for target in target_rows:
                key = target["key"]
                if key in conflicts:
                    continue
                decision, fingerprint = _evaluate(record, target)
                if key in fingerprints and fingerprints[key] != fingerprint:
                    decisions[key] = _decision("conflicting_duplicate_details")
                    conflicts.add(key)
                else:
                    decisions[key] = decision
                    fingerprints[key] = fingerprint
    counts = Counter(d["status"] for d in decisions.values())
    summary = dict(scanned=scanned, target_count=len(decisions), eligible=counts["eligible"],
                   excluded=counts["excluded"], unresolved=counts["unresolved"],
                   reasons=dict(Counter(d["reason"] for d in decisions.values())),
                   seller_categories=dict(Counter(d["seller_category"] for d in decisions.values())),
                   matched_detail_records=matched, malformed_lines=malformed, oversized_lines=oversized,
                   unsupported_rules=["ownership_duration", "LTV", "non_seller_religious_owner_exclusion"],
                   snapshot_caveat="Property characteristics are enrichment-time snapshots, not verified as of sale. Seller categories are name-based estimates from matched historical sale events.",
                   warnings=[])
    if malformed or oversized:
        summary["warnings"].append("Unreadable/oversized detail lines were skipped; missing targets remain unresolved. Malformed count covers parsed lines; non-target ID prefixes bypass parsing.")
    return decisions, summary
