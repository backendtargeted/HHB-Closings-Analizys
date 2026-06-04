"""Resumable upload capabilities and analyze validation."""

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
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
        self.assertIn(done.status_code, (200, 202), done.get_data(as_text=True))

        import time

        deadline = time.time() + 30
        payload = done.get_json()
        while time.time() < deadline and payload.get("status") != "completed":
            st = client.get(f"/api/upload/resumable/{upload_id}/status")
            self.assertEqual(st.status_code, 200)
            payload = st.get_json()
            if payload.get("status") == "failed":
                self.fail(payload.get("finalize_error"))
            time.sleep(0.1)

        self.assertEqual(payload.get("status"), "completed")
        self.assertIn("final_path", payload)
        self.assertTrue(str(payload["final_path"]).endswith(".csv"))

    def test_init_cleans_expired_sessions_without_deadlock(self):
        """create_upload runs cleanup while holding the lock; must not re-enter cancel_upload."""
        from app.services import resumable_uploads

        resumable_uploads.ensure_dirs()
        expired_id = "expired-test-session"
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        manifest_path = resumable_uploads._manifest_path(expired_id)
        manifest_path.write_text(
            json.dumps(
                {
                    "upload_id": expired_id,
                    "kind": "csv",
                    "filename": "old.csv",
                    "total_size": 1,
                    "chunk_size": 1,
                    "total_chunks": 1,
                    "uploaded_chunks": [],
                    "status": "pending",
                    "final_path": None,
                    "created_at": stale_time,
                    "updated_at": stale_time,
                }
            ),
            encoding="utf-8",
        )

        client = app.test_client()
        init = client.post(
            "/api/upload/resumable/init",
            json={"kind": "csv", "filename": "contacts.csv", "total_size": 12, "chunk_size": 5},
        )
        self.assertEqual(init.status_code, 200, init.get_data(as_text=True))
        self.assertFalse(manifest_path.exists())

    def test_reisift_kind_upload_complete(self):
        client = app.test_client()
        init = client.post(
            "/api/upload/resumable/init",
            json={
                "kind": "reisift",
                "filename": "contacts.csv",
                "total_size": 12,
                "chunk_size": 5,
            },
        )
        self.assertEqual(init.status_code, 200, init.get_data(as_text=True))
        upload_id = init.get_json()["upload_id"]

        for idx, data in enumerate([b"abcde", b"fghij", b"kl"]):
            r = client.put(f"/api/upload/resumable/{upload_id}/chunk/{idx}", data=data)
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

        done = client.post(f"/api/upload/resumable/{upload_id}/complete")
        self.assertIn(done.status_code, (200, 202), done.get_data(as_text=True))

        import time

        deadline = time.time() + 30
        payload = done.get_json()
        while time.time() < deadline and payload.get("status") != "completed":
            st = client.get(f"/api/upload/resumable/{upload_id}/status")
            self.assertEqual(st.status_code, 200)
            payload = st.get_json()
            if payload.get("status") == "failed":
                self.fail(payload.get("finalize_error"))
            time.sleep(0.1)

        self.assertEqual(payload.get("status"), "completed")
        self.assertTrue(str(payload.get("final_path", "")).endswith(".csv"))


class TestMonthlyConsolidatedAnalyzePaths(unittest.TestCase):
    def test_analyze_from_resumable_paths(self):
        from pathlib import Path

        client = app.test_client()
        fixtures = Path(__file__).resolve().parent / "fixtures"

        def upload_fixture(kind: str, fixture_name: str) -> str:
            data = (fixtures / fixture_name).read_bytes()
            init = client.post(
                "/api/upload/resumable/init",
                json={
                    "kind": kind,
                    "filename": fixture_name,
                    "total_size": len(data),
                    "chunk_size": len(data),
                },
            )
            self.assertEqual(init.status_code, 200, init.get_data(as_text=True))
            upload_id = init.get_json()["upload_id"]
            put = client.put(f"/api/upload/resumable/{upload_id}/chunk/0", data=data)
            self.assertEqual(put.status_code, 200)
            done = client.post(f"/api/upload/resumable/{upload_id}/complete")
            self.assertIn(done.status_code, (200, 202), done.get_data(as_text=True))

            import time

            deadline = time.time() + 30
            payload = done.get_json()
            while time.time() < deadline and payload.get("status") != "completed":
                st = client.get(f"/api/upload/resumable/{upload_id}/status")
                self.assertEqual(st.status_code, 200)
                payload = st.get_json()
                if payload.get("status") == "failed":
                    self.fail(payload.get("finalize_error"))
                time.sleep(0.1)

            self.assertEqual(payload.get("status"), "completed")
            path_key = f"{kind}_path"
            if done.status_code == 200 and path_key in done.get_json():
                return done.get_json()[path_key]
            return payload["final_path"]

        reisift_path = upload_fixture("reisift", "monthly_reisift_sample.csv")
        ql_path = upload_fixture("qualified_leads", "qualified_leads_sample.csv")

        r = client.post(
            "/api/monthly-consolidated/analyze",
            json={"reisift_path": reisift_path, "qualified_leads_path": ql_path},
        )
        self.assertEqual(r.status_code, 202, r.get_data(as_text=True))
        job_id = r.get_json()["job_id"]

        import time

        deadline = time.time() + 30
        status = None
        while time.time() < deadline:
            st = client.get(f"/api/monthly-consolidated/{job_id}/status")
            self.assertEqual(st.status_code, 200, st.get_data(as_text=True))
            status = st.get_json()
            if status.get("status") == "completed":
                break
            if status.get("status") == "failed":
                self.fail(status.get("message"))
            time.sleep(0.2)

        self.assertEqual(status.get("status"), "completed")
        done = client.get(f"/api/monthly-consolidated/{job_id}")
        self.assertEqual(done.status_code, 200, done.get_data(as_text=True))
        payload = done.get_json()
        self.assertEqual(payload.get("status"), "completed")
        self.assertIn("metrics", payload)


class TestAnalyzeXor(unittest.TestCase):
    def test_analyze_requires_csv_path(self):
        client = app.test_client()
        r = client.post("/api/analyze", json={})
        self.assertEqual(r.status_code, 400)
        self.assertIn("csv_path", r.get_json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()
