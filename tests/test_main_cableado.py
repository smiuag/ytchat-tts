import asyncio
import queue
import threading
import unittest
import sys
import types
from unittest.mock import Mock, patch

import main


class ConexionFalsa:
    def __init__(self, *args):
        self.llamadas = []

    def conectar(self, url):
        self.llamadas.append(("conectar", url))

    def desconectar(self):
        self.llamadas.append(("desconectar",))


class PruebasCableadoMain(unittest.TestCase):
    def test_main_registra_el_entorno_en_un_hilo(self):
        message_box = Mock()
        ctypes_falso = types.SimpleNamespace(
            windll=types.SimpleNamespace(
                user32=types.SimpleNamespace(MessageBoxW=message_box)))
        with patch.object(main, "_verificar_instancia_unica", return_value=False), \
                patch.object(main, "configurar_logging"), \
                patch.object(main.diagnostico, "instalar_capturadores"), \
                patch.object(main.diagnostico, "registrar_entorno_en_hilo") as registrar, \
                patch.object(main.diagnostico, "registrar_entorno") as bloquear, \
                patch.dict(sys.modules, {"ctypes": ctypes_falso}), \
                patch.object(sys, "exit", side_effect=SystemExit(0)):
            with self.assertRaises(SystemExit):
                main.main()

        registrar.assert_called_once_with(main.APP_VERSION)
        bloquear.assert_not_called()

    def test_main_no_registra_el_entorno_de_forma_bloqueante(self):
        message_box = Mock()
        ctypes_falso = types.SimpleNamespace(
            windll=types.SimpleNamespace(
                user32=types.SimpleNamespace(MessageBoxW=message_box)))
        with patch.object(main, "_verificar_instancia_unica", return_value=False), \
                patch.object(main, "configurar_logging"), \
                patch.object(main.diagnostico, "instalar_capturadores"), \
                patch.object(main.diagnostico, "registrar_entorno_en_hilo"), \
                patch.object(main.diagnostico, "registrar_entorno") as bloquear, \
                patch.dict(sys.modules, {"ctypes": ctypes_falso}), \
                patch.object(sys, "exit", side_effect=SystemExit(0)):
            with self.assertRaises(SystemExit):
                main.main()

        bloquear.assert_not_called()

    def test_aviso_de_instancia_usa_banderas_de_primer_plano(self):
        message_box = Mock()
        ctypes_falso = types.SimpleNamespace(
            windll=types.SimpleNamespace(
                user32=types.SimpleNamespace(MessageBoxW=message_box)))

        with patch.object(main, "_verificar_instancia_unica", return_value=False), \
                patch.object(main, "configurar_logging"), \
                patch.object(main.diagnostico, "instalar_capturadores"), \
                patch.object(main.diagnostico, "registrar_entorno_en_hilo"), \
                patch.dict(sys.modules, {"ctypes": ctypes_falso}), \
                patch.object(sys, "exit", side_effect=SystemExit(0)):
            with self.assertRaises(SystemExit):
                main.main()

        banderas = message_box.call_args.args[3]
        self.assertEqual(banderas, 0x40 | 0x00010000 | 0x00040000)

    def test_los_callbacks_comparten_el_registro_de_conexiones(self):
        with patch.object(main.conexion, "Conexiones", ConexionFalsa):
            conectar, desconectar = main.armar_callbacks_captura(
                object(), {}, object(), object())

        conectar("directo")
        desconectar()
        self.assertIs(conectar.__self__, desconectar.__self__)
        self.assertEqual(conectar.__self__.llamadas,
                         [("conectar", "directo"), ("desconectar",)])

    def test_iniciar_interfaz_cierra_sonidos_sin_marcar_limpio_al_volver(self):
        orden = []
        conectar = object()
        desconectar = object()

        def armar(*args):
            orden.append("callbacks")
            return conectar, desconectar

        def iniciar(**kwargs):
            orden.append(("gui", kwargs["iniciar_captura_cb"],
                          kwargs["detener_captura_cb"]))

        with patch.object(main, "armar_callbacks_captura", side_effect=armar), \
                patch.object(main.diagnostico, "registrar_cierre_fallos",
                             side_effect=lambda: orden.append("cierre")), \
                patch.object(main._snd, "cerrar", side_effect=lambda: orden.append("sonido")):
            main.iniciar_interfaz({}, object(), object(), object(), object(), iniciar)

        self.assertEqual(orden, ["callbacks", ("gui", conectar, desconectar),
                                 "sonido"])
        self.assertNotIn("cierre", orden)

    def test_iniciar_interfaz_no_duplica_marca_limpia_y_cierra_sonidos(self):
        conectar = object()
        desconectar = object()
        registro = Mock()

        def gui_falsa(**kwargs):
            registro()

        def armar(*a):
            return conectar, desconectar

        with patch.object(main, "armar_callbacks_captura", side_effect=armar), \
                patch.object(main.diagnostico, "registrar_cierre_fallos", registro), \
                patch.object(main._snd, "cerrar") as cerrar:
            main.iniciar_interfaz({}, object(), object(), object(), object(), gui_falsa)

        self.assertEqual(registro.call_count, 1)
        cerrar.assert_called_once_with()


class PruebasInstanciaUnica(unittest.TestCase):
    def test_already_exists_es_otra_instancia(self):
        self.assertTrue(main._hay_otra_instancia(183))

    def test_access_denied_tambien_cuenta_como_otra_instancia(self):
        # El mutex existe pero lo creó una instancia elevada o de otro usuario.
        self.assertTrue(main._hay_otra_instancia(5))

    def test_sin_error_no_hay_otra_instancia(self):
        self.assertFalse(main._hay_otra_instancia(0))


class PruebasReconexion(unittest.TestCase):
    def _config(self, max_intentos=3):
        return {"reconectar": True, "max_intentos": max_intentos,
                "espera_entre_intentos": 0}

    def _correr(self, captura, config):
        estados = []
        with patch.object(main, "_captura", side_effect=captura), \
                patch.object(main._snd, "reproducir"):
            main.captura_con_reconexion(
                "v", queue.Queue(), config, threading.Event(), main.Stats(),
                on_estado=lambda tipo, texto: estados.append((tipo, texto)))
        return estados

    def test_los_intentos_se_reinician_tras_cada_reconexion(self):
        caidas = [0]

        def captura(video_id, cola, cfg, parada, stats, on_message, on_estado,
                    sesion_activa):
            # Cada intento conecta y luego sufre un microcorte.
            caidas[0] += 1
            on_estado("conectado", "ok")
            if caidas[0] >= 6:
                parada.set()
            return RuntimeError("microcorte")

        estados = self._correr(captura, self._config(max_intentos=3))
        self.assertEqual(caidas[0], 6)
        self.assertFalse(any("agotaron" in texto for _, texto in estados))
        # Y el aviso de reintento vuelve a contar desde 1 cada vez.
        reintentos = [texto for tipo, texto in estados if tipo == "reintentando"]
        self.assertTrue(all("(intento 1 de 3)" in texto for texto in reintentos))

    def test_los_fallos_seguidos_si_agotan_los_intentos(self):
        def captura(video_id, cola, cfg, parada, stats, on_message, on_estado,
                    sesion_activa):
            return RuntimeError("no conecta")

        estados = self._correr(captura, self._config(max_intentos=3))
        self.assertTrue(any("agotaron los 3" in texto for _, texto in estados))

    def test_captura_cierra_el_loop_de_asyncio_de_cada_intento(self):
        loops = []

        def en_loop(*args, **kwargs):
            loops.append(asyncio.get_event_loop())
            return None

        with patch.object(main, "_captura_en_loop", side_effect=en_loop):
            main._captura("v", queue.Queue(), {}, threading.Event(), main.Stats())
            main._captura("v", queue.Queue(), {}, threading.Event(), main.Stats())
        self.assertEqual(len(loops), 2)
        self.assertIsNot(loops[0], loops[1])
        self.assertTrue(all(loop.is_closed() for loop in loops))


class PruebasInfoVideoCancelable(unittest.TestCase):
    def test_no_encadena_mas_pasos_si_la_sesion_ya_no_vale(self):
        modulo = types.SimpleNamespace(YoutubeDL=Mock(side_effect=RuntimeError("fallo")))
        with patch.dict(sys.modules, {"yt_dlp": modulo}), \
                patch.object(main.ytdlp_bin, "info_video") as ejecutable, \
                patch.object(main, "_descargar_watch") as respaldo:
            titulo, tipo, metadatos = main.obtener_info_video(
                "A" * 11, sesion_activa=lambda: False)
        ejecutable.assert_not_called()
        respaldo.assert_not_called()
        self.assertEqual((titulo, tipo, metadatos), ("", main.deteccion.DESCONOCIDO, {}))

    def test_sesion_vigente_sigue_la_cadena_completa(self):
        modulo = types.SimpleNamespace(YoutubeDL=Mock(side_effect=RuntimeError("fallo")))
        with patch.dict(sys.modules, {"yt_dlp": modulo}), \
                patch.object(main.ytdlp_bin, "info_video", return_value=None) as ejecutable, \
                patch.object(main, "_descargar_watch", return_value="") as respaldo, \
                patch.object(main, "_clasificar_por_api", return_value=main.deteccion.DESCONOCIDO):
            main.obtener_info_video("A" * 11, sesion_activa=lambda: True)
        ejecutable.assert_called_once()
        respaldo.assert_called_once()


if __name__ == "__main__":
    unittest.main()
