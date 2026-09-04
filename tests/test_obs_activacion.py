"""Pruebas de la activación del servidor websocket de OBS."""

import subprocess
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import obs_activacion


class TestActivacionObs(unittest.TestCase):

    def test_ajustes_activos_no_se_tocan(self):
        accion, frase = obs_activacion.decidir_activacion(
            True, SimpleNamespace(activo=True))

        self.assertEqual(accion, obs_activacion.NO_TOCAR)
        self.assertIn("ya está activado", frase)

    def test_obs_abierto_pide_cerrarlo_sin_tocar_nada(self):
        accion, frase = obs_activacion.decidir_activacion(
            True, SimpleNamespace(activo=False))

        self.assertEqual(accion, obs_activacion.NO_TOCAR)
        self.assertIn("Ciérralo", frase)

    def test_obs_cerrado_con_ajustes_apagados_se_puede_activar(self):
        accion, frase = obs_activacion.decidir_activacion(
            False, SimpleNamespace(activo=False))

        self.assertEqual(accion, obs_activacion.ACTIVAR)
        self.assertIn("Se puede activar", frase)

    def test_ajustes_activados_solo_cambian_el_servidor(self):
        ajustes = {
            "alerts_enabled": False,
            "auth_required": True,
            "first_load": False,
            "server_enabled": False,
            "server_password": "secreto",
            "server_port": 4455,
        }

        resultado = obs_activacion.ajustes_con_servidor_activado(ajustes)

        self.assertTrue(resultado["server_enabled"])
        for clave in ("alerts_enabled", "auth_required", "first_load",
                      "server_password", "server_port"):
            self.assertEqual(resultado[clave], ajustes[clave])

    def test_deteccion_de_obs_oculta_la_consola(self):
        resultado = SimpleNamespace(stdout="obs64.exe                 1234")
        with mock.patch.object(obs_activacion.subprocess, "run",
                               return_value=resultado) as ejecutar:
            self.assertTrue(obs_activacion.obs_esta_en_ejecucion())

        self.assertEqual(
            ejecutar.call_args.kwargs["creationflags"],
            getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def test_activar_servidor_lo_deja_activo_en_el_archivo(self):
        ajustes = self._ajustes_de_prueba()
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "global.ini"
            ruta.write_text(json.dumps(ajustes), encoding="utf-8")

            obs_activacion.activar_servidor(ruta)

            self.assertTrue(json.loads(ruta.read_text(encoding="utf-8"))["server_enabled"])

    def test_activar_servidor_conserva_las_otras_claves_del_archivo(self):
        ajustes = self._ajustes_de_prueba()
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "global.ini"
            ruta.write_text(json.dumps(ajustes), encoding="utf-8")

            obs_activacion.activar_servidor(ruta)

            resultado = json.loads(ruta.read_text(encoding="utf-8"))
        for clave in ("alerts_enabled", "auth_required", "first_load",
                      "server_password", "server_port"):
            self.assertEqual(resultado[clave], ajustes[clave])

    def test_activar_servidor_no_deja_temporales(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "config.json"
            ruta.write_text(json.dumps(self._ajustes_de_prueba()), encoding="utf-8")

            obs_activacion.activar_servidor(ruta)

            self.assertEqual(list(Path(directorio).glob("*.tmp")), [])

    def test_un_fallo_al_escribir_conserva_el_archivo_de_obs(self):
        # Es el config.json del propio OBS: si se trunca, OBS pierde su contraseña.
        ajustes = self._ajustes_de_prueba()
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "config.json"
            ruta.write_text(json.dumps(ajustes), encoding="utf-8")
            with mock.patch.object(obs_activacion.archivos, "escribir_json_atomico",
                                   side_effect=OSError("disco lleno")):
                frase = obs_activacion.activar_servidor(ruta)
            resultado = json.loads(ruta.read_text(encoding="utf-8"))

        self.assertIn("No se pudo activar el servidor websocket de OBS", frase)
        self.assertEqual(resultado, ajustes)

    def test_activar_servidor_informa_el_error_si_no_existe_el_archivo(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = Path(directorio) / "inexistente.json"

            frase = obs_activacion.activar_servidor(ruta)

        self.assertIn("No se pudo activar el servidor websocket de OBS", frase)

    @staticmethod
    def _ajustes_de_prueba():
        return {
            "alerts_enabled": False,
            "auth_required": True,
            "first_load": False,
            "server_enabled": False,
            "server_password": "secreto",
            "server_port": 4455,
        }


if __name__ == "__main__":
    unittest.main()
