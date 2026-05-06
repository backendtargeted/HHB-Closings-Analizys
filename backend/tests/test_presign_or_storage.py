"""Resumable upload capabilities and analyze validation."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402

class TestUploadCapabilities(unittest.TestCase):
    def test_capabilities_resumable_true(self):
        client = app.test_client()
        r = client.get("/api/upload/capabilities")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertFalse(data.get("presigned_upload"))
        self.assertTrue(data.get("resumable_upload"))
        self.assertIn("limits", data)


class TestResumableUploadFlow(unittest.TestCase):
    def test_chunked_upload_complete(self):
        client = app.test_client()
        init = client.post(
            "/api/upload/resumable/init",
            json={"kind": "csv", "filename": "contacts.csv", "total_size": 12, "chunk_size": 5},
        )
        self.assertEqual(init.status_code, 200, init.get_data(as_text=True))
        upload_id = init.get_json()["upload_id"]

        c0 = client.put(f"/api/upload/resumable/{upload_id}/chunk/0", data=b"abcde")
        c1 = client.put(f"/api/upload/resumable/{upload_id}/chunk/1", data=b"fghij")
        c2 = client.put(f"/api/upload/resumable/{upload_id}/chunk/2", data=b"kl")
        self.assertEqual(c0.status_code, 200)
        self.assertEqual(c1.status_code, 200)
        self.assertEqual(c2.status_code, 200)

        done = client.post(f"/api/upload/resumable/{upload_id}/complete")
        self.assertEqual(done.status_code, 200, done.get_data(as_text=True))
        payload = done.get_json()
        self.assertEqual(payload.get("kind"), "csv")
        self.assertIn("csv_path", payload)
        self.assertTrue(str(payload["csv_path"]).endswith(".csv"))


class TestAnalyzeXor(unittest.TestCase):
    def test_analyze_requires_csv_path(self):
        client = app.test_client()
        r = client.post("/api/analyze", json={})
        self.assertEqual(r.status_code, 400)
        self.assertIn("csv_path", r.get_json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()
