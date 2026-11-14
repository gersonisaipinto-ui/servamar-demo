"""Offline checks for PostgreSQL DEMO export filters and backup content."""
import io
import json
import unittest
import zipfile
from datetime import date
from unittest.mock import patch
from flask import Flask

import demo_vessels


class DemoExportTests(unittest.TestCase):
    def setUp(self):
        self.rows=[
            {"registration":"DEMO-001","vessel_name":"FICTICIA UNO","captain":"PERSONA DE PRUEBA",
             "entry_date":"2026-11-01","movement_date":"2026-11-01",
             "due_date":"2027-01-30","stage":"ingreso","notes":""},
            {"registration":"DEMO-002","vessel_name":"FICTICIA DOS","captain":"PERSONA DE PRUEBA",
             "entry_date":"2026-11-02","movement_date":"2026-11-02",
             "due_date":None,"stage":"cierre","notes":""},
        ]

    def test_export_all_keeps_closed_records(self):
        rows=demo_vessels.demo_export_filter(self.rows,"all","vencimiento")
        result=demo_vessels.demo_export_records(rows)
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]["expiry"],"30/01/2027")
        self.assertEqual(result[1]["expiry"],"")
        self.assertEqual(result[1]["status"],"Permiso cerrado")
        self.assertEqual(result[0]["email"],"")

    def test_custom_period_filters_using_dd_mm_yyyy_only_on_display(self):
        result=demo_vessels.demo_export_filter(
            self.rows,"custom","ingreso","2026-11-01","2026-11-01")
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["registration"],"DEMO-001")

    def test_custom_invalid_range(self):
        with self.assertRaises(ValueError):
            demo_vessels.demo_export_filter(
                self.rows,"custom","vencimiento","2027-03-01","2027-01-01")

    def test_formulas_are_not_interpreted_as_formula_cells(self):
        data=[{**self.rows[0],"vessel_name":"=HYPERLINK(\"example\",\"x\")"}]
        rows=demo_vessels.demo_export_records(data)
        self.assertTrue(rows[0]["name"].startswith("'="))

    def test_portable_backup_zip_has_manifest_no_secrets(self):
        fixture={"format":"SERVAMAR-DEMO-BACKUP-V1",
                 "created_at":"2026-11-14T08:00:00-06:00",
                 "scope":"Solo ficticios","vessels":self.rows,
                 "movements":[],"audit":[]}
        flask=Flask(__name__)
        flask.register_blueprint(demo_vessels.bp)
        with patch.object(demo_vessels,"demo_backup_payload",return_value=fixture):
            with flask.test_client() as client:
                response=client.get("/api/demo/backup")
        self.assertEqual(response.status_code,200)
        archive=zipfile.ZipFile(io.BytesIO(response.data))
        self.assertEqual(set(archive.namelist()),{"demo_vessels.json","manifest.json"})
        saved=json.loads(archive.read("demo_vessels.json"))
        manifest=json.loads(archive.read("manifest.json"))
        self.assertEqual(saved["vessels"][0]["registration"],"DEMO-001")
        self.assertEqual(manifest["counts"]["vessels"],2)
        self.assertNotIn("vapid",response.data.decode("latin1").lower())


if __name__=="__main__":
    unittest.main()
