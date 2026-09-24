import csv
import io
import json
import zipfile

import pytest
from flask import Flask

from app.api import patches
from app.services.analysis import parse_tags
from app.services.web_leads import tags_have_8020


def upload_csv(rows, name):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return io.BytesIO(buffer.getvalue().encode()), name


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(patches, "PATCHES_ROOT", tmp_path)
    app = Flask(__name__)
    app.register_blueprint(patches.patches_bp, url_prefix="/api/patches")
    return app.test_client()


def test_monthly_sms_alone_persists_exports_and_review(client):
    response = client.post("/api/patches/monthly", data={
        "report_month": "2026-09",
        "sms_files": upload_csv([
            {"Phone 1": "6315550100", "Labels": "Wrong Number", "Date": "2026-09-30"},
            {"Phone 1": "6315550101", "Labels": "Undefined", "Date": ""},
            {"Phone 1": "6315550102", "Labels": "DNC", "Date": "2026-10-01"},
        ], "actual labels.csv"),
    })
    assert response.status_code == 200, response.json
    payload = response.json
    assert payload["monthly"]["sources"][0]["included_rows"] == 2
    assert payload["monthly"]["sources"][0]["outside_month_rows"] == 1
    assert payload["samples"]["sms"][0]["phone_status"] == "Wrong"
    assert len(payload["samples"]["sms"]) == 1
    assert payload["samples"]["cold_calling"][0]["status"] == "Follow Up"
    assert payload["samples"]["review_rows"][0]["reason"] == "unmapped_property_labels"
    patches._patch_job_meta.clear()  # export remains available after process-memory loss
    response = client.get(f"/api/patches/{payload['job_id']}/export?file=all")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as bundle:
        assert "ingestion_review.csv" in bundle.namelist()
        assert "marketing_activity_tags.csv" in bundle.namelist()
        summary = json.loads(bundle.read("ingestion_summary.json"))
        assert summary["monthly"]["report_month"] == "2026-09"
        phones = list(csv.DictReader(io.StringIO(bundle.read("phone_status_tags_updates.csv").decode())))
        assert [row["phone"] for row in phones] == ["6315550100"]
        tags = list(csv.DictReader(io.StringIO(bundle.read("marketing_activity_tags.csv").decode())))
        assert len(tags) == 1
        assert all(row["tag"] == "(MARKETING) SMS - 9/2026" for row in tags)
    assert client.get(f"/api/patches/{payload['job_id']}/export?file=sf").status_code == 404
    assert client.delete(f"/api/patches/{payload['job_id']}").status_code == 200


def test_all_three_salesforce_reports_without_campaigns(client):
    response = client.post("/api/patches/monthly", data={
        "report_month": "2026-09",
        "qualified_leads": upload_csv([{"Street": "1 Main St", "Create Date": "2026-09-01", "Lead Status": "Converted"}], "ql.csv"),
        "opportunities": upload_csv([{"Address (Street)": "2 Main St", "Created Date": "2026-09-02", "Stage": "Closed Lost", "Close Date": "2026-09-15"}], "opportunities.csv"),
        "transactions": upload_csv([{"Address (Street)": "3 Main St", "Path": "Closed", "Date Contract Signed": "2026-09-03", "Closed Date": "2026-09-25"}], "transactions.csv"),
    })
    assert response.status_code == 200, response.json
    tags = {row["salesforce_tag"] for row in response.json["samples"]["salesforce_tags"]}
    assert tags == {"(SF) STATUS - New - 2026-09-01", "(SF) UPDATED - Opportunity - 2026-09-02",
                    "(SF) UPDATED - Under Contract - 2026-09-03", "(CLOSED) 8020 - 9/2026"}
    assert len(response.json["monthly"]["sources"]) == 3


@pytest.mark.parametrize("month", ["", "2026-13", "0000-01", "September 2026"])
def test_invalid_month_rejected(client, month):
    assert client.post("/api/patches/monthly", data={"report_month": month}).status_code == 400


def test_salesforce_report_can_run_alone(client):
    response = client.post("/api/patches/monthly", data={"report_month": "2026-09", "qualified_leads": upload_csv(
        [{"Street": "1 Main St", "Create Date": "2026-09-02", "Lead Status": "New"}], "ql.csv")})
    assert response.status_code == 200, response.json
    assert [row["source"] for row in response.json["monthly"]["sources"]] == ["qualified_leads"]
    assert len(response.json["samples"]["salesforce_tags"]) == 1


def test_wrong_file_type_rejected(client):
    assert client.post("/api/patches/monthly", data={"report_month": "2026-09", "sms_files": (io.BytesIO(b"x"), "sms.xlsx")}).status_code == 400


def test_calling_alone_needs_no_salesforce_or_sms_and_exports_only_calling(client):
    response = client.post("/api/patches/monthly", data={"report_month": "2026-09", "cold_csv": upload_csv(
        [{"Phone": "6315550100", "Address": "1 Main St", "Log Type": "Decision Maker - Lead", "Log Time (Date)": "9/2/2026"}], "calls.csv")})
    assert response.status_code == 200, response.json
    payload = response.json
    assert payload["samples"]["cold_calling"][0]["status"] == "lead"
    assert payload["samples"]["salesforce_tags"] == []
    assert payload["samples"]["sms"][0]["phone_status"] == "Correct"
    assert set(payload["samples"]["sms"][0]["phone_tag"].split(",")) == {"Correct", "Contacted"}
    exported = client.get(f"/api/patches/{payload['job_id']}/export?file=all")
    with zipfile.ZipFile(io.BytesIO(exported.data)) as bundle:
        assert "property_status_updates.csv" in bundle.namelist()
        assert "marketing_activity_tags.csv" in bundle.namelist()
        assert "salesforce_status_tags.csv" not in bundle.namelist()
        assert "phone_status_tags_updates.csv" in bundle.namelist()


def test_new_marketing_tags_roundtrip_without_inventing_provider():
    tags = "(MARKETING) CC - 9/2026,(MARKETING) SMS - 9/2026,(8020) CC - 9/2026"
    events = parse_tags(tags)
    assert len(events) == 2  # repeated import via old and new grammar is idempotent
    assert all(row["type"] == "contact" for row in events)
    assert {row["channel"] for row in events} == {"CC", "SMS"}
    assert not tags_have_8020("(MARKETING) CC - 9/2026")


def test_background_run_returns_then_polls_to_reviewed_result(client):
    response = client.post("/api/patches/monthly", data={
        "report_month": "2026-09", "background": "true",
        "sms_files": upload_csv([{"Phone": "6315550100", "Labels": "Do Not Call"}], "labels.csv"),
    })
    assert response.status_code == 202
    job_id = response.json["job_id"]
    patches._monthly_jobs[job_id].result(timeout=20)
    result = client.get(f"/api/patches/monthly/{job_id}")
    assert result.status_code == 200
    assert result.json["status"] == "completed"
    assert result.json["samples"]["sms"][0]["phone_status"] == "DNC"
    assert client.get(f"/api/patches/{job_id}/export?file=review").status_code == 200


def test_background_schema_failure_is_visible(client):
    response = client.post("/api/patches/monthly", data={
        "report_month": "2026-09", "background": "true",
        "sms_files": upload_csv([{"MissingPhone": "x"}], "labels.csv"),
    })
    assert response.status_code == 202
    job_id = response.json["job_id"]
    patches._monthly_jobs[job_id].result(timeout=20)
    result = client.get(f"/api/patches/monthly/{job_id}").json
    assert result["status"] == "failed"
    assert "Phone" in result["detail"]
