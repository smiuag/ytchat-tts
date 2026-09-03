import socket
import unittest
from unittest import mock

import relevo_ffmpeg


class PruebasRelevoFfmpeg(unittest.TestCase):

    def test_puerto_libre_devuelve_uno_usable(self):
        puerto = relevo_ffmpeg.puerto_libre()
        # Si de verdad esta libre, se puede volver a atar sin que reviente.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", puerto))

    def test_puertos_libres_consecutivos_no_chocan(self):
        a = relevo_ffmpeg.puerto_libre()
        b = relevo_ffmpeg.puerto_libre()
        self.assertNotEqual(a, b)

    def test_direccion_relevo(self):
        self.assertEqual(relevo_ffmpeg.direccion_relevo(1234),
                         "tcp://127.0.0.1:1234")

    def test_argumentos_relevo_copia_sin_recodificar(self):
        argumentos = relevo_ffmpeg.argumentos_relevo(
            "ffmpeg.exe", "https://video.example/hls.m3u8",
            "https://audio.example/hls.m3u8", 5000)
        self.assertEqual(argumentos, [
            "ffmpeg.exe", "-loglevel", "warning", "-nostdin",
            "-i", "https://video.example/hls.m3u8",
            "-i", "https://audio.example/hls.m3u8",
            "-map", "0:v:0", "-map", "1:a:0",
            "-c", "copy", "-f", "mpegts", "-listen", "1",
            "tcp://127.0.0.1:5000",
        ])


class PruebasCicloDeVida(unittest.TestCase):

    def test_iniciar_sin_ffmpeg_devuelve_none(self):
        relevo = relevo_ffmpeg.RelevoFfmpeg("video", "audio")
        with mock.patch("imageio_ffmpeg.get_ffmpeg_exe",
                        side_effect=Exception("no hay ffmpeg")):
            self.assertIsNone(relevo.iniciar())
        self.assertFalse(relevo.activo())
        self.assertIsNone(relevo.direccion)

    def test_iniciar_si_popen_falla_devuelve_none(self):
        relevo = relevo_ffmpeg.RelevoFfmpeg("video", "audio")
        with mock.patch("imageio_ffmpeg.get_ffmpeg_exe", return_value="ffmpeg.exe"), \
                mock.patch("subprocess.Popen", side_effect=OSError("no se pudo")):
            self.assertIsNone(relevo.iniciar())
        self.assertFalse(relevo.activo())

    def test_iniciar_ok_arma_direccion_y_queda_activo(self):
        relevo = relevo_ffmpeg.RelevoFfmpeg("video", "audio")
        proceso = mock.Mock()
        proceso.poll.return_value = None
        with mock.patch("imageio_ffmpeg.get_ffmpeg_exe", return_value="ffmpeg.exe"), \
                mock.patch("subprocess.Popen", return_value=proceso), \
                mock.patch.object(relevo_ffmpeg, "puerto_libre", return_value=9999):
            direccion = relevo.iniciar()
        self.assertEqual(direccion, "tcp://127.0.0.1:9999")
        self.assertEqual(relevo.direccion, "tcp://127.0.0.1:9999")
        self.assertTrue(relevo.activo())

    def test_detener_mata_el_proceso_y_limpia_estado(self):
        relevo = relevo_ffmpeg.RelevoFfmpeg("video", "audio")
        proceso = mock.Mock()
        proceso.poll.return_value = None
        with mock.patch("imageio_ffmpeg.get_ffmpeg_exe", return_value="ffmpeg.exe"), \
                mock.patch("subprocess.Popen", return_value=proceso), \
                mock.patch.object(relevo_ffmpeg, "puerto_libre", return_value=9999):
            relevo.iniciar()
        relevo.detener()
        proceso.kill.assert_called_once()
        self.assertFalse(relevo.activo())
        self.assertIsNone(relevo.direccion)

    def test_detener_sin_haber_iniciado_no_revienta(self):
        relevo_ffmpeg.RelevoFfmpeg("video", "audio").detener()

    def test_activo_si_el_proceso_termino_solo(self):
        relevo = relevo_ffmpeg.RelevoFfmpeg("video", "audio")
        proceso = mock.Mock()
        proceso.poll.return_value = None
        with mock.patch("imageio_ffmpeg.get_ffmpeg_exe", return_value="ffmpeg.exe"), \
                mock.patch("subprocess.Popen", return_value=proceso), \
                mock.patch.object(relevo_ffmpeg, "puerto_libre", return_value=9999):
            relevo.iniciar()
        proceso.poll.return_value = 1
        self.assertFalse(relevo.activo())


if __name__ == "__main__":
    unittest.main()
