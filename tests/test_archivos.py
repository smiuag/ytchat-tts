"""Tests de la escritura atómica y la lectura tolerante de JSON (archivos.py)."""

import tempfile
import unittest
from pathlib import Path

import archivos


class TestArchivos(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ruta = Path(self._tmp.name) / "datos.json"

    def _temporales(self):
        return list(self.ruta.parent.glob("*.tmp"))

    def test_ida_y_vuelta_sin_dejar_temporal(self):
        datos = {"clave": 1, "texto": "canción", "lista": [1, 2]}
        archivos.escribir_json_atomico(self.ruta, datos)
        self.assertEqual(archivos.leer_json(self.ruta, None), datos)
        self.assertEqual(self._temporales(), [])
        # ensure_ascii=False por defecto: el archivo es legible a mano.
        self.assertIn("canción", self.ruta.read_text(encoding="utf-8"))

    def test_un_fallo_conserva_el_archivo_anterior(self):
        archivos.escribir_json_atomico(self.ruta, {"a": 1})
        with self.assertRaises(TypeError):
            archivos.escribir_json_atomico(self.ruta, {"a": object()})
        self.assertEqual(archivos.leer_json(self.ruta, None), {"a": 1})
        self.assertEqual(self._temporales(), [])

    def test_leer_inexistente_devuelve_el_predeterminado(self):
        predeterminado = []
        self.assertIs(archivos.leer_json(self.ruta, predeterminado), predeterminado)

    def test_leer_corrupto_devuelve_el_predeterminado(self):
        self.ruta.write_text("{ roto", encoding="utf-8")
        self.assertEqual(archivos.leer_json(self.ruta, {"x": 0}), {"x": 0})

    def test_acepta_rutas_como_cadena(self):
        archivos.escribir_json_atomico(str(self.ruta), [1])
        self.assertEqual(archivos.leer_json(str(self.ruta), None), [1])


if __name__ == "__main__":
    unittest.main()
