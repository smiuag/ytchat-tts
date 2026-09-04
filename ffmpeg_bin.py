"""Localiza el ejecutable de ffmpeg: un único resolvedor para toda la app.

Lo usan el gestor de descargas (mux de yt-dlp), el relevo de directos y la
caché de vídeo. Antes cada uno buscaba por su cuenta (PATH, imageio_ffmpeg o
la carpeta del .exe) y no coincidían: se podía «tener» ffmpeg para descargar
y no encontrarlo para el relevo, o al revés.

Orden de búsqueda:
  1. Empaquetada: el ffmpeg.exe que construir.bat deja junto al .exe.
  2. imageio_ffmpeg (en desarrollo trae un ffmpeg portable en site-packages;
     el paquete lo excluye porque ya lleva la copia del punto 1).
  3. Un ffmpeg en el PATH.
"""

from __future__ import annotations

import os
import shutil
import sys

NOMBRE_BINARIO = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"


def ruta_ffmpeg() -> str | None:
    """Ruta al ejecutable de ffmpeg, o None si no hay ninguno."""
    if getattr(sys, "frozen", False):
        # Import perezoso: config importa diagnostico, que importa ytdlp_bin,
        # que importa este módulo; a nivel de módulo cerraría el ciclo.
        import config
        candidato = config.app_dir() / NOMBRE_BINARIO
        if candidato.is_file():
            return str(candidato)
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return shutil.which("ffmpeg")
