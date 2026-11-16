import unittest
from datetime import date
from demo_movement_replay import replay_movements
from demo_movement_correction import plan_movement_correction

class V69DeleteOnlyExtension(unittest.TestCase):
    def test_jaja_delete_extension_keeps_initial_vessel_state(self):
        entry=date(2026,11,14)
        original=replay_movements(entry,[{"kind":"ampliacion","event_date":entry}])
        self.assertEqual(original["stage"],"ampliacion")
        rows=[(1,"ampliacion",entry,"ingreso",date(2027,2,12),"ampliacion",date(2027,11,14))]
        plan=plan_movement_correction(entry,rows,1,"delete",current_state=(original["stage"],original["due_date"],original["movement_date"]))
        self.assertEqual(plan["rows"],[])
        self.assertEqual(plan["after"]["stage"],"ingreso")
        self.assertEqual(plan["after"]["due_date"],date(2027,2,12))
        self.assertEqual(plan["after"]["movement_date"],entry)
        self.assertEqual(plan["after"]["history"],[])

if __name__=="__main__":
    unittest.main()
