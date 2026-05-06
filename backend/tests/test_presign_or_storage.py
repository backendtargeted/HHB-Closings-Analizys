"""Presigned upload capabilities and analyze XOR validation."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402

_S3_KEYS = (
    "S3_ENDPOINT",
    "S3_PUBLIC_ENDPOINT",
    "S3_BUCKET",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
)


def _s3_env_empty():
    return {k: "" for k in _S3_KEYS}


def _s3_env_full():
    return {
        "S3_ENDPOINT": "http://minio-internal:9000",
        "S3_PUBLIC_ENDPOINT": "https://minio.example.test",
        "S3_BUCKET": "test-bucket",
        "S3_ACCESS_KEY": "access",
        "S3_SECRET_KEY": "secret",
        "S3_REGION": "us-east-1",
        "S3_USE_PATH_STYLE": "true",
    }


class TestUploadCapabilities(unittest.TestCase):
    def test_capabilities_presigned_false_when_s3_unset(self):
        with patch.dict(os.environ, _s3_env_empty(), clear=False):
            client = app.test_client()
            r = client.get("/api/upload/capabilities")
            self.assertEqual(r.status_code, 200)
            self.assertFalse(r.get_json().get("presigned_upload"))

    def test_presign_returns_503_when_s3_unset(self):
        with patch.dict(os.environ, _s3_env_empty(), clear=False):
            client = app.test_client()
            r = client.post("/api/upload/presign", json={"kind": "csv", "filename": "a.csv"})
            self.assertEqual(r.status_code, 503)
            self.assertIn("detail", r.get_json())

    def test_presign_returns_payload_when_s3_configured_and_boto_mocked(self):
        mock_client = MagicMock()
        mock_client.generate_presigned_url.return_value = "https://minio.example.test/test-bucket/k?sig=1"
        with patch.dict(os.environ, _s3_env_full(), clear=False):
            with patch("app.services.object_storage.boto3.client", return_value=mock_client):
                client = app.test_client()
                cap = client.get("/api/upload/capabilities")
                self.assertTrue(cap.get_json().get("presigned_upload"))

                r = client.post("/api/upload/presign", json={"kind": "csv", "filename": "contacts.csv"})
                self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
                data = r.get_json()
                self.assertIn("object_key", data)
                self.assertTrue(data["object_key"].startswith("analysis-incoming/"))
                self.assertIn("upload", data)
                self.assertEqual(data["upload"]["method"], "PUT")
                self.assertIn("url", data["upload"])
                self.assertIn("headers", data["upload"])
                mock_client.generate_presigned_url.assert_called()


class TestAnalyzeXor(unittest.TestCase):
    def test_analyze_requires_exactly_one_csv_source(self):
        client = app.test_client()
        r = client.post("/api/analyze", json={})
        self.assertEqual(r.status_code, 400)
        self.assertIn("exactly one", r.get_json()["detail"].lower())

    def test_analyze_rejects_both_csv_path_and_object_key(self):
        client = app.test_client()
        r = client.post(
            "/api/analyze",
            json={"csv_path": "/tmp/x.csv", "csv_object_key": "analysis-incoming/u/f.csv"},
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("exactly one", r.get_json()["detail"].lower())

    def test_analyze_rejects_both_closings_path_and_object_key(self):
        client = app.test_client()
        r = client.post(
            "/api/analyze",
            json={
                "csv_path": "/tmp/x.csv",
                "closings_path": "/tmp/y.xlsx",
                "closings_object_key": "analysis-incoming/u/f.xlsx",
            },
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("closings_path", r.get_json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()
