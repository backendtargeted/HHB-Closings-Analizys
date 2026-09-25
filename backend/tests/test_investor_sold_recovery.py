import hashlib
import json

import pytest
from flask import Flask
from app.api import investor_sold as api
from app.services.report_store import load_investor_sold_report


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    job_id = "51432a92-5b5e-445b-a599-625ecc353d78"
    raw = json.dumps({"job_id": job_id, "status": "completed", "created_at": "2026-09-25",
                      "metrics": {"rows": [], "report_type": "investor_sold"}}).encode()
    monkeypatch.setattr(api, "_RECOVERY_BACKUPS", {hashlib.sha256(raw).hexdigest(): job_id})
    monkeypatch.setattr(api, "get_reports_dir", lambda: tmp_path)
    app = Flask(__name__)
    app.register_blueprint(api.investor_sold_bp, url_prefix="/api/investor-sold")
    return app.test_client(), tmp_path, raw, job_id


def test_restores_original_id_and_can_reload(recovery):
    client, root, raw, job_id = recovery
    response = client.post("/api/investor-sold/restore", data=raw, content_type="application/json")
    assert response.status_code == 201
    saved = load_investor_sold_report(job_id, reports_dir=root)
    assert saved["created_at"] == "2026-09-25"
    assert saved["metrics"]["rows"] == []
    assert not list(root.rglob("*.tmp"))


def test_never_overwrites_existing_report(recovery):
    client, root, raw, job_id = recovery
    dest = root / "investor_sold" / f"{job_id}.json"
    dest.parent.mkdir()
    dest.write_text("existing content", encoding="utf-8")
    assert client.post("/api/investor-sold/restore", data=raw).status_code == 409
    assert dest.read_text(encoding="utf-8") == "existing content"
    assert not list(root.rglob("*.tmp"))


@pytest.mark.parametrize("data", [b"{}", b"invalid", b'{"job_id":"../../escape"}'])
def test_unapproved_payloads_rejected(recovery, data):
    client, root, _, _ = recovery
    assert client.post("/api/investor-sold/restore", data=data).status_code == 403
    assert not list(root.iterdir())


def test_oversized_rejected(recovery, monkeypatch):
    client, root, raw, _ = recovery
    monkeypatch.setattr(api, "_RECOVERY_MAX_BYTES", 10)
    assert client.post("/api/investor-sold/restore", data=raw).status_code == 413
    assert not list(root.iterdir())
