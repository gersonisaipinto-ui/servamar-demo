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

    def test_ajuste_ultimo_dia_del_mes(self):
        self.assertEqual(add_months(date(2024,2,29),12),date(2025,2,28))

if __name__=="__main__":
    unittest.main()
