"""V62 PostgreSQL integration: isolated fictitious records, never operational data."""
import os
import unittest
import uuid
from datetime import date, timedelta

from flask import Flask
from demo_vessels import init_demo_vessels, dbconnect


@unittest.skipUnless(os.getenv("SERVAMAR_TEST_POSTGRES_URL"),
                     "Requires dedicated SERVAMAR_TEST_POSTGRES_URL")
class DemoMovementDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The module reads URL at import time; explicitly set the test connection.
        import demo_vessels
        cls.original_url = demo_vessels.URL
        demo_vessels.URL = os.environ["SERVAMAR_TEST_POSTGRES_URL"]
        cls.original_mode = os.environ.get("SERVAMAR_DEMO_MODE")
        os.environ["SERVAMAR_DEMO_MODE"] = "YES"
        cls.app = Flask(__name__)
        cls.app.testing = True
        init_demo_vessels(cls.app)

    @classmethod
    def tearDownClass(cls):
        import demo_vessels
        demo_vessels.URL = cls.original_url
        if cls.original_mode is None:
            os.environ.pop("SERVAMAR_DEMO_MODE", None)
        else:
            os.environ["SERVAMAR_DEMO_MODE"] = cls.original_mode

    def setUp(self):
        self.client = self.app.test_client()
        self.registration = "DEMO-" + uuid.uuid4().hex[:12].upper()
        response = self.client.post("/api/demo/vessels", json={
            "registration": self.registration, "vessel_name": "Vessel Test",
            "captain": "Captain Test", "stage": "ingreso",
            "entry_date": "2026-11-04", "movement_date": "2026-11-04",
            "notes": "V62 integration"
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        self.vessel_id = response.get_json()["id"]

    def tearDown(self):
        with dbconnect() as db:
            db.execute("DELETE FROM servamar_demo_movements WHERE vessel_id=%s", (self.vessel_id,))
            db.execute("DELETE FROM servamar_demo_movement_corrections WHERE vessel_id=%s", (self.vessel_id,))
            db.execute("DELETE FROM servamar_demo_vessel_audit WHERE vessel_id=%s", (self.vessel_id,))
            db.execute("DELETE FROM servamar_demo_vessels WHERE id=%s", (self.vessel_id,))

    def vessel(self):
        with dbconnect() as db:
            return db.execute("SELECT stage,due_date,version FROM servamar_demo_vessels WHERE id=%s",
                              (self.vessel_id,)).fetchone()

    def move(self, kind, event_date):
        version = self.vessel()[2]
        response = self.client.post(f"/api/demo/vessels/{self.vessel_id}/movement",
                                    json={"kind": kind, "event_date": event_date, "version": version})
        self.assertEqual(response.status_code, 200, response.get_json())

    def movements(self):
        response = self.client.get(f"/api/demo/vessels/{self.vessel_id}/movements")
        self.assertEqual(response.status_code, 200)
        return response.get_json()["items"]

    def test_edit_recalculates_and_audits(self):
        self.move("ampliacion", "2026-12-01")
        self.move("salida", "2027-01-01")
        self.move("retorno", "2027-01-20")
        movement_id = next(x["id"] for x in self.movements() if x["kind"] == "salida")
        response = self.client.patch(
            f"/api/demo/vessels/{self.vessel_id}/movements/{movement_id}",
            json={"kind": "salida", "event_date": "2027-01-05", "version": self.vessel()[2]})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.vessel()[1], date(2027, 11, 19))
        self.assertEqual(next(x for x in self.movements() if x["kind"] == "salida")["event_date"],
                         "2027-01-05")
        with dbconnect() as db:
            audit = db.execute("""SELECT action FROM servamar_demo_movement_corrections
                                  WHERE vessel_id=%s ORDER BY id DESC LIMIT 1""",
                               (self.vessel_id,)).fetchone()
        self.assertEqual(audit[0], "edit")

    def test_delete_return_reopens_exit(self):
        self.move("salida", "2026-12-01")
        self.move("retorno", "2026-12-10")
        movement_id = next(x["id"] for x in self.movements() if x["kind"] == "retorno")
        response = self.client.delete(
            f"/api/demo/vessels/{self.vessel_id}/movements/{movement_id}",
            json={"version": self.vessel()[2]})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.vessel()[0], "salida")
        self.assertEqual(self.vessel()[1], date(2027, 3, 1))
        self.assertEqual(len(self.movements()), 1)

    def test_invalid_delete_rolls_back_without_audit(self):
        self.move("salida", "2026-12-01")
        self.move("retorno", "2026-12-10")
        original = self.vessel()
        movement_id = next(x["id"] for x in self.movements() if x["kind"] == "salida")
        response = self.client.delete(
            f"/api/demo/vessels/{self.vessel_id}/movements/{movement_id}",
            json={"version": original[2]})
        self.assertEqual(response.status_code, 409, response.get_json())
        self.assertEqual(self.vessel(), original)
        self.assertEqual(len(self.movements()), 2)
        with dbconnect() as db:
            count = db.execute("""SELECT COUNT(*) FROM servamar_demo_movement_corrections
                                  WHERE vessel_id=%s""", (self.vessel_id,)).fetchone()[0]
        self.assertEqual(count, 0)

    def test_stale_version_does_not_modify_history(self):
        self.move("salida", "2026-12-01")
        movement_id = self.movements()[0]["id"]
        response = self.client.patch(
            f"/api/demo/vessels/{self.vessel_id}/movements/{movement_id}",
            json={"version": 1, "kind": "salida", "event_date": "2026-12-02"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.movements()[0]["event_date"], "2026-12-01")


if __name__ == "__main__":
    unittest.main()
