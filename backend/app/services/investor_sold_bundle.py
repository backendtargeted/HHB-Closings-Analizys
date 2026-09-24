"""Validate and stream-extract the canonical Gate 7 ZIP inside its worker."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import zipfile
import zlib

INPUT_NAMES = {
    "sold_properties_full.csv": "sold_path",
    "reisift_export.csv": "reisift_path",
    "qualified_leads.xlsx": "ql_path", "qualified_leads.csv": "ql_path",
    "sold_property_details.jsonl": "property_details_path",
    "opportunities.xlsx": "opportunities_path", "opportunities.csv": "opportunities_path",
    "transactions.xlsx": "transactions_path", "transactions.csv": "transactions_path",
}
REQUIRED_ROLES = {"sold_path", "reisift_path", "ql_path", "property_details_path"}
CHUNK_BYTES = 1024 * 1024


def extract_investor_sold_bundle(bundle_path: str, destination: Path) -> dict[str, str]:
    """Reject unsafe/ambiguous archives before writing; never use extractall."""
    try:
        limit = int(os.environ.get("INVESTOR_SOLD_BUNDLE_MAX_UNCOMPRESSED_BYTES", str(4 * 1024**3)))
        if limit <= 0:
            raise ValueError
    except ValueError as exc:
        raise ValueError("Bundle uncompressed byte limit must be a positive integer") from exc
    written: list[Path] = []
    try:
        with zipfile.ZipFile(bundle_path) as archive:
            selected = {}
            prefixes = set()
            declared_total = 0
            for item in archive.infolist():
                name = item.filename
                parts = name.rstrip("/").split("/")
                mode = item.external_attr >> 16
                if (not name or name != item.orig_filename or "\\" in name or name.startswith("/") or
                        any(p in {"", ".", ".."} or ":" in p for p in parts) or
                        stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR})):
                    raise ValueError(f"Unsafe ZIP entry: {name}")
                if item.flag_bits & 1:
                    raise ValueError("Encrypted ZIP entries are not supported")
                declared_total += item.file_size
                if declared_total > limit:
                    raise ValueError("Bundle exceeds uncompressed byte limit")
                if parts[0] == "__MACOSX" or parts[-1] == ".DS_Store":
                    continue
                if item.is_dir():
                    if len(parts) > 1:
                        raise ValueError("Bundle permits only a single wrapping folder")
                    continue
                if len(parts) > 2 or parts[-1] not in INPUT_NAMES:
                    raise ValueError(f"Unexpected bundle file: {name}")
                role = INPUT_NAMES[parts[-1]]
                if role in selected:
                    raise ValueError(f"Ambiguous bundle: multiple files for {role}")
                prefixes.add(tuple(parts[:-1]))
                selected[role] = item
            if len(prefixes) > 1:
                raise ValueError("Bundle files must be at root or inside one shared wrapping folder")
            missing = REQUIRED_ROLES - selected.keys()
            if missing:
                raise ValueError("Bundle is missing required inputs: " + ", ".join(sorted(missing)))
            destination.mkdir(parents=True, exist_ok=True)
            root = destination.resolve()
            result = {}
            actual_total = 0
            for role, item in selected.items():
                target = root / item.filename.split("/")[-1]
                # Exclusive creation prevents following pre-existing links or overwriting files.
                with archive.open(item) as source, target.open("xb") as output:
                    written.append(target)
                    copied = 0
                    while chunk := source.read(CHUNK_BYTES):
                        copied += len(chunk)
                        actual_total += len(chunk)
                        if actual_total > limit or copied > item.file_size:
                            raise ValueError("Bundle exceeds uncompressed byte limit or declared size")
                        output.write(chunk)
                    if copied != item.file_size:
                        raise ValueError("Corrupt ZIP entry size")
                result[role] = str(target)
            return result
    except (zipfile.BadZipFile, EOFError, RuntimeError, NotImplementedError, OSError, zlib.error) as exc:
        raise ValueError(f"Invalid or unreadable Gate 7 ZIP bundle: {exc}") from exc
    finally:
        # A failed extraction must not leave partial source files available for analysis.
        import sys
        if sys.exc_info()[0] is not None:
            for path in written:
                path.unlink(missing_ok=True)
