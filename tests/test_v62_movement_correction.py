import unittest
from datetime import date, timedelta
from demo_movement_replay import replay_movements
from demo_movement_correction import plan_movement_correction


class CorrectionPlanTests(unittest.TestCase):
    def setUp(self):
        self.entry = date(2026, 11, 4)
        self.events = [
            {"kind": "ampliacion", "event_date": date(2026, 12, 1)},
            {"kind": "salida", "event_date": date(2027, 1, 1)},
            {"kind": "retorno", "event_date": date(2027, 1, 20)},
        ]
        self.original = replay_movements(self.entry, self.events)
        self.rows = [
            (i, item["kind"], item["event_date"], item["stage_before"],
             item["due_before"], item["stage_after"], item["due_after"])
            for i, item in enumerate(self.original["history"], 1)
        ]
        self.state = (self.original["stage"], self.original["due_date"],
                      self.original["movement_date"])

    def test_edit_exit_date_recalculates_later_return(self):
        result = plan_movement_correction(self.entry, self.rows, 2, "edit",
                                          "salida", date(2027, 1, 5), self.state)
        self.assertEqual(result["after"]["stage"], "ampliacion")
        self.assertEqual(result["after"]["due_date"], date(2027, 11, 19))
        self.assertEqual([r[0] for r in result["rows"]], [1, 2, 3])

    def test_delete_last_return_reopens_exit(self):
        result = plan_movement_correction(self.entry, self.rows, 3, "delete",
                                          current_state=self.state)
        self.assertEqual(result["after"]["stage"], "salida")
        self.assertEqual(result["after"]["due_date"], date(2027, 4, 1))
        self.assertEqual([r[0] for r in result["rows"]], [1, 2])

    def test_delete_exit_with_return_is_rejected(self):
        with self.assertRaises(ValueError):
            plan_movement_correction(self.entry, self.rows, 2, "delete",
                                     current_state=self.state)

    def test_stale_vessel_state_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "estado"):
            plan_movement_correction(self.entry, self.rows, 2, "delete",
                                     current_state=("ingreso", None, self.entry))

    def test_corrupt_stored_snapshot_is_rejected(self):
        rows = list(self.rows)
        broken = list(rows[0])
        broken[6] = self.entry + timedelta(days=1)
        rows[0] = tuple(broken)
        with self.assertRaisesRegex(ValueError, "Historial almacenado"):
            plan_movement_correction(self.entry, rows, 3, "delete",
                                     current_state=self.state)

    def test_out_of_order_edit_is_rejected(self):
        with self.assertRaises(ValueError):
            plan_movement_correction(self.entry, self.rows, 2, "edit", "salida",
                                     date(2026, 11, 5), self.state)

    def test_unknown_movement_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no encontrado"):
            plan_movement_correction(self.entry, self.rows, 99, "delete",
                                     current_state=self.state)


if __name__ == "__main__":
    unittest.main()
