"""Localiza y actualiza el ejecutable independiente de yt-dlp."""

import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import NamedTuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import diagnostico
import ffmpeg_bin
from esclavo_audio import TAMANIO_MINIMO
from progreso_ytdlp import PLANTILLA, analizar_linea_progreso


URL_API_RELEASES = (
    "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
)
USER_AGENT = "ytchat-tts/2.0"
NOMBRE_BINARIO = "yt-dlp.exe"
NOMBRE_FIRMAS = "SHA2-256SUMS"
SUBDIRECTORIO_DATOS = "YTChat TTS"
TIEMPO_ESPERA = 30
LIMITE_CACHE = "300K"
# Limita la caché para no ahogar la reproducción que usa la misma conexión.
# diagnostico importa este módulo para consultar la versión de yt-dlp.
if hasattr(diagnostico, "obtener_logger"):
    logger = diagnostico.obtener_logger(__name__)
else:
    logger = logging.getLogger(f"ytchat.{__name__}")


class ResultadoDescarga(NamedTuple):
    """Resultado que se puede mostrar sin propagar errores de red."""

    correcta: bool
    motivo: str


def resultado_actualizacion_es_fallo(estado: str) -> bool:
    """Indica si el resultado de actualizar yt-dlp es un fallo."""
    return estado not in ("ya_al_dia", "actualizado")


def mensaje_de_actualizacion(estado, version_actual="", version_nueva="",
                             motivo="") -> str:
    """Elige el anuncio breve para cada resultado de la actualización."""
    if estado == "ya_al_dia":
        return f"Ya tienes yt-dlp al día, versión {version_actual or version_nueva}."
    if estado == "actualizado":
        return f"yt-dlp se actualizó a la versión {version_nueva or version_actual}."
    if estado == "sin_conexion":
        return "No pude comprobar la última versión de yt-dlp. Revisa tu conexión."
    if estado == "firma_incorrecta":
        return ("La descarga de yt-dlp no pasó una comprobación de seguridad. "
                "No se instaló nada.")
    if estado == "cancelado":
        return "Se canceló la descarga de yt-dlp."
    mensaje = "No se pudo actualizar yt-dlp"
    return f"{mensaje}: {motivo}." if motivo else f"{mensaje}."


def _ruta_actualizada() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / SUBDIRECTORIO_DATOS / NOMBRE_BINARIO
    return Path.home() / SUBDIRECTORIO_DATOS / NOMBRE_BINARIO


def _ruta_del_paquete() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve().parent / NOMBRE_BINARIO


def ruta_ytdlp() -> str | None:
    """Devuelve la copia más reciente entre la actualizada (LOCALAPPDATA) y
    la que viaja junto al ejecutable.

    Gana la de fecha de modificación más nueva: si el usuario instala un
    paquete nuevo, su yt-dlp puede ser posterior a la copia que actualizó
    hace meses, y antes esa copia vieja ganaba siempre. A igual fecha se
    mantiene la actualizada.
    """
    candidatas = [ruta for ruta in (_ruta_actualizada(), _ruta_del_paquete())
                  if ruta is not None and ruta.is_file()]
    if not candidatas:
        return None

    def fecha(ruta: Path) -> float:
        try:
            return ruta.stat().st_mtime
        except OSError:
            return 0.0

    return str(max(candidatas, key=fecha))


def version_ytdlp(ruta: str | os.PathLike) -> str:
    """Lee la versión de un ejecutable sin abrir una ventana de consola."""
    try:
        resultado = subprocess.run(
            [str(ruta), "--version"],
            capture_output=True,
            text=True,
            timeout=TIEMPO_ESPERA,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if resultado.returncode:
        return ""
    return resultado.stdout.strip()


def info_video(video_id: str) -> dict | None:
    """Datos del vídeo pedidos al programa. None si no se pudo."""
    ruta = ruta_ytdlp()
    if ruta is None:
        return None
    try:
        resultado = subprocess.run(
            [ruta, "--dump-json", "--quiet", "--no-warnings",
             "--skip-download", "--no-playlist", "--socket-timeout", "20",
             f"https://www.youtube.com/watch?v={video_id}"],
            capture_output=True,
            text=True,
            timeout=TIEMPO_ESPERA,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        if resultado.returncode:
            return None
        datos = json.loads(resultado.stdout)
        return datos if isinstance(datos, dict) else None
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        return None


def descargar_audio(video_id: str, destino: Path, aviso_progreso=None,
                    tope_segundos: int = 600) -> bool:
    """Descarga la mejor pista de audio a la caché interna."""
    # A 6,6 megabits, 24 MB tardan 29 s y los vídeos largos superan 90 s.
    ruta = ruta_ytdlp()
    if ruta is None:
        return False
    destino = Path(destino)
    try:
        proceso = subprocess.Popen(
            [ruta, "-f", "ba", "-o", str(destino), "--no-playlist",
             "--no-warnings", "--newline", "--progress-template", PLANTILLA,
             f"https://www.youtube.com/watch?v={video_id}"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        inicio = time.monotonic()
        import queue
        import threading
        cola: queue.Queue = queue.Queue()

        def _lector():
            try:
                flujo = proceso.stdout
                if flujo is None:
                    cola.put(None)
                    return
                for linea in flujo:
                    cola.put(linea)
                cola.put(None)
            except Exception:
                try:
                    cola.put(None)
                except Exception:
                    pass

        hilo = threading.Thread(target=_lector, daemon=True)
        hilo.start()
        while True:
            transcurrido = time.monotonic() - inicio
            if transcurrido > tope_segundos:
                try:
                    proceso.kill()
                except Exception:
                    pass
                try:
                    proceso.wait(timeout=5)
                except Exception:
                    pass
                return False
            restante = tope_segundos - transcurrido
            espera = restante if restante < 0.2 else 0.2
            if espera <= 0:
                espera = 0.05
            try:
                linea = cola.get(timeout=espera)
            except queue.Empty:
                if proceso.poll() is not None:
                    # El proceso terminó pero el lector aún no entregó el centinela;
                    # se espera un poco más sin volver a bloquear indefinidamente.
                    # Si el hilo ya no vive y la cola está vacía, se sale.
                    if not hilo.is_alive() and cola.empty():
                        break
                continue
            if linea is None:
                break
            datos = analizar_linea_progreso(linea)
            if datos is not None and aviso_progreso is not None:
                aviso_progreso(int(datos["pct"]))
        # Salida normal por fin de flujo: esperar al proceso sin colgarse
        # más allá del tope.
        while True:
            if proceso.poll() is not None:
                break
            if time.monotonic() - inicio > tope_segundos:
                try:
                    proceso.kill()
                except Exception:
                    pass
                try:
                    proceso.wait(timeout=5)
                except Exception:
                    pass
                return False
            time.sleep(0.05)
        try:
            codigo = proceso.wait(timeout=5)
        except Exception:
            codigo = getattr(proceso, "returncode", None)
        if codigo is None:
            codigo = getattr(proceso, "returncode", 0) or 0
        if codigo != 0:
            logger.debug("descargar audio: yt-dlp terminó con error")
            return False
        return destino.is_file() and destino.stat().st_size >= TAMANIO_MINIMO
    except Exception as exc:
        logger.debug("descargar audio: %s", exc)
        return False


def _argumentos_video_cache(ruta: str | os.PathLike, temporal: Path, video_id: str) -> list[str]:
    argumentos = [
        str(ruta), "-f", "bv*+ba/b", "-o", str(temporal), "--no-playlist",
        "--no-warnings", "--limit-rate", LIMITE_CACHE,
        "--merge-output-format", "mp4",
    ]
    ffmpeg = ffmpeg_bin.ruta_ffmpeg()
    if ffmpeg:
        argumentos.extend(["--ffmpeg-location", ffmpeg])
    argumentos.append(f"https://www.youtube.com/watch?v={video_id}")
    return argumentos


def descargar_video_cache(video_id: str, destino: Path, cancel_event=None,
                          tope_segundos: int = 3600) -> bool:
    """Descarga vídeo y audio completos a un archivo local limitado."""
    ruta = ruta_ytdlp()
    if ruta is None:
        return False
    destino = Path(destino)
    temporal = None
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".ytcache-", suffix=".mp4",
                                         dir=destino.parent, delete=False) as archivo:
            temporal = Path(archivo.name)
        temporal.unlink()
        argumentos = _argumentos_video_cache(ruta, temporal, video_id)
        from subprocesos import Estado, ejecutar
        estado = ejecutar(
            argumentos, cancel_event=cancel_event, tope_segundos=tope_segundos,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if estado == Estado.exito:
            if (temporal.is_file() and temporal.stat().st_size > 0
                    and (cancel_event is None or not cancel_event.is_set())):
                os.replace(temporal, destino)
                temporal = None
                return True
            return False
        return False
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("descargar vídeo de caché: %s", exc)
        return False
    finally:
        if temporal is not None:
            # Además del temporal, lo que yt-dlp deja a medias al cancelar o
            # fallar: «.ytcache-x.mp4.part», «.ytcache-x.f137.mp4»… Todos
            # comparten el tallo único del temporal, así que el glob no
            # alcanza a otra descarga.
            for resto in [temporal, *temporal.parent.glob(temporal.stem + "*")]:
                try:
                    if resto.exists():
                        resto.unlink()
                except OSError:
                    pass


def ultima_version_ytdlp() -> tuple[str, str, str] | None:
    """Devuelve versión, descarga del ejecutable y descarga de sus firmas."""
    try:
        solicitud = Request(URL_API_RELEASES, headers={"User-Agent": USER_AGENT})
        with urlopen(solicitud, timeout=TIEMPO_ESPERA) as respuesta:
            datos = json.load(respuesta)
        activos = {activo["name"]: activo for activo in datos["assets"]}
        ejecutable = activos[NOMBRE_BINARIO]["browser_download_url"]
        firmas = activos[NOMBRE_FIRMAS]["browser_download_url"]
        return datos["tag_name"], ejecutable, firmas
    except (HTTPError, URLError, OSError, KeyError, TypeError, ValueError,
            json.JSONDecodeError):
        return None


def firma_sha256(texto: str, nombre: str) -> str:
    """Extrae la firma de un archivo SHA2-256SUMS para un nombre concreto."""
    nombre = str(nombre).strip()
    for linea in texto.splitlines():
        partes = linea.strip().split(None, 1)
        if len(partes) != 2:
            continue
        firma, archivo = partes
        if archivo.lstrip("*").strip() == nombre:
            return firma.lower()
    return ""


class _DescargaCancelada(Exception):
    pass


def porcentaje_descarga(descargado: int, total: int | None) -> int | None:
    """Calcula un porcentaje entero o None si no hay total conocido."""
    if total is None or total <= 0:
        return None
    return min(100, max(0, int(descargado * 100 / total)))


def debe_actualizar_texto_progreso(anterior: int | None, actual: int | None) -> bool:
    """Indica si el texto debe cambiar al avanzar otra decena."""
    if actual is None:
        return False
    return anterior is None or actual >= anterior + 10 or actual == 100


def sondear_cancelacion(terminado, dialogo, cancelado, reprogramar) -> bool:
    """Un tic del sondeo del dialogo de descarga. Devuelve si se reprogramó."""
    if terminado.is_set():
        return False
    if dialogo.WasCancelled():
        cancelado.set()
    reprogramar()
    return True


def _descargar_archivo(url: str, destino: Path, aviso=None, cancelar=None) -> None:
    solicitud = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(solicitud, timeout=TIEMPO_ESPERA) as respuesta:
        total = None
        try:
            total = int(respuesta.headers.get("Content-Length"))
        except (AttributeError, TypeError, ValueError):
            pass
        descargado = 0
        with destino.open("wb") as archivo:
            while True:
                if cancelar is not None and cancelar():
                    raise _DescargaCancelada
                bloque = respuesta.read(1024 * 1024)
                if not bloque:
                    break
                archivo.write(bloque)
                descargado += len(bloque)
                if aviso is not None:
                    aviso(porcentaje_descarga(descargado, total), descargado, total)


def descargar_ytdlp(url: str, firma: str, destino: str | os.PathLike,
                    aviso_progreso=None, cancelar=None) -> ResultadoDescarga:
    """Descarga, verifica y reemplaza un ejecutable sin ejecutar el temporal."""
    if not url.lower().startswith("https://"):
        return ResultadoDescarga(False, "la descarga exige una URL https")
    destino = Path(destino)
    temporal = None
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
                prefix=".yt-dlp-", suffix=".tmp", dir=destino.parent,
                delete=False) as archivo:
            temporal = Path(archivo.name)
        if aviso_progreso is None and cancelar is None:
            _descargar_archivo(url, temporal)
        else:
            _descargar_archivo(url, temporal, aviso_progreso, cancelar)
        resumen = hashlib.sha256()
        with temporal.open("rb") as archivo:
            for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
                resumen.update(bloque)
        if resumen.hexdigest().lower() != firma.strip().lower():
            return ResultadoDescarga(False, "la firma SHA-256 no coincide")
        os.replace(temporal, destino)
        temporal = None
        return ResultadoDescarga(True, "yt-dlp actualizado")
    except _DescargaCancelada:
        return ResultadoDescarga(False, "descarga cancelada")
    except (OSError, HTTPError, URLError, ValueError) as error:
        return ResultadoDescarga(False, f"no se pudo descargar yt-dlp: {error}")
    finally:
        if temporal is not None:
            try:
                temporal.unlink()
            except OSError:
                pass


def asegurar_ytdlp(destino: str | os.PathLike | None = None) -> ResultadoDescarga:
    """Asegura una copia local y no descarga si ya existe un binario."""
    if destino is None:
        destino = _ruta_actualizada()
    destino = Path(destino)
    if ruta_ytdlp() is not None:
        return ResultadoDescarga(True, "yt-dlp ya está disponible")
    ultima = ultima_version_ytdlp()
    if ultima is None:
        return ResultadoDescarga(False, "no se pudo consultar la última versión")
    _, url_ejecutable, url_firmas = ultima
    try:
        solicitud = Request(url_firmas, headers={"User-Agent": USER_AGENT})
        with urlopen(solicitud, timeout=TIEMPO_ESPERA) as respuesta:
            texto_firmas = respuesta.read().decode("utf-8")
    except (HTTPError, URLError, OSError, UnicodeError):
        return ResultadoDescarga(False, "no se pudieron descargar las firmas")
    firma = firma_sha256(texto_firmas, NOMBRE_BINARIO)
    if not firma:
        return ResultadoDescarga(False, "no se encontró la firma de yt-dlp.exe")
    return descargar_ytdlp(url_ejecutable, firma, destino)


def actualizar_ytdlp(avisar_antes_descarga=None, aviso_progreso=None,
                    cancelar=None) -> tuple[str, str, str]:
    """Compara con la última publicada y actualiza si hace falta.

    Devuelve (estado, versión instalada, versión nueva).
    """
    ruta = ruta_ytdlp()
    version_instalada = version_ytdlp(ruta) if ruta else ""
    ultima = ultima_version_ytdlp()
    if ultima is None:
        return "sin_conexion", version_instalada, ""

    version_nueva, url_ejecutable, url_firmas = ultima
    if ruta and version_instalada == version_nueva:
        return "ya_al_dia", version_instalada, version_nueva

    try:
        solicitud = Request(url_firmas, headers={"User-Agent": USER_AGENT})
        with urlopen(solicitud, timeout=TIEMPO_ESPERA) as respuesta:
            texto_firmas = respuesta.read().decode("utf-8")
    except (HTTPError, URLError, OSError, UnicodeError):
        return "sin_conexion", version_instalada, version_nueva

    firma = firma_sha256(texto_firmas, NOMBRE_BINARIO)
    if not firma:
        return "otro_fallo", version_instalada, version_nueva
    if avisar_antes_descarga is not None:
        avisar_antes_descarga()
    resultado = descargar_ytdlp(url_ejecutable, firma, _ruta_actualizada(),
                                aviso_progreso, cancelar)
    if resultado.correcta:
        return "actualizado", version_instalada, version_nueva
    if "firma" in resultado.motivo.lower():
        return "firma_incorrecta", version_instalada, version_nueva
    if "cancelada" in resultado.motivo.lower():
        return "cancelado", version_instalada, version_nueva
    return "otro_fallo", version_instalada, version_nueva
