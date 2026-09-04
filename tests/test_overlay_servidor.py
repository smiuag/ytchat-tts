import json
import queue
import socket
import threading
import time
import unittest
import io
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from unittest import mock

from overlay_datos import evento_de_mensaje
from overlay_servidor import OverlayPuertoOcupadoError, OverlayServidor
import overlay_servidor


def puerto_libre():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def esperar_clientes(servidor, cantidad=1):
    limite = time.monotonic() + 2
    while time.monotonic() < limite:
        if servidor.estado()["clientes"] == cantidad:
            return
        time.sleep(0.01)
    raise AssertionError("el cliente SSE no se registró")


def leer_evento(respuesta):
    datos = bytearray()
    while True:
        linea = respuesta.readline()
        if not linea:
            raise AssertionError("el flujo SSE terminó antes del evento")
        if linea == b"\n":
            if datos:
                return json.loads(bytes(datos).decode("utf-8"))
            continue
        if linea.startswith(b"data: "):
            datos.extend(linea[6:].rstrip(b"\n"))


class OverlayServidorTests(unittest.TestCase):
    def setUp(self):
        self.servidor = OverlayServidor(puerto_libre(), pagina=b"pagina")
        self.servidor.iniciar()
        self.base = f"http://127.0.0.1:{self.servidor.puerto}"

    def tearDown(self):
        self.servidor.detener()

    def test_sirve_pagina_estado_y_esta_atado_a_localhost(self):
        with urlopen(self.base + "/chat") as respuesta:
            self.assertEqual(respuesta.read(), b"pagina")
        with urlopen(self.base + "/estado") as respuesta:
            self.assertEqual(json.load(respuesta), {"clientes": 0})
        self.assertEqual(self.servidor._servidor.server_address[0], "127.0.0.1")

    def test_difusion_llega_a_todos_los_clientes(self):
        uno = urlopen(self.base + "/eventos", timeout=3)
        dos = urlopen(self.base + "/eventos", timeout=3)
        try:
            esperar_clientes(self.servidor, 2)
            evento = evento_de_mensaje("Ana", "Hola", "youtube")
            self.servidor.difundir(evento)
            self.assertEqual(leer_evento(uno), evento)
            self.assertEqual(leer_evento(dos), evento)
        finally:
            uno.close()
            dos.close()

    def test_cliente_tardio_recibe_los_ultimos_treinta(self):
        eventos = [evento_de_mensaje(str(i), "texto", "youtube")
                   for i in range(35)]
        for evento in eventos:
            self.servidor.difundir(evento)
        respuesta = urlopen(self.base + "/eventos", timeout=3)
        try:
            esperar_clientes(self.servidor)
            recibidos = [leer_evento(respuesta) for _ in range(30)]
            self.assertEqual(recibidos, eventos[-30:])
        finally:
            respuesta.close()

    def test_parada_cierra_el_hilo_y_permite_reutilizar_puerto(self):
        hilo = self.servidor._hilo
        self.servidor.detener()
        self.assertFalse(hilo.is_alive())
        siguiente = OverlayServidor(self.servidor.puerto, pagina=b"otra")
        try:
            siguiente.iniciar()
            self.assertTrue(siguiente._hilo.is_alive())
        finally:
            siguiente.detener()

    def test_parada_cierra_la_conexion_sse(self):
        conexion = socket.create_connection(("127.0.0.1", self.servidor.puerto),
                                             timeout=3)
        try:
            conexion.sendall(
                b"GET /eventos HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Accept: text/event-stream\r\n"
                b"\r\n")
            cabeceras = bytearray()
            while b"\r\n\r\n" not in cabeceras:
                parte = conexion.recv(4096)
                self.assertTrue(parte, "el servidor no envió las cabeceras SSE")
                cabeceras.extend(parte)
            self.assertIn(b"Content-Type: text/event-stream", cabeceras)
            esperar_clientes(self.servidor)

            self.servidor.detener()

            conexion.settimeout(5)
            while conexion.recv(4096):
                pass
        finally:
            conexion.close()

    def test_puerto_ocupado_falla_sin_cambiarlo(self):
        puerto = puerto_libre()
        ocupado = socket.socket()
        ocupado.bind(("127.0.0.1", puerto))
        try:
            servidor = OverlayServidor(puerto, pagina=b"pagina")
            with self.assertRaises(OverlayPuertoOcupadoError) as contexto:
                servidor.iniciar()
            self.assertIn(str(puerto), str(contexto.exception))
            self.assertIsNone(servidor._servidor)
            self.assertIsNone(servidor._hilo)
        finally:
            ocupado.close()

    def test_no_registra_texto_en_el_log(self):
        texto = "<img src=x onerror=HACKEADO>"
        self.servidor.difundir(evento_de_mensaje("autor", texto, "youtube"))
        self.assertEqual(len(self.servidor._anillo), 1)

    def test_cada_evento_lleva_un_id_creciente(self):
        respuesta = urlopen(self.base + "/eventos", timeout=3)
        try:
            esperar_clientes(self.servidor)
            self.servidor.difundir(evento_de_mensaje("Ana", "uno", "youtube"))
            self.servidor.difundir(evento_de_mensaje("Ana", "dos", "youtube"))
            epoca = self.servidor._epoca
            self.assertEqual(respuesta.readline(), f"id: {epoca}-1\n".encode())
            self.assertTrue(respuesta.readline().startswith(b"data: "))
            self.assertEqual(respuesta.readline(), b"\n")
            self.assertEqual(respuesta.readline(), f"id: {epoca}-2\n".encode())
        finally:
            respuesta.close()

    def test_reconexion_con_last_event_id_solo_recibe_lo_nuevo(self):
        eventos = [evento_de_mensaje(str(i), "texto", "youtube") for i in range(3)]
        for evento in eventos:
            self.servidor.difundir(evento)
        peticion = Request(self.base + "/eventos",
                           headers={"Last-Event-ID": f"{self.servidor._epoca}-2"})
        respuesta = urlopen(peticion, timeout=3)
        try:
            esperar_clientes(self.servidor)
            self.assertEqual(leer_evento(respuesta), eventos[2])
            nuevo = evento_de_mensaje("Ana", "vivo", "youtube")
            self.servidor.difundir(nuevo)
            self.assertEqual(leer_evento(respuesta), nuevo)
        finally:
            respuesta.close()

    def test_last_event_id_de_otra_ejecucion_reenvia_el_anillo_entero(self):
        eventos = [evento_de_mensaje(str(i), "texto", "youtube") for i in range(3)]
        for evento in eventos:
            self.servidor.difundir(evento)
        for cabecera in ("otra-2", "basura", f"{self.servidor._epoca}-x"):
            with self.subTest(cabecera=cabecera):
                peticion = Request(self.base + "/eventos",
                                   headers={"Last-Event-ID": cabecera})
                respuesta = urlopen(peticion, timeout=3)
                try:
                    self.assertEqual(leer_evento(respuesta), eventos[0])
                finally:
                    respuesta.close()

    def test_ultimo_id_visto(self):
        self.assertEqual(overlay_servidor.ultimo_id_visto("abcd-12", "abcd"), 12)
        self.assertEqual(overlay_servidor.ultimo_id_visto("otra-12", "abcd"), 0)
        self.assertEqual(overlay_servidor.ultimo_id_visto(None, "abcd"), 0)
        self.assertEqual(overlay_servidor.ultimo_id_visto("abcd-", "abcd"), 0)

    def test_un_cliente_que_no_drena_su_cola_se_corta(self):
        canal = queue.Queue(maxsize=2)
        with self.servidor._bloqueo:
            self.servidor._clientes.add(canal)
        try:
            for i in range(3):
                self.servidor.difundir(evento_de_mensaje("Ana", str(i), "youtube"))
            self.assertIsNone(canal.get_nowait())
            self.assertTrue(canal.empty())
        finally:
            with self.servidor._bloqueo:
                self.servidor._clientes.discard(canal)

    def test_la_cola_de_cada_cliente_tiene_tope(self):
        original = overlay_servidor.TOPE_COLA
        overlay_servidor.TOPE_COLA = 5
        respuesta = urlopen(self.base + "/eventos", timeout=3)
        try:
            esperar_clientes(self.servidor)
            canal = next(iter(self.servidor._clientes))
            self.assertEqual(canal.maxsize, 5)
        finally:
            overlay_servidor.TOPE_COLA = original
            respuesta.close()

    def test_latido_despues_de_silencio(self):
        original = overlay_servidor.INTERVALO_LATIDO
        overlay_servidor.INTERVALO_LATIDO = 0.05
        respuesta = urlopen(self.base + "/eventos", timeout=3)
        try:
            esperar_clientes(self.servidor)
            self.assertEqual(respuesta.readline(), b": latido\n")
        finally:
            overlay_servidor.INTERVALO_LATIDO = original
            respuesta.close()

    def test_hilo_del_servidor_es_demonio(self):
        self.assertTrue(self.servidor._hilo.daemon)

    def test_pagina_se_busca_en_la_carpeta_de_la_aplicacion(self):
        carpeta = Path("carpeta-del-ejecutable")
        ruta_esperada = carpeta / "web" / "chat.html"
        original = Path.open
        def abrir(ruta, *args, **kwargs):
            self.assertEqual(ruta, ruta_esperada)
            return io.BytesIO(b"paquete")
        with mock.patch.object(overlay_servidor.config, "app_dir", return_value=carpeta), \
                mock.patch.object(Path, "open", new=abrir):
            self.assertEqual(overlay_servidor._leer_pagina(), b"paquete")


class EnvoltorioOverlayTests(unittest.TestCase):
    def tearDown(self):
        overlay_servidor.apagar()

    def test_difundir_apagado_no_hace_nada(self):
        overlay_servidor.difundir({"texto": "sin panel"})
        self.assertFalse(overlay_servidor.esta_encendido())

    def test_envolver_encendido_y_apagado(self):
        puerto = puerto_libre()
        overlay_servidor.encender(puerto)
        self.assertTrue(overlay_servidor.esta_encendido())
        self.assertEqual(overlay_servidor.puerto_actual(), puerto)
        overlay_servidor.apagar()
        overlay_servidor.apagar()
        self.assertEqual(overlay_servidor.cuantos_miran(), 0)

    def test_cuantos_miran_cuenta_un_cliente_sse(self):
        puerto = puerto_libre()
        overlay_servidor.encender(puerto)
        respuesta = urlopen(f"http://127.0.0.1:{puerto}/eventos", timeout=3)
        try:
            limite = time.monotonic() + 2
            while time.monotonic() < limite and overlay_servidor.cuantos_miran() != 1:
                time.sleep(0.01)
            self.assertEqual(overlay_servidor.cuantos_miran(), 1)
        finally:
            respuesta.close()

    def test_puerto_actual_es_none_con_el_panel_apagado(self):
        self.assertIsNone(overlay_servidor.puerto_actual())

    def test_encender_dos_veces_conserva_la_misma_instancia(self):
        puerto = puerto_libre()
        try:
            overlay_servidor.encender(puerto)
            instancia = overlay_servidor._INSTANCIA
            overlay_servidor.encender(puerto)
            self.assertIs(overlay_servidor._INSTANCIA, instancia)
        finally:
            overlay_servidor.apagar()
        self.assertFalse(overlay_servidor.esta_encendido())


if __name__ == "__main__":
    unittest.main()
