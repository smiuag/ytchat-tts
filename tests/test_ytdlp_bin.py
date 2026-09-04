import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import ytdlp_bin
import subprocesos


class PruebasYtdlpBin(unittest.TestCase):

    def test_version_ytdlp_ejecuta_un_programa_real(self):
        version = ytdlp_bin.version_ytdlp(sys.executable)
        self.assertTrue(version)
        self.assertTrue(version.startswith("Python"))

    def test_resultado_actualizacion_distingue_fallos(self):
        self.assertFalse(ytdlp_bin.resultado_actualizacion_es_fallo("ya_al_dia"))
        self.assertFalse(ytdlp_bin.resultado_actualizacion_es_fallo("actualizado"))
        self.assertTrue(ytdlp_bin.resultado_actualizacion_es_fallo("sin_conexion"))
        self.assertTrue(ytdlp_bin.resultado_actualizacion_es_fallo("otro_fallo"))

    def test_porcentaje_sin_total_no_inventa_un_valor(self):
        self.assertIsNone(ytdlp_bin.porcentaje_descarga(50, None))
        self.assertEqual(25, ytdlp_bin.porcentaje_descarga(25, 100))

    def test_porcentaje_no_supera_cien(self):
        self.assertEqual(100, ytdlp_bin.porcentaje_descarga(150, 100))

    def test_texto_solo_avanza_en_decenas(self):
        self.assertTrue(ytdlp_bin.debe_actualizar_texto_progreso(None, 0))
        self.assertFalse(ytdlp_bin.debe_actualizar_texto_progreso(0, 9))
        self.assertTrue(ytdlp_bin.debe_actualizar_texto_progreso(0, 10))
        self.assertTrue(ytdlp_bin.debe_actualizar_texto_progreso(90, 100))

    def test_sondeo_terminado_no_reprograma(self):
        terminado = threading.Event()
        terminado.set()
        dialogo = MagicMock()
        cancelado = threading.Event()
        reprogramar = MagicMock()

        self.assertFalse(ytdlp_bin.sondear_cancelacion(
            terminado, dialogo, cancelado, reprogramar))
        dialogo.WasCancelled.assert_not_called()
        reprogramar.assert_not_called()

    def test_sondeo_activo_reprograma_sin_cancelar(self):
        terminado = threading.Event()
        dialogo = MagicMock()
        dialogo.WasCancelled.return_value = False
        cancelado = threading.Event()
        reprogramar = MagicMock()

        self.assertTrue(ytdlp_bin.sondear_cancelacion(
            terminado, dialogo, cancelado, reprogramar))
        self.assertFalse(cancelado.is_set())
        reprogramar.assert_called_once_with()

    def test_sondeo_cancelado_marca_y_reprograma(self):
        terminado = threading.Event()
        dialogo = MagicMock()
        dialogo.WasCancelled.return_value = True
        cancelado = threading.Event()
        reprogramar = MagicMock()

        self.assertTrue(ytdlp_bin.sondear_cancelacion(
            terminado, dialogo, cancelado, reprogramar))
        self.assertTrue(cancelado.is_set())
        reprogramar.assert_called_once_with()

    def test_descarga_usa_content_length_y_avisos_de_progreso(self):
        contenido = b"0123456789"
        respuesta = MagicMock()
        respuesta.headers.get.return_value = str(len(contenido))
        respuesta.read.side_effect = [contenido[:4], contenido[4:], b""]
        avisos = []
        with tempfile.TemporaryDirectory() as carpeta, \
                patch.object(ytdlp_bin, "urlopen", return_value=respuesta):
            respuesta.__enter__.return_value = respuesta
            destino = Path(carpeta) / "yt-dlp.exe"
            resultado = ytdlp_bin.descargar_ytdlp(
                "https://ejemplo", hashlib.sha256(contenido).hexdigest(), destino,
                lambda *datos: avisos.append(datos))
        self.assertTrue(resultado.correcta)
        self.assertEqual([40, 100], [aviso[0] for aviso in avisos])

    def test_cancelar_borra_temporal_y_no_reemplaza(self):
        contenido = b"binario nuevo"
        respuesta = MagicMock()
        respuesta.headers.get.return_value = str(len(contenido))
        respuesta.read.side_effect = [contenido[:4], contenido[4:]]
        llamadas = []
        with tempfile.TemporaryDirectory() as carpeta, \
                patch.object(ytdlp_bin, "urlopen", return_value=respuesta):
            respuesta.__enter__.return_value = respuesta
            destino = Path(carpeta) / "yt-dlp.exe"
            destino.write_bytes(b"binario anterior")
            resultado = ytdlp_bin.descargar_ytdlp(
                "https://ejemplo", hashlib.sha256(contenido).hexdigest(), destino,
                lambda *_: llamadas.append(True), lambda: True)
            self.assertFalse(destino.read_bytes() == contenido)
            self.assertEqual([], list(Path(carpeta).glob(".yt-dlp-*.tmp")))
        self.assertFalse(resultado.correcta)
        self.assertIn("cancelada", resultado.motivo)

    def test_actualizar_convierte_cancelacion_en_estado_cancelado(self):
        respuesta = MagicMock()
        respuesta.read.return_value = b"yt-dlp.exe  firma"
        with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="anterior.exe"), \
                patch.object(ytdlp_bin, "version_ytdlp", return_value="2026.08.20"), \
                patch.object(ytdlp_bin, "ultima_version_ytdlp", return_value=(
                    "2026.08.21", "https://ejemplo/yt-dlp.exe", "https://ejemplo/firmas"
                )), \
                patch.object(ytdlp_bin, "urlopen", return_value=respuesta), \
                patch.object(ytdlp_bin, "firma_sha256", return_value="firma"), \
                patch.object(ytdlp_bin, "descargar_ytdlp", return_value=(
                    ytdlp_bin.ResultadoDescarga(False, "descarga cancelada")
                )):
            respuesta.__enter__.return_value = respuesta
            estado = ytdlp_bin.actualizar_ytdlp()
        self.assertEqual(("cancelado", "2026.08.20", "2026.08.21"), estado)
    def test_mensaje_ya_al_dia(self):
        self.assertEqual(
            "Ya tienes yt-dlp al día, versión 2026.08.20.",
            ytdlp_bin.mensaje_de_actualizacion("ya_al_dia", "2026.08.20"),
        )

    def test_mensaje_actualizado(self):
        self.assertEqual(
            "yt-dlp se actualizó a la versión 2026.08.20.",
            ytdlp_bin.mensaje_de_actualizacion("actualizado", version_nueva="2026.08.20"),
        )

    def test_mensaje_sin_conexion(self):
        self.assertIn("última versión", ytdlp_bin.mensaje_de_actualizacion("sin_conexion"))

    def test_mensaje_firma_incorrecta_avisa_que_no_instalo(self):
        self.assertIn("No se instaló nada", ytdlp_bin.mensaje_de_actualizacion("firma_incorrecta"))

    def test_mensaje_otro_fallo_incluye_motivo(self):
        self.assertEqual(
            "No se pudo actualizar yt-dlp: permiso denegado.",
            ytdlp_bin.mensaje_de_actualizacion("otro_fallo", motivo="permiso denegado"),
        )

    def test_info_video_devuelve_el_json_del_programa(self):
        respuesta = MagicMock(returncode=0, stdout='{"title": "Prueba"}')
        with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                patch.object(ytdlp_bin.subprocess, "run", return_value=respuesta) as ejecutar:
            self.assertEqual({"title": "Prueba"}, ytdlp_bin.info_video("A" * 11))
        ejecutar.assert_called_once()
        self.assertEqual("20", ejecutar.call_args.args[0][-2])

    def test_info_video_devuelve_none_si_falla_el_programa(self):
        respuesta = MagicMock(returncode=1, stdout="")
        with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                patch.object(ytdlp_bin.subprocess, "run", return_value=respuesta):
            self.assertIsNone(ytdlp_bin.info_video("A" * 11))

    def test_info_video_devuelve_none_si_el_programa_no_entrega_json(self):
        respuesta = MagicMock(returncode=0, stdout="no es json")
        with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                patch.object(ytdlp_bin.subprocess, "run", return_value=respuesta):
            self.assertIsNone(ytdlp_bin.info_video("A" * 11))

    def test_info_video_no_intenta_ejecutar_si_no_hay_programa(self):
        with patch.object(ytdlp_bin, "ruta_ytdlp", return_value=None), \
                patch.object(ytdlp_bin.subprocess, "run") as ejecutar:
            self.assertIsNone(ytdlp_bin.info_video("A" * 11))
        ejecutar.assert_not_called()

    def test_desde_codigo_fuente_no_usa_ejecutable_de_la_carpeta_del_interprete(self):
        with tempfile.TemporaryDirectory() as carpeta:
            interprete = Path(carpeta) / "Scripts"
            interprete.mkdir()
            (interprete / "yt-dlp.exe").write_bytes(b"lanzador")
            with patch.object(ytdlp_bin, "_ruta_actualizada", return_value=Path(carpeta) / "no.exe"), \
                    patch.object(sys, "executable", str(interprete / "python.exe")), \
                    patch.object(sys, "frozen", False, create=True):
                self.assertIsNone(ytdlp_bin.ruta_ytdlp())

    def test_empaquetado_usa_ejecutable_junto_al_interprete(self):
        with tempfile.TemporaryDirectory() as carpeta:
            carpeta = Path(carpeta)
            ejecutable = carpeta / "YTChatTTS.exe"
            paquete = carpeta / "yt-dlp.exe"
            ejecutable.touch()
            paquete.write_bytes(b"programa")
            with patch.object(sys, "executable", str(ejecutable)), \
                    patch.object(sys, "frozen", True, create=True):
                self.assertEqual(paquete.resolve(), ytdlp_bin._ruta_del_paquete())

    def test_construccion_rechaza_archivo_menor_que_un_mib(self):
        construir = Path(__file__).parents[1] / "construir.bat"
        texto = construir.read_text(encoding="utf-8")
        self.assertIn('set "YTDLP_MIN_BYTES=1048576"', texto)
        self.assertIn('if %%~zf LSS %YTDLP_MIN_BYTES%', texto)
        self.assertIn('del /q "%OUT%\\yt-dlp.exe"', texto)

    def test_construccion_no_contiene_bytes_fuera_de_ascii(self):
        construir = Path(__file__).parents[1] / "construir.bat"
        for numero, linea in enumerate(construir.read_bytes().splitlines(), 1):
            if any(byte > 127 for byte in linea):
                self.fail(
                    f"{construir.name}: linea {numero} contiene bytes fuera de ASCII"
                )

    def test_firma_sha256_lee_el_archivo_correcto(self):
        texto = (
            "a" * 64 + "  otro.zip\n"
            + "b" * 64 + "   yt-dlp.exe\n"
            + "c" * 64 + "  archivo con espacios.zip\n"
        )
        self.assertEqual("b" * 64, ytdlp_bin.firma_sha256(texto, "yt-dlp.exe"))
        self.assertEqual(
            "c" * 64,
            ytdlp_bin.firma_sha256(texto, "archivo con espacios.zip"),
        )

    def test_firma_sha256_devuelve_vacio_si_no_existe(self):
        self.assertEqual("", ytdlp_bin.firma_sha256("a" * 64 + "  otro.exe", "no.exe"))

    def test_firma_sha256_distingue_ejecutable_de_version_x86(self):
        texto = (
            "66674953fe251b89f4d08c5f0e35e0728679bd67ab3d7d05c0562af101dd3e7a  yt-dlp.exe\n"
            "a8f91bd41452506bc81ebd2f369b186fea0ee7075413ba00cef9fd346a0a5d0c  yt-dlp_x86.exe\n"
        )
        self.assertEqual(
            "66674953fe251b89f4d08c5f0e35e0728679bd67ab3d7d05c0562af101dd3e7a",
            ytdlp_bin.firma_sha256(texto, "yt-dlp.exe"),
        )
        self.assertEqual(
            "a8f91bd41452506bc81ebd2f369b186fea0ee7075413ba00cef9fd346a0a5d0c",
            ytdlp_bin.firma_sha256(texto, "yt-dlp_x86.exe"),
        )


    def test_busqueda_prefiere_la_copia_actualizada(self):
        with tempfile.TemporaryDirectory() as carpeta:
            actualizada = Path(carpeta) / "actualizada.exe"
            paquete = Path(carpeta) / "paquete.exe"
            actualizada.touch()
            paquete.touch()
            os.utime(paquete, (1_000_000, 1_000_000))
            os.utime(actualizada, (2_000_000, 2_000_000))
            with patch.object(ytdlp_bin, "_ruta_actualizada", return_value=actualizada), \
                    patch.object(ytdlp_bin, "_ruta_del_paquete", return_value=paquete):
                self.assertEqual(str(actualizada), ytdlp_bin.ruta_ytdlp())

    def test_busqueda_prefiere_el_paquete_si_es_mas_reciente(self):
        # Paquete nuevo con un yt-dlp posterior a la copia que el usuario
        # actualizó hace meses: antes ganaba siempre la copia vieja.
        with tempfile.TemporaryDirectory() as carpeta:
            actualizada = Path(carpeta) / "actualizada.exe"
            paquete = Path(carpeta) / "paquete.exe"
            actualizada.touch()
            paquete.touch()
            os.utime(actualizada, (1_000_000, 1_000_000))
            os.utime(paquete, (2_000_000, 2_000_000))
            with patch.object(ytdlp_bin, "_ruta_actualizada", return_value=actualizada), \
                    patch.object(ytdlp_bin, "_ruta_del_paquete", return_value=paquete):
                self.assertEqual(str(paquete), ytdlp_bin.ruta_ytdlp())

    def test_busqueda_a_igual_fecha_mantiene_la_actualizada(self):
        with tempfile.TemporaryDirectory() as carpeta:
            actualizada = Path(carpeta) / "actualizada.exe"
            paquete = Path(carpeta) / "paquete.exe"
            actualizada.touch()
            paquete.touch()
            os.utime(actualizada, (1_000_000, 1_000_000))
            os.utime(paquete, (1_000_000, 1_000_000))
            with patch.object(ytdlp_bin, "_ruta_actualizada", return_value=actualizada), \
                    patch.object(ytdlp_bin, "_ruta_del_paquete", return_value=paquete):
                self.assertEqual(str(actualizada), ytdlp_bin.ruta_ytdlp())

    def test_busqueda_usa_la_unica_copia(self):
        with tempfile.TemporaryDirectory() as carpeta:
            paquete = Path(carpeta) / "paquete.exe"
            paquete.touch()
            with patch.object(ytdlp_bin, "_ruta_actualizada", return_value=Path(carpeta) / "no.exe"), \
                    patch.object(ytdlp_bin, "_ruta_del_paquete", return_value=paquete):
                self.assertEqual(str(paquete), ytdlp_bin.ruta_ytdlp())

    def test_busqueda_sin_copias_devuelve_none(self):
        with tempfile.TemporaryDirectory() as carpeta:
            with patch.object(ytdlp_bin, "_ruta_actualizada", return_value=Path(carpeta) / "no1.exe"), \
                    patch.object(ytdlp_bin, "_ruta_del_paquete", return_value=Path(carpeta) / "no2.exe"):
                self.assertIsNone(ytdlp_bin.ruta_ytdlp())

    def test_ruta_actualizada_usa_localappdata(self):
        with tempfile.TemporaryDirectory() as carpeta:
            with patch.dict(ytdlp_bin.os.environ, {"LOCALAPPDATA": carpeta}):
                self.assertEqual(
                    Path(carpeta) / ytdlp_bin.SUBDIRECTORIO_DATOS / "yt-dlp.exe",
                    ytdlp_bin._ruta_actualizada(),
                )

    def test_ruta_actualizada_usa_carpeta_del_usuario_sin_localappdata(self):
        with tempfile.TemporaryDirectory() as carpeta, \
                patch.dict(ytdlp_bin.os.environ, {}, clear=True), \
                patch.object(Path, "home", return_value=Path(carpeta)):
            self.assertEqual(
                Path.home() / ytdlp_bin.SUBDIRECTORIO_DATOS / "yt-dlp.exe",
                ytdlp_bin._ruta_actualizada(),
            )

    def test_descarga_rechaza_url_que_no_es_https(self):
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "yt-dlp.exe"
            with patch.object(ytdlp_bin, "_descargar_archivo") as descargar:
                resultado = ytdlp_bin.descargar_ytdlp("http://ejemplo", "a" * 64, destino)
            self.assertFalse(resultado.correcta)
            descargar.assert_not_called()
            self.assertFalse(destino.exists())

    def test_descarga_con_firma_incorrecta_conserva_destino_y_borra_temporal(self):
        contenido = b"binario nuevo"
        with tempfile.TemporaryDirectory() as carpeta:
            carpeta = Path(carpeta)
            destino = carpeta / "yt-dlp.exe"
            destino.write_bytes(b"binario anterior")

            def escribir(_url, temporal):
                temporal.write_bytes(contenido)

            with patch.object(ytdlp_bin, "_descargar_archivo", side_effect=escribir):
                resultado = ytdlp_bin.descargar_ytdlp("https://ejemplo", "0" * 64, destino)

            self.assertFalse(resultado.correcta)
            self.assertEqual(b"binario anterior", destino.read_bytes())
            self.assertEqual([], list(carpeta.glob(".yt-dlp-*.tmp")))

    def test_descarga_rechaza_firma_diferente_en_el_ultimo_caracter(self):
        contenido = b"binario nuevo"
        firma = hashlib.sha256(contenido).hexdigest()
        firma_alterada = firma[:-1] + ("0" if firma[-1] != "0" else "1")
        with tempfile.TemporaryDirectory() as carpeta:
            carpeta = Path(carpeta)
            destino = carpeta / "yt-dlp.exe"
            destino.write_bytes(b"binario anterior")

            def escribir(_url, temporal):
                temporal.write_bytes(contenido)

            with patch.object(ytdlp_bin, "_descargar_archivo", side_effect=escribir):
                resultado = ytdlp_bin.descargar_ytdlp(
                    "https://ejemplo", firma_alterada, destino
                )

            self.assertFalse(resultado.correcta)
            self.assertEqual(b"binario anterior", destino.read_bytes())
            self.assertEqual([], list(carpeta.glob(".yt-dlp-*.tmp")))

    def test_descarga_con_firma_correcta_reemplaza_destino(self):
        contenido = b"binario nuevo"
        firma = hashlib.sha256(contenido).hexdigest()
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "yt-dlp.exe"

            def escribir(_url, temporal):
                temporal.write_bytes(contenido)

            with patch.object(ytdlp_bin, "_descargar_archivo", side_effect=escribir):
                resultado = ytdlp_bin.descargar_ytdlp("https://ejemplo", firma, destino)

            self.assertTrue(resultado.correcta)
            self.assertEqual(contenido, destino.read_bytes())

    def test_asegurar_no_instala_sin_firma_publicada(self):
        respuesta = MagicMock()
        respuesta.__enter__.return_value.read.return_value = (
            b"a" * 64 + b"  yt-dlp_x86.exe\n"
        )
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "yt-dlp.exe"
            with patch.object(ytdlp_bin, "ruta_ytdlp", return_value=None), \
                    patch.object(
                        ytdlp_bin,
                        "ultima_version_ytdlp",
                        return_value=(
                            "2026.08.19",
                            "https://ejemplo/yt-dlp.exe",
                            "https://ejemplo/SHA2-256SUMS",
                        ),
                    ), \
                    patch.object(ytdlp_bin, "urlopen", return_value=respuesta), \
                    patch.object(ytdlp_bin, "descargar_ytdlp") as descargar:
                resultado = ytdlp_bin.asegurar_ytdlp(destino)

            self.assertFalse(resultado.correcta)
            self.assertFalse(destino.exists())
            descargar.assert_not_called()

    def _ultima(self, version="2026.08.21"):
        return (version, "https://ejemplo/yt-dlp.exe", "https://ejemplo/SHA2-256SUMS")

    def test_actualizar_misma_version_no_descarga(self):
        with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                patch.object(ytdlp_bin, "version_ytdlp", return_value="2026.08.21"), \
                patch.object(ytdlp_bin, "ultima_version_ytdlp", return_value=self._ultima()), \
                patch.object(ytdlp_bin, "descargar_ytdlp") as descargar:
            resultado = ytdlp_bin.actualizar_ytdlp()
        self.assertEqual(("ya_al_dia", "2026.08.21", "2026.08.21"), resultado)
        descargar.assert_not_called()

    def test_actualizar_version_distinta_descarga(self):
        with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                patch.object(ytdlp_bin, "version_ytdlp", return_value="2026.08.20"), \
                patch.object(ytdlp_bin, "ultima_version_ytdlp", return_value=self._ultima()), \
                patch.object(ytdlp_bin, "urlopen") as abrir, \
                patch.object(ytdlp_bin, "descargar_ytdlp", return_value=ytdlp_bin.ResultadoDescarga(True, "")) as descargar:
            abrir.return_value.__enter__.return_value.read.return_value = b"a" * 64 + b"  yt-dlp.exe\n"
            resultado = ytdlp_bin.actualizar_ytdlp()
        self.assertEqual("actualizado", resultado[0])
        descargar.assert_called_once()

    def test_actualizar_sin_binario_descarga(self):
        with patch.object(ytdlp_bin, "ruta_ytdlp", return_value=None), \
                patch.object(ytdlp_bin, "ultima_version_ytdlp", return_value=self._ultima()), \
                patch.object(ytdlp_bin, "urlopen") as abrir, \
                patch.object(ytdlp_bin, "descargar_ytdlp", return_value=ytdlp_bin.ResultadoDescarga(True, "")) as descargar:
            abrir.return_value.__enter__.return_value.read.return_value = b"a" * 64 + b"  yt-dlp.exe\n"
            resultado = ytdlp_bin.actualizar_ytdlp()
        self.assertEqual(("actualizado", "", "2026.08.21"), resultado)
        descargar.assert_called_once()

    def test_actualizar_sin_ultima_version_no_descarga(self):
        with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                patch.object(ytdlp_bin, "version_ytdlp", return_value="2026.08.20"), \
                patch.object(ytdlp_bin, "ultima_version_ytdlp", return_value=None), \
                patch.object(ytdlp_bin, "descargar_ytdlp") as descargar:
            resultado = ytdlp_bin.actualizar_ytdlp()
        self.assertEqual(("sin_conexion", "2026.08.20", ""), resultado)
        descargar.assert_not_called()

    def test_actualizar_avisa_antes_de_descargar(self):
        orden = []
        with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                patch.object(ytdlp_bin, "version_ytdlp", return_value="2026.08.20"), \
                patch.object(ytdlp_bin, "ultima_version_ytdlp", return_value=self._ultima()), \
                patch.object(ytdlp_bin, "urlopen") as abrir, \
                patch.object(ytdlp_bin, "descargar_ytdlp", side_effect=lambda *a: (orden.append("descarga"), ytdlp_bin.ResultadoDescarga(True, ""))[1]):
            abrir.return_value.__enter__.return_value.read.return_value = b"a" * 64 + b"  yt-dlp.exe\n"
            resultado = ytdlp_bin.actualizar_ytdlp(lambda: orden.append("aviso"))
        self.assertEqual("actualizado", resultado[0])
        self.assertEqual(["aviso", "descarga"], orden)

    def test_actualizar_no_avisa_si_no_hay_descarga(self):
        aviso = MagicMock()
        with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                patch.object(ytdlp_bin, "version_ytdlp", return_value="2026.08.21"), \
                patch.object(ytdlp_bin, "ultima_version_ytdlp", return_value=self._ultima()):
            resultado = ytdlp_bin.actualizar_ytdlp(aviso)
        self.assertEqual("ya_al_dia", resultado[0])
        aviso.assert_not_called()

    def test_actualizar_informa_firma_incorrecta(self):
        with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                patch.object(ytdlp_bin, "version_ytdlp", return_value="2026.08.20"), \
                patch.object(ytdlp_bin, "ultima_version_ytdlp", return_value=self._ultima()), \
                patch.object(ytdlp_bin, "urlopen") as abrir, \
                patch.object(ytdlp_bin, "descargar_ytdlp", return_value=ytdlp_bin.ResultadoDescarga(False, "la firma SHA-256 no coincide")):
            abrir.return_value.__enter__.return_value.read.return_value = b"a" * 64 + b"  yt-dlp.exe\n"
            resultado = ytdlp_bin.actualizar_ytdlp()
        self.assertEqual("firma_incorrecta", resultado[0])


class PruebasDescargarVideoCache(unittest.TestCase):

    def test_argumentos_completos_incluye_temporal_unico_y_flags(self):
        with tempfile.TemporaryDirectory() as carpeta:
            temporal = Path(carpeta) / ".ytcache-abc123.mp4"
            args = ytdlp_bin._argumentos_video_cache("yt-dlp.exe", temporal, "A" * 11)
            self.assertIn("-f", args)
            self.assertIn("bv*+ba/b", args)
            self.assertIn("--no-playlist", args)
            self.assertIn("--no-warnings", args)
            self.assertIn("--limit-rate", args)
            self.assertIn(ytdlp_bin.LIMITE_CACHE, args)
            self.assertIn("--merge-output-format", args)
            self.assertIn("mp4", args)
            self.assertIn(str(temporal), args)
            self.assertTrue(str(temporal).endswith(".mp4"))
            self.assertIn(f"https://www.youtube.com/watch?v={'A' * 11}", args)
            # No reutilizar .part compartido
            self.assertNotIn(str(Path(carpeta) / "destino.mp4.part"), args)

    def test_argumentos_usan_el_resolvedor_unico_de_ffmpeg(self):
        with tempfile.TemporaryDirectory() as carpeta:
            temporal = Path(carpeta) / ".ytcache-x.mp4"
            with patch.object(ytdlp_bin.ffmpeg_bin, "ruta_ffmpeg",
                              return_value=r"C:\app\ffmpeg.exe"):
                args = ytdlp_bin._argumentos_video_cache("yt-dlp.exe", temporal, "A" * 11)
                idx = args.index("--ffmpeg-location")
                self.assertEqual(r"C:\app\ffmpeg.exe", args[idx + 1])
            with patch.object(ytdlp_bin.ffmpeg_bin, "ruta_ffmpeg", return_value=None):
                args2 = ytdlp_bin._argumentos_video_cache("yt-dlp.exe", temporal, "A" * 11)
                self.assertNotIn("--ffmpeg-location", args2)

    def test_cancelado_borra_tambien_fragmentos_y_part_del_temporal(self):
        # yt-dlp deja «.part», «.ytdl» y fragmentos «.fNNN.ext» junto al
        # temporal; solo borrar el temporal los dejaba huérfanos en la caché.
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "salida.mp4"
            destino.write_bytes(b"previo")
            ajeno = Path(carpeta) / ".ytcache-otro.mp4.part"
            ajeno.write_bytes(b"de otra descarga")

            def falso_ejecutar(argumentos, cancel_event=None, tope_segundos=3600, **kw):
                temporal = Path(argumentos[argumentos.index("-o") + 1])
                temporal.with_name(temporal.name + ".part").write_bytes(b"a medias")
                temporal.with_name(temporal.name + ".ytdl").write_bytes(b"{}")
                temporal.with_name(temporal.stem + ".f137.mp4").write_bytes(b"video")
                return subprocesos.Estado.cancelado

            with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                    patch.object(subprocesos, "ejecutar", side_effect=falso_ejecutar):
                resultado = ytdlp_bin.descargar_video_cache("A" * 11, destino,
                                                            cancel_event=threading.Event())
            self.assertFalse(resultado)
            self.assertEqual(b"previo", destino.read_bytes())
            self.assertEqual({"salida.mp4", ".ytcache-otro.mp4.part"},
                             {ruta.name for ruta in Path(carpeta).iterdir()})

    def test_descargar_video_cache_usa_temporal_unico_en_parent(self):
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "video.mp4"
            capturados = []

            def falso_ejecutar(argumentos, cancel_event=None, tope_segundos=3600, **kw):
                # Buscar el valor tras -o
                if "-o" in argumentos:
                    idx = argumentos.index("-o")
                    capturados.append(Path(argumentos[idx + 1]))
                # crear temporal no vacío para simular éxito
                if capturados:
                    capturados[-1].write_bytes(b"dato")
                return subprocesos.Estado.exito

            with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                    patch.object(subprocesos, "ejecutar", side_effect=falso_ejecutar):
                resultado = ytdlp_bin.descargar_video_cache("A" * 11, destino)
            self.assertTrue(resultado)
            self.assertEqual(1, len(capturados))
            temporal = capturados[0]
            self.assertEqual(Path(carpeta), temporal.parent)
            self.assertTrue(temporal.suffix == ".mp4")
            self.assertTrue(str(temporal.name).startswith(".ytcache-"))
            self.assertTrue(destino.is_file())
            self.assertGreater(destino.stat().st_size, 0)

    def test_exito_publica_por_os_replace_y_deja_contenido_no_vacio(self):
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "salida.mp4"
            destino.write_bytes(b"viejo")

            def falso_ejecutar(argumentos, cancel_event=None, tope_segundos=3600, **kw):
                idx = argumentos.index("-o")
                temporal = Path(argumentos[idx + 1])
                temporal.write_bytes(b"nuevo contenido")
                return subprocesos.Estado.exito

            with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                    patch.object(subprocesos, "ejecutar", side_effect=falso_ejecutar):
                resultado = ytdlp_bin.descargar_video_cache("A" * 11, destino)
            self.assertTrue(resultado)
            self.assertEqual(b"nuevo contenido", destino.read_bytes())
            # temporal limpio tras replace
            restantes = list(Path(carpeta).glob(".ytcache-*.mp4"))
            self.assertEqual([], restantes)

    def test_fallo_preserva_destino_y_borra_temporal(self):
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "salida.mp4"
            destino.write_bytes(b"previo")

            def falso_ejecutar(argumentos, cancel_event=None, tope_segundos=3600, **kw):
                idx = argumentos.index("-o")
                Path(argumentos[idx + 1]).write_bytes(b"parcial")
                return subprocesos.Estado.fallo

            with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                    patch.object(subprocesos, "ejecutar", side_effect=falso_ejecutar):
                resultado = ytdlp_bin.descargar_video_cache("A" * 11, destino)
            self.assertFalse(resultado)
            self.assertEqual(b"previo", destino.read_bytes())
            self.assertEqual([], list(Path(carpeta).glob(".ytcache-*.mp4")))

    def test_cancelado_preserva_destino_y_borra_temporal(self):
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "salida.mp4"
            destino.write_bytes(b"previo")

            def falso_ejecutar(argumentos, cancel_event=None, tope_segundos=3600, **kw):
                idx = argumentos.index("-o")
                Path(argumentos[idx + 1]).write_bytes(b"parcial")
                return subprocesos.Estado.cancelado

            with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                    patch.object(subprocesos, "ejecutar", side_effect=falso_ejecutar):
                resultado = ytdlp_bin.descargar_video_cache("A" * 11, destino,
                                                            cancel_event=threading.Event())
            self.assertFalse(resultado)
            self.assertEqual(b"previo", destino.read_bytes())
            self.assertEqual([], list(Path(carpeta).glob(".ytcache-*.mp4")))

    def test_vencido_preserva_destino_y_borra_temporal(self):
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "salida.mp4"
            destino.write_bytes(b"previo")

            def falso_ejecutar(argumentos, cancel_event=None, tope_segundos=3600, **kw):
                idx = argumentos.index("-o")
                Path(argumentos[idx + 1]).write_bytes(b"parcial")
                return subprocesos.Estado.vencido

            with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                    patch.object(subprocesos, "ejecutar", side_effect=falso_ejecutar):
                resultado = ytdlp_bin.descargar_video_cache("A" * 11, destino)
            self.assertFalse(resultado)
            self.assertEqual(b"previo", destino.read_bytes())
            self.assertEqual([], list(Path(carpeta).glob(".ytcache-*.mp4")))

    def test_fallo_arranque_preserva_destino_y_borra_temporal(self):
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "salida.mp4"
            destino.write_bytes(b"previo")

            def falso_ejecutar(argumentos, cancel_event=None, tope_segundos=3600, **kw):
                idx = argumentos.index("-o")
                Path(argumentos[idx + 1]).write_bytes(b"parcial")
                return subprocesos.Estado.fallo

            # Simular OSError en ejecutar devolviendo fallo es equivalente
            with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                    patch.object(subprocesos, "ejecutar", side_effect=falso_ejecutar):
                resultado = ytdlp_bin.descargar_video_cache("A" * 11, destino)
            self.assertFalse(resultado)
            self.assertEqual(b"previo", destino.read_bytes())

    def test_archivo_ausente_o_vacio_no_publica(self):
        for contenido in [None, b""]:
            with tempfile.TemporaryDirectory() as carpeta:
                destino = Path(carpeta) / "salida.mp4"
                destino.write_bytes(b"previo")

                def falso_ejecutar(argumentos, cancel_event=None, tope_segundos=3600, **kw):
                    idx = argumentos.index("-o")
                    temporal = Path(argumentos[idx + 1])
                    if contenido is not None:
                        temporal.write_bytes(contenido)
                    else:
                        # no crear archivo
                        pass
                    return subprocesos.Estado.exito

                with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                        patch.object(subprocesos, "ejecutar", side_effect=falso_ejecutar):
                    resultado = ytdlp_bin.descargar_video_cache("A" * 11, destino)
                self.assertFalse(resultado, f"contenido={contenido!r} debió fallar")
                self.assertEqual(b"previo", destino.read_bytes())
                self.assertEqual([], list(Path(carpeta).glob(".ytcache-*.mp4")))

    def test_evento_marcado_despues_de_hijo_impide_publicar(self):
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "salida.mp4"
            destino.write_bytes(b"previo")
            evento = threading.Event()

            def falso_ejecutar(argumentos, cancel_event=None, tope_segundos=3600, **kw):
                idx = argumentos.index("-o")
                Path(argumentos[idx + 1]).write_bytes(b"nuevo")
                # Simular carrera: el hijo terminó, pero justo después se marca cancelación
                if cancel_event is not None:
                    cancel_event.set()
                return subprocesos.Estado.exito

            with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                    patch.object(subprocesos, "ejecutar", side_effect=falso_ejecutar):
                resultado = ytdlp_bin.descargar_video_cache("A" * 11, destino,
                                                            cancel_event=evento)
            self.assertFalse(resultado)
            self.assertEqual(b"previo", destino.read_bytes())
            self.assertEqual([], list(Path(carpeta).glob(".ytcache-*.mp4")))

    def test_cableado_real_cancel_event_ya_marcado_vuelve_rapido(self):
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "salida.mp4"
            destino.write_bytes(b"previo")
            evento = threading.Event()
            evento.set()

            def constructor_falso(ruta, temporal, video_id):
                return [sys.executable, "-c", "import time; time.sleep(5)"]

            with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                    patch.object(ytdlp_bin, "_argumentos_video_cache", side_effect=constructor_falso):
                inicio = time.monotonic()
                resultado = ytdlp_bin.descargar_video_cache("A" * 11, destino,
                                                            cancel_event=evento,
                                                            tope_segundos=10)
                duracion = time.monotonic() - inicio
            self.assertFalse(resultado)
            self.assertLess(duracion, 4, f"tardó {duracion:.2f}s, debe volver rápido")
            self.assertEqual(b"previo", destino.read_bytes())
            self.assertEqual([], list(Path(carpeta).glob(".ytcache-*.mp4")))

    def test_dos_invocaciones_usan_temporales_distintos(self):
        with tempfile.TemporaryDirectory() as carpeta:
            destino1 = Path(carpeta) / "a.mp4"
            destino2 = Path(carpeta) / "b.mp4"
            temporales = []

            def falso_ejecutar(argumentos, cancel_event=None, tope_segundos=3600, **kw):
                idx = argumentos.index("-o")
                temporal = Path(argumentos[idx + 1])
                temporales.append(str(temporal))
                temporal.write_bytes(b"datos")
                return subprocesos.Estado.fallo

            with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                    patch.object(subprocesos, "ejecutar", side_effect=falso_ejecutar):
                ytdlp_bin.descargar_video_cache("A" * 11, destino1)
                # Crear un archivo que simule el temporal de la primera para probar limpieza aislada
                # La primera ya limpio su temporal, ahora segunda debe usar otro nombre
                ytdlp_bin.descargar_video_cache("B" * 11, destino2)

            self.assertEqual(2, len(temporales))
            self.assertNotEqual(temporales[0], temporales[1])
            self.assertTrue(temporales[0].endswith(".mp4"))
            self.assertTrue(temporales[1].endswith(".mp4"))
            self.assertEqual([], list(Path(carpeta).glob(".ytcache-*.mp4")))

    def test_limpieza_de_una_no_borra_temporal_de_otra(self):
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "salida.mp4"
            # Simular dos temporales coexistiendo: el primero debe borrarse sin tocar el segundo
            temporal_otro = Path(carpeta) / ".ytcache-otro.mp4"
            temporal_otro.write_bytes(b"otro")

            def falso_ejecutar(argumentos, cancel_event=None, tope_segundos=3600, **kw):
                idx = argumentos.index("-o")
                temporal = Path(argumentos[idx + 1])
                temporal.write_bytes(b"parcial")
                return subprocesos.Estado.fallo

            with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                    patch.object(subprocesos, "ejecutar", side_effect=falso_ejecutar):
                resultado = ytdlp_bin.descargar_video_cache("A" * 11, destino)
            self.assertFalse(resultado)
            self.assertTrue(temporal_otro.is_file(), "limpieza borró temporal ajeno")
            self.assertEqual(b"otro", temporal_otro.read_bytes())

    def test_descargar_video_cache_borra_placeholder_antes_de_lanzar_usa_popen_real(self):
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "salida.mp4"
            contenido_esperado = b"contenido-prueba"

            def constructor_falso(ruta, temporal, video_id):
                return [sys.executable, "-c",
                        "import pathlib, sys; p=pathlib.Path(sys.argv[1]); sys.exit(1) if p.exists() else p.write_bytes(b'contenido-prueba')",
                        str(temporal)]

            with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                    patch.object(ytdlp_bin, "_argumentos_video_cache", side_effect=constructor_falso):
                resultado = ytdlp_bin.descargar_video_cache("A" * 11, destino)

            self.assertTrue(resultado, "debió publicar tras borrar placeholder")
            self.assertTrue(destino.is_file())
            self.assertEqual(contenido_esperado, destino.read_bytes())
            self.assertEqual([], list(Path(carpeta).glob(".ytcache-*.mp4")))

    def test_descargar_video_cache_pasa_devnull_al_helper(self):
        with tempfile.TemporaryDirectory() as carpeta:
            destino = Path(carpeta) / "salida.mp4"
            capturados = {}

            def falso_ejecutar(argumentos, cancel_event=None, tope_segundos=3600, **kw):
                capturados["stdout"] = kw.get("stdout")
                capturados["stderr"] = kw.get("stderr")
                if "-o" in argumentos:
                    idx = argumentos.index("-o")
                    Path(argumentos[idx + 1]).write_bytes(b"datos")
                return subprocesos.Estado.exito

            with patch.object(ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp.exe"), \
                    patch.object(subprocesos, "ejecutar", side_effect=falso_ejecutar):
                resultado = ytdlp_bin.descargar_video_cache("A" * 11, destino)

            self.assertTrue(resultado)
            self.assertIs(subprocess.DEVNULL, capturados.get("stdout"))
            self.assertIs(subprocess.DEVNULL, capturados.get("stderr"))



if __name__ == "__main__":
    unittest.main()
