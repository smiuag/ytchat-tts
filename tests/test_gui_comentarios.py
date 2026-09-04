"""Pruebas del cableado de escritura del panel de comentarios."""

import queue
import unittest
from unittest import mock

import wx

import gui_comentarios
import youtube_api


class DialogoFalso:
    instancias = []

    def __init__(self, parent, etiqueta, maximo, enviar, **kwargs):
        self.enviar = enviar
        self.__class__.instancias.append(self)

    def ShowModal(self):
        return wx.ID_OK

    def Destroy(self):
        pass


class TestComentariosPanel(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = wx.App() if not wx.App.Get() else wx.App.Get()
        cls.frame = wx.Frame(None)

    @classmethod
    def tearDownClass(cls):
        cls.frame.Destroy()

    def setUp(self):
        DialogoFalso.instancias = []
        self.parches = [
            mock.patch.object(gui_comentarios, "DialogoRedactar", DialogoFalso),
            mock.patch.object(gui_comentarios.credenciales, "hay_sesion", return_value=True),
            mock.patch.object(gui_comentarios.youtube_api, "google_disponible", return_value=True),
            mock.patch.object(gui_comentarios, "anunciar"),
            mock.patch.object(gui_comentarios._snd, "reproducir"),
        ]
        for parche in self.parches:
            parche.start()
        self.addCleanup(lambda: [parche.stop() for parche in reversed(self.parches)])
        self.panel = gui_comentarios.ComentariosPanel(
            self.frame, queue.Queue(), {"tamanio_fuente_chat": 12})
        self.addCleanup(self.panel.Destroy)

    def test_comentar_llega_al_envio(self):
        self.panel.set_video("video", autocargar=False)
        self.panel._enviar_escritura = mock.Mock()
        self.panel._comentar()
        DialogoFalso.instancias[0].enviar("texto")
        self.panel._enviar_escritura.assert_called_once()
        accion = self.panel._enviar_escritura.call_args.args[0]
        cliente = mock.Mock()
        accion(cliente)
        cliente.publicar_comentario.assert_called_once_with("video", "texto")

    def test_responder_llega_al_envio(self):
        comentario = youtube_api.Comentario("Ana", "hola", 0, "", 0,
                                             "comentario", "canal")
        self.panel._coms = [comentario]
        self.panel.lb.Append("Ana: hola")
        self.panel.lb.SetSelection(0)
        self.panel._enviar_escritura = mock.Mock()
        self.panel._responder()
        DialogoFalso.instancias[0].enviar("texto")
        self.panel._enviar_escritura.assert_called_once()
        accion = self.panel._enviar_escritura.call_args.args[0]
        cliente = mock.Mock()
        accion(cliente)
        cliente.responder_comentario.assert_called_once_with("comentario", "texto")

    def test_comentar_cerrado_no_abre_dialogo_y_anuncia(self):
        self.panel.set_video("video", autocargar=False)
        self.panel._comentarios_cerrados = True
        self.panel._comentar()
        self.assertEqual(DialogoFalso.instancias, [])
        gui_comentarios.anunciar.assert_called_once_with(
            "Este video tiene los comentarios desactivados")

    def test_error_de_comentarios_cerrados_se_olvida_al_cambiar_video(self):
        self.panel._pagina_err(Exception("commentsDisabled"))
        self.assertTrue(self.panel._comentarios_cerrados)
        self.panel.set_video("video", autocargar=False)
        self.assertFalse(self.panel._comentarios_cerrados)

    def _comentario(self, texto, identificador):
        return youtube_api.Comentario("Ana", texto, 0, "", 0, identificador, "canal")

    def test_la_pagina_de_un_video_anterior_se_descarta(self):
        # Una carga en curso del vídeo anterior que llega tarde no debe
        # aterrizar en el nuevo ni dejar «Cargar más» paginando el viejo.
        self.panel.set_video("viejo", autocargar=False)
        generacion_vieja = self.panel._generacion
        self.panel.set_video("nuevo", autocargar=False)
        self.panel._pagina_ok([self._comentario("del viejo", "c1")], "token-viejo",
                              generacion_vieja)
        self.assertEqual(self.panel.lb.GetCount(), 0)
        self.assertEqual(self.panel._next_token, "")
        self.assertFalse(self.panel.btn_mas.IsEnabled())

    def test_el_error_de_un_video_anterior_se_ignora(self):
        self.panel.set_video("viejo", autocargar=False)
        generacion_vieja = self.panel._generacion
        self.panel.set_video("nuevo", autocargar=False)
        self.panel._pagina_err(Exception("commentsDisabled"), generacion_vieja)
        self.assertFalse(self.panel._comentarios_cerrados)
        gui_comentarios.anunciar.assert_not_called()

    def test_la_pagina_del_video_vigente_si_se_muestra(self):
        self.panel.set_video("nuevo", autocargar=False)
        self.panel._pagina_ok([self._comentario("hola", "c1")], "mas",
                              self.panel._generacion)
        self.assertEqual(self.panel.lb.GetCount(), 1)
        self.assertEqual(self.panel._next_token, "mas")
        self.assertTrue(self.panel.btn_mas.IsEnabled())

    def test_cambiar_de_video_olvida_la_carga_en_curso(self):
        self.panel.set_video("viejo", autocargar=False)
        self.panel._cargando = True
        self.panel.btn_recargar.Disable()
        self.panel.set_video("nuevo", autocargar=False)
        self.assertFalse(self.panel._cargando)
        self.assertTrue(self.panel.btn_recargar.IsEnabled())
        self.panel.limpiar()
        self.assertEqual(self.panel._video_id, "")

    def test_la_carga_lleva_la_generacion_a_la_respuesta(self):
        self.panel.set_video("video", autocargar=False)
        cliente = mock.Mock(leer_comentarios=mock.Mock(return_value=([], "")))
        diferidos = []
        with mock.patch.object(gui_comentarios.credenciales, "hay_lectura", return_value=True), \
                mock.patch.object(self.panel, "_cliente", return_value=cliente), \
                mock.patch.object(gui_comentarios.diagnostico, "crear_hilo",
                                  side_effect=lambda objetivo, nombre: mock.Mock(start=objetivo)), \
                mock.patch.object(gui_comentarios.wx, "CallAfter",
                                  side_effect=lambda fn, *args: diferidos.append((fn, args))):
            self.panel._cargar_pagina("")
        self.assertEqual(diferidos, [(self.panel._pagina_ok, ([], "", self.panel._generacion))])
        gui_comentarios.anunciar.assert_called_once_with("Cargando comentarios", urgente=False)

    def test_aplicar_orden_recarga_pero_elegir_no(self):
        self.panel._recargar = mock.Mock()
        evento = wx.CommandEvent(wx.EVT_CHOICE.typeId, self.panel.cho_orden.GetId())
        evento.SetEventObject(self.panel.cho_orden)
        self.panel.cho_orden.GetEventHandler().ProcessEvent(evento)
        self.panel._recargar.assert_not_called()
        evento = wx.CommandEvent(wx.EVT_BUTTON.typeId,
                                 self.panel.btn_aplicar_orden.GetId())
        evento.SetEventObject(self.panel.btn_aplicar_orden)
        self.panel.btn_aplicar_orden.GetEventHandler().ProcessEvent(evento)
        self.panel._recargar.assert_called_once()


if __name__ == "__main__":
    unittest.main()
