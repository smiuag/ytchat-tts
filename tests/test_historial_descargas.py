"""Pruebas de la lógica pura del historial de descargas."""

import tempfile
import unittest
from pathlib import Path

import historial_descargas as historial


class TestHistorialDescargas(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ruta = Path(self._tmp.name) / "historial_descargas.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_cargar_inexistente_devuelve_lista_vacia(self):
        self.assertEqual(historial.cargar(self.ruta), [])

    def test_cargar_corrupto_devuelve_lista_vacia(self):
        self.ruta.write_text("no es json", encoding="utf-8")
        self.assertEqual(historial.cargar(self.ruta), [])

    def test_agregar_pone_lo_nuevo_primero_sin_mutar(self):
        anterior = [{"nombre": "anterior"}]
        resultado = historial.agregar(anterior, {"nombre": "nuevo"})
        self.assertEqual([e["nombre"] for e in resultado], ["nuevo", "anterior"])
        self.assertEqual(anterior, [{"nombre": "anterior"}])

    def test_agregar_respeta_el_tope(self):
        entradas = [{"nombre": "vieja"}, {"nombre": "menos vieja"}]
        resultado = historial.agregar(entradas, {"nombre": "nueva"}, tope=2)
        self.assertEqual([e["nombre"] for e in resultado], ["nueva", "vieja"])

    def test_formatear_devuelve_nombre_fecha_y_estado(self):
        entrada = {"nombre": "video.mp4", "fecha": "2026-08-28T12:00:00",
                   "estado": "completado"}
        self.assertEqual(historial.formatear(entrada),
                         ("video.mp4", "2026-08-28T12:00:00", "completado"))

    def test_guardar_y_cargar_conservan_las_entradas(self):
        entradas = [{"nombre": "video.mp4", "url": "https://youtu.be/abc",
                     "estado": "completado", "carpeta": "C:/Descargas"}]
        historial.guardar(self.ruta, entradas)
        self.assertEqual(historial.cargar(self.ruta), entradas)
        self.assertEqual(list(self.ruta.parent.glob("*.tmp")), [])

    def test_cargar_descarta_entradas_que_no_son_dict(self):
        self.ruta.write_text('[{"nombre": "a"}, "basura"]', encoding="utf-8")
        self.assertEqual(historial.cargar(self.ruta), [{"nombre": "a"}])


if __name__ == "__main__":
    unittest.main()
