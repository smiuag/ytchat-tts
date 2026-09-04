"""Tests del parseo de importes de Super Chat (montos.parsear_monto)."""

import unittest

from montos import parsear_monto


class TestParsearMonto(unittest.TestCase):

    def test_vacio_o_none(self):
        self.assertIsNone(parsear_monto(""))
        self.assertIsNone(parsear_monto(None))

    def test_sin_numero(self):
        self.assertIsNone(parsear_monto("gracias"))

    def test_anglosajon_simple(self):
        self.assertEqual(parsear_monto("$10.00"), ("$", 10.0))

    def test_euro_prefijo_punto_decimal(self):
        self.assertEqual(parsear_monto("€15.50"), ("€", 15.5))

    def test_euro_sufijo_coma_decimal(self):
        self.assertEqual(parsear_monto("5,00 €"), ("€", 5.0))

    def test_europeo_millar_y_decimal(self):
        # 1.234,56 -> 1234.56
        self.assertEqual(parsear_monto("1.234,56 €"), ("€", 1234.56))

    def test_anglosajon_millar_y_decimal(self):
        # 1,234.56 -> 1234.56
        self.assertEqual(parsear_monto("$1,234.56"), ("$", 1234.56))

    def test_sin_decimales_grandes(self):
        self.assertEqual(parsear_monto("¥500"), ("¥", 500.0))

    def test_codigo_divisa_multiletra(self):
        divisa, valor = parsear_monto("PYG 50000")
        self.assertEqual(divisa, "PYG")
        self.assertEqual(valor, 50000.0)

    def test_divisa_desconocida(self):
        # Solo número, sin símbolo reconocible.
        self.assertEqual(parsear_monto("42.00"), ("?", 42.0))

    def test_us_dollar_prefijo_compuesto(self):
        divisa, valor = parsear_monto("US$ 3.50")
        self.assertEqual(divisa, "US$")
        self.assertEqual(valor, 3.5)

    def test_millar_con_coma_sin_decimales(self):
        # Divisas sin decimales: YouTube separa los millares con coma.
        self.assertEqual(parsear_monto("¥1,000"), ("¥", 1000.0))
        self.assertEqual(parsear_monto("₩10,000"), ("₩", 10000.0))
        self.assertEqual(parsear_monto("CA$1,000"), ("CA$", 1000.0))
        self.assertEqual(parsear_monto("¥1,234,567"), ("¥", 1234567.0))

    def test_millar_con_punto_sin_decimales(self):
        self.assertEqual(parsear_monto("Rp 15.000"), ("Rp", 15000.0))
        self.assertEqual(parsear_monto("1.000 €"), ("€", 1000.0))

    def test_una_o_dos_cifras_tras_el_separador_es_decimal(self):
        self.assertEqual(parsear_monto("1,5 €"), ("€", 1.5))
        self.assertEqual(parsear_monto("$1.50"), ("$", 1.5))


if __name__ == "__main__":
    unittest.main()
