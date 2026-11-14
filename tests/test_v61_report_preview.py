"""Unit tests for the V61 report-preview filter (no database connection needed)."""
import unittest
from datetime import date
from unittest.mock import patch
from demo_vessels import demo_export_filter

class PreviewFilterTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            dict(registration="DEMO-001", entry_date="2026-11-01", due_date="2026-11-29"),
            dict(registration="DEMO-002", entry_date="2026-11-02", due_date="2026-12-14"),
        ]

    def test_all_history_includes_both(self):
        self.assertEqual(len(demo_export_filter(self.rows, "all", "vencimiento")), 2)

    def test_custom_range_includes_only_november(self):
        result = demo_export_filter(self.rows, "custom", "vencimiento", "2026-11-01", "2026-11-30")
        self.assertEqual([r["registration"] for r in result], ["DEMO-001"])

    def test_entry_date_filter(self):
        result = demo_export_filter(self.rows, "custom", "ingreso", "2026-11-01", "2026-11-30")
        self.assertEqual(len(result), 2)

    def test_empty_period(self):
        self.assertEqual(demo_export_filter(self.rows, "custom", "vencimiento", "2025-01-01", "2025-01-31"), [])

    def test_reversed_dates_rejected(self):
        with self.assertRaises(ValueError):
            demo_export_filter(self.rows, "custom", "vencimiento", "2026-12-31", "2026-01-01")

if __name__ == "__main__":
    unittest.main()
