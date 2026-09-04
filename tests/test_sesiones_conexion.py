import queue
import sys
import threading
import types
import unittest
from unittest import mock

from conexion import Conexiones
from sesiones import RegistroSesiones


class RegistroEspia(RegistroSesiones):
    def __init__(self):
        super().__init__()
        self.sesiones = []

    def abrir(self):
        sesion = super().abrir()
        self.sesiones.append(sesion)
        return sesion


class HiloInerte:
    def start(self):
        return None


class HiloEjecuta:
    def __init__(self, objetivo):
        self.objetivo = objetivo

    def start(self):
        self.objetivo()


def crear_hilo_inerte(*args, **kwargs):
    return HiloInerte()


class PruebasSesiones(unittest.TestCase):
    def test_abrir_dos_veces_para_la_sesion_anterior(self):
        registro = RegistroSesiones()
        anterior = registro.abrir()
        nueva = registro.abrir()
        self.assertTrue(anterior.parada.is_set())
        self.assertFalse(nueva.parada.is_set())

    def test_vigente_solo_acepta_el_gen_recien_abierto(self):
        registro = RegistroSesiones()
        anterior = registro.abrir()
        nueva = registro.abrir()
        self.assertTrue(registro.vigente(nueva.gen))
        self.assertFalse(registro.vigente(anterior.gen))

    def test_cerrar_es_idempotente_y_para_la_vigente(self):
        registro = RegistroSesiones()
        sesion = registro.abrir()
        self.assertTrue(registro.cerrar())
        self.assertTrue(sesion.parada.is_set())
        self.assertFalse(registro.cerrar())

    def test_una_sesion_cerrada_deja_de_ser_vigente(self):
        # El hilo Chat que seguía en yt-dlp tras desconectar no debe pasar
        # el guard y aplicar título, historial o «conectado» del vídeo cancelado.
        registro = RegistroSesiones()
        sesion = registro.abrir()
        self.assertTrue(registro.vigente(sesion.gen))
        registro.cerrar()
        self.assertFalse(registro.vigente(sesion.gen))


class PruebasCableadoConexiones(unittest.TestCase):
    def setUp(self):
        self.gui_falsa = types.SimpleNamespace(_gui_frame=None)
        self.modulo_gui_anterior = sys.modules.get("gui")
        sys.modules["gui"] = self.gui_falsa
        self.registro = RegistroEspia()
        self.conexiones = Conexiones(
            queue.Queue(), {}, mock.Mock(), threading.Event(),
            crear_hilo=crear_hilo_inerte, registro=self.registro)

    def tearDown(self):
        if self.modulo_gui_anterior is None:
            sys.modules.pop("gui", None)
        else:
            sys.modules["gui"] = self.modulo_gui_anterior

    def test_conectar_dos_veces_para_la_sesion_de_youtube(self):
        self.conexiones.conectar("dQw4w9WgXcQ")
        self.conexiones.conectar("9bZkp7q19f0")
        self.assertTrue(self.registro.sesiones[0].parada.is_set())
        self.assertFalse(self.registro.sesiones[1].parada.is_set())

    def test_conectar_youtube_y_tiktok_para_youtube(self):
        self.conexiones.conectar("dQw4w9WgXcQ")
        self.conexiones.conectar("https://www.tiktok.com/@pepe/live")
        self.assertTrue(self.registro.sesiones[0].parada.is_set())
        self.assertFalse(self.registro.sesiones[1].parada.is_set())

    def test_desconectar_para_la_sesion_vigente(self):
        self.conexiones.conectar("dQw4w9WgXcQ")
        self.conexiones.desconectar()
        self.assertTrue(self.registro.sesiones[0].parada.is_set())

    def test_youtube_difunde_solo_despues_del_guard_de_sesion(self):
        import main
        callbacks = {}
        def hilo(objetivo, nombre, **kwargs):
            # Se filtra por nombre para que los hilos auxiliares no bloqueen la prueba.
            return HiloEjecuta(objetivo) if nombre == "Chat" else HiloInerte()
        def captura(*args, **kwargs):
            callbacks.update(kwargs)
        with mock.patch.object(main, "obtener_info_video",
                               return_value=("Título", main.deteccion.LIVE, {})), \
                mock.patch.object(main.deteccion, "tiene_chat_en_vivo", return_value=True), \
                mock.patch.object(main, "captura_con_reconexion", side_effect=captura), \
                mock.patch("overlay_servidor.difundir") as difundir:
            self.conexiones._crear_hilo = hilo
            self.conexiones.conectar("dQw4w9WgXcQ")
            callbacks["on_message"]("Ana", "Hola", "12:00", monto="US$ 5")
        difundir.assert_called_once()
        self.assertEqual(difundir.call_args.args[0]["plataforma"], "youtube")
        self.assertEqual(difundir.call_args.args[0]["monto"], "US$ 5")

    def test_tiktok_difunde_el_regalo(self):
        import main
        callbacks = {}
        def hilo(objetivo, nombre, **kwargs):
            # Se filtra por nombre para ejecutar solo el hilo que usa esta prueba.
            return HiloEjecuta(objetivo) if nombre == "TikTok" else HiloInerte()
        def captura(*args, **kwargs):
            callbacks.update(kwargs)
        self.conexiones._crear_hilo = hilo
        with mock.patch.object(main, "procesar_entrante", side_effect=lambda *a, **k: k["on_message"](
                "Ana", "Hola", main.TIPO_TEXTO, "regalo", "")), \
                mock.patch.object(__import__("tiktok_captura"), "capturar_con_reconexion", side_effect=captura), \
                mock.patch("overlay_servidor.difundir") as difundir:
            self.conexiones._conectar_tiktok("pepe")
            callbacks["on_evento"]("Ana", "Hola", main.TIPO_TEXTO, "regalo", "")
        self.assertEqual(difundir.call_args.args[0]["plataforma"], "tiktok")

    def test_youtube_pasa_el_guard_de_sesion_a_obtener_info_video(self):
        import main
        recibido = {}

        def info(vid, **kwargs):
            recibido.update(kwargs)
            return ("Título", main.deteccion.LIVE, {})
        with mock.patch.object(main, "obtener_info_video", side_effect=info), \
                mock.patch.object(main.deteccion, "tiene_chat_en_vivo", return_value=False):
            self.conexiones._crear_hilo = lambda objetivo, nombre, **kwargs: (
                HiloEjecuta(objetivo) if nombre == "Chat" else HiloInerte())
            self.conexiones.conectar("dQw4w9WgXcQ")
        # Mientras la sesión sigue vigente responde True; al abrir otra, False:
        # así obtener_info_video deja de encadenar pasos tras desconectar.
        self.assertTrue(recibido["sesion_activa"]())
        self.registro.abrir()
        self.assertFalse(recibido["sesion_activa"]())

    def test_los_detalles_del_directo_se_consultan_nada_mas_conectar(self):
        import main
        import wx
        consultas = []
        esperas = []
        hilos = {}
        frame = mock.Mock()
        frame._alive = True
        self.gui_falsa._gui_frame = frame

        class ClienteFalso:
            def __init__(self, credenciales):
                pass

            def detalles_directo(self, vid):
                consultas.append(vid)
                return {"espectadores": 42, "comienzo": "12:00"}

        def hilo(objetivo, nombre, **kwargs):
            if nombre == "Chat":
                return HiloEjecuta(objetivo)
            hilos[nombre] = objetivo
            return HiloInerte()

        credenciales_falso = types.SimpleNamespace(hay_lectura=lambda: True,
                                                   cargar=lambda: {})
        youtube_api_falso = types.SimpleNamespace(google_disponible=lambda: True,
                                                  ClienteYouTube=ClienteFalso)
        llamadas = []
        with mock.patch.object(main, "obtener_info_video",
                               return_value=("Título", main.deteccion.LIVE, {})), \
                mock.patch.object(main.deteccion, "tiene_chat_en_vivo", return_value=True), \
                mock.patch.object(main, "captura_con_reconexion"), \
                mock.patch.dict(sys.modules, {"credenciales": credenciales_falso,
                                              "youtube_api": youtube_api_falso}), \
                mock.patch.object(wx, "CallAfter",
                                  side_effect=lambda fn, *a, **k: llamadas.append((fn, a))):
            self.conexiones._crear_hilo = hilo
            self.conexiones.conectar("dQw4w9WgXcQ")
            parada = self.registro.sesiones[0].parada

            def esperar(timeout=None):
                # La primera espera ya cierra la sesión: el bucle da UNA vuelta.
                esperas.append(timeout)
                parada.set()
                return True
            with mock.patch.object(parada, "wait", side_effect=esperar):
                hilos["DetallesDirecto"]()

        # Antes se esperaba un minuto entero antes de la primera consulta.
        self.assertEqual(consultas, ["dQw4w9WgXcQ"])
        self.assertEqual(esperas, [60])
        self.assertIn((frame.set_espectadores, (42,)), llamadas)

    def test_youtube_sesion_vieja_no_difunde(self):
        import main
        callbacks = {}
        def captura(*args, **kwargs):
            callbacks.update(kwargs)
        with mock.patch.object(main, "obtener_info_video",
                               return_value=("Título", main.deteccion.LIVE, {})), \
                mock.patch.object(main.deteccion, "tiene_chat_en_vivo", return_value=True), \
                mock.patch.object(main, "captura_con_reconexion", side_effect=captura), \
                mock.patch("overlay_servidor.difundir") as difundir:
            # Se filtra por nombre para que los hilos auxiliares no bloqueen la prueba.
            self.conexiones._crear_hilo = lambda objetivo, nombre, **kwargs: (
                HiloEjecuta(objetivo) if nombre == "Chat" else HiloInerte())
            self.conexiones.conectar("dQw4w9WgXcQ")
            self.registro.abrir()
            callbacks["on_message"]("Ana", "viejo", "12:00")
        difundir.assert_not_called()


class TestPlataformaMensajesChat(unittest.TestCase):
    def setUp(self):
        self.gui_falsa = types.SimpleNamespace(_gui_frame=None)
        self.modulo_gui_anterior = sys.modules.get("gui")
        sys.modules["gui"] = self.gui_falsa
        self.registro = RegistroEspia()
        self.conexiones = Conexiones(
            queue.Queue(), {}, mock.Mock(), threading.Event(),
            crear_hilo=crear_hilo_inerte, registro=self.registro)

    def tearDown(self):
        if self.modulo_gui_anterior is None:
            sys.modules.pop("gui", None)
        else:
            sys.modules["gui"] = self.modulo_gui_anterior

    def test_youtube_entrega_plataforma_youtube_a_gui(self):
        import main
        import wx
        callbacks = {}
        def hilo(objetivo, nombre, **kwargs):
            return HiloEjecuta(objetivo) if nombre == "Chat" else HiloInerte()
        def captura(*args, **kwargs):
            callbacks.update(kwargs)
        frame = mock.Mock()
        frame._alive = True
        self.gui_falsa._gui_frame = frame
        llamadas = []
        def call_after(fn, *args, **kwargs):
            llamadas.append((fn, args, kwargs))
            # Capturar el método y argumentos sin ejecutar
            return mock.Mock()
        with mock.patch.object(main, "obtener_info_video",
                               return_value=("Título", main.deteccion.LIVE, {})), \
                mock.patch.object(main.deteccion, "tiene_chat_en_vivo", return_value=True), \
                mock.patch.object(main, "captura_con_reconexion", side_effect=captura), \
                mock.patch("overlay_servidor.difundir"), \
                mock.patch.object(wx, "CallAfter", side_effect=call_after):
            self.conexiones._crear_hilo = hilo
            self.conexiones.conectar("dQw4w9WgXcQ")
            callbacks["on_message"]("Ana", "Hola", "12:00", monto="US$ 5", canal_id="CANAL123")
        # Debe haber llamado a agregar_mensaje_chat con plataforma youtube
        agregados = [(fn, a, kw) for fn, a, kw in llamadas if fn is frame.agregar_mensaje_chat]
        self.assertTrue(agregados)
        fn, args, kwargs = agregados[0]
        self.assertEqual(kwargs.get("plataforma"), "youtube")
        # Verificar que canal_id también se entregó
        self.assertIn("CANAL123", args)

    def test_tiktok_entrega_plataforma_tiktok_a_gui(self):
        import main
        import wx
        import tiktok_captura
        callbacks = {}
        def hilo(objetivo, nombre, **kwargs):
            return HiloEjecuta(objetivo) if nombre == "TikTok" else HiloInerte()
        def captura(*args, **kwargs):
            callbacks.update(kwargs)
        frame = mock.Mock()
        frame._alive = True
        self.gui_falsa._gui_frame = frame
        llamadas = []
        def call_after(fn, *args, **kwargs):
            llamadas.append((fn, args, kwargs))
            return mock.Mock()
        self.conexiones._crear_hilo = hilo
        with mock.patch.object(main, "procesar_entrante",
                               side_effect=lambda *a, **k: k["on_message"](
                                   "Ana", "Hola", "12:00", main.TIPO_TEXTO, "regalo", "TIKID")), \
                mock.patch.object(tiktok_captura, "capturar_con_reconexion", side_effect=captura), \
                mock.patch("overlay_servidor.difundir"), \
                mock.patch.object(wx, "CallAfter", side_effect=call_after):
            self.conexiones._conectar_tiktok("pepe")
            callbacks["on_evento"]("Ana", "Hola", main.TIPO_TEXTO, "regalo", "TIKID")
        agregados = [(fn, a, kw) for fn, a, kw in llamadas if fn is frame.agregar_mensaje_chat]
        self.assertTrue(agregados)
        fn, args, kwargs = agregados[0]
        self.assertEqual(kwargs.get("plataforma"), "tiktok")


if __name__ == "__main__":
    unittest.main()
