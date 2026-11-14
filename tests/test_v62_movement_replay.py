import unittest
from datetime import date, timedelta
from demo_movement_replay import replay_movements


class MovementReplayTests(unittest.TestCase):
    def setUp(self):
        self.entry = date(2026, 11, 4)

    def test_initial_entry(self):
        result = replay_movements(self.entry, [])
        self.assertEqual(result["stage"], "ingreso")
        self.assertEqual(result["due_date"], self.entry + timedelta(days=90))

    def test_extension_is_twelve_calendar_months_from_entry(self):
        result = replay_movements(self.entry, [
            {"kind": "ampliacion", "event_date": date(2026, 12, 1)}
        ])
        self.assertEqual(result["due_date"], date(2027, 11, 4))

    def test_temporary_exit_and_return_adds_days_away(self):
        result = replay_movements(self.entry, [
            {"kind": "ampliacion", "event_date": date(2026, 12, 1)},
            {"kind": "salida", "event_date": date(2027, 1, 1)},
            {"kind": "retorno", "event_date": date(2027, 1, 20)},
        ])
        self.assertEqual(result["stage"], "ampliacion")
        self.assertEqual(result["due_date"], date(2027, 11, 23))
        self.assertEqual(len(result["history"]), 3)

    def test_ninety_days_away_closes_permit(self):
        result = replay_movements(self.entry, [
            {"kind": "salida", "event_date": date(2026, 12, 1)},
            {"kind": "retorno", "event_date": date(2027, 3, 1)},
        ])
        self.assertEqual(result["stage"], "cierre")
        self.assertIsNone(result["due_date"])

    def test_out_of_order_is_rejected(self):
        with self.assertRaises(ValueError):
            replay_movements(self.entry, [
                {"kind": "salida", "event_date": date(2027, 1, 1)},
                {"kind": "retorno", "event_date": date(2026, 12, 31)},
            ])

    def test_illegal_stage_transition_is_rejected(self):
        with self.assertRaises(ValueError):
            replay_movements(self.entry, [
                {"kind": "deposito", "event_date": date(2026, 12, 1)},
                {"kind": "salida", "event_date": date(2026, 12, 2)},
            ])

    def test_replay_after_corrected_exit_date(self):
        events = [
            {"kind": "salida", "event_date": date(2026, 12, 1)},
            {"kind": "retorno", "event_date": date(2026, 12, 10)},
        ]
        original = replay_movements(self.entry, events)
        events[0] = {"kind": "salida", "event_date": date(2026, 12, 3)}
        corrected = replay_movements(self.entry, events)
        self.assertEqual((original["due_date"] - corrected["due_date"]).days, 2)


if __name__ == "__main__":
    unittest.main()
