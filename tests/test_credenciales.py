"""Tests del almacén de credenciales (credenciales.py)."""

import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import config
import credenciales


class TestCredenciales(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # credenciales.ruta() usa config.app_dir()
        self._patch = mock.patch.object(config, "app_dir",
                                        return_value=Path(self._tmp.name))
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_cargar_sin_archivo_devuelve_defaults(self):
        d = credenciales.cargar()
        self.assertEqual(d["api_key"], "")
        self.assertIsNone(d["token"])

    def test_guardar_y_cargar(self):
        self.assertTrue(credenciales.guardar_campo("api_key", "AIzaTEST"))
        self.assertEqual(credenciales.cargar()["api_key"], "AIzaTEST")

    def test_guardar_campo_desconocido_falla(self):
        self.assertFalse(credenciales.guardar_campo("inexistente", "x"))

    def test_estado_lectura(self):
        self.assertFalse(credenciales.hay_lectura())
        credenciales.guardar_campo("api_key", "AIzaTEST")
        self.assertTrue(credenciales.hay_lectura())

    def test_estado_oauth_configurado(self):
        self.assertFalse(credenciales.hay_oauth_configurado())
        credenciales.guardar_campo("oauth_client_id", "id")
        credenciales.guardar_campo("oauth_client_secret", "secret")
        self.assertTrue(credenciales.hay_oauth_configurado())

    def test_sesion_y_cierre(self):
        self.assertFalse(credenciales.hay_sesion())
        credenciales.guardar_campo("token", '{"refresh_token": "x"}')
        self.assertTrue(credenciales.hay_sesion())
        credenciales.cerrar_sesion()
        self.assertFalse(credenciales.hay_sesion())
        # cerrar_sesion no borra la api_key
        credenciales.guardar_campo("api_key", "AIzaTEST")
        credenciales.guardar_campo("token", '{"refresh_token": "x"}')
        credenciales.cerrar_sesion()
        self.assertEqual(credenciales.cargar()["api_key"], "AIzaTEST")

    def test_archivo_corrupto_no_revienta(self):
        (Path(self._tmp.name) / "credenciales.json").write_text("{roto", encoding="utf-8")
        d = credenciales.cargar()
        self.assertEqual(d["api_key"], "")

    def test_guardar_no_deja_temporales(self):
        credenciales.guardar_campo("api_key", "AIzaTEST")
        self.assertEqual(list(Path(self._tmp.name).glob("*.tmp")), [])

    def test_guardar_campo_desde_varios_hilos_no_pisa_los_otros_campos(self):
        # guardar_campo es leer-modificar-escribir: sin candado, dos hilos que
        # escriben campos distintos a la vez se pisan el uno al otro.
        def escribir(clave, valor):
            for _ in range(15):
                credenciales.guardar_campo(clave, valor)
        hilos = [threading.Thread(target=escribir, args=("api_key", "K")),
                 threading.Thread(target=escribir, args=("oauth_client_id", "ID"))]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        d = credenciales.cargar()
        self.assertEqual((d["api_key"], d["oauth_client_id"]), ("K", "ID"))


if __name__ == "__main__":
    unittest.main()
