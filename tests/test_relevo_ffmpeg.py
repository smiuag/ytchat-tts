import io
import socket
import subprocess
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
        with mock.patch("ffmpeg_bin.ruta_ffmpeg", return_value=None):
            self.assertIsNone(relevo.iniciar())
        self.assertFalse(relevo.activo())
        self.assertIsNone(relevo.direccion)

    def test_iniciar_si_popen_falla_devuelve_none(self):
        relevo = relevo_ffmpeg.RelevoFfmpeg("video", "audio")
        with mock.patch("ffmpeg_bin.ruta_ffmpeg", return_value="ffmpeg.exe"), \
                mock.patch("subprocess.Popen", side_effect=OSError("no se pudo")):
            self.assertIsNone(relevo.iniciar())
        self.assertFalse(relevo.activo())

    def test_iniciar_ok_arma_direccion_y_queda_activo(self):
        relevo = relevo_ffmpeg.RelevoFfmpeg("video", "audio")
        proceso = mock.Mock()
        proceso.poll.return_value = None
        with mock.patch("ffmpeg_bin.ruta_ffmpeg", return_value="ffmpeg.exe"), \
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
        with mock.patch("ffmpeg_bin.ruta_ffmpeg", return_value="ffmpeg.exe"), \
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
        with mock.patch("ffmpeg_bin.ruta_ffmpeg", return_value="ffmpeg.exe"), \
                mock.patch("subprocess.Popen", return_value=proceso), \
                mock.patch.object(relevo_ffmpeg, "puerto_libre", return_value=9999):
            relevo.iniciar()
        proceso.poll.return_value = 1
        self.assertFalse(relevo.activo())


class PruebasDesfase(unittest.TestCase):
    """Reiniciar ffmpeg unos segmentos antes del borde para poder retroceder."""

    def test_sin_desfase_el_comando_no_cambia(self):
        con = relevo_ffmpeg.argumentos_relevo("f", "v", "a", 5000, 0)
        sin = relevo_ffmpeg.argumentos_relevo("f", "v", "a", 5000)
        self.assertEqual(con, sin)
        self.assertNotIn("-live_start_index", con)

    def test_con_desfase_las_dos_entradas_arrancan_en_el_mismo_indice(self):
        argumentos = relevo_ffmpeg.argumentos_relevo("f", "v", "a", 5000, 12)
        esperado = str(-(12 + relevo_ffmpeg.SEGMENTOS_BORDE))
        self.assertEqual(argumentos[4:10], [
            "-live_start_index", esperado, "-i", "v",
            "-live_start_index", esperado])
        self.assertEqual(argumentos[10:12], ["-i", "a"])

    def test_relevo_pasa_su_desfase_al_comando(self):
        relevo = relevo_ffmpeg.RelevoFfmpeg("video", "audio", desfase_segmentos=7)
        self.assertEqual(relevo.desfase_segmentos, 7)
        proceso = mock.Mock()
        proceso.poll.return_value = None
        with mock.patch.object(relevo_ffmpeg.ffmpeg_bin, "ruta_ffmpeg",
                               return_value="ffmpeg.exe"), \
                mock.patch("subprocess.Popen", return_value=proceso) as popen, \
                mock.patch.object(relevo_ffmpeg, "puerto_libre", return_value=9999):
            relevo.iniciar()
        argumentos = popen.call_args.args[0]
        self.assertEqual(argumentos.count("-live_start_index"), 2)
        self.assertIn(str(-(7 + relevo_ffmpeg.SEGMENTOS_BORDE)), argumentos)
        relevo.detener()

    def test_ventana_hls_lee_duracion_y_cuenta_segmentos(self):
        lista = ("#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:5\n"
                 "#EXT-X-MEDIA-SEQUENCE:2460\n"
                 "#EXTINF:5.000,\nseg1.ts\n#EXTINF:5.000,\nseg2.ts\n#EXTINF:4.980,\nseg3.ts\n")
        self.assertEqual(relevo_ffmpeg.ventana_hls(lista), (5.0, 3))

    def test_ventana_hls_sin_segmentos_o_sin_duracion_es_none(self):
        self.assertIsNone(relevo_ffmpeg.ventana_hls("#EXTM3U\n#EXT-X-TARGETDURATION:5\n"))
        self.assertIsNone(relevo_ffmpeg.ventana_hls("#EXTM3U\n#EXTINF:5.0,\nseg.ts\n"))
        self.assertIsNone(relevo_ffmpeg.ventana_hls("no es una lista"))

    def test_leer_ventana_hls_tolera_fallos_de_red(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("sin red")):
            self.assertIsNone(relevo_ffmpeg.leer_ventana_hls("https://x/lista.m3u8"))

    def test_leer_ventana_hls_devuelve_la_ventana(self):
        respuesta = mock.MagicMock()
        respuesta.__enter__.return_value.read.return_value = (
            b"#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXTINF:5.0,\na.ts\n#EXTINF:5.0,\nb.ts\n")
        with mock.patch("urllib.request.urlopen", return_value=respuesta):
            self.assertEqual(relevo_ffmpeg.leer_ventana_hls("https://x/lista.m3u8"), (5.0, 2))


class PruebasListener(unittest.TestCase):
    """La espera al listener sondea el puerto en vez de dormir un tiempo
    fijo: ffmpeg tarda en abrirlo lo que tarde en sondear las dos HLS."""

    def test_escuchando_detecta_un_listener_real_sin_conectarse(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as servidor:
            servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            servidor.bind(("127.0.0.1", 0))
            servidor.listen(1)
            puerto = servidor.getsockname()[1]
            self.assertTrue(relevo_ffmpeg.escuchando(puerto))
            servidor.settimeout(0.2)
            with self.assertRaises(socket.timeout):
                servidor.accept()  # nadie se conectó: la sonda no consume el cliente

    def test_escuchando_con_puerto_libre_es_falso(self):
        self.assertFalse(relevo_ffmpeg.escuchando(relevo_ffmpeg.puerto_libre()))

    def test_esperar_listener_sigue_en_cuanto_escucha(self):
        reloj = iter([0.0, 0.1, 0.2, 0.3])
        dormidas = []
        sondas = iter([False, False, True])
        with mock.patch.object(relevo_ffmpeg, "escuchando",
                               side_effect=lambda _p: next(sondas)):
            listo = relevo_ffmpeg.esperar_listener(
                5000, lambda: True, timeout=10, intervalo=0.1,
                ahora=lambda: next(reloj), dormir=dormidas.append)
        self.assertTrue(listo)
        self.assertEqual(dormidas, [0.1, 0.1])

    def test_esperar_listener_si_ffmpeg_muere_devuelve_falso(self):
        vivo = iter([True, False])
        with mock.patch.object(relevo_ffmpeg, "escuchando", return_value=False):
            listo = relevo_ffmpeg.esperar_listener(
                5000, lambda: next(vivo), timeout=10, intervalo=0,
                ahora=lambda: 0.0, dormir=lambda _s: None)
        self.assertFalse(listo)

    def test_esperar_listener_vence_el_plazo(self):
        reloj = iter([0.0, 5.0, 21.0])
        with mock.patch.object(relevo_ffmpeg, "escuchando", return_value=False):
            listo = relevo_ffmpeg.esperar_listener(
                5000, lambda: True, timeout=20, intervalo=0,
                ahora=lambda: next(reloj), dormir=lambda _s: None)
        self.assertFalse(listo)

    def test_esperar_listo_sin_iniciar_es_falso(self):
        self.assertFalse(relevo_ffmpeg.RelevoFfmpeg("v", "a").esperar_listo())

    def test_esperar_listo_usa_el_puerto_y_la_vida_del_proceso(self):
        relevo = relevo_ffmpeg.RelevoFfmpeg("video", "audio")
        proceso = mock.Mock()
        proceso.poll.return_value = None
        with mock.patch("ffmpeg_bin.ruta_ffmpeg", return_value="ffmpeg.exe"), \
                mock.patch("subprocess.Popen", return_value=proceso), \
                mock.patch.object(relevo_ffmpeg, "puerto_libre", return_value=9999):
            relevo.iniciar()
        with mock.patch.object(relevo_ffmpeg, "esperar_listener",
                               return_value=True) as esperar:
            self.assertTrue(relevo.esperar_listo(timeout=3))
        esperar.assert_called_once_with(9999, relevo.activo, 3)
        relevo.detener()


class PruebasStderr(unittest.TestCase):
    """Lo que ffmpeg escribe por stderr (403, «Invalid data found») va al
    registro; antes iba a DEVNULL y el fallo del relevo no dejaba rastro."""

    def _sincrono(self):
        return mock.patch.object(
            relevo_ffmpeg.diagnostico, "crear_hilo",
            side_effect=lambda target, _n, args=(): mock.Mock(
                start=lambda: target(*args)))

    def test_iniciar_pide_stderr_por_tuberia(self):
        relevo = relevo_ffmpeg.RelevoFfmpeg("video", "audio")
        proceso = mock.Mock()
        proceso.poll.return_value = None
        with mock.patch("ffmpeg_bin.ruta_ffmpeg", return_value="ffmpeg.exe"), \
                mock.patch("subprocess.Popen", return_value=proceso) as popen, \
                mock.patch.object(relevo_ffmpeg, "puerto_libre", return_value=9999):
            relevo.iniciar()
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.PIPE)
        relevo.detener()

    def test_cada_linea_de_stderr_queda_en_el_registro(self):
        relevo = relevo_ffmpeg.RelevoFfmpeg("video", "audio")
        proceso = mock.Mock()
        proceso.poll.return_value = None
        proceso.pid = 4242
        proceso.stderr = io.BytesIO(
            b"HTTP error 403 Forbidden\nInvalid data found when processing input\n")
        with mock.patch("ffmpeg_bin.ruta_ffmpeg", return_value="ffmpeg.exe"), \
                mock.patch("subprocess.Popen", return_value=proceso), \
                mock.patch.object(relevo_ffmpeg, "puerto_libre", return_value=9999), \
                self._sincrono(), \
                self.assertLogs(relevo_ffmpeg.logger, level="WARNING") as registro:
            relevo.iniciar()
        self.assertEqual(len(registro.records), 2)
        self.assertIn("403 Forbidden", registro.output[0])
        self.assertIn("pid=4242", registro.output[0])
        self.assertIn("Invalid data found", registro.output[1])
        self.assertTrue(proceso.stderr.closed)
        relevo.detener()

    def test_stderr_que_no_es_un_flujo_se_ignora_sin_colgarse(self):
        # Las pruebas del ciclo de vida dan un Mock como proceso: leer de su
        # stderr (otro Mock) no terminaría nunca.
        for flujo in (None, mock.Mock(), object()):
            relevo_ffmpeg.volcar_stderr(flujo, 1)

    def test_detener_no_espera_al_lector(self):
        relevo = relevo_ffmpeg.RelevoFfmpeg("video", "audio")
        proceso = mock.Mock()
        proceso.poll.return_value = None
        proceso.stderr = io.BytesIO(b"")
        with mock.patch("ffmpeg_bin.ruta_ffmpeg", return_value="ffmpeg.exe"), \
                mock.patch("subprocess.Popen", return_value=proceso), \
                mock.patch.object(relevo_ffmpeg, "puerto_libre", return_value=9999):
            relevo.iniciar()
        relevo.detener()
        proceso.kill.assert_called_once()
        proceso.wait.assert_called_once_with(timeout=5)


class PruebasRelevosVivos(unittest.TestCase):
    """Un relevo iniciado queda registrado para matarlo al salir de la app
    aunque nadie llegue a llamar a detener() (cierre durante la preparación)."""

    def _iniciado(self):
        relevo = relevo_ffmpeg.RelevoFfmpeg("video", "audio")
        proceso = mock.Mock()
        proceso.poll.return_value = None
        with mock.patch("ffmpeg_bin.ruta_ffmpeg", return_value="ffmpeg.exe"), \
                mock.patch("subprocess.Popen", return_value=proceso), \
                mock.patch.object(relevo_ffmpeg, "puerto_libre", return_value=9999):
            relevo.iniciar()
        return relevo, proceso

    def test_iniciar_registra_y_detener_desregistra(self):
        relevo, _ = self._iniciado()
        self.assertIn(relevo, relevo_ffmpeg._VIVOS)
        relevo.detener()
        self.assertNotIn(relevo, relevo_ffmpeg._VIVOS)

    def test_detener_todos_mata_los_que_quedaban(self):
        relevo, proceso = self._iniciado()
        relevo_ffmpeg.detener_todos()
        proceso.kill.assert_called_once()
        self.assertNotIn(relevo, relevo_ffmpeg._VIVOS)


if __name__ == "__main__":
    unittest.main()
