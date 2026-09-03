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

import socket
import subprocess

import diagnostico

logger = diagnostico.obtener_logger(__name__)

TIEMPO_ESPERA_LISTENER = 1.0  # s: margen para que ffmpeg abra el socket


def puerto_libre() -> int:
    """Un puerto TCP libre en localhost, elegido por el sistema operativo."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def direccion_relevo(puerto: int) -> str:
    return f"tcp://127.0.0.1:{puerto}"


def argumentos_relevo(ffmpeg_exe: str, video_url: str, audio_url: str,
                      puerto: int) -> list[str]:
    """Comando de ffmpeg: copia (sin recodificar) vídeo y audio a un único
    mpegts, escuchando en localhost para que VLC se conecte como cliente."""
    return [
        ffmpeg_exe, "-loglevel", "warning", "-nostdin",
        "-i", video_url, "-i", audio_url,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c", "copy", "-f", "mpegts", "-listen", "1",
        direccion_relevo(puerto),
    ]


class RelevoFfmpeg:
    """Ciclo de vida del proceso ffmpeg que remuxa vídeo+audio de un directo.

    No es pura (crea un proceso y un socket): la lógica testeable está en
    argumentos_relevo/puerto_libre/direccion_relevo, ya probadas aparte.
    """

    def __init__(self, video_url: str, audio_url: str):
        self._video_url = video_url
        self._audio_url = audio_url
        self._proceso: subprocess.Popen | None = None
        self._puerto: int | None = None

    @property
    def direccion(self) -> str | None:
        return direccion_relevo(self._puerto) if self._puerto is not None else None

    def iniciar(self) -> str | None:
        """Arranca ffmpeg y devuelve la dirección a la que VLC debe
        conectarse, o None si no se pudo (sin ffmpeg disponible, o el
        proceso no arrancó)."""
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:
            logger.warning("No se encontró ffmpeg para el relevo: %s", exc)
            return None
        puerto = puerto_libre()
        argumentos = argumentos_relevo(
            ffmpeg_exe, self._video_url, self._audio_url, puerto)
        try:
            self._proceso = subprocess.Popen(
                argumentos, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            logger.warning("No se pudo iniciar el relevo de ffmpeg: %s", exc)
            return None
        self._puerto = puerto
        logger.debug("RELEVO_FFMPEG iniciado puerto=%d pid=%s",
                     puerto, self._proceso.pid)
        return self.direccion

    def activo(self) -> bool:
        return self._proceso is not None and self._proceso.poll() is None

    def detener(self) -> None:
        proceso = self._proceso
        self._proceso = None
        self._puerto = None
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
