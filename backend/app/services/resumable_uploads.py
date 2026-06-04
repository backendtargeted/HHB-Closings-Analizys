"""
Resumable local chunk uploads for single-host deployments.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from ..utils.file_handler import UPLOAD_DIR

_UPLOAD_ROOT = Path(os.environ.get("UPLOAD_STORAGE_DIR", str(UPLOAD_DIR))).resolve()
_RESUMABLE_ROOT = _UPLOAD_ROOT / "resumable"
_SESSIONS_DIR = _RESUMABLE_ROOT / "sessions"
_CHUNKS_DIR = _RESUMABLE_ROOT / "chunks"
_FINAL_DIR = _RESUMABLE_ROOT / "final"

_MAX_CHUNK_MB_RAW = os.environ.get("UPLOAD_MAX_CHUNK_MB", "8").strip()
_MAX_TOTAL_MB_RAW = os.environ.get("UPLOAD_MAX_TOTAL_MB", os.environ.get("MAX_UPLOAD_MB", "2048")).strip()
_SESSION_TTL_HOURS_RAW = os.environ.get("UPLOAD_SESSION_TTL_HOURS", "24").strip()

try:
    _MAX_CHUNK_BYTES = max(1, int(_MAX_CHUNK_MB_RAW)) * 1024 * 1024
except ValueError:
    _MAX_CHUNK_BYTES = 8 * 1024 * 1024

try:
    _MAX_TOTAL_BYTES = max(1, int(_MAX_TOTAL_MB_RAW)) * 1024 * 1024
except ValueError:
    _MAX_TOTAL_BYTES = 2048 * 1024 * 1024

try:
    _SESSION_TTL_HOURS = max(1, int(_SESSION_TTL_HOURS_RAW))
except ValueError:
    _SESSION_TTL_HOURS = 24

_lock = threading.Lock()


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(filename: str) -> str:
    base = Path(filename or "upload.bin").name
    if not base or base in (".", ".."):
        base = "upload.bin"
    base = re.sub(r"[^\w.\-]+", "_", base, flags=re.UNICODE)
    return base[:200] if len(base) > 200 else base


def _manifest_path(upload_id: str) -> Path:
    return _SESSIONS_DIR / f"{upload_id}.json"


def _upload_chunk_dir(upload_id: str) -> Path:
    return _CHUNKS_DIR / upload_id


def ensure_dirs() -> None:
    _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    _CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    _FINAL_DIR.mkdir(parents=True, exist_ok=True)


_MCR_EXTENSIONS = (".csv", ".xlsx", ".xls")


def _validate_kind(kind: str) -> str:
    k = (kind or "").strip().lower()
    if k not in ("csv", "closings", "reisift", "qualified_leads"):
        raise ValueError("kind must be csv, closings, reisift, or qualified_leads")
    return k


def _validate_filename(kind: str, filename: str) -> str:
    safe = _safe_name(filename)
    lowered = safe.lower()
    if kind == "csv" and not lowered.endswith(".csv"):
        raise ValueError("CSV upload filename must end with .csv")
    if kind == "closings" and not (lowered.endswith(".xlsx") or lowered.endswith(".xls")):
        raise ValueError("Closings upload filename must end with .xlsx or .xls")
    if kind in ("reisift", "qualified_leads") and not any(
        lowered.endswith(ext) for ext in _MCR_EXTENSIONS
    ):
        raise ValueError(f"{kind} upload filename must end with .csv, .xlsx, or .xls")
    return safe


def resolve_trusted_final_path(raw_path: str) -> Path:
    """Ensure path points to a file under the resumable final directory."""
    if not raw_path or not str(raw_path).strip():
        raise ValueError("path is required")
    final_root = _FINAL_DIR.resolve()
    candidate = Path(str(raw_path).strip()).resolve()
    try:
        candidate.relative_to(final_root)
    except ValueError as exc:
        raise ValueError("path must be a completed resumable upload") from exc
    if not candidate.is_file():
        raise ValueError("uploaded file not found")
    return candidate


def _read_manifest(upload_id: str) -> Dict[str, Any]:
    path = _manifest_path(upload_id)
    if not path.exists():
        raise FileNotFoundError("Upload session not found")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_manifest(upload_id: str, data: Dict[str, Any]) -> None:
    path = _manifest_path(upload_id)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _destroy_upload_session(upload_id: str) -> None:
    """Remove session files. Caller must hold _lock if concurrent access is possible."""
    _manifest_path(upload_id).unlink(missing_ok=True)
    shutil.rmtree(_upload_chunk_dir(upload_id), ignore_errors=True)


def _cleanup_expired_sessions() -> None:
    now = datetime.now(timezone.utc)
    ttl = timedelta(hours=_SESSION_TTL_HOURS)
    for path in _SESSIONS_DIR.glob("*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            updated_raw = data.get("updated_at") or data.get("created_at")
            updated = datetime.fromisoformat(str(updated_raw))
            if now - updated > ttl:
                upload_id = str(data.get("upload_id") or path.stem)
                _destroy_upload_session(upload_id)
        except Exception:
            continue


def create_upload(kind: str, filename: str, total_size: int, chunk_size: int) -> Dict[str, Any]:
    ensure_dirs()
    with _lock:
        _cleanup_expired_sessions()
        kind_clean = _validate_kind(kind)
        safe_name = _validate_filename(kind_clean, filename)
        if total_size <= 0:
            raise ValueError("total_size must be > 0")
        if total_size > _MAX_TOTAL_BYTES:
            raise ValueError("File exceeds UPLOAD_MAX_TOTAL_MB")
        if chunk_size <= 0:
            raise ValueError("chunk_size must be > 0")
        if chunk_size > _MAX_CHUNK_BYTES:
            raise ValueError("chunk_size exceeds UPLOAD_MAX_CHUNK_MB")

        total_chunks = (total_size + chunk_size - 1) // chunk_size
        upload_id = str(uuid.uuid4())
        chunk_dir = _upload_chunk_dir(upload_id)
        chunk_dir.mkdir(parents=True, exist_ok=True)
        now = _utc_iso_now()
        manifest = {
            "upload_id": upload_id,
            "kind": kind_clean,
            "filename": safe_name,
            "total_size": int(total_size),
            "chunk_size": int(chunk_size),
            "total_chunks": int(total_chunks),
            "uploaded_chunks": [],
            "status": "pending",
            "final_path": None,
            "created_at": now,
            "updated_at": now,
        }
        _write_manifest(upload_id, manifest)
        return manifest


def upload_chunk(upload_id: str, chunk_index: int, chunk_data: bytes) -> Dict[str, Any]:
    ensure_dirs()
    with _lock:
        manifest = _read_manifest(upload_id)
        if manifest.get("status") == "completed":
            return manifest
        total_chunks = int(manifest["total_chunks"])
        if chunk_index < 0 or chunk_index >= total_chunks:
            raise ValueError("chunk_index out of range")
        if len(chunk_data) == 0:
            raise ValueError("Chunk is empty")
        if len(chunk_data) > _MAX_CHUNK_BYTES:
            raise ValueError("Chunk exceeds UPLOAD_MAX_CHUNK_MB")

        chunk_path = _upload_chunk_dir(upload_id) / f"{chunk_index:08d}.part"
        with open(chunk_path, "wb") as f:
            f.write(chunk_data)

        uploaded_chunks: List[int] = [int(i) for i in manifest.get("uploaded_chunks", [])]
        if chunk_index not in uploaded_chunks:
            uploaded_chunks.append(chunk_index)
            uploaded_chunks.sort()

        manifest["uploaded_chunks"] = uploaded_chunks
        manifest["status"] = "uploading"
        manifest["updated_at"] = _utc_iso_now()
        _write_manifest(upload_id, manifest)
        return manifest


def get_upload_status(upload_id: str) -> Dict[str, Any]:
    ensure_dirs()
    with _lock:
        return _read_manifest(upload_id)


def finalize_upload(upload_id: str) -> Dict[str, Any]:
    ensure_dirs()
    with _lock:
        manifest = _read_manifest(upload_id)
        if manifest.get("status") == "completed":
            return manifest

        total_chunks = int(manifest["total_chunks"])
        uploaded_chunks = [int(i) for i in manifest.get("uploaded_chunks", [])]
        missing = [i for i in range(total_chunks) if i not in set(uploaded_chunks)]
        if missing:
            raise ValueError(f"Missing chunks: {missing[:10]}")

        ext = Path(str(manifest["filename"])).suffix
        final_name = f"{manifest['kind']}_{upload_id}{ext}"
        final_path = _FINAL_DIR / final_name

        with open(final_path, "wb") as out:
            for i in range(total_chunks):
                part = _upload_chunk_dir(upload_id) / f"{i:08d}.part"
                if not part.exists():
                    raise ValueError(f"Missing chunk file: {i}")
                with open(part, "rb") as pf:
                    shutil.copyfileobj(pf, out, length=8 * 1024 * 1024)

        actual_size = final_path.stat().st_size
        expected_size = int(manifest["total_size"])
        if actual_size != expected_size:
            final_path.unlink(missing_ok=True)
            raise ValueError(f"Final size mismatch: expected {expected_size}, got {actual_size}")

        shutil.rmtree(_upload_chunk_dir(upload_id), ignore_errors=True)
        manifest["status"] = "completed"
        manifest["final_path"] = str(final_path)
        manifest["updated_at"] = _utc_iso_now()
        _write_manifest(upload_id, manifest)
        return manifest


def cancel_upload(upload_id: str) -> None:
    with _lock:
        _destroy_upload_session(upload_id)


def get_limits() -> Dict[str, int]:
    return {
        "max_chunk_bytes": _MAX_CHUNK_BYTES,
        "max_total_bytes": _MAX_TOTAL_BYTES,
        "session_ttl_hours": _SESSION_TTL_HOURS,
    }
