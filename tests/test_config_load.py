"""Tests de carga de config.ini (config.cargar_configuracion).

Se redirige app_dir() a un directorio temporal para no tocar el config.ini
real del proyecto.
"""

import tempfile
import unittest
import logging
from pathlib import Path
from unittest import mock

import config


class TestCargarConfiguracion(unittest.TestCase):

    def _cargar_en(self, contenido: str) -> dict:
        tmp = Path(self._tmp.name)
        (tmp / "config.ini").write_text(contenido, encoding="utf-8")
        with mock.patch.object(config, "app_dir", return_value=tmp):
            return config.cargar_configuracion()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._root = logging.getLogger()
        self._handlers = self._root.handlers[:]
        self._nivel_raiz = self._root.level
        self._logger_websockets = logging.getLogger("websockets.client")
        self._nivel_websockets = self._logger_websockets.level
        self.addCleanup(self._restaurar_logging)

    def _restaurar_logging(self):
        self._root.handlers[:] = self._handlers
        self._root.setLevel(self._nivel_raiz)
        self._logger_websockets.setLevel(self._nivel_websockets)

    def test_librerias_silenciadas_incluye_dependencias_nuevas(self):
        silenciadas = config.librerias_silenciadas()
        self.assertIn("websockets", silenciadas)
        self.assertIn("googleapiclient", silenciadas)

    def test_configurar_logging_bloquea_debug_de_websockets(self):
        with mock.patch.object(config, "app_dir", return_value=Path(self._tmp.name)), \
             mock.patch.object(config, "RotatingFileHandler"):
            config.configurar_logging()
        self.assertFalse(
            logging.getLogger("websockets.client").isEnabledFor(logging.DEBUG))

    def test_configurar_logging_conserva_warning_en_ytchat_log(self):
        """Si este nivel sube, el cierre por tope deja de llegar al archivo y se
        pierde la única pista disponible sobre la corrupción de heap al cerrar."""
        with mock.patch.object(config, "app_dir", return_value=Path(self._tmp.name)):
            config.configurar_logging()
        manejador = next(manejador for manejador in self._root.handlers
                         if getattr(manejador, "baseFilename", "").endswith("ytchat.log"))
        self.addCleanup(manejador.close)
        self.assertEqual(manejador.level, logging.WARNING)

    def test_configurar_logging_es_idempotente(self):
        with mock.patch.object(config, "app_dir", return_value=Path(self._tmp.name)), \
             mock.patch.object(config, "RotatingFileHandler"):
            config.configurar_logging()
            cuantos = len(self._root.handlers)
            config.configurar_logging()
        # Una segunda llamada duplicaba cada línea en consola y en ytchat.log.
        self.assertEqual(len(self._root.handlers), cuantos)

    def test_guardar_opcion_inserta_tras_la_ultima_clave_de_la_seccion(self):
        ruta = Path(self._tmp.name) / "config.ini"
        ruta.write_text("[a]\nx = 1\n\n# comentario final\n\n[b]\ny = 2\n",
                        encoding="utf-8")
        config.guardar_opcion(ruta, "a", "z", "3")
        # Antes la clave migrada caía tras la línea en blanco, pegada a [b].
        self.assertEqual(ruta.read_text(encoding="utf-8"),
                         "[a]\nx = 1\nz = 3\n\n# comentario final\n\n[b]\ny = 2\n")

    def test_guardar_opcion_en_seccion_vacia_va_tras_la_cabecera(self):
        ruta = Path(self._tmp.name) / "config.ini"
        ruta.write_text("[a]\n\n[b]\ny = 2\n", encoding="utf-8")
        config.guardar_opcion(ruta, "a", "z", "3")
        self.assertEqual(ruta.read_text(encoding="utf-8"), "[a]\nz = 3\n\n[b]\ny = 2\n")

    def test_guardar_opcion_al_final_sin_salto_de_linea(self):
        ruta = Path(self._tmp.name) / "config.ini"
        ruta.write_text("[a]\nx = 1", encoding="utf-8")
        config.guardar_opcion(ruta, "a", "z", "3")
        self.assertEqual(ruta.read_text(encoding="utf-8"), "[a]\nx = 1\nz = 3\n")

    def test_regenera_si_falta(self):
        tmp = Path(self._tmp.name)
        with mock.patch.object(config, "app_dir", return_value=tmp):
            cfg = config.cargar_configuracion()
        self.assertTrue((tmp / "config.ini").exists())
        self.assertEqual(cfg["formato_prefijo"], "nombre_mensaje")
        texto = (tmp / "config.ini").read_text(encoding="utf-8")
        self.assertIn("registro_detallado = false", texto)

    def test_registro_detallado_ausente_no_activa_manejador(self):
        ruta = Path(self._tmp.name) / "config.ini"
        ruta.write_text("[diagnostico]\n", encoding="utf-8")
        with mock.patch.object(config, "app_dir", return_value=Path(self._tmp.name)), \
             mock.patch.object(config.logging, "getLogger") as obtener_logger, \
             mock.patch.object(config, "RotatingFileHandler"), \
             mock.patch.object(config.diagnostico, "crear_manejador_detallado") as crear:
            config.configurar_logging()
            crear.assert_not_called()

    def test_registro_detallado_si_falla_lectura_no_activa_manejador(self):
        with mock.patch.object(config, "app_dir", return_value=Path(self._tmp.name)), \
             mock.patch.object(config.logging, "getLogger") as obtener_logger, \
             mock.patch.object(config, "RotatingFileHandler"), \
             mock.patch.object(config.configparser.ConfigParser, "read",
                               side_effect=Exception("fallo de prueba")), \
             mock.patch.object(config.diagnostico, "crear_manejador_detallado") as crear:
            config.configurar_logging()
            crear.assert_not_called()

    def test_registro_detallado_ausente_se_persiste_apagado(self):
        ruta = Path(self._tmp.name) / "config.ini"
        ruta.write_text("[diagnostico]\n", encoding="utf-8")
        with mock.patch.object(config, "app_dir", return_value=Path(self._tmp.name)):
            config.cargar_configuracion()
        texto = ruta.read_text(encoding="utf-8")
        self.assertIn("registro_detallado = false", texto)

    def test_registro_detallado_true_se_conserva(self):
        ruta = Path(self._tmp.name) / "config.ini"
        ruta.write_text("[diagnostico]\nregistro_detallado = true\n", encoding="utf-8")
        with mock.patch.object(config, "app_dir", return_value=Path(self._tmp.name)):
            config.cargar_configuracion()
        texto = ruta.read_text(encoding="utf-8")
        self.assertIn("registro_detallado = true", texto)

    def test_valores_basicos(self):
        cfg = self._cargar_en(config._CONFIG_FALLBACK)
        self.assertEqual(cfg["velocidad"], 175)
        self.assertEqual(cfg["volumen"], 1.0)
        self.assertEqual(cfg["estrategia"], "limite")
        self.assertTrue(cfg["reconectar"])

    def test_overlay_tiene_defaults_y_se_persiste_en_el_ejemplo(self):
        cfg = self._cargar_en(config._CONFIG_FALLBACK)
        self.assertFalse(cfg["overlay_activo"])
        self.assertEqual(cfg["overlay_puerto"], 8730)
        texto = (Path(self._tmp.name) / "config.ini").read_text(encoding="utf-8")
        self.assertIn("[overlay]", texto)
        self.assertIn("puerto = 8730", texto)

    def test_microfono_de_obs_viene_vacio_y_se_persiste_en_el_ejemplo(self):
        cfg = self._cargar_en(config._CONFIG_FALLBACK)
        self.assertEqual(cfg["obs_microfono"], "")
        texto = (Path(self._tmp.name) / "config.ini").read_text(encoding="utf-8")
        self.assertIn("[obs]", texto)
        self.assertIn("microfono =", texto)

    def test_programados_arranca_apagado_y_se_persiste_en_el_ejemplo(self):
        import config_predeterminada as _pred
        self.assertEqual(_pred.obtener("programados", "activo"), "false")
        cfg = self._cargar_en(config._CONFIG_FALLBACK)
        self.assertFalse(cfg["programados_activo"])
        texto = (Path(self._tmp.name) / "config.ini").read_text(encoding="utf-8")
        self.assertIn("[programados]", texto)
        self.assertIn("activo = false", texto)

    def test_programados_ausente_arranca_apagado_por_defecto(self):
        cfg = self._cargar_en("[voz]\nvelocidad = 175\n")
        self.assertFalse(cfg["programados_activo"])

    def test_overlay_puerto_tiene_minimo_uno(self):
        cfg = self._cargar_en("[overlay]\nactivo = true\npuerto = 0\n")
        self.assertTrue(cfg["overlay_activo"])
        self.assertEqual(cfg["overlay_puerto"], 1)

    def test_clamp_velocidad(self):
        cfg = self._cargar_en("[voz]\nvelocidad = 9000\n")
        self.assertEqual(cfg["velocidad"], 500)

    def test_clamp_volumen(self):
        cfg = self._cargar_en("[voz]\nvolumen = 5.0\n")
        self.assertEqual(cfg["volumen"], 1.0)

    def test_estrategia_invalida_cae_a_limite(self):
        cfg = self._cargar_en("[cola]\nestrategia = loquesea\n")
        self.assertEqual(cfg["estrategia"], "limite")

    def test_listas_de_filtros(self):
        cfg = self._cargar_en(
            "[filtros]\npalabras_silenciadas = Spam, Publicidad\n"
            "usuarios_silenciados = Bot1, BOT2\n")
        self.assertEqual(cfg["palabras_silenciadas"], ["spam", "publicidad"])
        self.assertEqual(cfg["usuarios_silenciados"], ["bot1", "bot2"])

    def test_formato_invalido_cae_a_default(self):
        cfg = self._cargar_en("[lectura]\nformato_prefijo = raro\n")
        self.assertEqual(cfg["formato_prefijo"], "nombre_mensaje")

    def test_formato_mensaje_nombre_se_conserva(self):
        cfg = self._cargar_en("[lectura]\nformato_prefijo = mensaje_nombre\n")
        self.assertEqual(cfg["formato_prefijo"], "mensaje_nombre")

    def test_inyecta_seccion_descargas_con_defaults(self):
        # Sin [descargas] en el INI, cargar_configuracion debe inyectar los
        # defaults canónicos y devolverlos en el dict.
        cfg = self._cargar_en("[voz]\nvoz = 0\n")
        self.assertIn("descargas", cfg)
        self.assertEqual(cfg["descargas_formato"], "mp4")
        self.assertEqual(cfg["descargas_bitrate"], 192)
        # En el INI queda «Descargas»; el dict ya trae la ruta resuelta
        # contra app_dir(), que es la que usa el gestor de descargas.
        self.assertEqual(cfg["descargas_carpeta"], str(Path(self._tmp.name) / "Descargas"))
        self.assertFalse(cfg["descargas_enumerar"])

    def test_obtener_opciones_descarga_devuelve_defaults_si_no_existe(self):
        import config
        with mock.patch.object(config, "app_dir", return_value=Path(self._tmp.name)):
            op = config.obtener_opciones_descarga()
        self.assertEqual(op["formato"], "mp4")
        self.assertEqual(op["bitrate"], 192)
        self.assertIn("Descargas", op["carpeta"])
        self.assertFalse(op["enumerar"])

    def test_obtener_opciones_no_persiste_carpeta_por_defecto(self):
        import config
        ruta = Path(self._tmp.name) / "config.ini"
        contenido = "[descargas]\nformato = mp4\nbitrate = 192\nenumerar = false\n"
        ruta.write_text(contenido, encoding="utf-8")
        with mock.patch.object(config, "app_dir", return_value=Path(self._tmp.name)):
            op = config.obtener_opciones_descarga()
        self.assertEqual(op["carpeta"], str(Path(self._tmp.name) / "Descargas"))
        self.assertEqual(ruta.read_text(encoding="utf-8"), contenido)

    def test_obtener_opciones_resuelve_carpeta_relativa_contra_app_dir(self):
        import config
        ruta = Path(self._tmp.name) / "config.ini"
        ruta.write_text("[descargas]\ncarpeta = Descargas\n", encoding="utf-8")
        with mock.patch.object(config, "app_dir", return_value=Path(self._tmp.name)):
            op = config.obtener_opciones_descarga()
        self.assertEqual(op["carpeta"], str(Path(self._tmp.name) / "Descargas"))

    def test_obtener_opciones_respeta_carpeta_absoluta(self):
        import config
        ruta = Path(self._tmp.name) / "config.ini"
        absoluta = Path(self._tmp.name) / "otra"
        ruta.write_text(f"[descargas]\ncarpeta = {absoluta}\n", encoding="utf-8")
        with mock.patch.object(config, "app_dir", return_value=Path(self._tmp.name)):
            op = config.obtener_opciones_descarga()
        self.assertEqual(op["carpeta"], str(absoluta))

    def test_cargar_configuracion_persiste_carpeta_predeterminada(self):
        for contenido in (
            "[voz]\nvoz = 0\n",
            "[descargas]\nformato = mp4\nbitrate = 192\nenumerar = false\n",
        ):
            with self.subTest(seccion="descargas" in contenido):
                ruta = Path(self._tmp.name) / "config.ini"
                ruta.write_text(contenido, encoding="utf-8")
                with mock.patch.object(config, "app_dir", return_value=Path(self._tmp.name)):
                    cfg = config.cargar_configuracion()
                # En el INI queda «Descargas»; el dict ya trae la ruta resuelta
                # contra app_dir(), que es la que usa el gestor de descargas.
                self.assertEqual(cfg["descargas_carpeta"],
                                 str(Path(self._tmp.name) / "Descargas"))
                self.assertRegex(
                    ruta.read_text(encoding="utf-8").lower(),
                    r"(?m)^\s*carpeta\s*=\s*descargas\s*$",
                )

    def test_guardar_opciones_descarga_persiste(self):
        import config
        with mock.patch.object(config, "app_dir", return_value=Path(self._tmp.name)):
            (Path(self._tmp.name) / "config.ini").write_text(
                config._CONFIG_FALLBACK, encoding="utf-8")
            config.guardar_opciones_descarga(
                {"formato": "mp3", "bitrate": 320, "carpeta": "/x/y", "enumerar": True})
            op = config.obtener_opciones_descarga()
        self.assertEqual(op["formato"], "mp3")
        self.assertEqual(op["bitrate"], 320)
        self.assertEqual(op["carpeta"], "/x/y")
        self.assertTrue(op["enumerar"])

    def test_guardar_opciones_descarga_normaliza_invalidos(self):
        import config
        with mock.patch.object(config, "app_dir", return_value=Path(self._tmp.name)):
            (Path(self._tmp.name) / "config.ini").write_text(
                config._CONFIG_FALLBACK, encoding="utf-8")
            # enumerar en el dict es bool, no string. Pasamos un valor truthy
            # pero el código debe normalizarlo (o mantenerlo si es bool True).
            # En este test pasamos un bool True para forzar la rama de
            # normalización a no actuar — y verificamos que un bitrate fuera
            # de rango y un formato inválido caen a los defaults.
            config.guardar_opciones_descarga(
                {"formato": "raro", "bitrate": 999, "enumerar": True})
            op = config.obtener_opciones_descarga()
        self.assertEqual(op["formato"], "mp4")
        self.assertEqual(op["bitrate"], 192)
        self.assertTrue(op["enumerar"])


if __name__ == "__main__":
    unittest.main()
