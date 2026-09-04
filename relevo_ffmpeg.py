"""Relevo de ffmpeg para directos con vídeo y audio en pistas separadas.

Cuando un directo no trae un formato combinado, VLC recibe el vídeo y el
audio como dos fuentes HLS independientemente en vivo vía «input-slave».
Comprobado con un directo real: cada 60-90 s, VLC pierde la sincronía entre
ambas y se resincroniza saltando la posición hacia atrás y congelando la
reproducción 25-50 s. Subir el búfer no lo evita (también comprobado):
es un límite del propio mecanismo de VLC, no de las opciones.

Streamlink y mpv evitan justo este problema remuxando antes con ffmpeg
(solo copia, sin recodificar) en un único flujo. Este módulo hace lo mismo:
ffmpeg lee las dos fuentes y las remuxa a un único flujo mpegts que escucha
en localhost; VLC se conecta ahí como si fuera una fuente normal, sin
input-slave.
"""

from __future__ import annotations

import atexit
import io
import socket
import subprocess
import time

import diagnostico
import ffmpeg_bin

logger = diagnostico.obtener_logger(__name__)

# Tope de espera a que ffmpeg abra el socket. ffmpeg sondea las dos entradas
# HLS antes de abrir la salida con «-listen 1», y eso tarda lo que tarde la
# red (comprobado: varios segundos). No es una espera fija: se sondea el
# puerto cada INTERVALO_SONDA y se sigue en cuanto escucha.
TIEMPO_ESPERA_LISTENER = 20.0
INTERVALO_SONDA = 0.1


def puerto_libre() -> int:
    """Un puerto TCP libre en localhost, elegido por el sistema operativo."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def escuchando(puerto: int) -> bool:
    """Dice si algo escucha ya en ese puerto de localhost, sin conectarse.

    ffmpeg con «-listen 1» acepta un único cliente, así que conectarse para
    comprobarlo consumiría la conexión que necesita VLC. En su lugar se
    intenta un bind: si falla con «dirección en uso» es que ffmpeg ya escucha
    (comprobado en Windows con un ffmpeg real: el listener de ffmpeg lleva
    SO_REUSEADDR y un bind sin esa opción falla con WSAEADDRINUSE).
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", puerto))
        except OSError:
            return True
    return False


def esperar_listener(puerto: int, sigue_vivo, timeout=TIEMPO_ESPERA_LISTENER,
                     intervalo=INTERVALO_SONDA, ahora=time.monotonic,
                     dormir=time.sleep) -> bool:
    """Espera a que el puerto escuche. False si el proceso murió antes o se
    agotó el plazo."""
    limite = ahora() + timeout
    while True:
        if not sigue_vivo():
            return False
        if escuchando(puerto):
            return True
        if ahora() >= limite:
            return False
        dormir(intervalo)


# Relevos con proceso vivo. Si la app se cierra mientras un relevo se estaba
# preparando en su hilo, nadie llega a llamar a detener(); en Windows el hijo
# no muere con el padre y ffmpeg quedaría esperando un cliente para siempre.
_VIVOS: set = set()


def detener_todos() -> None:
    for relevo in list(_VIVOS):
        relevo.detener()


atexit.register(detener_todos)


def direccion_relevo(puerto: int) -> str:
    return f"tcp://127.0.0.1:{puerto}"


def volcar_stderr(flujo, pid) -> None:
    """Pasa al registro cada línea que ffmpeg escriba por stderr.

    Con stderr a DEVNULL, un 403 de googlevideo o un «Invalid data found»
    no dejaban rastro y el fallo del relevo era imposible de diagnosticar.
    Solo se leen flujos reales: las pruebas dan un Mock/None como proceso y
    leer de un Mock no termina nunca.
    """
    if not isinstance(flujo, io.IOBase):
        return
    try:
        for linea in iter(flujo.readline, b""):
            texto = linea.decode("utf-8", errors="replace").rstrip()
            if texto:
                logger.warning("RELEVO_FFMPEG pid=%s: %s", pid, texto)
    except Exception as exc:
        logger.debug("lector de stderr del relevo: %s", exc)
    finally:
        try:
            flujo.close()
        except Exception:
            pass


# Segmentos que ffmpeg deja por detrás del borde al abrir un HLS en vivo
# (su live_start_index por defecto es -3). Un desfase de K segmentos se pide
# como -(K+3) para que «0» siga siendo exactamente el arranque de siempre.
SEGMENTOS_BORDE = 3


def argumentos_relevo(ffmpeg_exe: str, video_url: str, audio_url: str,
                      puerto: int, desfase_segmentos: int = 0) -> list[str]:
    """Comando de ffmpeg: copia (sin recodificar) vídeo y audio a un único
    mpegts, escuchando en localhost para que VLC se conecte como cliente.

    Con desfase, las dos entradas arrancan el mismo número de segmentos por
    detrás del borde. Las listas de vídeo y audio de YouTube comparten la
    numeración y la duración de segmento (comprobado con un directo real:
    5 s, misma MEDIA-SEQUENCE), así que empezar ambas en el mismo índice las
    deja alineadas y ffmpeg, que pone a cero el inicio de cada entrada por
    separado, no las desincroniza.
    """
    entrada = []
    if desfase_segmentos and desfase_segmentos > 0:
        entrada = ["-live_start_index",
                   str(-(int(desfase_segmentos) + SEGMENTOS_BORDE))]
    return [
        ffmpeg_exe, "-loglevel", "warning", "-nostdin",
        *entrada, "-i", video_url, *entrada, "-i", audio_url,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c", "copy", "-f", "mpegts", "-listen", "1",
        direccion_relevo(puerto),
    ]


def ventana_hls(texto: str) -> tuple[float, int] | None:
    """(segundos por segmento, segmentos en la lista) de una lista HLS, o
    None si el texto no es una lista de medios."""
    duracion = None
    segmentos = 0
    for linea in texto.splitlines():
        linea = linea.strip()
        if linea.startswith("#EXT-X-TARGETDURATION:"):
            try:
                duracion = float(linea.split(":", 1)[1])
            except ValueError:
                pass
        elif linea.startswith("#EXTINF:"):
            segmentos += 1
    if duracion is None or duracion <= 0 or segmentos == 0:
        return None
    return duracion, segmentos


def leer_ventana_hls(url: str, timeout: float = 8.0) -> tuple[float, int] | None:
    """Descarga la lista HLS y devuelve su ventana, o None si no se pudo.

    Sirve para saber cuánto se puede retroceder en un directo (YouTube deja
    una hora de segmentos de 5 s) sin tener que suponerlo.
    """
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as respuesta:
            texto = respuesta.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("No se pudo leer la ventana HLS del directo: %s", exc)
        return None
    ventana = ventana_hls(texto)
    if ventana is None:
        logger.warning("La lista HLS del directo no trae segmentos legibles")
    else:
        logger.debug("VENTANA_HLS segmento_s=%.1f segmentos=%d", *ventana)
    return ventana


class RelevoFfmpeg:
    """Ciclo de vida del proceso ffmpeg que remuxa vídeo+audio de un directo.

    No es pura (crea un proceso y un socket): la lógica testeable está en
    argumentos_relevo/puerto_libre/direccion_relevo, ya probadas aparte.
    """

    def __init__(self, video_url: str, audio_url: str, desfase_segmentos: int = 0):
        self._video_url = video_url
        self._audio_url = audio_url
        self._desfase_segmentos = max(0, int(desfase_segmentos or 0))
        self._proceso: subprocess.Popen | None = None
        self._puerto: int | None = None

    @property
    def direccion(self) -> str | None:
        return direccion_relevo(self._puerto) if self._puerto is not None else None

    @property
    def desfase_segmentos(self) -> int:
        return self._desfase_segmentos

    def iniciar(self) -> str | None:
        """Arranca ffmpeg y devuelve la dirección a la que VLC debe
        conectarse, o None si no se pudo (sin ffmpeg disponible, o el
        proceso no arrancó)."""
        ffmpeg_exe = ffmpeg_bin.ruta_ffmpeg()
        if not ffmpeg_exe:
            logger.warning("No se encontró ffmpeg para el relevo")
            return None
        puerto = puerto_libre()
        argumentos = argumentos_relevo(
            ffmpeg_exe, self._video_url, self._audio_url, puerto,
            self._desfase_segmentos)
        try:
            self._proceso = subprocess.Popen(
                argumentos, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            logger.warning("No se pudo iniciar el relevo de ffmpeg: %s", exc)
            return None
        self._puerto = puerto
        _VIVOS.add(self)
        logger.debug("RELEVO_FFMPEG iniciado puerto=%d pid=%s desfase_seg=%d",
                     puerto, self._proceso.pid, self._desfase_segmentos)
        # Hilo daemon: termina solo al cerrarse la tubería cuando ffmpeg
        # muere o detener() lo mata, así detener() no tiene que esperarlo.
        diagnostico.crear_hilo(
            volcar_stderr, "RelevoFfmpegStderr",
            args=(getattr(self._proceso, "stderr", None), self._proceso.pid),
        ).start()
        return self.direccion

    def esperar_listo(self, timeout=TIEMPO_ESPERA_LISTENER) -> bool:
        """Bloquea hasta que ffmpeg escuche en su puerto. False si el proceso
        murió antes (URL caducada, playlist inválida…) o venció el plazo; en
        ese caso VLC no debe recibir la dirección."""
        if self._puerto is None:
            return False
        listo = esperar_listener(self._puerto, self.activo, timeout)
        if not listo:
            logger.warning("RELEVO_FFMPEG sin listener puerto=%d activo=%s",
                           self._puerto, self.activo())
        return listo

    def activo(self) -> bool:
        return self._proceso is not None and self._proceso.poll() is None

    def detener(self) -> None:
        proceso = self._proceso
        self._proceso = None
        self._puerto = None
        _VIVOS.discard(self)
        if proceso is None:
            return
        try:
            proceso.kill()
        except Exception:
            pass
        try:
            proceso.wait(timeout=5)
        except Exception:
            pass
