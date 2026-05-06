"""
S3-compatible object storage (MinIO) for presigned browser uploads and server-side downloads.
Configure via S3_* environment variables (see RUNBOOK.md).
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Dict, Tuple

import boto3
from botocore.client import Config


def _strip_url(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _bucket() -> str:
    return os.environ.get("S3_BUCKET", "").strip()


def _region() -> str:
    return os.environ.get("S3_REGION", "us-east-1").strip() or "us-east-1"


def _access_key() -> str:
    return os.environ.get("S3_ACCESS_KEY", "").strip()


def _secret_key() -> str:
    return os.environ.get("S3_SECRET_KEY", "").strip()


def _endpoint_internal() -> str:
    return _strip_url(os.environ.get("S3_ENDPOINT", ""))


def _endpoint_public() -> str:
    return _strip_url(os.environ.get("S3_PUBLIC_ENDPOINT", ""))


def _use_path_style() -> bool:
    raw = os.environ.get("S3_USE_PATH_STYLE", "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _presign_expires() -> int:
    try:
        return max(60, int(os.environ.get("S3_PRESIGN_EXPIRES", "3600")))
    except ValueError:
        return 3600


def _s3_config() -> Config:
    style = "path" if _use_path_style() else "virtual"
    return Config(signature_version="s3v4", s3={"addressing_style": style})


def is_object_storage_configured() -> bool:
    return bool(
        _endpoint_internal()
        and _endpoint_public()
        and _bucket()
        and _access_key()
        and _secret_key()
    )


def _client(endpoint_url: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=_region(),
        aws_access_key_id=_access_key(),
        aws_secret_access_key=_secret_key(),
        config=_s3_config(),
    )


def safe_basename(filename: str) -> str:
    base = Path(filename or "upload").name
    if not base or base in (".", ".."):
        base = "upload.bin"
    base = re.sub(r"[^\w.\-]+", "_", base, flags=re.UNICODE)
    return base[:200] if len(base) > 200 else base


def build_object_key(kind: str, original_filename: str) -> str:
    if kind not in ("csv", "closings"):
        raise ValueError("kind must be csv or closings")
    uid = str(uuid.uuid4())
    name = safe_basename(original_filename)
    return f"analysis-incoming/{uid}/{name}"


def content_type_for_upload(kind: str, filename: str) -> str:
    fn = (filename or "").lower()
    if kind == "csv":
        return "text/csv"
    if fn.endswith(".xlsx"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if fn.endswith(".xls"):
        return "application/vnd.ms-excel"
    return "application/octet-stream"


def generate_presigned_put(object_key: str, content_type: str) -> Tuple[str, Dict[str, str], int]:
    """Return (url, headers_for_client, expires_in).

    Do not sign Content-Type in the URL signature. Reverse proxies/browsers can
    mutate or omit this header, causing SignatureDoesNotMatch on MinIO.
    """
    client = _client(_endpoint_public())
    expires = _presign_expires()
    url = client.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": _bucket(),
            "Key": object_key,
        },
        ExpiresIn=expires,
        HttpMethod="PUT",
    )
    headers: Dict[str, str] = {}
    return url, headers, expires


def download_object_to_tempfile(object_key: str) -> str:
    """Stream object to a temp file; caller must delete path when done."""
    import tempfile

    suffix = Path(object_key).suffix
    if suffix.lower() not in (".csv", ".xlsx", ".xls"):
        suffix = ".bin"
    client = _client(_endpoint_internal())
    resp = client.get_object(Bucket=_bucket(), Key=object_key)
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as out:
            body = resp["Body"]
            for chunk in iter(lambda: body.read(8 * 1024 * 1024), b""):
                if not chunk:
                    break
                out.write(chunk)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path


def delete_object(object_key: str) -> None:
    client = _client(_endpoint_internal())
    client.delete_object(Bucket=_bucket(), Key=object_key)


def delete_after_analysis_enabled() -> bool:
    return os.environ.get("S3_DELETE_AFTER_ANALYSIS", "").strip().lower() in ("1", "true", "yes", "on")
