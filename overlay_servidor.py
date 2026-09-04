"""Servidor local del panel de chat."""

from collections import deque
import http.server
import json
import queue
import secrets
import threading

import config

INTERVALO_LATIDO = 15
# Eventos que un espectador puede dejar sin leer antes de que se le corte.
TOPE_COLA = 64


class OverlayPuertoOcupadoError(RuntimeError):
    """El puerto solicitado no se pudo reservar."""


class _Servidor(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, propietario, direccion, puerto):
        self.propietario = propietario
        super().__init__((direccion, puerto), _Manejador)


class _Manejador(http.server.BaseHTTPRequestHandler):
    server_version = "OverlayChat/1.0"

    def log_message(self, formato, *argumentos):
        return

    def do_GET(self):
        if self.path == "/chat":
            contenido = self.server.propietario.pagina
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(contenido)))
            self.end_headers()
            self.wfile.write(contenido)
        elif self.path == "/estado":
            contenido = json.dumps(self.server.propietario.estado(),
                                   ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(contenido)))
            self.end_headers()
            self.wfile.write(contenido)
        elif self.path == "/eventos":
            self._eventos()
        else:
            self.send_error(404)

    def _eventos(self):
        propietario = self.server.propietario
        canal = queue.Queue(maxsize=TOPE_COLA)
        # Al reconectar en menos de diez segundos la página conserva lo
        # pintado; repetirle el anillo entero duplicaba mensajes.
        ultimo = ultimo_id_visto(self.headers.get("Last-Event-ID"), propietario._epoca)
        with propietario._bloqueo:
            anillo = [par for par in propietario._anillo if par[0] > ultimo]
            propietario._clientes.add(canal)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            for numero, evento in anillo:
                self._enviar(numero, evento)
            while not propietario._detener.is_set():
                try:
                    par = canal.get(timeout=INTERVALO_LATIDO)
                except queue.Empty:
                    self.wfile.write(b": latido\n\n")
                    self.wfile.flush()
                    continue
                if par is None:
                    break
                self._enviar(*par)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with propietario._bloqueo:
                propietario._clientes.discard(canal)
            # El navegador necesita EOF para detectar que el panel se apagó.
            self.close_connection = True

    def _enviar(self, numero, evento):
        datos = json.dumps(evento, ensure_ascii=False, separators=(",", ":"))
        identificador = f"{self.server.propietario._epoca}-{numero}"
        self.wfile.write((f"id: {identificador}\ndata: " + datos + "\n\n").encode("utf-8"))
        self.wfile.flush()


def ultimo_id_visto(cabecera, epoca) -> int:
    """Número del último evento que el espectador ya pintó, o 0."""
    # La época distingue esta ejecución de otra anterior: tras reiniciar la
    # aplicación la numeración vuelve a empezar y el anillo entero es nuevo.
    prefijo = f"{epoca}-"
    if not cabecera or not cabecera.startswith(prefijo):
        return 0
    try:
        return int(cabecera[len(prefijo):])
    except ValueError:
        return 0


def _cortar(canal):
    """Vacía la cola de un espectador y le manda el fin de flujo."""
    with canal.mutex:
        canal.queue.clear()
    canal.put_nowait(None)


class OverlayServidor:
    def __init__(self, puerto=8730, pagina=None):
        self.puerto = puerto
        self.pagina = pagina if pagina is not None else _leer_pagina()
        self._anillo = deque(maxlen=30)
        self._epoca = secrets.token_hex(4)
        self._contador = 0
        self._clientes = set()
        self._bloqueo = threading.Lock()
        self._detener = threading.Event()
        self._servidor = None
        self._hilo = None

    def iniciar(self):
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._detener.clear()
        direccion = "127.0.0.1"
        try:
            servidor = _Servidor(self, direccion, self.puerto)
        except OSError as error:
            raise OverlayPuertoOcupadoError(
                f"no se pudo reservar el puerto {self.puerto}") from error
        self._servidor = servidor
        self._hilo = threading.Thread(target=servidor.serve_forever,
                                       name="OverlayServidor", daemon=True)
        self._hilo.start()

    def detener(self):
        servidor, hilo = self._servidor, self._hilo
        if servidor is None:
            return
        self._detener.set()
        with self._bloqueo:
            clientes = list(self._clientes)
        for canal in clientes:
            _cortar(canal)
        servidor.shutdown()
        hilo.join(timeout=5)
        servidor.server_close()
        self._servidor = None
        self._hilo = None

    def difundir(self, evento):
        with self._bloqueo:
            self._contador += 1
            par = (self._contador, evento)
            self._anillo.append(par)
            clientes = list(self._clientes)
        for canal in clientes:
            try:
                canal.put_nowait(par)
            except queue.Full:
                # Un espectador que no drena su cola no puede retener memoria
                # sin tope: se le corta y su navegador reconecta con
                # Last-Event-ID, que le da lo que se perdió.
                _cortar(canal)

    def estado(self):
        with self._bloqueo:
            clientes = len(self._clientes)
        return {"clientes": clientes}


def _leer_pagina():
    from pathlib import Path
    ruta = config.app_dir() / "web" / "chat.html"
    with ruta.open("rb") as archivo:
        return archivo.read()


_INSTANCIA = None


def encender(puerto):
    global _INSTANCIA
    if _INSTANCIA is not None and _INSTANCIA._hilo is not None:
        return
    servidor = OverlayServidor(puerto)
    servidor.iniciar()
    _INSTANCIA = servidor


def apagar():
    global _INSTANCIA
    if _INSTANCIA is None:
        return
    _INSTANCIA.detener()
    _INSTANCIA = None


def esta_encendido():
    return _INSTANCIA is not None and _INSTANCIA._hilo is not None


def difundir(evento):
    if _INSTANCIA is not None:
        _INSTANCIA.difundir(evento)


def cuantos_miran():
    if _INSTANCIA is None:
        return 0
    return _INSTANCIA.estado()["clientes"]


def puerto_actual():
    return _INSTANCIA.puerto if _INSTANCIA is not None else None
