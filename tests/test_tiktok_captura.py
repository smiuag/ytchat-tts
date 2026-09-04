"""Tests de la lógica pura de tiktok_captura (detección de URLs y errores)."""

import threading
import unittest
from unittest import mock

import tiktok_captura
from tiktok_captura import (usuario_de_url, _mensaje_error, _es_error_permanente,
                            _mejor_flujo, autor_de_evento)


class TestUsuarioDeUrl(unittest.TestCase):

    def test_url_live_completa(self):
        self.assertEqual(
            usuario_de_url("https://www.tiktok.com/@tv_asahi_news/live"),
            "tv_asahi_news")

    def test_url_sin_live(self):
        self.assertEqual(
            usuario_de_url("https://www.tiktok.com/@usuario.x"), "usuario.x")

    def test_url_sin_esquema_ni_www(self):
        self.assertEqual(usuario_de_url("tiktok.com/@pepe/live"), "pepe")

    def test_url_movil(self):
        self.assertEqual(usuario_de_url("https://m.tiktok.com/@pepe/live"), "pepe")

    def test_con_query(self):
        self.assertEqual(
            usuario_de_url("https://www.tiktok.com/@pepe/live?lang=es"), "pepe")

    def test_usuario_suelto_no_vale(self):
        # Un "@usuario" sin dominio chocaría con los handles de YouTube.
        self.assertEqual(usuario_de_url("@pepe"), "")

    def test_youtube_no_es_tiktok(self):
        self.assertEqual(usuario_de_url("https://www.youtube.com/watch?v=abc"), "")
        self.assertEqual(usuario_de_url("https://youtu.be/dQw4w9WgXcQ"), "")

    def test_vacio_y_basura(self):
        self.assertEqual(usuario_de_url(""), "")
        self.assertEqual(usuario_de_url("   "), "")
        self.assertEqual(usuario_de_url("cualquier cosa"), "")

    def test_dominio_parecido_no_vale(self):
        self.assertEqual(usuario_de_url("https://notiktok.com/@pepe/live"), "")


class TestMensajesDeError(unittest.TestCase):

    def _exc(self, nombre, texto=""):
        return type(nombre, (Exception,), {})(texto)

    def test_offline_es_permanente_y_amigable(self):
        exc = self._exc("UserOfflineError", "user is offline")
        self.assertTrue(_es_error_permanente(exc))
        self.assertIn("no está en directo", _mensaje_error(exc))

    def test_usuario_inexistente(self):
        exc = self._exc("UserNotFoundError", "user not found")
        self.assertTrue(_es_error_permanente(exc))
        self.assertIn("No se encontró", _mensaje_error(exc))

    def test_error_generico_no_es_permanente(self):
        exc = Exception("connection reset by peer")
        self.assertFalse(_es_error_permanente(exc))
        self.assertIn("No se pudo conectar", _mensaje_error(exc))

    def test_error_de_firma(self):
        exc = self._exc("SignAPIError", "sign server unavailable")
        self.assertFalse(_es_error_permanente(exc))
        self.assertIn("firmas", _mensaje_error(exc))

    def test_404_del_servidor_de_firmas_no_es_usuario_inexistente(self):
        # httpx: «404 Not Found for url …eulerstream…». Antes, por la subcadena
        # «not found», se anunciaba usuario inexistente y se dejaba de reintentar.
        exc = self._exc("HTTPStatusError",
                        "Client error '404 Not Found' for url "
                        "'https://tiktok.eulerstream.com/webcast/sign_url'")
        self.assertFalse(_es_error_permanente(exc))
        self.assertNotIn("No se encontró", _mensaje_error(exc))
        self.assertIn("firmas", _mensaje_error(exc))

    def test_error_http_generico_es_transitorio(self):
        exc = self._exc("HTTPStatusError",
                        "Client error '404 Not Found' for url 'https://www.tiktok.com/x'")
        self.assertFalse(_es_error_permanente(exc))
        self.assertIn("HTTP", _mensaje_error(exc))

    def test_la_subcadena_sola_no_hace_permanente_un_error(self):
        self.assertFalse(_es_error_permanente(Exception("user not found")))
        self.assertFalse(_es_error_permanente(Exception("stream offline")))


class TestReconexion(unittest.TestCase):

    def _correr(self, sesion, max_intentos=3):
        estados = []
        with mock.patch.object(tiktok_captura, "disponible", return_value=True), \
                mock.patch.object(tiktok_captura, "_sesion", side_effect=sesion):
            tiktok_captura.capturar_con_reconexion(
                "pepe", {"max_intentos": max_intentos, "espera_entre_intentos": 0},
                threading.Event(), on_evento=lambda *a: None,
                on_estado=lambda tipo, texto: estados.append((tipo, texto)))
        return estados

    def test_los_intentos_se_reinician_tras_cada_reconexion(self):
        caidas = [0]

        def sesion(usuario, parada, on_evento, on_estado, on_info, on_espectadores,
                   anunciar_entradas=False):
            caidas[0] += 1
            on_estado("conectado", "ok")
            if caidas[0] >= 6:
                parada.set()
            return RuntimeError("microcorte")

        estados = self._correr(sesion, max_intentos=3)
        self.assertEqual(caidas[0], 6)
        self.assertFalse(any("agotaron" in texto for _, texto in estados))

    def test_los_fallos_seguidos_si_agotan_los_intentos(self):
        def sesion(*args, **kwargs):
            return RuntimeError("no conecta")

        estados = self._correr(sesion, max_intentos=3)
        self.assertTrue(any("agotaron los 3" in texto for _, texto in estados))


class TestMejorFlujo(unittest.TestCase):
    """Se prefiere el FLV: el HLS de TikTok suele dar timeout en el reproductor."""

    def test_prefiere_flv_hd_sobre_sd_y_hls(self):
        stream = {"flv_pull_url": {"HD1": "http://x/hd.flv", "SD1": "http://x/sd.flv"},
                  "hls_pull_url": "http://x/i.m3u8"}
        self.assertEqual(_mejor_flujo(stream), "http://x/hd.flv")

    def test_cae_a_sd_si_no_hay_hd(self):
        self.assertEqual(_mejor_flujo({"flv_pull_url": {"SD1": "http://x/sd.flv"}}),
                         "http://x/sd.flv")

    def test_cae_a_hls_si_no_hay_flv(self):
        self.assertEqual(_mejor_flujo({"hls_pull_url": "http://x/i.m3u8"}),
                         "http://x/i.m3u8")

    def test_rtmp_como_ultimo_recurso(self):
        self.assertEqual(_mejor_flujo({"rtmp_pull_url": "http://x/s.flv"}),
                         "http://x/s.flv")

    def test_vacio_si_no_hay_nada(self):
        self.assertEqual(_mejor_flujo({}), "")
        self.assertEqual(_mejor_flujo({"flv_pull_url": {}}), "")


class TestAutorDeEvento(unittest.TestCase):
    """Regresión del bug del wrapper .user: el autor debe leerse del proto crudo
    por su campo REAL (nick_name), sin depender del alias `nickname` ni de .user
    (que crashea con betterproto 2.0.0b7)."""

    class _UserInfoPlano:
        # Simula el `User` plano de un evento real: solo el campo real nick_name.
        def __init__(self, nick_name="", username="", ident=0):
            self.nick_name = nick_name
            self.username = username
            self.id = ident
        def __getattr__(self, n):
            # El alias `nickname` (y otros) no existe en un User plano: lanza,
            # como hace betterproto.
            raise AttributeError(n)

    class _EventoComentario:
        def __init__(self, user_info):
            self.user_info = user_info

    class _EventoUserCrash:
        # Regalo/suscripción sin user_info y con .user que revienta.
        user_info = None
        @property
        def user(self):
            raise TypeError("User.__init__() got an unexpected keyword argument 'nickName'")

    def test_lee_nick_name_real(self):
        ev = self._EventoComentario(self._UserInfoPlano(nick_name="María José", ident=7))
        nombre, ident = autor_de_evento(ev)
        self.assertEqual(nombre, "María José")
        self.assertEqual(ident, "7")

    def test_respaldo_username_si_no_hay_nick(self):
        ev = self._EventoComentario(self._UserInfoPlano(username="mariaj"))
        nombre, _ = autor_de_evento(ev)
        self.assertEqual(nombre, "mariaj")

    def test_user_que_crashea_no_tira_el_evento(self):
        # Antes esto reventaba y se perdía el evento; ahora cae a «Usuario».
        nombre, ident = autor_de_evento(self._EventoUserCrash())
        self.assertEqual(nombre, "Usuario")
        self.assertEqual(ident, "")


if __name__ == "__main__":
    unittest.main()
