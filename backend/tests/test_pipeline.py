import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="steel_test_")
os.environ["DATABASE_PATH"] = str(Path(TMP) / "test.db")
os.environ["CRAWL_LIVE"] = "false"
os.environ["SERPER_API_KEY"] = ""
os.environ["SERPER_MAX_QUERIES"] = "0"

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


class PipelineApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()
        resp = cls.client.post(
            "/api/runs",
            json={"product": "Stainless steel flat products and profiles", "country": "Brazil"},
        )
        assert resp.status_code == 202, resp.text
        cls.run_id = resp.json()["run_id"]

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_01_run_completes(self):
        resp = self.client.get(f"/api/runs/{self.run_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "completed", data.get("error"))
        self.assertGreaterEqual(data["company_count"], 15)

    def test_02_companies_dedup_and_scores(self):
        resp = self.client.get(f"/api/runs/{self.run_id}/companies", params={"limit": 100})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 19)
        names = [x["display_name"] for x in data["items"]]
        self.assertIn("Jatinox", names)
        self.assertIn("Jacinox DF", names)
        self.assertNotIn("Jatinox - Chapas de Aço Inox", names)
        self.assertNotIn("Jatinox - Barras de Aço Inox", names)

        by_name = {x["display_name"]: x for x in data["items"]}
        self.assertNotEqual(by_name["Jatinox"]["id"], by_name["Jacinox DF"]["id"])
        self.assertEqual(by_name["Jatinox"]["state"], "SP")
        self.assertEqual(by_name["Jacinox DF"]["state"], "DF")
        self.assertTrue(by_name["Tech-Inox"]["emails"])
        self.assertEqual(by_name["Tech-Inox"]["emails"][0]["value"], "atendimento@techmetais.com.br")

        tiers = {x["score"]["tier"] for x in data["items"]}
        self.assertTrue(tiers <= {"A", "B", "C", "D"})
        self.assertGreaterEqual(sum(1 for x in data["items"] if x["score"]["tier"] in {"A", "B"}), 8)

    def test_03_company_evidence_and_review(self):
        data = self.client.get(f"/api/runs/{self.run_id}/companies", params={"q": "Tech-Inox"}).json()
        company = data["items"][0]
        detail = self.client.get(f"/api/companies/{company['id']}").json()
        self.assertTrue(detail["sources"])
        email_source = [s for s in detail["sources"] if s["field"] == "email"]
        self.assertTrue(email_source)
        self.assertTrue(email_source[0]["source_url"])

        resp = self.client.post(
            f"/api/companies/{company['id']}/review",
            json={"status": "approved", "note": "verified in test"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["review_status"], "approved")

    def test_04_history_dedup(self):
        resp = self.client.post(
            "/api/runs",
            json={"product": "Stainless steel flat products and profiles", "country": "Brazil"},
        )
        run2 = resp.json()["run_id"]
        out = self.client.get(f"/api/runs/{run2}/companies", params={"limit": 100}).json()
        self.assertEqual(out["total"], 19)

    def test_05_export(self):
        resp = self.client.get("/api/export", params={"run_id": self.run_id})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp.headers["content-type"])
        text = resp.content.decode("utf-8-sig")
        lines = [x for x in text.splitlines() if x.strip()]
        self.assertGreaterEqual(len(lines), 16)
        self.assertIn("Jatinox", text)
        self.assertIn("atendimento@techmetais.com.br", text)


if __name__ == "__main__":
    unittest.main()
