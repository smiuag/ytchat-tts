from pathlib import Path
import tempfile
import unittest
from unittest import mock

import reproductor


class PruebasEsclavoReproductor(unittest.TestCase):

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parents[1])
        self.carpeta = Path(self.temporal.name)

    def tearDown(self):
        self.temporal.cleanup()

    def _panel(self):
        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._listo = True
        panel._video_id = "A" * 11
        panel._cargando = False
        panel._asegurar_player = mock.Mock(return_value=True)
        panel._timer_progreso = mock.Mock()
        panel._timer = mock.Mock()
        panel.lbl_estado = mock.Mock()
        panel._gen = 0
        panel._calidad_sel = 1080
        panel._vol = 80
        panel._muted = False
        panel._audio_local = None
        panel._descargar_video_cache = mock.Mock()
        return panel

    def _info_con_esclavo(self):
        return {"is_live": False, "formats": [
            {"url": "https://video", "height": 1080, "vcodec": "avc", "acodec": "none"},
            {"url": "https://audio", "vcodec": "none", "acodec": "opus", "abr": 128},
        ]}

    def _reproducir(self, panel, info):
        medio = mock.Mock()
        panel._info = info
        panel._inst = mock.Mock()
        panel._inst.media_new.return_value = medio
        panel._player = mock.Mock()
        panel._mostrar_pausa = mock.Mock()
        panel._error_carga = mock.Mock()
        relevo = mock.Mock()
        relevo.iniciar.return_value = None  # sin relevo: prueba el input-slave directo
        hilo = mock.Mock()
        hilo.start.side_effect = lambda: hilo.target()

        def crear(target, _nombre):
            hilo.target = target
            return hilo

        with mock.patch.object(reproductor, "anunciar"), \
                mock.patch.object(reproductor.diagnostico, "crear_hilo", side_effect=crear), \
                mock.patch.object(reproductor.wx, "CallAfter", side_effect=lambda fn, *a: fn(*a)), \
                mock.patch.object(reproductor.relevo_ffmpeg, "RelevoFfmpeg", return_value=relevo):
            panel._reproducir_calidad(1080, False)
        return medio

    def test_esclavo_utilizable_va_desde_disco(self):
        panel = self._panel()
        panel._audio_local = self.carpeta / "audio.webm"
        panel._audio_local.write_bytes(b"x" * 65536)
        medio = self._reproducir(panel, self._info_con_esclavo())
        medio.add_option.assert_any_call(f":input-slave={panel._audio_local}")

    def test_sin_audio_local_vuelve_a_url_de_red(self):
        medio = self._reproducir(self._panel(), self._info_con_esclavo())
        medio.add_option.assert_any_call(":input-slave=https://audio")

    def test_directo_usa_audio_de_red_aun_con_cache_utilizable(self):
        panel = self._panel()
        panel._audio_local = self.carpeta / "audio.webm"
        panel._audio_local.write_bytes(b"x" * 65536)
        info = self._info_con_esclavo()
        info["is_live"] = True
        medio = self._reproducir(panel, info)
        medio.add_option.assert_any_call(":input-slave=https://audio")
        self.assertFalse(any(f":input-slave={panel._audio_local}" in llamada.args[0]
                             for llamada in medio.add_option.call_args_list))

    def test_formato_progresivo_no_agrega_esclavo(self):
        info = {"is_live": False, "formats": [
            {"url": "https://progresivo", "height": 1080,
             "vcodec": "avc", "acodec": "opus"},
        ]}
        medio = self._reproducir(self._panel(), info)
        self.assertFalse(any(":input-slave=" in llamada.args[0]
                             for llamada in medio.add_option.call_args_list))

    def test_directo_no_descarga_audio(self):
        with mock.patch.object(reproductor.ytdlp_bin, "descargar_audio") as descargar:
            self.assertIsNone(reproductor._preparar_audio_local({"is_live": True}, "A" * 11))
        descargar.assert_not_called()

    def test_descarga_ocurre_dentro_del_hilo(self):
        panel = self._panel()
        hilo = mock.Mock()
        with mock.patch.object(reproductor, "_info_video", return_value=self._info_con_esclavo()), \
                mock.patch.object(reproductor.diagnostico, "crear_hilo", return_value=hilo) as crear, \
                mock.patch.object(reproductor.wx, "CallAfter") as llamar, \
                mock.patch.object(reproductor._cfg, "app_dir", return_value=self.carpeta), \
                mock.patch.object(reproductor.ytdlp_bin, "descargar_audio", return_value=False) as descargar:
            panel.cargar()
            descargar.assert_not_called()
            objetivo = crear.call_args.args[0]
            objetivo()
        descargar.assert_called_once()
        self.assertIsNone(llamar.call_args.args[-1])

    def test_descarga_fallida_deja_audio_local_en_none_y_sigue(self):
        panel = self._panel()
        panel._reproducir_calidad = mock.Mock()
        panel._info_listo(self._info_con_esclavo(), True, "A" * 11, 0,
                          audio_local=None)
        self.assertIsNone(panel._audio_local)
        panel._reproducir_calidad.assert_called_once()

    def test_excepcion_de_descarga_no_interrumpe(self):
        with mock.patch.object(reproductor._cfg, "app_dir", return_value=self.carpeta), \
                mock.patch.object(reproductor.ytdlp_bin, "descargar_audio",
                                  side_effect=OSError("fallo")):
            self.assertIsNone(reproductor._preparar_audio_local(
                self._info_con_esclavo(), "A" * 11))

    def test_poda_usa_tope_tres(self):
        with mock.patch.object(reproductor._cfg, "app_dir", return_value=self.carpeta), \
                mock.patch.object(reproductor.esclavo_audio, "sobrantes_de_cache",
                                  return_value=()) as podar, \
                mock.patch.object(reproductor.ytdlp_bin, "descargar_audio", return_value=False):
            reproductor._preparar_audio_local(self._info_con_esclavo(), "A" * 11)
        self.assertEqual(3, podar.call_args.args[1])

    def test_progreso_del_audio_anuncia_escalones_sin_repetir(self):
        def descargar(_video, _destino, aviso_progreso=None):
            for porcentaje in (10, 25, 50, 75, 80):
                aviso_progreso(porcentaje)
            return False

        with mock.patch.object(reproductor._cfg, "app_dir", return_value=self.carpeta), \
                mock.patch.object(reproductor.ytdlp_bin, "descargar_audio", side_effect=descargar), \
                mock.patch.object(reproductor.wx, "CallAfter") as llamar:
            reproductor._preparar_audio_local(self._info_con_esclavo(), "A" * 11)
        self.assertEqual([
            mock.call(reproductor.anunciar, "Preparando el audio, 25 por ciento"),
            mock.call(reproductor.anunciar, "Preparando el audio, 50 por ciento"),
            mock.call(reproductor.anunciar, "Preparando el audio, 75 por ciento"),
        ], llamar.call_args_list)

    def test_progreso_salta_a_ochenta_y_anuncia_una_sola_vez(self):
        def descargar(_video, _destino, aviso_progreso=None):
            for porcentaje in (10, 80):
                aviso_progreso(porcentaje)
            return False

        with mock.patch.object(reproductor._cfg, "app_dir", return_value=self.carpeta), \
                mock.patch.object(reproductor.ytdlp_bin, "descargar_audio", side_effect=descargar), \
                mock.patch.object(reproductor.wx, "CallAfter") as llamar:
            reproductor._preparar_audio_local(self._info_con_esclavo(), "A" * 11)
        self.assertEqual(
            [mock.call(reproductor.anunciar, "Preparando el audio, 75 por ciento")],
            llamar.call_args_list)


if __name__ == "__main__":
    unittest.main()
