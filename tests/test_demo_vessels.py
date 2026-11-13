"""Validación aislada del nuevo laboratorio, sin conectar PostgreSQL."""
import unittest
from datetime import date
from demo_vessels import validate, add_months

class DemoVesselsRulesTests(unittest.TestCase):
    def sample(self,**updates):
        item={"registration":"DEMO-001","vessel_name":"Barco ficticio",
              "captain":"Capitán ficticio","stage":"ingreso",
              "entry_date":"2026-11-13","movement_date":"2026-11-13","notes":""}
        item.update(updates)
        return item

    def test_ingreso_90_dias(self):
        x=validate(self.sample())
        self.assertEqual(x[6],date(2027,2,11))

    def test_ampliacion_12_meses_desde_ingreso(self):
        x=validate(self.sample(stage="ampliacion", movement_date="2026-12-01"))
        self.assertEqual(x[6],date(2027,11,13))

    def test_deposito_12_meses_desde_movimiento(self):
        x=validate(self.sample(stage="deposito",movement_date="2026-12-02"))
        self.assertEqual(x[6],date(2027,12,2))

    def test_salida_90_dias_desde_movimiento(self):
        x=validate(self.sample(stage="salida",movement_date="2026-12-01"))
        self.assertEqual(x[6],date(2027,3,1))

    def test_cierre_sin_vencimiento(self):
        self.assertIsNone(validate(self.sample(stage="cierre"))[6])

    def test_rechaza_registro_no_ficticio(self):
        with self.assertRaisesRegex(ValueError,"DEMO-"):
            validate(self.sample(registration="ST-1234"))

    def test_rechaza_movimiento_anterior(self):
        with self.assertRaises(ValueError):
            validate(self.sample(movement_date="2026-10-01"))

    def test_retorno_oportuno_suma_dias_fuera(self):
        from demo_vessels import movement_transition
        entry=date(2026,11,13)
        initial=entry+__import__('datetime').timedelta(days=90)
        exit_date=date(2026,12,1)
        departure_stage,return_deadline=movement_transition(
            'ingreso',initial,entry,exit_date,'salida')
        self.assertEqual(departure_stage,'salida')
        self.assertEqual(return_deadline,date(2027,3,1))
        resumed_stage,new_due=movement_transition(
            'salida',return_deadline,entry,date(2026,12,16),'retorno',
            {'event_date':exit_date,'stage_before':'ingreso','due_before':initial})
        self.assertEqual(resumed_stage,'ingreso')
        self.assertEqual(new_due,initial+__import__('datetime').timedelta(days=15))

    def test_retorno_tardio_cierra_permiso(self):
        from demo_vessels import movement_transition
        entry=date(2026,11,13)
        exit_date=date(2026,12,1)
        stage,due=movement_transition(
            'salida',exit_date+__import__('datetime').timedelta(days=90),
            entry,exit_date+__import__('datetime').timedelta(days=90),'retorno',
            {'event_date':exit_date,'stage_before':'ingreso',
             'due_before':entry+__import__('datetime').timedelta(days=90)})
        self.assertEqual(stage,'cierre')
        self.assertIsNone(due)

    def test_deposito_no_permite_salida_temporal(self):
        from demo_vessels import movement_transition
        with self.assertRaisesRegex(ValueError,'salida temporal'):
            movement_transition('deposito',date(2027,11,13),
                                date(2026,11,13),date(2026,12,1),'salida')

    def test_no_hay_segunda_salida_sin_retorno(self):
        from demo_vessels import movement_transition
        with self.assertRaises(ValueError):
            movement_transition('salida',date(2027,3,1),
                                date(2026,11,13),date(2026,12,5),'salida')

    def test_cierre_no_admite_movimientos(self):
        from demo_vessels import movement_transition
        with self.assertRaises(ValueError):
            movement_transition('cierre',None,date(2026,11,13),
                                date(2026,12,5),'ampliacion')

    def test_ajuste_ultimo_dia_del_mes(self):
        self.assertEqual(add_months(date(2024,2,29),12),date(2025,2,28))

if __name__=="__main__":
    unittest.main()
