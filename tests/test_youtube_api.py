"""Tests de los parsers puros de youtube_api (sin red ni libs de Google)."""

import unittest
import sys
import types
from unittest import mock

from youtube_api import (
    ClienteYouTube, normalizar_comentario, parsear_pagina_comentarios,
    comentarios_desactivados, mensaje_error_api,
)


class ServicioFalso:
    def __init__(self, respuesta):
        self.respuesta = respuesta

    def videos(self):
        return self

    def list(self, **kwargs):
        self.parametros = kwargs
        return self

    def execute(self):
        return self.respuesta


class TestDetallesDirecto(unittest.TestCase):

    def cliente(self, respuesta):
        cliente = ClienteYouTube({"api_key": "clave"})
        cliente._svc_lectura = ServicioFalso(respuesta)
        return cliente

    def test_respuesta_completa(self):
        cliente = self.cliente({"items": [{"liveStreamingDetails": {
            "concurrentViewers": "30",
            "actualStartTime": "2026-08-27T14:03:12Z",
        }}]})
        self.assertEqual(cliente.detalles_directo("abc"), {
            "espectadores": 30, "comienzo": "2026-08-27T14:03:12Z"})

    def test_respuesta_sin_espectadores(self):
        cliente = self.cliente({"items": [{"liveStreamingDetails": {
            "actualStartTime": "2026-08-27T14:03:12Z",
        }}]})
        self.assertEqual(cliente.detalles_directo("abc"), {
            "espectadores": None, "comienzo": "2026-08-27T14:03:12Z"})

    def test_respuesta_vacia(self):
        cliente = self.cliente({"items": []})
        self.assertEqual(cliente.detalles_directo("abc"), {
            "espectadores": None, "comienzo": ""})


class TestDatosChatDirecto(unittest.TestCase):

    def cliente(self, respuesta):
        cliente = ClienteYouTube({"api_key": "clave"})
        cliente._svc_lectura = ServicioFalso(respuesta)
        return cliente

    def test_sin_video(self):
        self.assertEqual(self.cliente({"items": []}).datos_chat_directo("abc"), {
            "hay_video": False, "hay_directo": False, "live_chat_id": ""})

    def test_video_que_no_es_directo(self):
        self.assertEqual(self.cliente({"items": [{}]}).datos_chat_directo("abc"), {
            "hay_video": True, "hay_directo": False, "live_chat_id": ""})

    def test_directo_con_chat(self):
        self.assertEqual(self.cliente({"items": [{"liveStreamingDetails": {
            "activeLiveChatId": "chat"}}]}).datos_chat_directo("abc"), {
            "hay_video": True, "hay_directo": True, "live_chat_id": "chat"})

    def test_resolvedor_conserva_el_id(self):
        self.assertEqual(self.cliente({"items": [{"liveStreamingDetails": {
            "activeLiveChatId": "chat"}}]}).resolver_live_chat_id("abc"), "chat")


class TestNormalizarComentario(unittest.TestCase):

    def test_basico(self):
        c = normalizar_comentario({
            "authorDisplayName": "Ana",
            "textOriginal": "hola",
            "likeCount": 5,
            "publishedAt": "2026-01-01T00:00:00Z",
            "authorChannelId": {"value": "UCabc"},
        }, comment_id="x1")
        self.assertEqual(c.autor, "Ana")
        self.assertEqual(c.texto, "hola")
        self.assertEqual(c.likes, 5)
        self.assertEqual(c.autor_canal_id, "UCabc")
        self.assertEqual(c.comment_id, "x1")
        self.assertFalse(c.es_respuesta)

    def test_campos_faltantes(self):
        c = normalizar_comentario({})
        self.assertEqual(c.autor, "Usuario")
        self.assertEqual(c.texto, "")
        self.assertEqual(c.likes, 0)
        self.assertEqual(c.autor_canal_id, "")

    def test_likecount_invalido(self):
        c = normalizar_comentario({"likeCount": "no-numero"})
        self.assertEqual(c.likes, 0)

    def test_textdisplay_como_respaldo(self):
        c = normalizar_comentario({"textDisplay": "<b>hola</b>"})
        self.assertEqual(c.texto, "<b>hola</b>")

    def test_canal_como_string(self):
        c = normalizar_comentario({"authorChannelId": "UCxyz"})
        self.assertEqual(c.autor_canal_id, "UCxyz")


class TestParsearPagina(unittest.TestCase):

    def _resp(self):
        return {
            "items": [{
                "snippet": {
                    "totalReplyCount": 1,
                    "topLevelComment": {
                        "id": "top1",
                        "snippet": {"authorDisplayName": "Ana", "textOriginal": "hola",
                                    "likeCount": 3},
                    },
                },
                "replies": {"comments": [{
                    "id": "rep1",
                    "snippet": {"authorDisplayName": "Beto", "textOriginal": "que tal"},
                }]},
            }],
            "nextPageToken": "NEXT",
        }

    def test_intercala_respuestas(self):
        coms, nxt = parsear_pagina_comentarios(self._resp())
        self.assertEqual(nxt, "NEXT")
        self.assertEqual(len(coms), 2)
        self.assertEqual(coms[0].autor, "Ana")
        self.assertEqual(coms[0].respuestas, 1)
        self.assertFalse(coms[0].es_respuesta)
        self.assertEqual(coms[1].autor, "Beto")
        self.assertTrue(coms[1].es_respuesta)

    def test_excluir_respuestas(self):
        coms, _ = parsear_pagina_comentarios(self._resp(), incluir_respuestas=False)
        self.assertEqual(len(coms), 1)
        self.assertEqual(coms[0].autor, "Ana")

    def test_respuesta_conserva_id_para_responder(self):
        coms, _ = parsear_pagina_comentarios(self._resp())
        self.assertEqual(coms[0].comment_id, "top1")
        self.assertEqual(coms[1].comment_id, "rep1")

    def test_pagina_vacia(self):
        coms, nxt = parsear_pagina_comentarios({})
        self.assertEqual(coms, [])
        self.assertEqual(nxt, "")


class TestMensajeError(unittest.TestCase):

    def test_quota(self):
        self.assertIn("cuota", mensaje_error_api("The request cannot be completed: quotaExceeded"))

    def test_comentarios_desactivados(self):
        self.assertIn("desactivados", mensaje_error_api("commentsDisabled"))

    def test_reconoce_comentarios_desactivados(self):
        self.assertTrue(comentarios_desactivados("commentsDisabled"))
        self.assertTrue(comentarios_desactivados("Disabled comments"))
        self.assertFalse(comentarios_desactivados("videoNotFound"))

    def test_video_no_encontrado(self):
        self.assertIn("vídeo", mensaje_error_api("videoNotFound"))

    def test_sin_permiso(self):
        self.assertIn("permiso", mensaje_error_api("insufficientPermissions"))

    def test_generico(self):
        self.assertIn("Error de la API", mensaje_error_api("algo raro"))


class TestCableadoChatDirecto(unittest.TestCase):

    def test_entrega_la_causa_a_la_interfaz(self):
        import main
        llamadas = []
        frame = types.SimpleNamespace(
            _alive=True, set_live_chat_id=lambda *args: llamadas.append(args))
        cliente = mock.Mock(datos_chat_directo=mock.Mock(return_value={
            "hay_video": True, "hay_directo": True, "live_chat_id": ""}))
        modulos = {
            "credenciales": types.SimpleNamespace(hay_lectura=lambda: True,
                                                    cargar=lambda: {}),
            "youtube_api": types.SimpleNamespace(
                google_disponible=lambda: True, ClienteYouTube=lambda _: cliente),
            "gui": types.SimpleNamespace(_gui_frame=frame),
            "wx": types.SimpleNamespace(CallAfter=lambda funcion, *args: funcion(*args)),
        }
        with mock.patch.dict(sys.modules, modulos):
            main._resolver_live_chat_id("abc")
        self.assertEqual(llamadas, [("", "chat_desactivado", "abc")])


if __name__ == "__main__":
    unittest.main()
