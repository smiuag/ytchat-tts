"""Gestor de descargas con yt-dlp (módulo puro, sin wx).

Frontera pura/plataforma: este módulo no importa `wx` ni el módulo de yt-dlp.

NO se acopla con las 2 llamadas yt-dlp existentes en `main.obtener_info_video`
ni en `reproductor._info_video`: este módulo hace sus PROPIAS llamadas a
el programa independiente, en su propio hilo.

Modos soportados:
  - mp4  : bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best
  - webm : bestvideo[ext=webm]+bestaudio[ext=webm]/best[ext=webm]/best
  - mp3  : bestaudio + conversión a mp3
  - m4a  : bestaudio + conversión a m4a
"""
from __future__ import annotations

import logging
import json
import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

import diagnostico
from config import app_dir, obtener_opciones_descarga
import ffmpeg_bin
import ytdlp_bin
from progreso_ytdlp import PLANTILLA, analizar_linea_progreso

logger = diagnostico.obtener_logger(__name__)

@dataclass
class ItemDescarga:
    """Una descarga encolada. El estado se va mutando desde el hilo de descarga."""
    id: str
    url: str
    tipo: str                # "video" | "playlist" | "error"
    estado: str = "en_cola"  # en_cola | descargando | completado | error | cancelado
    progreso: float = 0.0    # 0..100
    mensaje: str = ""
    nombre: str = ""
    carpeta: str = ""        # destino elegido al encolar (para el historial)


# ── Helpers puros (testeables en Linux) ──────────────────────────────────────

INTERVALO_PROGRESO_S = 0.5
# Tope del análisis previo de la URL: sin él, una red caída dejaba el ítem
# «en cola» para siempre.
TIEMPO_ESPERA_ANALISIS = 60
# Marca con la que yt-dlp imprime la ruta definitiva (tras unir audio y
# vídeo o convertir): así se distingue de cualquier otra línea de salida.
PREFIJO_RUTA_FINAL = "RUTA_FINAL"
# Sufijo de fragmento DASH que deja yt-dlp: «.f140.m4a», «.f137.mp4.part»…
_RE_FRAGMENTO = re.compile(r"^\.f[\w-]+\.[A-Za-z0-9]+(\.part|\.ytdl)?$")


def _matar_arbol(proceso) -> None:
    """Mata a yt-dlp Y a su ffmpeg hijo. En Windows kill() solo mata al
    padre: el ffmpeg que estaba uniendo audio y vídeo seguía vivo y escribiendo
    en la carpeta. taskkill /T baja el árbol entero; kill() queda de red."""
    pid = getattr(proceso, "pid", None)
    if os.name == "nt" and isinstance(pid, int):
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=10, check=False,
                           creationflags=_sin_ventana())
        except Exception as exc:
            logger.debug("taskkill: %s", exc)
    try:
        proceso.kill()
    except Exception as exc:
        logger.debug("kill: %s", exc)


def _vigilar_cancelacion(proceso, cancel_event, intervalo=0.2) -> bool:
    while proceso.poll() is None:
        if cancel_event.wait(intervalo):
            _matar_arbol(proceso)
            return True
    return False


def nombre_base_descarga(nombre_archivo: str) -> str:
    """«Título [id].f140.m4a.part» → «Título [id]»: lo que comparten todos
    los archivos (fragmentos, .part, .ytdl) de una misma descarga."""
    nombre = Path(nombre_archivo).name
    for sufijo in (".part", ".ytdl"):
        if nombre.endswith(sufijo):
            nombre = nombre[: -len(sufijo)]
    fragmento = re.search(r"\.f[\w-]+\.[A-Za-z0-9]+$", nombre)
    if fragmento:
        return nombre[: fragmento.start()]
    return Path(nombre).stem


def limpiar_restos_descarga(carpeta, nombre_archivo: str) -> list[str]:
    """Borra lo que una descarga cancelada deja en su carpeta.

    Conservador a propósito: solo archivos de ESA carpeta cuyo nombre empiece
    por el nombre base de la descarga y sean claramente temporales (.part,
    .ytdl o un fragmento .fNNN.ext). Un archivo ya terminado no se toca.
    Devuelve los nombres borrados.
    """
    base = nombre_base_descarga(nombre_archivo) if nombre_archivo else ""
    if not base:
        return []
    borrados = []
    try:
        entradas = list(Path(carpeta).iterdir())
    except OSError:
        return []
    for ruta in entradas:
        nombre = ruta.name
        if not nombre.startswith(base) or not ruta.is_file():
            continue
        resto = nombre[len(base):]
        if not (resto.endswith(".part") or resto.endswith(".ytdl")
                or _RE_FRAGMENTO.match(resto)):
            continue
        try:
            ruta.unlink()
            borrados.append(nombre)
        except OSError as exc:
            logger.debug("no se pudo borrar %s: %s", nombre, exc)
    return borrados


def debe_emitir_progreso(ultimo_ts, ahora, pct):
    """Decide si toca avisar del progreso, para no inundar la interfaz."""
    return (ultimo_ts is None or pct >= 100.0 or
            ahora - ultimo_ts >= INTERVALO_PROGRESO_S)


def recortar_url_registro(url: str) -> str:
    """Devuelve el identificador de vídeo sin parámetros para el registro."""
    partes = urlparse(url)
    consulta = parse_qs(partes.query)
    if consulta.get("v"):
        return consulta["v"][0]
    segmentos = [segmento for segmento in partes.path.split("/") if segmento]
    if partes.netloc.lower().endswith("youtu.be") and segmentos:
        return segmentos[0]
    if len(segmentos) >= 2 and segmentos[0] in ("shorts", "embed", "live"):
        return segmentos[1]
    return segmentos[-1] if segmentos else "sin identificador"

def formato_a_ydl(formato: str, bitrate: int) -> str:
    """Selector que se pasa a YoutubeDL como `format`.

    mp4/webm piden el mejor stream de vídeo con esa extensión combinada con el
    mejor audio compatible, y caen a un fallback genérico si no hay.
    mp3/m4a piden solo el mejor audio y `descargar()` añade la conversión.
    """
    f = (formato or "").lower().strip()
    if f == "mp4":
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    if f == "webm":
        return "bestvideo[ext=webm]+bestaudio[ext=webm]/best[ext=webm]/best"
    if f in ("mp3", "m4a"):
        return "bestaudio"
    return "best"


def construir_outtmpl(opciones: dict, enumerar: bool) -> str:
    """Plantilla de nombre de archivo para yt-dlp.

    El directorio se pasa en `opciones["carpeta"]`; yt-dlp lo une con el nombre.
    Con `enumerar=True` yt-dlp prefijará «01 - », «02 - », etc. SOLO si el
    resultado es una playlist; en vídeos sueltos el prefijo no aparece (el
    condicional «&…|» de yt-dlp; un %(playlist_index)02d a secas daba «NA - »).
    """
    carpeta = str(opciones.get("carpeta") or (app_dir() / "Descargas"))
    if enumerar:
        nombre = "%(playlist_index&{:02d} - |)s%(title)s [%(id)s].%(ext)s"
    else:
        nombre = "%(title)s [%(id)s].%(ext)s"
    return str(Path(carpeta) / nombre)


def analizar_url(url: str) -> dict:
    """Inspecciona una URL y devuelve tipo / id / título / cuenta.

    Pide los datos al programa independiente. Si no está disponible, devuelve
    el mismo error que se informaba cuando faltaba el módulo de Python.
    """
    ruta = ytdlp_bin.ruta_ytdlp()
    if ruta is None:
        return {"tipo": "error", "id": "", "titulo": "", "cuenta": 0,
                "mensaje": "yt-dlp no está instalado"}
    # -J (un único JSON) y --flat-playlist: --dump-json emitía un JSON por
    # entrada en las playlists y json.loads fallaba con «Extra data».
    try:
        resultado = subprocess.run(
            [ruta, "-J", "--flat-playlist", "--quiet", "--no-warnings",
             "--skip-download", "--no-playlist", "--socket-timeout", "20", url],
            capture_output=True, text=True, creationflags=_sin_ventana(),
            check=False, timeout=TIEMPO_ESPERA_ANALISIS,
        )
        if resultado.returncode:
            return {"tipo": "error", "id": "", "titulo": "", "cuenta": 0,
                    "mensaje": resultado.stderr.strip() or "yt-dlp falló"}
        info = json.loads(resultado.stdout)
    except (OSError, subprocess.SubprocessError, TypeError, ValueError) as exc:
        logger.warning("analizar_url falló: %s", exc)
        return {"tipo": "error", "id": "", "titulo": "", "cuenta": 0,
                "mensaje": str(exc)}
    if not info:
        return {"tipo": "error", "id": "", "titulo": "", "cuenta": 0,
                "mensaje": "URL vacía"}
    tipo = info.get("_type")
    if tipo == "playlist" or "entries" in info:
        return {"tipo": "playlist",
                "id": info.get("id", ""),
                "titulo": info.get("title", ""),
                "cuenta": len(info.get("entries") or [])}
    return {"tipo": "video",
            "id": info.get("id", ""),
            "titulo": info.get("title", ""),
            "cuenta": 1}


def _sin_ventana() -> int:
    """Evita una ventana de consola en Windows al ejecutar yt-dlp."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def argumentos_descarga(url, opciones, enumerar, ffmpeg_location=None) -> list[str]:
    """Arma los argumentos de una descarga, sin ejecutar programas."""
    f = (opciones.get("formato") or "mp4").lower().strip()
    bitrate = int(opciones.get("bitrate") or 192)
    # --print after_move: el nombre que llega por el progreso es el del
    # fragmento («….f140.m4a»); el definitivo solo se sabe tras unir o
    # convertir. --print implica --quiet, y --progress recupera el progreso.
    argumentos = ["--newline", "--no-warnings", "--progress",
                  "--progress-template", PLANTILLA,
                  "--print", f"after_move:{PREFIJO_RUTA_FINAL} %(filepath)s",
                  "-f", formato_a_ydl(f, bitrate), "-o",
                  construir_outtmpl(opciones, enumerar)]
    if f in ("mp3", "m4a"):
        argumentos.extend(["-x", "--audio-format", f,
                           "--audio-quality", f"{bitrate}K"])
    if ffmpeg_location is None:
        ffmpeg_location = ffmpeg_bin.ruta_ffmpeg()
    if ffmpeg_location is not None:
        argumentos.extend(["--ffmpeg-location", str(ffmpeg_location)])
    argumentos.extend(["--", url])
    return argumentos


def descargar(url: str, opciones: dict,
              progreso_cb: Callable, estado_cb: Callable,
              cancel_event: threading.Event) -> None:
    """Lanza la descarga en el HILO ACTUAL.

    Pensada para correr dentro de `threading.Thread(target=descargar, ...)` que
    crea `GestorDescargas.encolar`. El hilo SIEMPRE termina: las excepciones se
    convierten en `estado_cb("error" | "cancelado", mensaje)` y se hace
    `return`. NUNCA se re-lanza fuera del hilo.

    Callbacks:
      - progreso_cb(pct: float, velocidad, eta, nombre) — se invoca desde el
        progress hook de yt-dlp cada vez que hay actualización de bytes.
      - estado_cb(estado: str, mensaje: str) — transiciones de estado: primero
        "descargando", luego uno de "completado" | "cancelado" | "error".
    """
    ruta = ytdlp_bin.ruta_ytdlp()
    if ruta is None:
        estado_cb("error", "yt-dlp no está instalado")
        return

    if not tiene_ffmpeg():
        # Error CLARO (no el genérico de yt-dlp) para que el usuario ciego
        # sepa exactamente qué falta. La GUI ya hace 3-vías con este mensaje.
        estado_cb("error",
                   "ffmpeg no encontrado. La descarga necesita ffmpeg para "
                   "unir audio y vídeo o extraer audio. Usa la versión "
                   "empaquetada o instala ffmpeg. En desarrollo, alcanza "
                   "con tener ffmpeg en el PATH.")
        return

    enumerar = bool(opciones.get("enumerar", False))
    ultimo_progreso_ts = None
    ultimo_archivo = ""   # último nombre visto en el progreso: base de la limpieza
    carpeta = Path(construir_outtmpl(opciones, enumerar)).parent

    def cancelar(proceso) -> None:
        _matar_arbol(proceso)
        proceso.wait()
        borrados = limpiar_restos_descarga(carpeta, ultimo_archivo)
        if borrados:
            logger.info("descarga cancelada: borrados %d restos", len(borrados))
        estado_cb("cancelado", "Descarga cancelada")

    estado_cb("descargando", "")
    try:
        proceso = subprocess.Popen(
            [ruta, *argumentos_descarga(url, opciones, enumerar)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            creationflags=_sin_ventana(),
        )
        if cancel_event.is_set():
            cancelar(proceso)
            return
        diagnostico.crear_hilo(
            _vigilar_cancelacion, "Vigilante-cancelacion",
            args=(proceso, cancel_event),
        ).start()
        for linea in iter(proceso.stdout.readline, ""):
            if cancel_event.is_set():
                cancelar(proceso)
                return
            if linea.startswith(PREFIJO_RUTA_FINAL + " "):
                # Ruta definitiva: se anuncia y persiste el nombre real, no
                # el del fragmento temporal.
                ruta_final = linea[len(PREFIJO_RUTA_FINAL) + 1:].strip()
                if ruta_final:
                    try:
                        progreso_cb(100.0, None, None, Path(ruta_final).name)
                    except Exception as exc:
                        logger.debug("progreso_cb lanzó: %s", exc)
                continue
            datos = analizar_linea_progreso(linea)
            if datos is None:
                continue
            ultimo_archivo = datos["nombre"]
            ahora = time.monotonic()
            if not debe_emitir_progreso(ultimo_progreso_ts, ahora, datos["pct"]):
                continue
            ultimo_progreso_ts = ahora
            try:
                progreso_cb(datos["pct"], datos["velocidad"], datos["eta"],
                            datos["nombre"])
            except Exception as exc:
                logger.debug("progreso_cb lanzó: %s", exc)
        proceso.wait()
        if cancel_event.is_set():
            limpiar_restos_descarga(carpeta, ultimo_archivo)
            estado_cb("cancelado", "Descarga cancelada")
        elif proceso.returncode == 0:
            estado_cb("completado", "")
        else:
            estado_cb("error", f"yt-dlp terminó con código {proceso.returncode}")
    except OSError as exc:
        logger.warning("descargar falló: %s", exc)
        estado_cb("error", str(exc) or exc.__class__.__name__)
    except Exception as exc:
        logger.warning("descargar falló: %s", exc)
        estado_cb("error", str(exc) or exc.__class__.__name__)


def tiene_ffmpeg() -> bool:
    """¿Hay ffmpeg disponible? El mismo resolvedor que usa la descarga."""
    return ffmpeg_bin.ruta_ffmpeg() is not None


def frase_aviso_descarga(estado: str, mensaje: str, nombre: str) -> str:
    """Devuelve el aviso accesible de un fin de descarga."""
    if estado == "completado":
        return "Descarga completada" + (f": {nombre}" if nombre else "")
    if estado == "error":
        return "Error en la descarga" + (f": {mensaje}" if mensaje else "")
    if estado == "cancelado":
        return "Descarga cancelada"
    return ""


# ── Gestor de cola ───────────────────────────────────────────────────────────

class GestorDescargas:
    """Cola de descargas. Cada ítem corre en su propio hilo (daemon).

    Los callbacks que recibe `encolar` llevan el `item_id` como primer
    argumento, así la capa de GUI puede actualizar la fila correspondiente
    de su `wx.ListCtrl` sin tener que mantener un mapping externo.
    """

    def __init__(self, opciones: Optional[dict] = None) -> None:
        self._opciones: dict = dict(opciones) if opciones else obtener_opciones_descarga()
        self._items: dict[str, ItemDescarga] = {}
        self._eventos: dict[str, threading.Event] = {}
        self._orden: list[str] = []
        self._suscriptores_fin: list[Callable] = []
        self._lock = threading.Lock()

    def set_opciones(self, op: dict) -> None:
        """Reemplaza las opciones que se pasan a cada descarga nueva."""
        with self._lock:
            self._opciones = dict(op)

    def suscribir_fin(self, callback: Callable) -> None:
        """Añade un aviso de estado sin duplicarlo.

        `callback(estado, mensaje, nombre, item)` corre en el HILO DE DESCARGA:
        quien toque wx debe pasar por wx.CallAfter. Recibe el ItemDescarga
        para que el historial se registre aunque el diálogo esté cerrado.
        """
        with self._lock:
            if callback not in self._suscriptores_fin:
                self._suscriptores_fin.append(callback)

    def encolar(self, url: str, progreso_cb: Callable, estado_cb: Callable,
                creado_cb: Optional[Callable] = None) -> str:
        """Crea un ItemDescarga, lo deja en 'en_cola' y lanza su hilo.

        `progreso_cb(item_id, pct, velocidad, eta, nombre)` y
        `estado_cb(item_id, estado, mensaje)` reciben el id del ítem.
        """
        item_id = uuid.uuid4().hex[:12]
        with self._lock:
            carpeta = str(self._opciones.get("carpeta") or "")
        it = ItemDescarga(id=item_id, url=url, tipo="video", nombre=url,
                          carpeta=carpeta)
        ev = threading.Event()
        with self._lock:
            self._items[item_id] = it
            self._eventos[item_id] = ev
            self._orden.append(item_id)
        logger.info("descarga encolada: %s, vídeo %s", item_id,
                    recortar_url_registro(url))
        if creado_cb is not None:
            creado_cb(item_id)

        def _cb_estado(estado: str, mensaje: str = "") -> None:
            it.estado = estado
            it.mensaje = mensaje
            logger.info("descarga %s: estado %s", item_id, estado)
            try:
                estado_cb(item_id, estado, mensaje)
            except Exception as exc:
                logger.debug("estado_cb lanzó: %s", exc)
            nombre = it.nombre if it.nombre != it.url else ""
            with self._lock:
                suscriptores = list(self._suscriptores_fin)
            for suscriptor in suscriptores:
                try:
                    suscriptor(estado, mensaje, nombre, it)
                except Exception as exc:
                    logger.warning("suscriptor de descarga lanzó: %s", exc)
            if estado in ("completado", "cancelado", "error"):
                logger.info("descarga %s terminó: %s", item_id, estado)

        def _cb_progreso(pct: float, vel, eta, nombre: str) -> None:
            it.progreso = max(0.0, min(100.0, float(pct)))
            if nombre:
                it.nombre = nombre
            try:
                progreso_cb(item_id, it.progreso, vel, eta, it.nombre)
            except Exception as exc:
                logger.debug("progreso_cb lanzó: %s", exc)

        def _run() -> None:
            # Doble red de seguridad: capturar lo que sea que se escape.
            try:
                info = analizar_url(url)
                it.tipo = info.get("tipo", "video")
                titulo = info.get("titulo") or ""
                if titulo:
                    _cb_progreso(it.progreso, "", "", titulo)
                if ev.is_set():
                    # Cancelada durante el análisis: no lanzar yt-dlp para nada.
                    _cb_estado("cancelado", "Descarga cancelada")
                    return
                logger.info("descarga %s: inicio", item_id)
                descargar(url, self._opciones, _cb_progreso, _cb_estado, ev)
            except Exception as exc:
                logger.warning("hilo descarga: %s", exc)
                _cb_estado("error", str(exc) or exc.__class__.__name__)

        hilo = diagnostico.crear_hilo(_run, f"Descarga-{item_id}")
        hilo.start()
        return item_id

    def cancelar(self, item_id: str) -> None:
        """Marca el evento de cancelación para que termine el proceso."""
        ev = self._eventos.get(item_id)
        if ev is not None:
            ev.set()

    def obtener(self, item_id: str) -> Optional[ItemDescarga]:
        with self._lock:
            return self._items.get(item_id)

    def lista(self) -> list[ItemDescarga]:
        with self._lock:
            return [self._items[i] for i in self._orden if i in self._items]


_gestor_unico: Optional[GestorDescargas] = None
_lock_gestor_unico = threading.Lock()


def gestor() -> GestorDescargas:
    """Devuelve el gestor de descargas compartido por la aplicación."""
    global _gestor_unico
    with _lock_gestor_unico:
        if _gestor_unico is None:
            _gestor_unico = GestorDescargas()
        return _gestor_unico


def reiniciar_gestor() -> None:
    """Descarta el gestor compartido. Solo se usa en las pruebas."""
    global _gestor_unico
    with _lock_gestor_unico:
        _gestor_unico = None
