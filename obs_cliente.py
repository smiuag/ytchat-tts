"""Cliente sincrónico para el servidor websocket de OBS Studio."""

import base64
import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect


RUTA_CONFIG_OBS = os.path.join(
    os.environ.get("APPDATA", ""),
    "obs-studio",
    "plugin_config",
    "obs-websocket",
    "config.json",
)


@dataclass(frozen=True)
class AjustesObs:
    activo: bool = False
    puerto: int = 4455
    password: str = ""


def leer_ajustes(ruta=None):
    """Lee la configuración de OBS sin modificarla."""
    try:
        with open(ruta or RUTA_CONFIG_OBS, "r", encoding="utf-8") as archivo:
            datos = json.load(archivo)
        return AjustesObs(
            activo=bool(datos.get("server_enabled", False)),
            puerto=int(datos.get("server_port", 4455)),
            password=str(datos.get("server_password", "")),
        )
    except (OSError, ValueError, TypeError, KeyError):
        return AjustesObs()


def respuesta_auth(password, salt, challenge):
    """Calcula la respuesta de autenticación exigida por OBS."""
    secreto = base64.b64encode(
        hashlib.sha256((password + salt).encode("utf-8")).digest()
    ).decode("ascii")
    return base64.b64encode(
        hashlib.sha256((secreto + challenge).encode("utf-8")).digest()
    ).decode("ascii")


class ObsError(RuntimeError):
    """Fallo entendible producido al comunicarse con OBS."""


MENSAJE_CONEXION_PERDIDA = "Se perdió la conexión con OBS. Vuelve a conectar."


def mensaje_de_fallo_obs(motivo):
    """Traduce un motivo técnico a un mensaje breve para el usuario."""
    if isinstance(motivo, ObsError):
        return str(motivo)
    texto = str(motivo or "").lower()
    if any(clave in texto for clave in
           ("refused", "no connection", "10061", "unreachable", "timed out")):
        return ("No se pudo conectar con OBS. Comprueba que OBS esté abierto y "
                "que su servidor websocket esté activado.")
    if any(clave in texto for clave in ("authentication", "4009", "unauthorized")):
        return "OBS rechazó la contraseña guardada. Vuelve a conectar para leerla de nuevo."
    if any(clave in texto for clave in ("601", "already exists")):
        return "Ya existe una fuente con ese nombre en OBS."
    if any(clave in texto for clave in ("600", "not found", "no scene")):
        return "OBS no encuentra la escena o la fuente indicada."
    # Se comparte la forma de avisos_red, pero OBS necesita una taxonomía propia.
    return "OBS no pudo completar la operación. Inténtalo de nuevo."


class ClienteObs:
    """Cliente del protocolo websocket de OBS Studio."""

    _TIEMPO_LIMITE = 10.0
    _TIEMPO_LECTURA = 0.5

    def __init__(self, ajustes=None, conectar_fn=None):
        self.ajustes = ajustes or AjustesObs()
        self._conectar_fn = conectar_fn or connect
        self._transporte = None
        # websockets.sync no admite dos recv a la vez: el ajuste fino y el
        # resto del diálogo piden desde hilos distintos.
        self._cerrojo = threading.Lock()

    @property
    def conectado(self):
        return self._transporte is not None

    def conectar(self, parada=None):
        # Reconectar sin cerrar dejaba el socket anterior abierto para siempre.
        self.cerrar()
        limite = time.monotonic() + self._TIEMPO_LIMITE
        transporte = None
        try:
            transporte = self._conectar_fn(
                f"ws://127.0.0.1:{self.ajustes.puerto}"
            )
            saludo = self._recibir(transporte, parada, limite)
            if saludo.get("op") != 0:
                raise ObsError(mensaje_de_fallo_obs("saludo inválido"))
            # Solo se piden respuestas; sin esto OBS empuja eventos que se
            # acumulan en la cola del socket entre sondeos.
            identificacion = {"op": 1, "d": {"rpcVersion": saludo["d"]["rpcVersion"],
                                             "eventSubscriptions": 0}}
            autenticacion = saludo.get("d", {}).get("authentication")
            if autenticacion:
                identificacion["d"]["authentication"] = respuesta_auth(
                    self.ajustes.password,
                    autenticacion["salt"],
                    autenticacion["challenge"],
                )
            transporte.send(json.dumps(identificacion))
            confirmacion = self._recibir(transporte, parada, limite)
            if confirmacion.get("op") != 2:
                raise ObsError(mensaje_de_fallo_obs("authentication"))
            self._transporte = transporte
        except ObsError:
            if transporte is not None:
                transporte.close()
            raise
        except Exception as error:
            if transporte is not None:
                transporte.close()
            raise ObsError(mensaje_de_fallo_obs(error)) from error

    def pedir(self, tipo, datos=None, parada=None):
        with self._cerrojo:
            transporte = self._transporte
            if transporte is None:
                raise ObsError(mensaje_de_fallo_obs("not connected"))
            identificador = str(uuid.uuid4())
            peticion = {
                "op": 6,
                "d": {
                    "requestType": tipo,
                    "requestId": identificador,
                    "requestData": datos or {},
                },
            }
            limite = time.monotonic() + self._TIEMPO_LIMITE
            try:
                transporte.send(json.dumps(peticion))
                while True:
                    mensaje = self._recibir(transporte, parada, limite)
                    if mensaje.get("op") != 7:
                        continue
                    datos_respuesta = mensaje.get("d", {})
                    if datos_respuesta.get("requestId") != identificador:
                        continue
                    estado = datos_respuesta.get("requestStatus", {})
                    if not estado.get("result", False):
                        motivo = f"{estado.get('code', '')} {estado.get('comment', '')}"
                        raise ObsError(mensaje_de_fallo_obs(motivo))
                    return datos_respuesta
            except ObsError:
                raise
            except ConnectionClosed as error:
                # OBS colgó: si el transporte se quedara, conectado seguiría en
                # True y cada petición fallaría con «Inténtalo de nuevo».
                self.cerrar()
                raise ObsError(MENSAJE_CONEXION_PERDIDA) from error
            except Exception as error:
                raise ObsError(mensaje_de_fallo_obs(error)) from error

    def cerrar(self):
        if self._transporte is not None:
            try:
                self._transporte.close()
            finally:
                self._transporte = None

    @classmethod
    def _recibir(cls, transporte, parada, limite):
        while True:
            if parada is not None and parada.is_set():
                raise ObsError("Operación cancelada.")
            restante = limite - time.monotonic()
            if restante <= 0:
                raise ObsError(mensaje_de_fallo_obs("timed out"))
            try:
                mensaje = transporte.recv(timeout=min(cls._TIEMPO_LECTURA, restante))
            except TimeoutError:
                continue
            if isinstance(mensaje, bytes):
                mensaje = mensaje.decode("utf-8")
            return json.loads(mensaje)
