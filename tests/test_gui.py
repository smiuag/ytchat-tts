"""Pruebas de la salida accesible de los registros."""

import logging
import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import gui
import gui_comentarios
import gui_preferencias
import config
import reproductor
import apagado
import alias
import programados
import ytdlp_bin
from lista_chat import MensajeChat, ListaChat


class TestInicioGui(unittest.TestCase):

    def _menu_frame(self):
        frame = mock.Mock()
        frame._accel.return_value = ""
        elementos = []

        def crear_menu():
            menu = mock.MagicMock()

            def agregar(*args):
                elemento = mock.Mock()
                elementos.append((args[-1], elemento))
                return elemento

            menu.Append.side_effect = agregar
            menu.AppendRadioItem.side_effect = lambda *args: mock.Mock()
            menu.AppendCheckItem.side_effect = lambda *args: mock.Mock()
            return menu

        with mock.patch.object(gui.wx, "Menu", side_effect=crear_menu), \
                mock.patch.object(gui.wx, "MenuBar"):
            gui.YTChatFrame._build_menubar(frame)
        frame._elementos_menu = elementos
        return frame

    def _handler_menu(self, frame, elemento):
        return next(llamada.args[1] for llamada in frame.Bind.call_args_list
                    if llamada.args[2] is elemento)

    def _elemento_menu(self, frame, texto):
        return next(elemento for etiqueta, elemento in frame._elementos_menu
                    if texto in etiqueta)

    def test_muestra_trae_al_frente_y_enfoca_la_url_en_ese_orden(self):
        orden = []
        aplicacion = mock.Mock()
        frame = mock.Mock()
        frame.txt_url.SetFocus.side_effect = lambda: orden.append("foco")
        frame.Show.side_effect = lambda: orden.append("muestra")
        frame.Raise.side_effect = lambda: orden.append("frente")
        configuracion = mock.Mock()
        configuracion.get.return_value = ""

        with mock.patch.object(gui, "AplicacionYTChat", return_value=aplicacion), \
                mock.patch.object(gui, "YTChatFrame", return_value=frame), \
                mock.patch.object(gui, "app_dir", return_value=Path(".")), \
                mock.patch.object(gui, "_ao2_init"), \
                mock.patch.object(gui, "_listar_voces_sapi5", return_value=[]), \
                mock.patch.object(gui._snd, "reproducir"), \
                mock.patch.object(gui.wx, "CallAfter"):
            gui.iniciar_gui(configuracion, object(), object(), object(), object())

        self.assertEqual(orden, ["muestra", "frente", "foco"])

    def test_inicio_programa_el_precalentamiento(self):
        aplicacion = mock.Mock()
        frame = mock.Mock()
        configuracion = mock.Mock()
        configuracion.get.return_value = ""

        with mock.patch.object(gui, "AplicacionYTChat", return_value=aplicacion), \
                mock.patch.object(gui, "YTChatFrame", return_value=frame), \
                mock.patch.object(gui, "app_dir", return_value=Path(".")), \
                mock.patch.object(gui, "_ao2_init"), \
                mock.patch.object(gui, "_listar_voces_sapi5", return_value=[]), \
                mock.patch.object(gui._snd, "reproducir"), \
                mock.patch.object(gui.wx, "CallAfter") as call_after:
            gui.iniciar_gui(configuracion, object(), object(), object(), object())

        call_after.assert_any_call(frame._arrancar_precalentamiento)

    def test_asercion_de_wx_se_registra_sin_anunciarse(self):
        aplicacion = mock.Mock()
        with mock.patch.object(gui.logger, "warning") as registrar, \
                mock.patch.object(gui, "anunciar") as anunciar:
            gui.AplicacionYTChat.OnAssert(
                aplicacion, "ventana.cpp", 42, "indice < total", "índice inválido")

        registrar.assert_called_once_with(
            "wx aserción archivo=%s línea=%s condición=%s mensaje=%s",
            "ventana.cpp", 42, "indice < total", "índice inválido")
        anunciar.assert_not_called()

    def test_fin_de_sesion_usa_el_cierre_normal_de_la_ventana(self):
        aplicacion = mock.Mock()
        ventana = mock.Mock()
        evento = object()
        anterior = gui._gui_frame
        try:
            gui._gui_frame = ventana
            gui.AplicacionYTChat._on_fin_sesion(aplicacion, evento)
        finally:
            gui._gui_frame = anterior

        ventana._on_close.assert_called_once_with(evento)

    def test_menu_conectar_difiere_la_conexion(self):
        frame = self._menu_frame()
        conexion = self._handler_menu(frame, frame.mi_conectar)
        with mock.patch.object(gui.wx, "CallAfter") as diferir:
            conexion(mock.Mock())

        diferir.assert_called_once_with(frame._conectar_si_procede)
        frame._conectar_si_procede.assert_not_called()

    def test_menu_historial_difiere_la_apertura(self):
        frame = self._menu_frame()
        historial = self._handler_menu(
            frame, self._elemento_menu(frame, "Historial de directos"))
        with mock.patch.object(gui.wx, "CallAfter") as diferir:
            historial(mock.Mock())
        diferir.assert_called_once_with(frame._on_historial)
        frame._on_historial.assert_not_called()

    def test_menu_descargar_este_video_difiere_la_apertura(self):
        frame = self._menu_frame()
        url = "https://www.youtube.com/watch?v=prueba"
        frame._rep_panel.get_url_para_descarga.return_value = url
        descargar = self._handler_menu(frame, frame.mi_descargar_este)
        with mock.patch.object(gui.wx, "CallAfter") as diferir:
            descargar(mock.Mock())
        diferir.assert_called_once_with(frame._abrir_descargas, url=url)
        frame._abrir_descargas.assert_not_called()

    def test_menu_transmision_difiere_la_apertura(self):
        frame = self._menu_frame()
        transmision = self._handler_menu(frame, frame.mi_transmision)
        with mock.patch.object(gui.wx, "CallAfter") as diferir:
            transmision(mock.Mock())
        diferir.assert_called_once_with(frame._on_transmision, None)
        frame._on_transmision.assert_not_called()

    def test_menu_descargas_difiere_la_apertura(self):
        frame = self._menu_frame()
        descargas = self._handler_menu(frame, frame.mi_descargas)
        with mock.patch.object(gui.wx, "CallAfter") as diferir:
            descargas(mock.Mock())
        diferir.assert_called_once_with(frame._abrir_descargas)
        frame._abrir_descargas.assert_not_called()

    def test_menu_actualizar_ytdlp_difiere_la_apertura(self):
        frame = self._menu_frame()
        actualizar = self._handler_menu(frame, frame.mi_actualizar_ytdlp)
        with mock.patch.object(gui.wx, "CallAfter") as diferir:
            actualizar(mock.Mock())
        diferir.assert_called_once_with(frame._on_actualizar_ytdlp, None)
        frame._on_actualizar_ytdlp.assert_not_called()

    def test_menu_preferencias_difiere_la_apertura(self):
        frame = self._menu_frame()
        preferencias = self._handler_menu(
            frame, self._elemento_menu(frame, "Preferencias"))
        with mock.patch.object(gui.wx, "CallAfter") as diferir:
            preferencias(mock.Mock())
        diferir.assert_called_once_with(frame._on_preferencias, None)
        frame._on_preferencias.assert_not_called()

    def test_menu_acerca_de_difiere_la_apertura(self):
        frame = self._menu_frame()
        acerca_de = self._handler_menu(
            frame, self._elemento_menu(frame, "Acerca de"))
        with mock.patch.object(gui.wx, "CallAfter") as diferir:
            acerca_de(mock.Mock())
        diferir.assert_called_once_with(frame._on_about, None)
        frame._on_about.assert_not_called()

    def test_bind_menu_difiere_el_manejador(self):
        frame = mock.Mock()
        item = mock.Mock()
        manejador = mock.Mock()
        gui.YTChatFrame._bind_menu(frame, item, manejador)
        evento = frame.Bind.call_args.args[1]
        diferidos = []

        with mock.patch.object(gui.wx, "CallAfter",
                               side_effect=lambda fn, *args: diferidos.append((fn, args))):
            evento(mock.Mock())

        manejador.assert_not_called()
        diferidos[0][0](*diferidos[0][1])
        manejador.assert_called_once_with()

    def test_bind_menu_pasa_los_argumentos_en_orden(self):
        frame = mock.Mock()
        item = mock.Mock()
        manejador = mock.Mock()
        gui.YTChatFrame._bind_menu(frame, item, manejador, "primero", 2, True)
        evento = frame.Bind.call_args.args[1]

        with mock.patch.object(gui.wx, "CallAfter") as diferir:
            evento(mock.Mock())

        diferir.assert_called_once_with(manejador, "primero", 2, True)

    def test_reconstruir_el_menu_destruye_el_anterior_y_conserva_reanudar(self):
        # Preferencias reconstruye la barra: la vieja se destruye y el ítem de
        # pausa sale con el estado real de la lectura, no siempre «Pausar».
        frame = mock.Mock()
        frame._accel.return_value = ""
        frame._worker.esta_pausado.return_value = True
        with mock.patch.object(gui.wx, "Menu"), \
                mock.patch.object(gui.wx, "MenuBar"):
            gui.YTChatFrame._build_menubar(frame)

        frame.GetMenuBar.return_value.Destroy.assert_called_once_with()
        frame._sincronizar_pausa.assert_called_once_with()
        gui.YTChatFrame._sincronizar_pausa(frame)
        frame.mi_pausa.SetItemLabel.assert_called_once_with("&Reanudar lectura")

    def test_sincronizar_pausa_sin_worker_no_revienta(self):
        frame = mock.Mock()
        frame._worker.esta_pausado.side_effect = AttributeError
        gui.YTChatFrame._sincronizar_pausa(frame)
        frame.mi_pausa.SetItemLabel.assert_not_called()

    def test_contador_accesible_selecciona_todo_al_recibir_el_foco(self):
        contador = mock.Mock()
        contador.GetTextValue.return_value = "123"
        evento = mock.Mock()

        gui.ContadorAccesible._on_focus(contador, evento)

        contador.SetSelection.assert_called_once_with(0, 3)
        evento.Skip.assert_called_once_with()


class EventoTecladoFalso:
    def __init__(self, codigo, modificadores=0):
        self.codigo = codigo
        self.modificadores = modificadores
        self.omitido = False

    def GetKeyCode(self):
        return self.codigo

    def GetModifiers(self):
        return self.modificadores

    def Skip(self):
        self.omitido = True


class TestEnterEnListas(unittest.TestCase):

    def test_chat_alt_enter_se_deja_pasar_al_acelerador(self):
        # Alt+Enter es el acelerador de «Enviar mensaje»: no debe copiar.
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame._copiar_mensaje = mock.Mock()
        evento = EventoTecladoFalso(gui.wx.WXK_RETURN, gui.wx.MOD_ALT)
        frame._on_chat_char_hook(evento)
        frame._copiar_mensaje.assert_not_called()
        self.assertTrue(evento.omitido)

    def test_comentarios_alt_enter_se_deja_pasar_al_acelerador(self):
        panel = gui_comentarios.ComentariosPanel.__new__(
            gui_comentarios.ComentariosPanel)
        panel._leer = mock.Mock()
        evento = EventoTecladoFalso(gui_comentarios.wx.WXK_RETURN, gui_comentarios.wx.MOD_ALT)
        panel._on_char_hook(evento)
        panel._leer.assert_not_called()
        self.assertTrue(evento.omitido)

    def test_chat_enlaza_el_gancho_de_caracteres(self):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame.lb_chat = mock.Mock()
        frame._enlazar_eventos_chat()
        enlaces = [llamada.args[0] for llamada in frame.lb_chat.Bind.call_args_list]
        self.assertIn(gui.wx.EVT_CHAR_HOOK, enlaces)

    def test_chat_enter_copia_sin_omitirlo(self):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame._copiar_mensaje = mock.Mock()
        evento = EventoTecladoFalso(gui.wx.WXK_RETURN)
        frame._on_chat_char_hook(evento)
        frame._copiar_mensaje.assert_called_once_with()
        self.assertFalse(evento.omitido)

    def test_chat_otra_tecla_se_deja_pasar(self):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame._copiar_mensaje = mock.Mock()
        evento = EventoTecladoFalso(ord("a"))
        frame._on_chat_char_hook(evento)
        frame._copiar_mensaje.assert_not_called()
        self.assertTrue(evento.omitido)

    def test_comentarios_enlaza_el_gancho_de_caracteres(self):
        panel = gui_comentarios.ComentariosPanel.__new__(
            gui_comentarios.ComentariosPanel)
        panel.lb = mock.Mock()
        panel._enlazar_eventos_lista()
        enlaces = [llamada.args[0] for llamada in panel.lb.Bind.call_args_list]
        self.assertIn(gui_comentarios.wx.EVT_CHAR_HOOK, enlaces)

    def test_comentarios_enter_lee_sin_omitirlo(self):
        panel = gui_comentarios.ComentariosPanel.__new__(
            gui_comentarios.ComentariosPanel)
        panel._leer = mock.Mock()
        evento = EventoTecladoFalso(gui_comentarios.wx.WXK_RETURN)
        panel._on_char_hook(evento)
        panel._leer.assert_called_once_with()
        self.assertFalse(evento.omitido)

    def test_comentarios_otra_tecla_se_deja_pasar(self):
        panel = gui_comentarios.ComentariosPanel.__new__(
            gui_comentarios.ComentariosPanel)
        panel._leer = mock.Mock()
        evento = EventoTecladoFalso(ord("a"))
        panel._on_char_hook(evento)
        panel._leer.assert_not_called()
        self.assertTrue(evento.omitido)


class TestComentariosPanel(unittest.TestCase):

    def _panel_sin_api_key(self):
        app = gui_comentarios.wx.App(False)
        frame = gui_comentarios.wx.Frame(None)
        self.addCleanup(frame.Destroy)
        self.addCleanup(app.Destroy)
        hay_lectura = self.enterContext(mock.patch.object(gui_comentarios.credenciales, "hay_lectura", return_value=False))
        parches = ((gui_comentarios.youtube_api, "google_disponible", True),
                   (gui_comentarios.credenciales, "hay_sesion", False),
                   (gui_comentarios, "anunciar", None))
        for objeto, nombre, valor in parches:
            self.enterContext(mock.patch.object(objeto, nombre, return_value=valor))
        self.enterContext(mock.patch.object(gui_comentarios.wx, "MessageBox",
                                             side_effect=AssertionError("Se abrió un modal")))
        return gui_comentarios.ComentariosPanel(frame, queue.Queue(), {"tamanio_fuente_chat": 12}), hay_lectura

    def test_autocarga_sin_api_key_muestra_aviso_sin_modal(self):
        panel, _ = self._panel_sin_api_key()
        panel.set_video("unvideo", autocargar=True)
        self.assertEqual(panel.lb.GetCount(), 1)
        self.assertEqual(panel.lb.GetString(0),
                         "Falta la API key. Ponla en Preferencias, pestaña API, "
                         "para leer comentarios.")
        self.assertEqual(panel._video_id, "unvideo")
        self.assertNotIn("conectate a un video", panel.btn_comentar.GetLabel().lower())

    def test_recargar_tras_agregar_api_key_carga_el_video_recordado(self):
        panel, hay_lectura = self._panel_sin_api_key()
        panel.set_video("unvideo", autocargar=True)
        hay_lectura.return_value = True
        cliente = mock.Mock(leer_comentarios=mock.Mock(return_value=([], "")))
        def hilo_inmediato(objetivo, nombre):
            return mock.Mock(start=objetivo)

        with mock.patch.object(panel, "_cliente", return_value=cliente), \
                mock.patch.object(gui_comentarios.diagnostico, "crear_hilo",
                                  side_effect=hilo_inmediato):
            panel._recargar()
        cliente.leer_comentarios.assert_called_once_with("unvideo", page_token="", orden="relevance")

    def test_mostrar_no_disponible_olvida_el_video(self):
        panel, _ = self._panel_sin_api_key()
        panel.set_video("unvideo", autocargar=False)
        panel.mostrar_no_disponible("No hay comentarios aquí.")
        self.assertEqual(panel._video_id, "")


class GrabadorDeVoz:
    """Ocupa el lugar del lector de pantalla y anota lo que se le diría."""

    def __init__(self):
        self.hablado = []
        self.interrupciones = []
        self.brailleado = []

    def speak(self, texto, interrupt=None):
        self.hablado.append(texto)
        self.interrupciones.append(interrupt)

    def braille(self, texto):
        self.brailleado.append(texto)


class TestRegistroEsAnunciable(unittest.TestCase):

    def test_obs_vigilante_si_se_anuncia(self):
        self.assertTrue(gui.registro_es_anunciable("ytchat.obs_vigilante"))

    def test_diagnostico_no_se_anuncia(self):
        self.assertFalse(gui.registro_es_anunciable("ytchat.diagnostico"))

    def test_tecnicos_no_se_anuncian(self):
        for nombre in ("ytchat.descargas", "ytchat.main", "ytchat.tts_worker",
                       "ytchat.sound_player"):
            with self.subTest(nombre=nombre):
                self.assertFalse(gui.registro_es_anunciable(nombre))

    def test_nombres_vacios_no_se_anuncian(self):
        self.assertFalse(gui.registro_es_anunciable(""))
        self.assertFalse(gui.registro_es_anunciable(None))

    def test_manejador_consulta_el_nombre_del_registro(self):
        manejador = gui.WxAnnouncingHandler()
        registro = logging.LogRecord(
            "diagnostico.hilos", logging.INFO, __file__, 1, "oculto", (), None)
        with mock.patch.object(gui, "registro_es_anunciable", return_value=False) as decidir:
            with mock.patch.object(gui, "anunciar") as anunciar:
                manejador.emit(registro)
        decidir.assert_called_once_with("diagnostico.hilos")
        anunciar.assert_not_called()

    def test_anunciar_interrumpe_por_defecto(self):
        grabador = GrabadorDeVoz()
        with mock.patch.object(gui, "_ao2", grabador):
            gui.anunciar("hola")

        self.assertEqual(grabador.hablado, ["hola"])
        self.assertEqual(grabador.interrupciones, [True])

    def test_anunciar_no_interrumpe_si_no_es_urgente(self):
        grabador = GrabadorDeVoz()
        with mock.patch.object(gui, "_ao2", grabador):
            gui.anunciar("hola", urgente=False)

        self.assertEqual(grabador.interrupciones, [False])

    def test_anunciar_desde_otro_hilo_se_reenvia_al_hilo_principal(self):
        # La voz va por COM: desde un hilo ajeno no se habla, se difiere.
        grabador = GrabadorDeVoz()
        with mock.patch.object(gui, "_ao2", grabador), \
                mock.patch.object(gui.wx, "IsMainThread", return_value=False), \
                mock.patch.object(gui.wx, "CallAfter") as diferir:
            gui.anunciar("hola", urgente=False)

        diferir.assert_called_once_with(gui.anunciar, "hola", False)
        self.assertEqual(grabador.hablado, [])
        self.assertEqual(grabador.brailleado, [])

    def test_anunciar_envia_braille_en_los_dos_casos(self):
        grabador = GrabadorDeVoz()
        with mock.patch.object(gui, "_ao2", grabador):
            gui.anunciar("urgente")
            gui.anunciar("no urgente", urgente=False)

        self.assertEqual(grabador.brailleado, ["urgente", "no urgente"])

    def test_anunciar_registra_el_fallo_de_voz_sin_propagarse(self):
        salida = mock.Mock()
        salida.speak.side_effect = RuntimeError("COM no disponible")
        with mock.patch.object(gui, "_ao2", salida), \
                mock.patch.object(gui.logger, "warning") as registrar:
            gui.anunciar("hola")

        registrar.assert_called_once_with(
            "No se pudo anunciar con voz: %s", mock.ANY)
        self.assertEqual(str(registrar.call_args.args[1]), "COM no disponible")

    def test_anunciar_no_registra_fallo_si_la_voz_responde(self):
        grabador = GrabadorDeVoz()
        with mock.patch.object(gui, "_ao2", grabador), \
                mock.patch.object(gui.logger, "warning") as registrar:
            gui.anunciar("hola")

        registrar.assert_not_called()

    def test_aviso_de_espera_no_interrumpe(self):
        panel = mock.Mock()
        panel._cargando = True
        panel._inicio_progreso = 10
        panel._ultimo_aviso_progreso = None
        with mock.patch.object(reproductor.time, "monotonic", return_value=12), \
                mock.patch.object(reproductor.progreso, "aviso_de_espera",
                                  return_value="Buscando el vídeo, 2 segundos"), \
                mock.patch.object(reproductor, "anunciar") as anunciar:
            reproductor.ReproductorPanel._on_timer_progreso(panel, None)

        anunciar.assert_called_once_with("Buscando el vídeo, 2 segundos", urgente=False)

    def test_manejador_omite_diagnostico_sin_parchear_anunciar(self):
        grabador = GrabadorDeVoz()
        registro = logging.LogRecord(
            "ytchat.diagnostico", logging.INFO, __file__, 1, "oculto", (), None)
        with mock.patch.object(gui, "_ao2", grabador):
            gui.WxAnnouncingHandler().emit(registro)

        self.assertEqual(grabador.hablado, [])
        self.assertEqual(grabador.brailleado, [])

    def test_manejador_anuncia_mensaje_de_aplicacion(self):
        grabador = GrabadorDeVoz()
        registro = logging.LogRecord(
            "ytchat.obs_vigilante", logging.INFO, __file__, 1, "OBS volvio a responder", (), None)
        with mock.patch.object(gui, "_ao2", grabador):
            gui.WxAnnouncingHandler().emit(registro)

        self.assertEqual(grabador.hablado, ["OBS volvio a responder"])

    def test_log_wx_redirige_segun_nivel(self):
        with mock.patch.object(gui.logger, "warning") as warn, \
                mock.patch.object(gui.logger, "debug") as dbg:
            redir = gui._LogWx()
            redir.DoLogRecord(gui.wx.LOG_Error, "fallo error", None)
            redir.DoLogRecord(gui.wx.LOG_Warning, "aviso", None)
            redir.DoLogRecord(gui.wx.LOG_Message, "mensaje", None)
            redir.DoLogRecord(gui.wx.LOG_Info, "info", None)
            redir.DoLogRecord(gui.wx.LOG_Debug, "debug", None)
        self.assertEqual(warn.call_count, 2)
        self.assertEqual(dbg.call_count, 3)
        warn.assert_any_call("wx: %s", "fallo error")
        warn.assert_any_call("wx: %s", "aviso")
        dbg.assert_any_call("wx: %s", "mensaje")


class TestAltoContraste(unittest.TestCase):
    """Con un tema de alto contraste de Windows la paleta propia no se aplica:
    esos colores los eligió el usuario precisamente para poder ver."""

    def test_sin_alto_contraste_se_pinta_la_paleta(self):
        control = mock.Mock()
        with mock.patch.object(gui, "ALTO_CONTRASTE", False):
            gui._tc(control)
        control.SetBackgroundColour.assert_called_once_with(gui._T.field)
        control.SetForegroundColour.assert_called_once_with(gui._T.text)

    def test_con_alto_contraste_no_se_toca_ningun_color(self):
        control = mock.Mock()
        with mock.patch.object(gui, "ALTO_CONTRASTE", True):
            gui._tc(control)
            gui._pintar(control, gui._T.bg, gui._T.text)
            gui._titulo(control)
        control.SetBackgroundColour.assert_not_called()
        control.SetForegroundColour.assert_not_called()
        control.SetFont.assert_called_once()   # la negrita de sección sí queda

    def test_pintar_solo_aplica_lo_que_se_le_pasa(self):
        control = mock.Mock()
        with mock.patch.object(gui, "ALTO_CONTRASTE", False):
            gui._pintar(control, fg=gui._T.dim)
        control.SetBackgroundColour.assert_not_called()
        control.SetForegroundColour.assert_called_once_with(gui._T.dim)

    def test_la_deteccion_nunca_revienta(self):
        self.assertIn(gui._detectar_alto_contraste(), (True, False))


class TestVentanaReal(unittest.TestCase):
    """Comprobaciones que necesitan la ventana de verdad (tamaños, Wrap)."""

    def setUp(self):
        self.app = gui.wx.App(False) if not gui.wx.App.Get() else gui.wx.App.Get()

    def _ventana(self, **worker_extra):
        configuracion = {
            "atajos_raw": {}, "filtro_activo": "todos",
            "mostrar_botones_reproductor": False, "mostrar_metadatos": True,
            "mostrar_total_superchats": True, "overlay_activo": False,
            "programados_activo": False,
        }
        from types import SimpleNamespace
        stats = SimpleNamespace(leidos=0, superchats=0, descartados=0)
        worker = SimpleNamespace(get_rate=lambda: 0, get_volume=lambda: 100, **worker_extra)
        with mock.patch.object(gui.diagnostico, "crear_hilo"):
            frame = gui.YTChatFrame(None, configuracion, queue.Queue(), stats, worker,
                                    __import__("threading").Event())
        self.addCleanup(frame.Destroy)
        frame.Show()
        gui.wx.Yield()
        return frame

    @staticmethod
    def _saltos(frame):
        return frame.lbl_tipo.GetLabel().count("\n")

    def test_el_texto_de_tipo_se_vuelve_a_ensanchar(self):
        # Wrap() solo parte; al agrandar la ventana el texto debe volver a
        # una línea y no quedarse troceado con los saltos de la ventana chica.
        frame = self._ventana()
        frame.SetSize((650, 700)); gui.wx.Yield()
        self.assertGreater(self._saltos(frame), 0)
        frame.SetSize((1500, 700)); gui.wx.Yield()
        self.assertEqual(self._saltos(frame), 0)
        self.assertEqual(frame.lbl_tipo.GetLabel(), gui.MENSAJE_INICIAL)

    def test_el_wrap_usa_el_ancho_actual_y_no_el_anterior(self):
        frame = self._ventana()
        frame.SetSize((1500, 700)); gui.wx.Yield()
        frame.SetSize((650, 700)); gui.wx.Yield()
        ancho_panel = frame._panel_principal.GetClientSize().width
        self.assertLessEqual(frame.lbl_tipo.GetBestSize().width, ancho_panel - 20)

    def test_fijar_tipo_conserva_el_texto_original(self):
        frame = self._ventana()
        frame.SetSize((650, 700)); gui.wx.Yield()
        frame._fijar_tipo("Directo programado: aún sin chat. Hay comentarios.")
        frame.SetSize((1500, 700)); gui.wx.Yield()
        self.assertEqual(frame.lbl_tipo.GetLabel(),
                         "Directo programado: aún sin chat. Hay comentarios.")

    def test_con_el_reproductor_a_la_vista_el_piso_sale_del_sizer(self):
        frame = self._ventana()
        self.assertLess(frame.GetMinClientSize().height, 500)
        frame._mostrar_zona(True)
        minimo = frame._panel_principal.GetSizer().GetMinSize()
        area = gui.wx.Display(frame).GetClientArea()
        esperado = max(480, min(minimo.height, area.height - 110))
        self.assertGreater(esperado, 500)
        self.assertAlmostEqual(frame.GetMinClientSize().height, esperado, delta=4)
        # La ventana se agrandó para que quepa todo (o ya cabía).
        self.assertGreaterEqual(frame.GetClientSize().height, esperado - 4)

    def test_el_piso_no_sigue_al_ancho_de_la_ventana(self):
        # La etiqueta sin partir no debe empujar el mínimo hasta el ancho actual.
        frame = self._ventana()
        frame.SetSize((1500, 700)); gui.wx.Yield()
        frame._mostrar_zona(True)
        self.assertLess(frame.GetMinClientSize().width, 1000)

    def test_reconstruir_el_menu_destruye_la_barra_anterior(self):
        frame = self._ventana(esta_pausado=lambda: True)
        anterior = frame.GetMenuBar()
        frame._build_menubar()
        self.assertIsNot(frame.GetMenuBar(), anterior)
        self.assertFalse(bool(anterior))
        self.assertEqual(frame.mi_pausa.GetItemLabelText(), "Reanudar lectura")


class TestFocoAlActivar(unittest.TestCase):
    """Al activarse la ventana no se roba el foco si ya está en un control
    suyo (p. ej. al cerrarse un aviso mientras se estaba en el reproductor)."""

    def _frame(self, conectado=True):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame._alive = True
        frame._conectado = conectado
        frame._foco_contenido = mock.Mock()
        frame.txt_url = mock.Mock()
        return frame

    def _control_dentro_de(self, frame):
        padre = mock.Mock()
        padre.GetParent.return_value = None
        # La cadena de padres llega al frame: el control es suyo.
        control = mock.Mock()
        control.GetParent.return_value = frame
        return control

    def test_no_mueve_el_foco_si_ya_esta_dentro_de_la_ventana(self):
        frame = self._frame()
        with mock.patch.object(gui.wx.Window, "FindFocus",
                               return_value=self._control_dentro_de(frame)):
            frame._foco_al_activar()
        frame._foco_contenido.assert_not_called()
        frame.txt_url.SetFocus.assert_not_called()

    def test_sin_foco_va_al_contenido_si_hay_conexion(self):
        frame = self._frame()
        with mock.patch.object(gui.wx.Window, "FindFocus", return_value=None):
            frame._foco_al_activar()
        frame._foco_contenido.assert_called_once_with()

    def test_foco_fuera_de_la_ventana_va_a_la_url_sin_conexion(self):
        frame = self._frame(conectado=False)
        ajeno = mock.Mock()
        ajeno.GetParent.return_value = None
        with mock.patch.object(gui.wx.Window, "FindFocus", return_value=ajeno):
            frame._foco_al_activar()
        frame.txt_url.SetFocus.assert_called_once_with()

    def test_on_activate_difiere_la_decision(self):
        frame = self._frame()
        frame._foco_al_activar = mock.Mock()
        evento = mock.Mock()
        evento.GetActive.return_value = True
        with mock.patch.object(gui.wx, "CallAfter") as diferir:
            frame._on_activate(evento)
        diferir.assert_called_once_with(frame._foco_al_activar)
        evento.Skip.assert_called_once_with()


class TestConexionCancelable(unittest.TestCase):

    def _frame(self):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame._conectado = False
        frame._conectando = False
        frame.txt_url = mock.Mock()
        frame.txt_url.GetValue.return_value = "abcdefghijk"
        frame.btn_conectar = mock.Mock()
        frame.mi_conectar = mock.Mock()
        frame.mi_desconectar = mock.Mock()
        frame.on_conectar_cb = mock.Mock()
        frame.on_desconectar_cb = mock.Mock()
        frame.set_conectado = mock.Mock()
        return frame

    def test_mientras_conecta_desconectar_sigue_disponible(self):
        frame = self._frame()
        with mock.patch.object(gui._snd, "reproducir"), \
                mock.patch.object(gui, "anunciar"):
            frame._on_conectar(None)
        self.assertTrue(frame._conectando)
        frame.mi_desconectar.Enable.assert_called_once_with(True)
        frame.btn_conectar.Enable.assert_called_once_with()
        frame.btn_conectar.Disable.assert_not_called()
        frame.on_conectar_cb.assert_called_once_with("abcdefghijk")

    def test_desconectar_durante_la_conexion_la_cancela(self):
        frame = self._frame()
        with mock.patch.object(gui._snd, "reproducir"), \
                mock.patch.object(gui, "anunciar") as anunciar:
            frame._on_conectar(None)
            frame._desconectar_si_procede()
        frame.on_desconectar_cb.assert_called_once_with()
        frame.set_conectado.assert_called_once_with(False)
        anunciar.assert_called_with("Conexión cancelada")
        frame.txt_url.SetFocus.assert_called_once_with()

    def test_sin_conexion_ni_intento_desconectar_no_hace_nada(self):
        frame = self._frame()
        frame._desconectar_si_procede()
        frame.on_desconectar_cb.assert_not_called()

    def test_la_respuesta_de_conexion_apaga_el_estado_conectando(self):
        frame = self._frame()
        frame._conectando = True
        frame._actualizar_menus_por_conexion = mock.Mock()
        gui.YTChatFrame._set_conectado_ui(frame, True)
        self.assertFalse(frame._conectando)

    def test_alt_enter_sin_poder_escribir_anuncia_el_motivo(self):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame._panel_redactar = mock.Mock()
        frame._panel_redactar.motivo.return_value = "Conéctate a un directo para escribir en el chat"
        with mock.patch.object(gui, "anunciar") as anunciar:
            frame._on_enviar_live(None)
        anunciar.assert_called_once_with("Conéctate a un directo para escribir en el chat")
        frame._panel_redactar.enfocar.assert_not_called()

    def test_alt_enter_con_chat_disponible_enfoca_el_compositor(self):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame._panel_redactar = mock.Mock()
        frame._panel_redactar.motivo.return_value = ""
        with mock.patch.object(gui, "anunciar") as anunciar:
            frame._on_enviar_live(None)
        anunciar.assert_not_called()
        frame._panel_redactar.enfocar.assert_called_once_with()

    def test_respuesta_de_la_api_con_la_ventana_destruida_se_ignora(self):
        # Un frame sin construir se comporta como uno ya destruido (bool False).
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        with mock.patch.object(gui._snd, "reproducir") as sonar, \
                mock.patch.object(gui, "anunciar") as anunciar:
            frame._api_ok("Mensaje enviado al chat")
            frame._api_err(RuntimeError("x"))
        sonar.assert_not_called()
        anunciar.assert_not_called()


class _BarraDeMenu:

    def __init__(self):
        self.llamadas = []

    def EnableTop(self, *args):
        self.llamadas.append(args)


class _ControlMenu:

    def Enable(self, habilitado):
        pass


class TestMenusPorConexion(unittest.TestCase):

    def test_no_apaga_menu_reproductor_sin_conexion(self):
        frame = mock.Mock()
        frame._conectado = False
        frame._mi_ver_conexion = []
        frame._mi_voz_conexion = []
        frame._mi_filtro_sub = _ControlMenu()
        frame._es_tiktok = False
        frame._rep_panel = None
        frame.mi_descargar_este = _ControlMenu()
        barra = _BarraDeMenu()
        frame.GetMenuBar.return_value = barra

        gui.YTChatFrame._actualizar_menus_por_conexion(frame)

        self.assertEqual(barra.llamadas, [])


class TestAliasEnLaLista(unittest.TestCase):

    def test_lista_muestra_el_alias_del_autor(self):
        autor = "xX_gamer_29384756_Xx"
        alias.usar({autor.lower(): "Carlos"})
        self.addCleanup(alias.usar, {})
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame._config = {"limpiar_emojis": True}

        texto = frame._format_display(autor, "hola", "12:00", 0, "")

        self.assertEqual(texto, "Carlos: hola, 12:00")


class DialogoAliasFalso:

    def __init__(self, aceptar, valor):
        self.aceptar = aceptar
        self.valor = valor
        self.destruido = False

    def ShowModal(self):
        return gui.wx.ID_OK if self.aceptar else gui.wx.ID_CANCEL

    def GetValue(self):
        return self.valor

    def Destroy(self):
        self.destruido = True


class MenuChatFalso:

    def __init__(self):
        self.etiquetas = {}
        self.handlers = {}

    def Append(self, identificador, etiqueta):
        self.etiquetas[identificador] = etiqueta

    def AppendSeparator(self):
        pass

    def Bind(self, _evento, handler, id):
        self.handlers[id] = handler

    def Destroy(self):
        pass


class TestAliasDesdeElChat(unittest.TestCase):

    autor = "xX_gamer_29384756_Xx"

    def _frame(self):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame.lb_chat = mock.Mock()
        frame._rebuild_listbox = mock.Mock()
        return frame

    def test_aceptar_guarda_persiste_y_redibuja(self):
        frame = self._frame()
        dialogo = DialogoAliasFalso(True, "Carlos")
        alias.usar({})
        with mock.patch.object(gui.wx, "TextEntryDialog", return_value=dialogo), \
                mock.patch.object(gui.alias, "guardar") as guardar, \
                mock.patch.object(gui, "anunciar") as anunciar:
            frame._editar_alias_autor(self.autor)

        self.assertEqual(alias.visible(self.autor), "Carlos")
        guardar.assert_called_once_with(
            gui.app_dir() / "alias.json", {self.autor.lower(): "Carlos"})
        frame._rebuild_listbox.assert_called_once_with()
        frame.lb_chat.SetFocus.assert_called_once_with()
        self.assertTrue(dialogo.destruido)
        anunciar.assert_called_once_with("Alias guardado, Carlos")
        alias.usar({})

    def test_aceptar_vacio_quita_el_alias(self):
        frame = self._frame()
        dialogo = DialogoAliasFalso(True, "")
        alias.usar({self.autor.lower(): "Carlos"})
        with mock.patch.object(gui.wx, "TextEntryDialog", return_value=dialogo), \
                mock.patch.object(gui.alias, "guardar") as guardar, \
                mock.patch.object(gui, "anunciar") as anunciar:
            frame._editar_alias_autor(self.autor)

        self.assertEqual(alias.visible(self.autor), self.autor)
        guardar.assert_called_once_with(gui.app_dir() / "alias.json", {})
        frame._rebuild_listbox.assert_called_once_with()
        anunciar.assert_called_once_with("Alias quitado")
        alias.usar({})

    def test_cancelar_no_guarda_ni_redibuja(self):
        frame = self._frame()
        dialogo = DialogoAliasFalso(False, "Carlos")
        alias.usar({})
        with mock.patch.object(gui.wx, "TextEntryDialog", return_value=dialogo), \
                mock.patch.object(gui.alias, "guardar") as guardar, \
                mock.patch.object(gui, "anunciar") as anunciar:
            frame._editar_alias_autor(self.autor)

        guardar.assert_not_called()
        frame._rebuild_listbox.assert_not_called()
        anunciar.assert_not_called()
        frame.lb_chat.SetFocus.assert_called_once_with()

    def test_menu_muestra_alias_y_moderacion_recibe_autor_real(self):
        frame = self._frame()
        frame.lb_chat.GetSelection.return_value = 0
        registro = MensajeChat(plataforma="youtube", autor=self.autor,
                               identificador="canal-real", texto="hola",
                               hora="12:00:00", tipo="text", monto="")
        frame._get_selected_data = mock.Mock(return_value=registro)
        frame._autor_esta_silenciado = mock.Mock(return_value=False)
        frame._live_chat_id = "chat"
        frame._moderar = mock.Mock()
        frame._silenciar_autor = mock.Mock()
        menu = MenuChatFalso()
        alias.usar({self.autor.lower(): "Carlos"})
        with mock.patch.object(gui.wx, "Menu", return_value=menu), \
                mock.patch.object(gui.wx, "NewIdRef", side_effect=range(1, 11)), \
                mock.patch.object(gui.youtube_api, "google_disponible", return_value=True), \
                mock.patch.object(gui.credenciales, "hay_sesion", return_value=True):
            frame._mostrar_menu_chat()

        self.assertIn("Silenciar a Carlos (solo TTS)", menu.etiquetas.values())
        self.assertIn("Expulsar 5 min a Carlos (timeout)", menu.etiquetas.values())
        self.assertIn("Banear a Carlos del directo (permanente)", menu.etiquetas.values())
        self.assertIn("Cambiar el &alias de Carlos…", menu.etiquetas.values())
        identificador_ban = next(i for i, texto in menu.etiquetas.items()
                                 if texto.startswith("Banear"))
        identificador_silenciar = next(i for i, texto in menu.etiquetas.items()
                                       if texto.startswith("Silenciar"))
        with mock.patch.object(gui.wx, "CallAfter",
                               side_effect=lambda funcion, *args: funcion(*args)):
            menu.handlers[identificador_ban](None)
            menu.handlers[identificador_silenciar](None)
        frame._moderar.assert_called_once_with(self.autor, "canal-real", None)
        frame._silenciar_autor.assert_called_once_with(self.autor, False)
        alias.usar({})


class TestIdentidadModeracionChat(unittest.TestCase):
    """Moderación usa exclusivamente el registro seleccionado, nunca el último homónimo."""

    def _frame_con_chat(self):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame._chat = ListaChat(max_items=500)
        frame._pendientes = []
        frame._pendientes_timer = None
        frame._filtro = None
        frame._config = {"limpiar_emojis": True, "silenciados_runtime": set(),
                         "silenciados_ocultar": set()}
        frame._sc_totales = {}
        frame._live_chat_id = "live123"
        frame._conectado = True
        frame._alive = True
        frame._autor_esta_oculto = lambda autor: False
        frame._autor_esta_silenciado = lambda autor: False
        frame._moderar = mock.Mock()
        frame._silenciar_autor = mock.Mock()
        frame._rehabilitar_autor = mock.Mock()
        frame.lb_chat = mock.Mock()
        frame.lb_chat.Freeze = mock.Mock()
        frame.lb_chat.Thaw = mock.Mock()
        frame.lb_chat.Delete = mock.Mock()
        frame.lb_chat.Append = mock.Mock()
        frame.lb_chat.Clear = mock.Mock()
        frame.lb_chat.GetSelection = mock.Mock(return_value=0)
        frame.lb_chat.GetCount = mock.Mock(return_value=0)
        return frame

    def _encolar_y_volcar(self, frame, plataforma, autor, identificador, texto="hola"):
        with mock.patch.object(gui.wx, "CallLater", return_value=mock.Mock()):
            frame.agregar_mensaje_chat(autor, texto, "12:00:00", "text", "", identificador,
                                       plataforma=plataforma)
        # Volcar sin depender del temporizador ni de wx.App.
        with mock.patch.object(gui.wx.Window, "FindFocus", return_value=None):
            frame._volcar_pendientes()

    def test_homonimos_banear_recibe_identificador_antiguo(self):
        frame = self._frame_con_chat()
        self._encolar_y_volcar(frame, "youtube", "Igual", "AAA", "mensaje A")
        self._encolar_y_volcar(frame, "youtube", "Igual", "BBB", "mensaje B")
        # Seleccionar fila antigua (0 -> AAA).
        frame.lb_chat.GetSelection.return_value = 0
        menu = MenuChatFalso()
        alias.usar({})
        with mock.patch.object(gui.wx, "Menu", return_value=menu), \
                mock.patch.object(gui.wx, "NewIdRef", side_effect=range(1, 20)), \
                mock.patch.object(gui.youtube_api, "google_disponible", return_value=True), \
                mock.patch.object(gui.credenciales, "hay_sesion", return_value=True):
            frame._mostrar_menu_chat()
        identificador_ban = next(i for i, texto in menu.etiquetas.items() if texto.startswith("Banear"))
        with mock.patch.object(gui.wx, "CallAfter", side_effect=lambda fn, *a: fn(*a)):
            menu.handlers[identificador_ban](None)
        frame._moderar.assert_called_once_with("Igual", "AAA", None)
        self.assertNotEqual(frame._moderar.call_args.args[1], "BBB")
        alias.usar({})

    def test_homonimos_timeout_recibe_identificador_antiguo(self):
        frame = self._frame_con_chat()
        self._encolar_y_volcar(frame, "youtube", "Igual", "AAA")
        self._encolar_y_volcar(frame, "youtube", "Igual", "BBB")
        frame.lb_chat.GetSelection.return_value = 0
        menu = MenuChatFalso()
        with mock.patch.object(gui.wx, "Menu", return_value=menu), \
                mock.patch.object(gui.wx, "NewIdRef", side_effect=range(1, 20)), \
                mock.patch.object(gui.youtube_api, "google_disponible", return_value=True), \
                mock.patch.object(gui.credenciales, "hay_sesion", return_value=True):
            frame._mostrar_menu_chat()
        identificador_timeout = next(i for i, texto in menu.etiquetas.items() if texto.startswith("Expulsar"))
        with mock.patch.object(gui.wx, "CallAfter", side_effect=lambda fn, *a: fn(*a)):
            menu.handlers[identificador_timeout](None)
        frame._moderar.assert_called_once_with("Igual", "AAA", 300)

    def test_tiktok_no_muestra_moderacion_aunque_tenga_identificador(self):
        frame = self._frame_con_chat()
        self._encolar_y_volcar(frame, "tiktok", "Igual", "TIK123")
        frame.lb_chat.GetSelection.return_value = 0
        menu = MenuChatFalso()
        with mock.patch.object(gui.wx, "Menu", return_value=menu), \
                mock.patch.object(gui.wx, "NewIdRef", side_effect=range(1, 20)), \
                mock.patch.object(gui.youtube_api, "google_disponible", return_value=True), \
                mock.patch.object(gui.credenciales, "hay_sesion", return_value=True):
            frame._mostrar_menu_chat()
        self.assertNotIn("Banear a Igual del directo (permanente)", menu.etiquetas.values())
        self.assertNotIn("Expulsar 5 min a Igual (timeout)", menu.etiquetas.values())

    def test_youtube_sin_identificador_no_muestra_moderacion(self):
        frame = self._frame_con_chat()
        self._encolar_y_volcar(frame, "youtube", "Igual", "")
        frame.lb_chat.GetSelection.return_value = 0
        menu = MenuChatFalso()
        with mock.patch.object(gui.wx, "Menu", return_value=menu), \
                mock.patch.object(gui.wx, "NewIdRef", side_effect=range(1, 20)), \
                mock.patch.object(gui.youtube_api, "google_disponible", return_value=True), \
                mock.patch.object(gui.credenciales, "hay_sesion", return_value=True):
            frame._mostrar_menu_chat()
        self.assertNotIn("Banear a Igual del directo (permanente)", menu.etiquetas.values())

    def test_copia_usa_texto_del_registro_seleccionado(self):
        frame = self._frame_con_chat()
        self._encolar_y_volcar(frame, "youtube", "Igual", "AAA", "texto A")
        self._encolar_y_volcar(frame, "youtube", "Igual", "BBB", "texto B")
        frame.lb_chat.GetSelection.return_value = 0
        frame._clipboard_set = mock.Mock()
        with mock.patch.object(gui._snd, "reproducir"), mock.patch.object(gui, "anunciar"):
            frame._copiar_mensaje()
        frame._clipboard_set.assert_called_once_with("texto A")

    def test_copia_todo_usa_registro_seleccionado(self):
        frame = self._frame_con_chat()
        self._encolar_y_volcar(frame, "youtube", "Igual", "AAA", "hola")
        frame.lb_chat.GetSelection.return_value = 0
        # Forzar monto y hora conocidas.
        frame._chat.todos[0] = MensajeChat(plataforma="youtube", autor="Igual",
                                          identificador="AAA", texto="hola",
                                          hora="12:34:56", tipo="text", monto="$5")
        frame._chat.visibles = [0]
        frame._clipboard_set = mock.Mock()
        with mock.patch.object(gui._snd, "reproducir"), mock.patch.object(gui, "anunciar"):
            frame._copiar_todo()
        frame._clipboard_set.assert_called_once_with("Igual: hola, 12:34:56 [$5]")

    def test_releer_usa_registro_seleccionado(self):
        frame = self._frame_con_chat()
        frame._cola = mock.Mock()
        frame._cola.put = mock.Mock()
        self._encolar_y_volcar(frame, "youtube", "Ana", "AAA", "hola mundo")
        frame.lb_chat.GetSelection.return_value = 0
        with mock.patch.object(gui, "anunciar"):
            frame._releer_mensaje()
        self.assertTrue(frame._cola.put.called)
        texto_tts = frame._cola.put.call_args.args[0]["texto_tts"]
        self.assertIn("hola mundo", texto_tts)

    def test_abrir_enlace_usa_texto_del_registro(self):
        frame = self._frame_con_chat()
        self._encolar_y_volcar(frame, "youtube", "Ana", "AAA", "mira https://example.com")
        frame.lb_chat.GetSelection.return_value = 0
        with mock.patch.object(gui.webbrowser, "open") as abrir, \
                mock.patch.object(gui, "anunciar"):
            frame._abrir_enlace()
        abrir.assert_called_once_with("https://example.com")

    def test_alias_solo_cambia_texto_visible_moderacion_recibe_real(self):
        frame = self._frame_con_chat()
        self._encolar_y_volcar(frame, "youtube", "xX_gamer_29384756_Xx", "CANAL1", "hola")
        frame.lb_chat.GetSelection.return_value = 0
        alias.usar({"xx_gamer_29384756_xx": "Carlos"})
        menu = MenuChatFalso()
        with mock.patch.object(gui.wx, "Menu", return_value=menu), \
                mock.patch.object(gui.wx, "NewIdRef", side_effect=range(1, 20)), \
                mock.patch.object(gui.youtube_api, "google_disponible", return_value=True), \
                mock.patch.object(gui.credenciales, "hay_sesion", return_value=True):
            frame._mostrar_menu_chat()
        self.assertIn("Silenciar a Carlos (solo TTS)", menu.etiquetas.values())
        identificador_ban = next(i for i, texto in menu.etiquetas.items() if texto.startswith("Banear"))
        with mock.patch.object(gui.wx, "CallAfter", side_effect=lambda fn, *a: fn(*a)):
            menu.handlers[identificador_ban](None)
        frame._moderar.assert_called_once_with("xX_gamer_29384756_Xx", "CANAL1", None)
        alias.usar({})


class TestProgramadosEnPreferencias(unittest.TestCase):

    def _dialogo(self, mensajes, seleccion):
        dialogo = gui_preferencias.PreferenciasDialog.__new__(
            gui_preferencias.PreferenciasDialog)
        dialogo._mensajes_programados = mensajes
        dialogo._ruta_programados = Path(tempfile.mktemp(suffix=".json"))
        dialogo.lista_programados = mock.Mock()
        dialogo.lista_programados.GetSelection.return_value = seleccion
        dialogo._refrescar_programados = mock.Mock()
        self.addCleanup(lambda: dialogo._ruta_programados.unlink(missing_ok=True))
        return dialogo

    def test_quitar_persiste_que_el_mensaje_desaparecio(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "mensajes_programados.json"
            mensajes = [
                {"texto": "Quitar", "minutos_min": 10, "minutos_max": 10,
                 "activo": True, "proximo": 100.0},
                {"texto": "Conservar", "minutos_min": 10, "minutos_max": 10,
                 "activo": True, "proximo": 200.0},
            ]
            dialogo = self._dialogo(mensajes, 0)
            dialogo._ruta_programados = ruta
            def guardar_doble(ruta_a_guardar, mensajes_a_guardar):
                Path(ruta_a_guardar).write_text(
                    json.dumps(mensajes_a_guardar, ensure_ascii=False), encoding="utf-8")

            with mock.patch.object(
                    gui_preferencias.programados, "guardar",
                    side_effect=guardar_doble), \
                    mock.patch.object(gui_preferencias, "anunciar"):
                dialogo._quitar_programado(None)

            guardados = json.loads(ruta.read_text(encoding="utf-8"))
            self.assertEqual(guardados, [mensajes[0]])
            self.assertNotIn("Quitar", ruta.read_text(encoding="utf-8"))


    def test_guardar_edita_la_fila_elegida(self):
        mensajes = [
            {"texto": "Primero", "proximo": 100.0},
            {"texto": "Segundo", "proximo": 200.0},
            {"texto": "Tercero", "proximo": 300.0},
        ]
        dialogo = self._dialogo(mensajes, 2)
        dialogo._datos_programado = mock.Mock(return_value={"texto": "Editado"})
        dialogo._validar_programado = mock.Mock(return_value=True)
        with mock.patch.object(gui_preferencias.programados, "guardar"), \
                mock.patch.object(gui_preferencias, "anunciar"):
            dialogo._guardar_programado(None)

        self.assertEqual(mensajes[0]["texto"], "Primero")
        self.assertEqual(mensajes[2]["texto"], "Editado")

    def test_guardar_conserva_el_proximo_envio(self):
        mensajes = [
            {"texto": "Primero", "proximo": 100.0},
            {"texto": "Segundo", "proximo": 200.0},
        ]
        dialogo = self._dialogo(mensajes, 1)
        dialogo._datos_programado = mock.Mock(return_value={"texto": "Corregido"})
        dialogo._validar_programado = mock.Mock(return_value=True)
        with mock.patch.object(gui_preferencias.programados, "guardar"), \
                mock.patch.object(gui_preferencias, "anunciar"):
            dialogo._guardar_programado(None)

        self.assertEqual(mensajes[1]["proximo"], 200.0)

    def test_quitar_sin_seleccion_anuncia_y_no_revienta(self):
        dialogo = self._dialogo([], -1)
        with mock.patch.object(gui_preferencias, "anunciar") as anunciar:
            dialogo._quitar_programado(None)

        anunciar.assert_called_once_with("Elige primero un mensaje de la lista")


class TestCategoriasDePreferencias(unittest.TestCase):

    def setUp(self):
        self.app = gui.wx.App(False) if not gui.wx.App.Get() else gui.wx.App.Get()
        self.ruta = Path.cwd()
        self.parche_ruta = mock.patch.object(
            gui_preferencias.cfg, "app_dir", return_value=self.ruta)
        self.parche_ruta.start()
        self.addCleanup(self.parche_ruta.stop)

    def _dialogo(self):
        with mock.patch.object(gui, "_listar_voces_sapi5", return_value=["Voz de prueba"]):
            dialogo = gui_preferencias.PreferenciasDialog(None, {})
        self.addCleanup(dialogo.Destroy)
        return dialogo

    @staticmethod
    def _buscar(raiz, nombre):
        pendientes = [raiz]
        while pendientes:
            control = pendientes.pop()
            if control.GetName() == nombre:
                return control
            pendientes.extend(control.GetChildren())
        return None

    def test_tiene_trece_categorias_en_el_orden_acordado(self):
        dialogo = self._dialogo()
        self.assertEqual(
            [dialogo.nb.GetPageText(i) for i in range(dialogo.nb.GetPageCount())],
            ["Voz", "Lectura", "Cola de lectura", "Interfaz y sonidos",
             "Reproductor", "Conexion", "Filtros",
             "Estado (F2)", "Atajos", "API y sesión", "Mensajes automáticos",
             "Transmisión", "Diagnóstico"])

    def test_abre_con_el_foco_en_la_lista_de_categorias(self):
        dialogo = self._dialogo()
        self.assertIs(gui.wx.Window.FindFocus(), dialogo.lista_categorias)

    def test_controles_nuevos_tienen_su_nombre_accesible(self):
        dialogo = self._dialogo()
        for nombre, pagina in (
                ("Estrategia de la cola", "PagCola"),
                ("Tamaño máximo de la cola", "PagCola"),
                ("Leer solo el nombre a partir de", "PagCola"),
                ("Reconectar automáticamente si se corta", "PagConexion"),
                ("Espera entre intentos, en segundos", "PagConexion"),
                ("Número máximo de intentos", "PagConexion"),
                ("Puerto del panel de chat", "PagTransmision"),
                ("Micrófono de OBS", "PagTransmision"),
                ("Guardar un registro detallado para diagnosticar fallos",
                 "PagDiagnostico")):
            control = self._buscar(dialogo, nombre)
            self.assertIsNotNone(control)
            self.assertEqual(control.GetParent().GetName(), pagina)

    def test_microfono_guardado_se_conserva_sin_consultar_obs(self):
        with mock.patch.object(gui, "_listar_voces_sapi5", return_value=["Voz de prueba"]):
            dialogo = gui_preferencias.PreferenciasDialog(
                None, {"obs_microfono": "Mic/Aux"})
        self.addCleanup(dialogo.Destroy)

        self.assertEqual(dialogo.cho_microfono_obs.GetStringSelection(), "Mic/Aux")
        self.assertEqual(dialogo.cho_microfono_obs.GetStrings(),
                         ["Elegir automáticamente", "Mic/Aux"])

    def test_buscar_microfonos_lanza_hilo_sin_conectar_al_construir(self):
        dialogo = self._dialogo()
        hilo = mock.Mock()
        consulta = {}

        def crear_hilo(target, nombre):
            consulta["target"] = target
            consulta["nombre"] = nombre
            return hilo

        gestor = mock.Mock()
        gestor.fuentes_audio.return_value = ("Mic/Aux",)
        with mock.patch.object(gui_preferencias.diagnostico, "crear_hilo",
                               side_effect=crear_hilo), \
                mock.patch.object(gui_preferencias, "GestorPanelObs",
                                  return_value=gestor) as gestor_clase, \
                mock.patch.object(gui_preferencias.obs_cliente, "leer_ajustes"), \
                mock.patch.object(gui_preferencias.wx, "CallAfter",
                                  side_effect=lambda funcion, *args: funcion(*args)):
            dialogo._buscar_microfonos(None)
            gestor_clase.assert_not_called()
            consulta["target"]()

        self.assertEqual(consulta["nombre"], "MicrofonosPrefs")
        hilo.start.assert_called_once_with()
        gestor.conectar.assert_called_once_with()

    def test_las_paginas_se_desplazan_en_vertical(self):
        # Atajos mide más de 1200 px: sin desplazamiento, sus botones de
        # abajo (y «Restablecer») quedaban fuera del alcance del ratón.
        dialogo = self._dialogo()
        for pagina in dialogo._paginas():
            with self.subTest(pagina=pagina.GetName()):
                self.assertIsInstance(pagina, gui.wx.ScrolledWindow)
                self.assertEqual(pagina.GetScrollPixelsPerUnit(), (0, 20))

    def test_cada_pagina_cabe_a_lo_ancho(self):
        # No hay desplazamiento horizontal: lo que no quepa a lo ancho se corta.
        dialogo = self._dialogo()
        barra = gui.wx.SystemSettings.GetMetric(gui.wx.SYS_VSCROLL_X)
        for pagina in dialogo._paginas():
            with self.subTest(pagina=pagina.GetName()):
                visible = pagina.GetClientSize().width
                self.assertGreater(visible, 100)
                self.assertLessEqual(pagina.GetSizer().GetMinSize().width, visible - barra)

    def test_el_dialogo_se_puede_agrandar_pero_no_por_debajo_de_las_paginas(self):
        dialogo = self._dialogo()
        self.assertTrue(dialogo.GetWindowStyleFlag() & gui.wx.RESIZE_BORDER)
        necesario = max(p.GetSizer().GetMinSize().width for p in dialogo._paginas())
        self.assertGreater(dialogo.GetMinSize().width, necesario)
        self.assertGreaterEqual(dialogo.GetSize().width, dialogo.GetMinSize().width)

    def test_respuestas_de_hilos_ignoran_el_dialogo_destruido(self):
        dialogo = self._dialogo()
        with mock.patch.object(gui_preferencias.PreferenciasDialog, "__bool__",
                               lambda self: False, create=True), \
                mock.patch.object(gui_preferencias, "anunciar") as anunciar, \
                mock.patch.object(gui_preferencias._snd, "reproducir") as sonar, \
                mock.patch.object(gui_preferencias.wx, "MessageBox") as aviso:
            dialogo._microfonos_encontrados(("Mic/Aux",))
            dialogo._api_login_ok()
            dialogo._api_login_err(RuntimeError("x"))
        anunciar.assert_not_called()
        sonar.assert_not_called()
        aviso.assert_not_called()

    def test_guardar_escribe_las_mismas_claves(self):
        dialogo = self._dialogo()
        with mock.patch.object(gui_preferencias.cfg, "guardar_opcion") as guardar, \
                mock.patch.object(gui_preferencias._snd, "reproducir"), \
                mock.patch.object(gui_preferencias, "anunciar"), \
                mock.patch.object(dialogo, "EndModal"):
            dialogo._on_guardar(None)

        claves = [(llamada.args[1], llamada.args[2]) for llamada in guardar.call_args_list]
        esperadas = [
            ("programados", "activo"),
            ("ui", "tamanio_fuente_chat"),
            ("ui", "mostrar_total_superchats"),
            ("ui", "autoplay_reproductor"),
            ("ui", "mostrar_metadatos"),
            ("ui", "mostrar_botones_reproductor"),
            ("ui", "cache_video_mb"),
            ("voz", "voz"), ("voz", "voz_eventos"), ("voz", "multivoz"),
            ("lectura", "formato_prefijo"),
            ("texto", "limpiar_emojis"), ("texto", "eliminar_urls"),
            ("tiktok", "anunciar_entradas"), ("texto", "max_longitud_mensaje"),
            ("cola", "estrategia"), ("cola", "tamanio_maximo"),
            ("cola", "umbral_solo_nombre"),
            ("reconexion", "reconectar"),
            ("reconexion", "espera_entre_intentos"),
            ("reconexion", "max_intentos"),
            ("diagnostico", "registro_detallado"),
            ("overlay", "puerto"), ("obs", "microfono"),
        ]
        esperadas.extend(("estado", componente)
                          for componente in gui_preferencias.estado_sesion.COMPONENTES)
        esperadas.extend([
            ("filtros", "palabras_silenciadas"),
            ("filtros", "usuarios_silenciados"),
        ])
        esperadas.extend(("atajos", accion)
                          for accion in dialogo._valores_atajo
                          if accion not in gui_preferencias.cfg.ATAJOS_FIJOS)
        self.assertEqual(claves, esperadas)


class TestGuardadoDeNuevasPreferencias(unittest.TestCase):
    def setUp(self):
        self.app = gui.wx.App(False) if not gui.wx.App.Get() else gui.wx.App.Get()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ruta = Path(self.tmp.name)
        (self.ruta / "config.ini").write_text(config._CONFIG_FALLBACK,
                                                encoding="utf-8")
        parche = mock.patch.object(gui_preferencias.cfg, "app_dir",
                                   return_value=self.ruta)
        parche.start()
        self.addCleanup(parche.stop)

    def _dialogo(self, configuracion=None):
        with mock.patch.object(gui, "_listar_voces_sapi5", return_value=["Voz de prueba"]):
            dialogo = gui_preferencias.PreferenciasDialog(None, configuracion or {})
        self.addCleanup(dialogo.Destroy)
        return dialogo

    def _guardar(self, dialogo):
        with mock.patch.object(gui_preferencias._snd, "reproducir"), \
                mock.patch.object(gui_preferencias, "anunciar") as anunciar, \
                mock.patch.object(dialogo, "EndModal"):
            dialogo._on_guardar(None)
        return anunciar

    def _opciones_guardadas(self):
        parser = config._mk_parser()
        parser.read(self.ruta / "config.ini", encoding="utf-8")
        return parser

    def test_cargar_configuracion_devuelve_registro_detallado_del_archivo(self):
        for valor, esperado in (("true", True), ("false", False)):
            with self.subTest(valor=valor):
                (self.ruta / "config.ini").write_text(
                    config._CONFIG_FALLBACK.replace("registro_detallado = false",
                                                    f"registro_detallado = {valor}"),
                    encoding="utf-8")
                self.assertEqual(config.cargar_configuracion()["registro_detallado"],
                                 esperado)

    def test_guardar_escribe_las_nueve_claves_nuevas(self):
        dialogo = self._dialogo()
        dialogo.rb_estrategia.SetSelection(0)
        dialogo.sp_cola_maxima.SetValue(42)
        dialogo.sp_umbral_nombre.SetValue(7)
        dialogo.chk_reconectar.SetValue(False)
        dialogo.sp_espera_reconexion.SetValue(12)
        dialogo.sp_max_intentos.SetValue(3)
        dialogo.chk_registro_detallado.SetValue(True)
        dialogo.sp_puerto_overlay.SetValue(9000)
        dialogo.cho_microfono_obs.Append("Mic/Aux")
        dialogo.cho_microfono_obs.SetSelection(1)

        anunciar = self._guardar(dialogo)
        opciones = self._opciones_guardadas()

        self.assertEqual(opciones.get("cola", "estrategia"), "todas")
        self.assertEqual(opciones.get("cola", "tamanio_maximo"), "42")
        self.assertEqual(opciones.get("cola", "umbral_solo_nombre"), "7")
        self.assertEqual(opciones.get("reconexion", "reconectar"), "false")
        self.assertEqual(opciones.get("reconexion", "espera_entre_intentos"), "12")
        self.assertEqual(opciones.get("reconexion", "max_intentos"), "3")
        self.assertEqual(opciones.get("diagnostico", "registro_detallado"), "true")
        self.assertEqual(opciones.get("overlay", "puerto"), "9000")
        self.assertEqual(opciones.get("obs", "microfono"), "Mic/Aux")
        anunciar.assert_has_calls([
            mock.call("Preferencias guardadas"),
            mock.call("El cambio del registro detallado se aplica al reiniciar la aplicación"),
        ])

    def test_estrategia_guarda_la_clave_y_no_la_etiqueta(self):
        for seleccion, clave, etiqueta in (
                (0, "todas", "Leer todos los mensajes"),
                (1, "limite", "Descartar los más viejos si se acumulan")):
            with self.subTest(clave=clave):
                dialogo = self._dialogo()
                dialogo.rb_estrategia.SetSelection(seleccion)
                self._guardar(dialogo)
                estrategia = self._opciones_guardadas().get("cola", "estrategia")
                self.assertEqual(estrategia, clave)
                self.assertNotEqual(estrategia, etiqueta)

    def test_cambiar_el_puerto_con_el_panel_encendido_avisa_donde_se_aplica(self):
        dialogo = self._dialogo({"overlay_activo": True, "overlay_puerto": 8730})
        dialogo.sp_puerto_overlay.SetValue(9000)

        anunciar = self._guardar(dialogo)

        anunciar.assert_any_call(
            "El puerto nuevo del panel de chat se aplica al apagarlo y "
            "volver a encenderlo desde el panel de transmisión")

    def test_el_puerto_sin_cambios_o_con_el_panel_apagado_no_avisa(self):
        for configuracion, puerto in (
                ({"overlay_activo": True, "overlay_puerto": 8730}, 8730),
                ({"overlay_activo": False, "overlay_puerto": 8730}, 9000)):
            with self.subTest(configuracion=configuracion, puerto=puerto):
                dialogo = self._dialogo(dict(configuracion))
                dialogo.sp_puerto_overlay.SetValue(puerto)
                anunciar = self._guardar(dialogo)
                self.assertEqual([llamada.args[0] for llamada in anunciar.call_args_list],
                                 ["Preferencias guardadas"])

    def test_microfono_automatico_se_guarda_vacio(self):
        dialogo = self._dialogo({"obs_microfono": "Mic/Aux"})
        dialogo.cho_microfono_obs.SetSelection(0)
        self.assertEqual(dialogo._ruta, self.ruta / "config.ini")

        self._guardar(dialogo)

        self.assertEqual(self._opciones_guardadas().get("obs", "microfono"), "")


class TestProgramadorGui(unittest.TestCase):
    def _frame(self, **config):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame._config = {"programados_activo": True, **config}
        frame._mensajes_programados = [{"texto": "Hola", "activo": True,
                                        "minutos_min": 5, "minutos_max": 5,
                                        "proximo": 0.0}]
        frame._programados_reloj_iniciado = True
        frame._programados_ultimo_envio = None
        frame._programado_en_curso = False
        frame._conectado = True
        frame._es_tiktok = False
        frame._live_chat_id = "chat"
        return frame

    def test_envio_exitoso_avanza_el_reloj(self):
        frame = self._frame()
        with mock.patch.object(gui.programados, "calcular_proximo",
                               return_value=900.0) as calcular:
            frame._programado_enviado(frame._mensajes_programados[0])
        self.assertEqual(frame._mensajes_programados[0]["proximo"], 900.0)
        self.assertIsNotNone(frame._programados_ultimo_envio)
        calcular.assert_called_once()

    def test_envia_con_el_doble_de_la_api_sin_anunciar_exito(self):
        frame = self._frame()
        cliente = mock.Mock()
        cliente.token_actualizado.return_value = None

        class Hilo:
            def __init__(self, objetivo):
                self.objetivo = objetivo

            def start(self):
                self.objetivo()

        with mock.patch.object(gui.youtube_api, "ClienteYouTube",
                               return_value=cliente), \
                mock.patch.object(gui.credenciales, "cargar", return_value={}), \
                mock.patch.object(gui.diagnostico, "crear_hilo",
                                  side_effect=lambda objetivo, nombre: Hilo(objetivo)), \
                mock.patch.object(gui.wx, "CallAfter",
                                  side_effect=lambda fn, *args: fn(*args)), \
                mock.patch.object(gui, "anunciar") as anunciar:
            frame._enviar_programado(frame._mensajes_programados[0], 1000.0)
        cliente.enviar_mensaje_live.assert_called_once_with("chat", "Hola")
        anunciar.assert_not_called()

    def test_no_duplica_un_envio_en_curso(self):
        frame = self._frame()
        frame._programado_en_curso = True
        with mock.patch.object(frame, "_sesion_api_disponible", return_value=True), \
                mock.patch.object(frame, "_enviar_programado") as enviar:
            frame._procesar_programado()
        enviar.assert_not_called()

    def test_procesar_arma_la_bandera_antes_de_enviar(self):
        frame = self._frame()
        frame._mensajes_programados[0]["proximo"] = 0.0

        class Hilo:
            def start(self):
                pass

        with mock.patch.object(gui.time, "time", return_value=1000.0), \
                mock.patch.object(frame, "_sesion_api_disponible", return_value=True), \
                mock.patch.object(gui.diagnostico, "crear_hilo",
                                  return_value=Hilo()):
            frame._procesar_programado()
        self.assertTrue(frame._programado_en_curso)

    def test_al_encender_da_cuerda_al_reloj(self):
        frame = self._frame()
        frame._programados_reloj_iniciado = False
        with mock.patch.object(gui.programados, "iniciar_reloj") as iniciar:
            frame._iniciar_programados_si_corresponde(1000.0)
        iniciar.assert_called_once()
        self.assertTrue(frame._programados_reloj_iniciado)

    def test_procesar_no_vuelve_a_dar_cuerda_al_reloj(self):
        frame = self._frame()
        frame._programados_reloj_iniciado = False
        frame._conectado = False
        mensaje = frame._mensajes_programados[0]
        with mock.patch.object(gui.time, "time", side_effect=(1000.0, 2000.0)):
            frame._procesar_programado()
            proximo = mensaje["proximo"]
            frame._procesar_programado()
        self.assertEqual(mensaje["proximo"], proximo)

    def test_no_envia_si_no_hay_conexion(self):
        frame = self._frame()
        frame._conectado = False
        with mock.patch.object(frame, "_sesion_api_disponible", return_value=True), \
                mock.patch.object(frame, "_enviar_programado") as enviar:
            frame._procesar_programado()
        enviar.assert_not_called()

    def test_no_envia_sin_sesion_api(self):
        frame = self._frame()
        with mock.patch.object(frame, "_sesion_api_disponible", return_value=False), \
                mock.patch.object(frame, "_enviar_programado") as enviar:
            frame._procesar_programado()
        enviar.assert_not_called()

    def test_no_envia_si_falta_live_chat_id(self):
        frame = self._frame()
        frame._live_chat_id = ""
        with mock.patch.object(frame, "_sesion_api_disponible", return_value=True), \
                mock.patch.object(frame, "_enviar_programado") as enviar:
            frame._procesar_programado()
        enviar.assert_not_called()

    def test_no_envia_si_interruptor_apagado(self):
        frame = self._frame(programados_activo=False)
        with mock.patch.object(frame, "_sesion_api_disponible", return_value=True), \
                mock.patch.object(frame, "_enviar_programado") as enviar:
            frame._procesar_programado()
        enviar.assert_not_called()

    def test_no_envia_en_tiktok(self):
        frame = self._frame()
        frame._es_tiktok = True
        with mock.patch.object(frame, "_sesion_api_disponible", return_value=True), \
                mock.patch.object(frame, "_enviar_programado") as enviar:
            frame._procesar_programado()
        enviar.assert_not_called()

    def test_no_envia_si_elegir_devuelve_none(self):
        frame = self._frame()
        with mock.patch.object(frame, "_sesion_api_disponible", return_value=True), \
                mock.patch.object(gui.programados, "elegir_envio", return_value=None), \
                mock.patch.object(frame, "_enviar_programado") as enviar:
            frame._procesar_programado()
        enviar.assert_not_called()

    def test_error_apaga_programador_y_anuncia_una_vez(self):
        frame = self._frame()
        with mock.patch.object(gui, "anunciar") as anunciar:
            frame._programado_fallo(RuntimeError("rateLimitExceeded"))
        self.assertFalse(frame._config["programados_activo"])
        anunciar.assert_called_once_with(
            "Los mensajes automáticos se detuvieron por un error del servicio.")

    def test_error_baja_la_bandera_de_envio(self):
        frame = self._frame()
        frame._programado_en_curso = True
        with mock.patch.object(gui, "anunciar"):
            frame._programado_fallo(RuntimeError("rateLimitExceeded"))
        self.assertFalse(frame._programado_en_curso)

    def test_snapshot_omite_proximo_si_el_interruptor_esta_apagado(self):
        frame = self._frame(programados_activo=False)
        frame._tipo_video = "live_youtube"
        frame._titulo_stream = "Directo"
        frame._metadatos = {}
        frame._sc_totales = {}
        snapshot = frame._snapshot_sesion()
        self.assertEqual(snapshot.programados_proximo, "")


class TestDescartesGui(unittest.TestCase):
    def _frame(self, descartados=3):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame._alive = True
        frame._config = {"umbral_solo_nombre": 0}
        frame._stats = mock.Mock(descartados=descartados)
        frame._descartes_avisado = False
        frame._actualizar_sb = mock.Mock()
        frame._procesar_programado = mock.Mock()
        return frame

    def test_el_timer_anuncia_los_descartes_una_sola_vez(self):
        frame = self._frame()
        with mock.patch.object(gui, "anunciar") as anunciar:
            frame._on_timer(None)
            frame._on_timer(None)
        anunciar.assert_called_once_with(gui.descartes.frase_aviso(0))
        self.assertTrue(frame._descartes_avisado)

    def test_el_snapshot_lleva_los_descartes_al_estado(self):
        frame = self._frame(descartados=7)
        frame.__dict__.update(
            _conectado=False, _es_tiktok=False,
            _tipo_video=gui.deteccion.DESCONOCIDO, _titulo_stream="",
            _metadatos={}, _sc_totales={}, _mensajes_programados=[],
            _obs_vigilante=None, _cola=mock.Mock(), _worker=mock.Mock())
        snapshot = frame._snapshot_sesion()
        self.assertEqual(snapshot.descartados, "Mensajes descartados: 7")

    def test_al_reconectar_puede_avisar_otra_vez(self):
        frame = self._frame()
        frame._conectado = True
        frame._live_chat_id = ""
        frame._causa_sin_chat = ""
        frame._tipo_video = gui.deteccion.DESCONOCIDO
        frame._es_tiktok = False
        frame._descartar_pendientes = mock.Mock()
        frame._chat = mock.Mock()
        frame.lb_chat = mock.Mock()
        frame._sc_totales = {}
        frame._metadatos = {}
        frame.txt_info = mock.Mock()
        frame._rep_panel = mock.Mock()
        frame._com_panel = mock.Mock()
        frame._worker = mock.Mock()
        frame._mostrar_zona = mock.Mock()
        frame._anunciar_conectado = mock.Mock()
        frame.set_titulo_stream = mock.Mock()
        frame.lbl_tipo = mock.Mock()
        frame.txt_url = mock.Mock()
        frame._set_conectado_ui = mock.Mock()
        frame._actualizar_estado_online = mock.Mock()
        frame._stats.reset.side_effect = lambda: setattr(frame._stats, "descartados", 0)

        with mock.patch.object(gui, "anunciar") as anunciar, \
                mock.patch.object(gui.wx, "CallAfter"), \
                mock.patch.object(gui._snd, "reproducir"):
            frame._on_timer(None)
            frame.set_conectado(False)
            self.assertFalse(frame._descartes_avisado)
            frame._stats.descartados = 3
            frame.set_conectado(True)
            frame._on_timer(None)

        avisos = [llamada.args[0] for llamada in anunciar.call_args_list]
        self.assertEqual(avisos.count(gui.descartes.frase_aviso(0)), 2)


class TestLiveChatIdPorSesion(unittest.TestCase):
    """El id del chat en vivo llega de un hilo que puede terminar tarde: si
    es de una conexión anterior, aceptarlo mandaría los mensajes programados
    y el compositor al directo equivocado."""

    def _frame(self, video_actual):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame.__dict__.update(_alive=True, _video_id_sesion=video_actual,
                              _live_chat_id="", _causa_sin_chat="")
        frame._actualizar_estado_online = mock.Mock()
        return frame

    def test_acepta_el_id_del_video_vigente(self):
        frame = self._frame("abc")
        frame.set_live_chat_id("chat-abc", "", video_id="abc")
        self.assertEqual(frame._live_chat_id, "chat-abc")
        frame._actualizar_estado_online.assert_called_once()

    def test_ignora_el_id_de_un_video_anterior(self):
        frame = self._frame("nuevo")
        frame.set_live_chat_id("chat-viejo", "", video_id="viejo")
        self.assertEqual(frame._live_chat_id, "")
        frame._actualizar_estado_online.assert_not_called()

    def test_sin_video_id_conserva_el_comportamiento_anterior(self):
        frame = self._frame("abc")
        frame.set_live_chat_id("chat", "causa")
        self.assertEqual((frame._live_chat_id, frame._causa_sin_chat), ("chat", "causa"))

    def test_set_tipo_video_fija_el_video_de_la_sesion(self):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame.__dict__.update(_alive=True, _video_id_sesion="", _config={},
                              _sc_totales={}, _tipo_video=gui.deteccion.DESCONOCIDO,
                              _es_tiktok=False)
        for nombre in ("_descartar_pendientes", "_chat", "lb_chat", "_com_panel",
                       "_rep_panel", "_fijar_tipo", "_actualizar_estado_online",
                       "_actualizar_titulo"):
            setattr(frame, nombre, mock.Mock())
        try:
            frame.set_tipo_video(gui.deteccion.LIVE, "abc")
        except Exception:
            pass  # el resto del método toca controles que aquí no existen
        self.assertEqual(frame._video_id_sesion, "abc")


class TestEstadoObsEnF2(unittest.TestCase):
    def _frame(self, toggles, vigilante=None):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame._config = {"estado_toggles": toggles, "programados_activo": False}
        frame._obs_vigilante = vigilante
        frame.__dict__.update(_conectado=False, _es_tiktok=False,
            _tipo_video=gui.deteccion.DESCONOCIDO, _titulo_stream="", _metadatos={},
            _sc_totales={}, _mensajes_programados=[])
        return frame
    def test_f2_dice_los_tres_datos_frescos_de_la_cache(self):
        vigilante = mock.Mock(estado=mock.Mock(return_value=gui.obs_vigilante.EstadoObs({"outputActive": True, "outputDuration": 60,
            "outputSkippedFrames": 2, "outputTotalFrames": 10},
            {"outputActive": True, "outputPaused": False, "outputTimecode": "00:01:00"}, "Principal")))
        frame = self._frame(set(gui._OBS_COMPONENTES), vigilante)
        with mock.patch.object(gui, "anunciar") as anunciar:
            frame._anunciar_estado()
        texto = anunciar.call_args.args[0]
        self.assertTrue(all(x in texto for x in ("Transmitiendo desde hace 1 min, 2 de 10 fotogramas perdidos",
                                                   "Grabando, 00:01:00", "Al aire: Principal")))
    def test_f2_omite_dato_pasado_y_sin_vigilante(self):
        for toggles, vigilante in (({"estado", *gui._OBS_COMPONENTES}, mock.Mock(estado=lambda: None)),
                                    ({"estado"}, None)):
            with mock.patch.object(gui, "anunciar") as anunciar:
                self._frame(toggles, vigilante)._anunciar_estado()
            self.assertEqual(anunciar.call_args.args[0], "Desconectado.")
    def test_marca_y_desmarca_los_componentes_de_obs(self):
        frame = self._frame({"obs_transmision"})
        with mock.patch.object(gui.obs_vigilante, "VigilanteObs") as clase:
            frame._actualizar_vigilante_obs()
            clase.return_value.iniciar.assert_called_once_with()
            frame._config["estado_toggles"] = set()
            frame._actualizar_vigilante_obs()
        clase.return_value.detener.assert_called_once_with()

class TestActualizarYtdlp(unittest.TestCase):

    class Dialogo:
        def __init__(self, cancelado=False):
            self.cancelado = cancelado
            self.actualizaciones = []
            self.destruido = False

        def WasCancelled(self):
            return self.cancelado

        def Update(self, *argumentos):
            self.actualizaciones.append(argumentos)

        def Destroy(self):
            self.destruido = True

    def _ejecutar(self, resultado):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        anuncios = []
        dialogos = []
        hilo = mock.Mock()
        hilo.start.side_effect = lambda: hilo.target()

        def crear(target, nombre):
            hilo.target = target
            return hilo

        with mock.patch.object(gui, "anunciar", side_effect=anuncios.append), \
                mock.patch.object(gui.diagnostico, "crear_hilo", side_effect=crear), \
                mock.patch.object(gui.wx, "CallAfter", side_effect=lambda fn, *args: fn(*args)), \
                mock.patch.object(gui.wx, "MessageBox", side_effect=lambda *args: dialogos.append(args)), \
                mock.patch.object(ytdlp_bin, "actualizar_ytdlp", return_value=resultado):
            gui.YTChatFrame._on_actualizar_ytdlp(frame, None)
        return anuncios, dialogos, hilo

    def test_activar_anuncia_antes_de_empezar(self):
        anuncios, dialogos, hilo = self._ejecutar(("ya_al_dia", "2026.08.20", "2026.08.20"))
        self.assertIn("Buscando", anuncios[0])
        hilo.start.assert_called_once()

    def test_cada_desenlace_anuncia_su_texto(self):
        casos = (
            (("actualizado", "2026.08.20", "2026.08.21"), "actualizó"),
            (("ya_al_dia", "2026.08.20", "2026.08.20"), "al día"),
            (("sin_conexion", "2026.08.20", ""), "conexión"),
            (("firma_incorrecta", "2026.08.20", "2026.08.21"), "No se instaló nada"),
            (("otro_fallo", "2026.08.20", "2026.08.21"), "No se pudo actualizar"),
        )
        for resultado, esperado in casos:
            with self.subTest(esperado=esperado):
                anuncios, dialogos, _ = self._ejecutar(resultado)
                self.assertIn("Buscando", anuncios[0])
                self.assertTrue(any(esperado in texto[0] for texto in dialogos))

    def test_fallo_de_red_no_propaga_excepcion_y_anuncia(self):
        anuncios, dialogos, hilo = self._ejecutar(("sin_conexion", "", ""))
        self.assertIn("conexión", dialogos[-1][0])
        hilo.start.assert_called_once()

    def test_pasa_el_estado_sin_mirar_el_motivo(self):
        with mock.patch.object(gui, "anunciar"), \
                mock.patch.object(gui.diagnostico, "crear_hilo") as crear, \
                mock.patch.object(gui.wx, "CallAfter", side_effect=lambda fn, *args: fn(*args)), \
                mock.patch.object(gui.wx, "MessageBox"), \
                mock.patch.object(ytdlp_bin, "mensaje_de_actualizacion") as mensaje, \
                mock.patch.object(ytdlp_bin, "actualizar_ytdlp", return_value=("firma_incorrecta", "", "2026.08.21")):
            hilo = mock.Mock()
            hilo.start.side_effect = lambda: hilo.target()
            crear.side_effect = lambda target, nombre: setattr(hilo, "target", target) or hilo
            gui.YTChatFrame._on_actualizar_ytdlp(gui.YTChatFrame.__new__(gui.YTChatFrame), None)
        mensaje.assert_called_once_with("firma_incorrecta", "", "2026.08.21")

    def test_cancelar_usa_was_cancelled_y_muestra_mensaje_propio(self):
        dialogo = self.Dialogo(cancelado=True)
        hilo = mock.Mock()
        hilo.start.side_effect = lambda: hilo.target()

        def crear(target, nombre):
            hilo.target = target
            return hilo

        def actualizar(antes, progreso, cancelar):
            antes()
            self.assertTrue(cancelar())
            return "cancelado", "2026.08.20", "2026.08.21"

        with mock.patch.object(gui, "anunciar"), \
                mock.patch.object(gui.diagnostico, "crear_hilo", side_effect=crear), \
                mock.patch.object(gui.wx, "CallAfter", side_effect=lambda fn, *args: fn(*args)), \
                mock.patch.object(gui.wx, "CallLater"), \
                mock.patch.object(gui.wx, "ProgressDialog", return_value=dialogo), \
                mock.patch.object(gui.wx, "MessageBox") as mensaje, \
                mock.patch.object(ytdlp_bin, "actualizar_ytdlp", side_effect=actualizar):
            gui.YTChatFrame._on_actualizar_ytdlp(gui.YTChatFrame.__new__(gui.YTChatFrame), None)
        self.assertIn("Se canceló la descarga de yt-dlp.", mensaje.call_args.args[0])
        self.assertTrue(dialogo.destruido)

    def test_icono_de_resultado_distingue_fallo_y_acierto(self):
        for estado, icono in (
                ("actualizado", gui.wx.ICON_INFORMATION),
                ("otro_fallo", gui.wx.ICON_ERROR)):
            with self.subTest(estado=estado):
                _, dialogos, _ = self._ejecutar((estado, "", "2026.08.21"))
                self.assertEqual(icono, dialogos[-1][2] & (gui.wx.ICON_ERROR | gui.wx.ICON_INFORMATION))

    def test_anuncia_antes_de_descargar_y_al_terminar(self):
        anuncios = []
        hilo = mock.Mock()
        hilo.start.side_effect = lambda: hilo.target()

        def crear(target, nombre):
            hilo.target = target
            return hilo

        def actualizar(aviso, _progreso, _cancelar):
            aviso()
            return "actualizado", "2026.08.20", "2026.08.21"

        with mock.patch.object(gui, "anunciar", side_effect=anuncios.append), \
                mock.patch.object(gui.diagnostico, "crear_hilo", side_effect=crear), \
                mock.patch.object(gui.wx, "CallAfter", side_effect=lambda fn, *args: fn(*args)), \
                mock.patch.object(gui.wx, "MessageBox") as mensaje, \
                mock.patch.object(gui.wx, "ProgressDialog") as progreso, \
                mock.patch.object(gui.wx, "CallLater"), \
                mock.patch.object(ytdlp_bin, "actualizar_ytdlp", side_effect=actualizar):
            progreso.return_value.IsCancelled.return_value = False
            gui.YTChatFrame._on_actualizar_ytdlp(gui.YTChatFrame.__new__(gui.YTChatFrame), None)
        self.assertIn("Buscando", anuncios[0])
        progreso.assert_called_once()
        self.assertEqual(1, mensaje.call_count)
        self.assertIn("actualizó", mensaje.call_args.args[0])


    def test_sondeo_de_cancelacion_se_reprograma(self):
        dialogo = self.Dialogo()
        hilo = mock.Mock()
        hilo.start.side_effect = lambda: hilo.target()

        def crear(target, nombre):
            hilo.target = target
            return hilo

        def actualizar(antes, _progreso, _cancelar):
            antes()
            return "cancelado", "2026.08.20", "2026.08.21"

        with mock.patch.object(gui, "anunciar"), \
                mock.patch.object(gui.diagnostico, "crear_hilo", side_effect=crear), \
                mock.patch.object(gui.wx, "CallAfter", side_effect=lambda fn, *args: fn(*args)), \
                mock.patch.object(gui.wx, "CallLater") as call_later, \
                mock.patch.object(gui.wx, "ProgressDialog", return_value=dialogo), \
                mock.patch.object(gui.wx, "MessageBox"), \
                mock.patch.object(ytdlp_bin, "actualizar_ytdlp", side_effect=actualizar):
            gui.YTChatFrame._on_actualizar_ytdlp(
                gui.YTChatFrame.__new__(gui.YTChatFrame), None)

        call_later.assert_called_once()
        self.assertEqual(call_later.call_args.args[0], 100)
        self.assertTrue(callable(call_later.call_args.args[1]))


class TestCierreVentana(unittest.TestCase):

    def test_el_overlay_activo_se_enciende_al_construir_la_ventana(self):
        configuracion = {"overlay_activo": True, "overlay_puerto": 8730}

        def construir_menu(frame):
            frame.mi_overlay = mock.Mock()

        with mock.patch.object(gui.wx.Frame, "__init__", return_value=None), \
                mock.patch.object(gui.YTChatFrame, "_build_menubar", construir_menu), \
                mock.patch.object(gui.YTChatFrame, "_build_ui"), \
                mock.patch.object(gui.YTChatFrame, "_bind_events"), \
                mock.patch.object(gui.YTChatFrame, "_init_timer"), \
                mock.patch.object(gui.YTChatFrame, "SetBackgroundColour"), \
                mock.patch.object(gui.YTChatFrame, "Centre"), \
                mock.patch.object(gui, "anunciar_conflictos_atajos"), \
                mock.patch.object(gui.diagnostico, "crear_hilo") as crear, \
                mock.patch.object(gui.overlay_servidor, "encender") as encender, \
                mock.patch.object(gui, "guardar_opcion"), \
                mock.patch.object(gui, "anunciar"):
            gui.YTChatFrame(None, configuracion, None, None, None, None)

        encender.assert_called_once_with(8730)

    def test_el_overlay_no_miente_si_el_puerto_esta_ocupado_al_arrancar(self):
        configuracion = {"overlay_activo": True, "overlay_puerto": 8730}

        with mock.patch.object(gui.wx.Frame, "__init__", return_value=None), \
                mock.patch.object(gui.YTChatFrame, "_build_menubar"), \
                mock.patch.object(gui.YTChatFrame, "_build_ui"), \
                mock.patch.object(gui.YTChatFrame, "_bind_events"), \
                mock.patch.object(gui.YTChatFrame, "_init_timer"), \
                mock.patch.object(gui.YTChatFrame, "SetBackgroundColour"), \
                mock.patch.object(gui.YTChatFrame, "Centre"), \
                mock.patch.object(gui, "anunciar_conflictos_atajos"), \
                mock.patch.object(gui.diagnostico, "crear_hilo"), \
                mock.patch.object(gui.overlay_servidor, "encender", side_effect=gui.overlay_servidor.OverlayPuertoOcupadoError), \
                mock.patch.object(gui, "guardar_opcion"), \
                mock.patch.object(gui, "anunciar") as anunciar:
            frame = gui.YTChatFrame(None, configuracion, None, None, None, None)

        self.assertFalse(frame._config["overlay_activo"])
        anunciar.assert_called_once_with(
            "No se pudo activar el panel, el puerto 8730 está ocupado")

    def test_el_precalentamiento_se_arranca_solo_con_la_ventana_viva(self):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame._alive = True
        frame._rep_panel = mock.Mock()
        frame._arrancar_precalentamiento()
        frame._rep_panel._precalentar.assert_called_once_with()

        frame._alive = False
        frame._rep_panel._precalentar.reset_mock()
        frame._arrancar_precalentamiento()
        frame._rep_panel._precalentar.assert_not_called()

    def _frame(self):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame._apagando = False
        frame._alive = True
        frame._timer = mock.Mock()
        frame._diagnostico_timer = mock.Mock()
        frame._pendientes_timer = None
        frame.on_desconectar_cb = None
        frame._parada = mock.Mock()
        frame._rep_panel = mock.Mock()
        frame._worker = mock.Mock()
        frame._diagnostico_parada = mock.Mock()
        frame.Hide = mock.Mock()
        frame.Destroy = mock.Mock()
        return frame

    def test_con_captura_viva_programa_espera_y_anuncia_cerrando(self):
        frame = self._frame()
        hilo = mock.Mock()
        hilo.name = "Chat"
        hilo.is_alive.return_value = True
        with mock.patch.object(gui.diagnostico, "hilos_vivos_de_la_aplicacion", return_value=("Chat",)), \
                mock.patch.object(gui, "anunciar") as anunciar, \
                mock.patch.object(gui.wx, "CallLater") as call_later, \
                mock.patch.object(gui.diagnostico.logger, "log") as logueo, \
                mock.patch.object(gui.diagnostico, "registrar_cierre_fallos") as registro:
            frame._on_close(None)

        anunciar.assert_called_once_with("Cerrando")
        call_later.assert_called_once_with(200, frame._comprobar_cierre)
        frame.Destroy.assert_not_called()
        registro.assert_not_called()
        logueo.assert_not_called()

    def test_sin_captura_no_anuncia_y_destruye(self):
        frame = self._frame()
        with mock.patch.object(gui.diagnostico, "hilos_vivos_de_la_aplicacion", return_value=()), \
                mock.patch.object(gui, "anunciar") as anunciar, \
                mock.patch.object(gui.wx, "CallLater") as call_later, \
                mock.patch.object(gui.diagnostico.logger, "log") as logueo, \
                mock.patch.object(gui.diagnostico, "registrar_cierre_fallos") as registro:
            frame._on_close(None)

        anunciar.assert_not_called()
        call_later.assert_not_called()
        frame.Destroy.assert_called_once_with()
        logueo.assert_called_once_with(logging.INFO, "%s", "CIERRE captura limpia")
        registro.assert_called_once_with()

    def test_al_cerrar_detiene_el_vigilante_de_interfaz(self):
        frame = self._frame()
        with mock.patch.object(gui.diagnostico, "hilos_vivos_de_la_aplicacion", return_value=()), \
                mock.patch.object(gui, "anunciar"), \
                mock.patch.object(gui.diagnostico.logger, "info"):
            frame._on_close(None)

        frame._diagnostico_parada.set.assert_called_once_with()

    def test_al_cerrar_para_los_dos_temporizadores(self):
        frame = self._frame()
        with mock.patch.object(gui.diagnostico, "hilos_vivos_de_la_aplicacion", return_value=()), \
                mock.patch.object(gui, "anunciar"), \
                mock.patch.object(gui.diagnostico.logger, "info"):
            frame._on_close(None)

        frame._timer.Stop.assert_called_once_with()
        frame._diagnostico_timer.Stop.assert_called_once_with()

    def test_encender_el_overlay_con_el_puerto_ocupado_no_persiste_ni_miente(self):
        frame = self._frame()
        frame._config = {"overlay_puerto": 8730, "overlay_activo": False}
        with mock.patch.object(gui.overlay_servidor, "encender",
                               side_effect=gui.overlay_servidor.OverlayPuertoOcupadoError()), \
                mock.patch.object(gui, "anunciar") as anunciar, \
                mock.patch.object(gui, "RUTA_CONFIG", None):
            resultado = frame._cambiar_overlay(True)
        self.assertFalse(resultado)
        self.assertFalse(frame._config["overlay_activo"])
        anunciar.assert_called_once_with(
            "No se pudo activar el panel, el puerto 8730 está ocupado")

    def test_el_puerto_ocupado_no_guarda_el_cambio_de_esta_sesion(self):
        frame = self._frame()
        frame._config = {"overlay_puerto": 8730, "overlay_activo": True}
        with mock.patch.object(gui.overlay_servidor, "encender",
                               side_effect=gui.overlay_servidor.OverlayPuertoOcupadoError()), \
                mock.patch.object(gui, "anunciar"), \
                mock.patch.object(gui, "guardar_opcion") as guardar:
            frame._cambiar_overlay(True)

        self.assertFalse(frame._config["overlay_activo"])
        guardar.assert_not_called()

    def test_cerrar_apaga_el_overlay(self):
        frame = self._frame()
        with mock.patch.object(gui.diagnostico, "hilos_vivos_de_la_aplicacion", return_value=()), \
                mock.patch.object(gui, "anunciar"), \
                mock.patch.object(gui.overlay_servidor, "apagar") as apagar:
            frame._on_close(None)
        apagar.assert_called_once_with()

    def test_el_timer_actualiza_la_marca_del_vigilante(self):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame._alive = True
        frame._diagnostico_marca = 10.0
        frame._diagnostico_censo = 10.0
        with mock.patch.object(gui.time, "monotonic", return_value=12.5), \
                mock.patch.object(gui.diagnostico, "debe_censar_hilos", return_value=None):
            frame._on_diagnostico_timer(None)

        self.assertEqual(frame._diagnostico_marca, 12.5)

    def test_el_vigilante_se_arranca_con_nombre_propio(self):
        hilos = []
        hilo = mock.Mock()

        def crear(target, nombre):
            hilos.append((target, nombre))
            return hilo

        configuracion = mock.Mock()
        configuracion.get.return_value = {}
        with mock.patch.object(gui.wx.Frame, "__init__", return_value=None), \
                mock.patch.object(gui.YTChatFrame, "_build_menubar"), \
                mock.patch.object(gui.YTChatFrame, "_build_ui"), \
                mock.patch.object(gui.YTChatFrame, "_bind_events"), \
                mock.patch.object(gui.YTChatFrame, "_init_timer"), \
                mock.patch.object(gui.YTChatFrame, "SetBackgroundColour"), \
                mock.patch.object(gui.YTChatFrame, "Centre"), \
                mock.patch.object(gui, "anunciar_conflictos_atajos"), \
                mock.patch.object(gui.diagnostico, "crear_hilo", side_effect=crear):
            gui.YTChatFrame(None, configuracion, None, None, None, None)

        self.assertEqual(len(hilos), 1)
        self.assertEqual(hilos[0][1], "VigilanteInterfaz")
        hilo.start.assert_called_once_with()

    def test_el_nombre_del_vigilante_no_es_de_captura(self):
        self.assertNotIn("VigilanteInterfaz", apagado.NOMBRES_HILOS_CAPTURA)

    def test_el_tope_del_cierre_sale_de_apagado(self):
        self.assertEqual(apagado.TOPE_ESPERA_CIERRE, 8.0)
        frame = self._frame()
        hilo = mock.Mock()
        hilo.name = "TikTok"
        hilo.is_alive.return_value = True
        with mock.patch.object(gui.diagnostico, "hilos_vivos_de_la_aplicacion", return_value=("TikTok",)), \
                mock.patch.object(gui, "anunciar"), \
                mock.patch.object(gui.wx, "CallLater"):
            frame._on_close(None)

        self.assertEqual(frame._cierre_tope, apagado.TOPE_ESPERA_CIERRE)

    def test_comprobar_cierre_con_hilos_vivos_reprograma_y_no_destruye(self):
        frame = self._frame()
        frame._cierre_inicio = 100.0
        tope = apagado.TOPE_ESPERA_CIERRE
        frame._cierre_tope = tope
        hilo = mock.Mock(name="Chat")
        hilo.name = "Chat"
        hilo.is_alive.return_value = True
        with mock.patch.object(gui.diagnostico, "hilos_vivos_de_la_aplicacion", return_value=("Chat",)), \
                mock.patch.object(gui.time, "monotonic", return_value=100.0 + tope - 1.0), \
                mock.patch.object(gui.wx, "CallLater") as call_later, \
                mock.patch.object(gui.diagnostico.logger, "log") as logueo, \
                mock.patch.object(gui.diagnostico, "registrar_cierre_fallos") as registro:
            frame._comprobar_cierre()

        call_later.assert_called_once_with(200, frame._comprobar_cierre)
        frame.Destroy.assert_not_called()
        registro.assert_not_called()
        logueo.assert_not_called()

    def test_comprobar_cierre_sin_hilos_destruye_y_registra_cierre_limpio(self):
        frame = self._frame()
        frame._cierre_inicio = 100.0
        frame._cierre_tope = apagado.TOPE_ESPERA_CIERRE
        with mock.patch.object(gui.diagnostico, "hilos_vivos_de_la_aplicacion", return_value=()), \
                mock.patch.object(gui.time, "monotonic", return_value=101.0), \
                mock.patch.object(gui.wx, "CallLater") as call_later, \
                mock.patch.object(gui.diagnostico.logger, "log") as logueo, \
                mock.patch.object(gui.diagnostico, "registrar_cierre_fallos") as registro:
            frame._comprobar_cierre()

        call_later.assert_not_called()
        frame.Destroy.assert_called_once_with()
        logueo.assert_called_once_with(logging.INFO, "%s", "CIERRE captura limpia")
        registro.assert_called_once_with()

    def test_comprobar_cierre_con_tope_vencido_destruye_y_registra_hilos(self):
        frame = self._frame()
        frame._cierre_inicio = 100.0
        tope = apagado.TOPE_ESPERA_CIERRE
        frame._cierre_tope = tope
        hilo = mock.Mock(name="TikTok")
        hilo.name = "TikTok"
        hilo.is_alive.return_value = True
        with mock.patch.object(gui.diagnostico, "hilos_vivos_de_la_aplicacion", return_value=("TikTok",)), \
                mock.patch.object(gui.time, "monotonic", return_value=100.0 + tope + 1.0), \
                mock.patch.object(gui.wx, "CallLater") as call_later, \
                mock.patch.object(gui.diagnostico.logger, "log") as logueo, \
                mock.patch.object(gui.diagnostico, "registrar_cierre_fallos") as registro:
            frame._comprobar_cierre()

        call_later.assert_not_called()
        frame.Destroy.assert_called_once_with()
        logueo.assert_called_once_with(
            logging.WARNING, "%s", f"CIERRE por tope={tope:.1f}s hilos vivos=TikTok")
        registro.assert_not_called()

    def test_nacimiento_tardio_detecta_reproductor_stop_nacido_en_detener_todo(self):
        import threading
        frame = self._frame()
        senal = threading.Event()
        hilo_real = None

        def detener_con_nacimiento():
            nonlocal hilo_real
            hilo_real = threading.Thread(target=lambda: senal.wait(timeout=5), name="ReproductorStop")
            hilo_real.start()

        frame._rep_panel.detener_todo.side_effect = detener_con_nacimiento
        llamadas = []

        def censo_aislado():
            if not llamadas:
                llamadas.append(1)
                return ()
            return tuple(sorted(h.name for h in threading.enumerate() if h.is_alive() and h.name == "ReproductorStop"))

        try:
            with mock.patch.object(gui.diagnostico, "hilos_vivos_de_la_aplicacion", side_effect=censo_aislado), \
                    mock.patch.object(gui, "anunciar") as anunciar, \
                    mock.patch.object(gui.wx, "CallLater") as call_later, \
                    mock.patch.object(gui.diagnostico.logger, "log") as logueo, \
                    mock.patch.object(gui.diagnostico, "registrar_cierre_fallos") as registro:
                frame._on_close(None)
                call_later.assert_called_once_with(200, frame._comprobar_cierre)
                frame.Destroy.assert_not_called()
                registro.assert_not_called()
                logueo.assert_not_called()
                anunciar.assert_not_called()
        finally:
            senal.set()
            if hilo_real is not None:
                hilo_real.join(timeout=2)
                self.assertFalse(hilo_real.is_alive())


if __name__ == "__main__":
    unittest.main()
