"""Constantes, carga de configuración, atajos de teclado y logging."""

from __future__ import annotations

import configparser
import logging
import re
import sys
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

import config_predeterminada

import diagnostico


LIBRERIAS_SILENCIADAS = (
    "httpx", "httpcore", "hpack", "h2", "websockets", "googleapiclient",
    "google_auth_httplib2", "google.auth", "urllib3", "asyncio", "comtypes",
    "libloader", "PIL", "charset_normalizer",
)


# ── Identidad ─────────────────────────────────────────────────────────────────

APP_NAME    = "YTChat TTS"
APP_VERSION = "2.1.0"

# ── Tipos de mensaje ──────────────────────────────────────────────────────────

TIPO_TEXTO     = "text"
TIPO_SUPERCHAT = "superchat"
TIPO_STICKER   = "sticker"
TIPO_MIEMBRO   = "member"
TIPO_ENTRADA   = "entrada"   # alguien entra al directo (solo TikTok, opcional)

FILTROS = [
    ("Todos",        None),
    ("Solo texto",   TIPO_TEXTO),
    ("Super Chats",  TIPO_SUPERCHAT),
    ("Membresías",   TIPO_MIEMBRO),
]


# ── Carpeta base ──────────────────────────────────────────────────────────────
# Cuando se empaqueta con PyInstaller (onedir), los archivos editables
# (config.ini, sounds.ini, sounds/) viven junto al .exe, no dentro de
# _MEIPASS. Esta función resuelve la ruta correcta en ambos contextos.

def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


# ── Logging ───────────────────────────────────────────────────────────────────

def librerias_silenciadas() -> tuple[str, ...]:
    return LIBRERIAS_SILENCIADAS


def configurar_logging(nivel_consola: int = logging.INFO) -> None:
    root = logging.getLogger()
    # Idempotente: se marcan los handlers propios y, si ya están puestos, no
    # se vuelven a añadir (cada línea saldría duplicada en consola y en el log).
    if any(getattr(h, "_ytchat_propio", False) for h in root.handlers):
        return
    root.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(nivel_consola)
    ch.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
    ch._ytchat_propio = True
    root.addHandler(ch)

    log_path = app_dir() / "ytchat.log"
    try:
        fh = RotatingFileHandler(log_path, maxBytes=1_048_576, backupCount=1, encoding="utf-8")
        fh.setLevel(logging.WARNING)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"))
        root.addHandler(fh)
    except Exception as exc:
        logger.warning("No se pudo crear ytchat.log: %s", exc)

    # El registro detallado se activa únicamente si se solicita en Preferencias.
    detallado = False
    try:
        p_diag = _mk_parser()
        p_diag.read(app_dir() / "config.ini", encoding="utf-8")
        detallado = p_diag.getboolean("diagnostico", "registro_detallado",
                                     fallback=False)
    except Exception as exc:
        logger.warning(
            "No se pudo leer la configuración de diagnóstico: %s", exc)
    if detallado:
        try:
            root.addHandler(diagnostico.crear_manejador_detallado(
                app_dir() / "ytchat-debug.log"))
        except Exception as exc:
            logger.warning(
                "No se pudo crear ytchat-debug.log: %s", exc)

    # ytchat.log conserva los avisos de terceros, que pueden explicar un fallo.
    # Las librerías de terceros no deben ocultar los diagnósticos propios.
    for _lib in librerias_silenciadas():
        logging.getLogger(_lib).setLevel(logging.WARNING)


# ── Atajos de teclado ─────────────────────────────────────────────────────────
# Esquema por ÁREA: el modificador indica la zona, para que sea intuitivo.
#   Ctrl  → Reproductor (vídeo/audio), como las apps de medios.
#   Alt   → Conexión y chat (acciones sobre el directo).
#   F     → Voz/lectura TTS (ajustes en caliente) y navegación.
# Se muestran como aceleradores en la barra de menú (NVDA los lee). No chocan
# con los mnemónicos de menú (Alt+inicial) porque usamos otras letras.
#
# Fijos (no editables): F9/F10 velocidad, F11/F12 volumen del TTS, Alt+F4 para
# cerrar y F6 / Shift+F6 para navegar entre regiones.

ATAJOS_DEFAULTS = config_predeterminada.seccion("atajos")

# Estas combinaciones se reservan aunque la gramática editable no admita
# Alt+F4 ni Shift+F6.
ATAJOS_FIJOS_DEFAULTS = {
    "salir": "alt+f4",
    "region_siguiente": "f6",
    "region_anterior": "shift+f6",
}

# Acciones cuya tecla NO debe poder cambiarse en el editor de atajos.
ATAJOS_FIJOS = {
    "velocidad_menos", "velocidad_mas", "volumen_menos", "volumen_mas",
    *ATAJOS_FIJOS_DEFAULTS,
}

# Agrupación para el editor de Preferencias (título de grupo, acciones).
ATAJOS_GRUPOS = [
    ("Reproductor (Ctrl)",
     ["rep_play", "rep_retro", "rep_avanz", "rep_detener", "rep_mute",
      "rep_vol_menos", "rep_vol_mas", "descargas_abrir", "pantalla_completa"]),
    ("Conexión y chat (Alt)",
     ["conectar", "desconectar", "enviar_chat", "ir_lista"]),
    ("Ventanas y paneles (Ctrl+Shift)",
     ["abrir_preferencias", "abrir_historial", "marcar_incidencia",
      "abrir_transmision", "obs_micro"]),
    ("Voz y lectura (teclas F)",
     ["pausa", "detener_tts", "velocidad_menos", "velocidad_mas",
      "volumen_menos", "volumen_mas", "silenciar_lectura",
      "silenciar_sonidos", "anunciar_estado"]),
    ("Ventana y navegación (fijos)",
     ["salir", "region_siguiente", "region_anterior"]),
]

# Modificador obligatorio por acción: reproductor → Ctrl, app → Alt, voz → F.
# El grupo de atajos fijos no impone modificador.
_AREA_POR_GRUPO = ("ctrl", "alt", "ctrl+shift", "f", None)
ATAJOS_AREA = {ac: _AREA_POR_GRUPO[i]
               for i, (_titulo, acs) in enumerate(ATAJOS_GRUPOS) for ac in acs}

_SIMBOLOS_PERMITIDOS = {",", ".", ";", "'", "[", "]", "/", "-"}
# Teclas con nombre admitidas (además de una letra/símbolo o una tecla F).
_TECLAS_NOMBRE = {"enter", "left", "right", "up", "down", "space"}
# Ctrl+Shift debe probarse antes que Ctrl para no quedarse con «shift+tecla».
_RE_ATAJO = re.compile(r"^(ctrl\+shift|ctrl|alt)\+(.+)$", re.IGNORECASE)
_RE_FKEY  = re.compile(r"^f(1[0-2]|[1-9])$", re.IGNORECASE)

logger = diagnostico.obtener_logger(__name__)


@dataclass(frozen=True, slots=True)
class Atajo:
    accion: str
    texto:  str
    tecla:  str


def todos_los_atajos_default() -> dict[str, str]:
    """Devuelve las combinaciones reservadas por la aplicación."""
    return {**ATAJOS_FIJOS_DEFAULTS, **ATAJOS_DEFAULTS}


def _normalizar_atajo(valor: str | None) -> str | None:
    """Normaliza a 'ctrl+x' / 'alt+enter' / 'ctrl+left' / 'f5'. None si no vale.

    Ctrl+Shift, Ctrl o Alt + tecla, o una tecla F sin modificador.
    """
    if valor is None:
        return None
    valor = valor.strip().lower().replace(" ", "")
    if not valor:
        return None
    if _RE_FKEY.match(valor):
        return valor
    m = _RE_ATAJO.match(valor)
    if not m:
        return None
    mod, key = m.group(1), m.group(2)
    if key in _TECLAS_NOMBRE:
        return f"{mod}+{key}"
    if len(key) == 1 and key.isascii() and (key.isalnum() or key in _SIMBOLOS_PERMITIDOS):
        return f"{mod}+{key}"
    return None


def atajo_valido_para_area(accion: str, normalizado: str | None) -> bool:
    """¿El atajo respeta el modificador del área de la acción?

    Reproductor → Ctrl, app → Alt, voz → tecla F. Vacío (desactivado) o acción
    sin área definida se aceptan sin restricción.
    """
    area = ATAJOS_AREA.get(accion)
    if not normalizado or area is None:
        return True
    if area == "f":
        return bool(_RE_FKEY.match(normalizado))
    # Ctrl+Shift pertenece a su área propia, no a la general de Ctrl.
    if area == "ctrl" and normalizado.startswith("ctrl+shift+"):
        return False
    return normalizado.startswith(area + "+")


def parsear_atajos(raw: dict | None) -> dict[str, Atajo]:
    raw = {} if raw is None else {k.lower(): v for k, v in raw.items()}
    resultado: dict[str, Atajo] = {}
    teclas_usadas: dict[str, str] = {}

    for accion, default in todos_los_atajos_default().items():
        valor_usuario = raw.get(accion)
        fija = accion in ATAJOS_FIJOS
        if not fija and valor_usuario is not None and valor_usuario.strip() == "":
            continue  # desactivado explícitamente

        normalizado = default if fija else _normalizar_atajo(valor_usuario)
        if not fija and valor_usuario is not None and normalizado is None:
            logger.warning("atajos: valor inválido para %r: %r. Usando default %r.",
                           accion, valor_usuario, default)
            normalizado = _normalizar_atajo(default)
        elif not fija and normalizado is None:
            normalizado = _normalizar_atajo(default)
        if normalizado is None:
            continue

        # El conflicto se mide por la combinación COMPLETA: 'ctrl+d' y 'alt+d'
        # son atajos distintos y no chocan; dos 'alt+d' sí.
        if normalizado in teclas_usadas:
            logger.warning("atajos: conflicto — %r y %r usan %r. Desactivando %r.",
                           teclas_usadas[normalizado], accion, normalizado, accion)
            continue
        teclas_usadas[normalizado] = accion
        tecla = normalizado.split("+", 1)[-1]
        resultado[accion] = Atajo(accion=accion, texto=normalizado, tecla=tecla)
    return resultado


def detectar_conflictos_atajos(raw: dict | None) -> list[tuple[str, str, str]]:
    """Devuelve (acción que pierde, acción que conserva, combinación)."""
    raw = {} if raw is None else {k.lower(): v for k, v in raw.items()}
    conflictos = []
    teclas_usadas: dict[str, str] = {}
    for accion, default in todos_los_atajos_default().items():
        fija = accion in ATAJOS_FIJOS
        valor_usuario = raw.get(accion)
        if not fija and valor_usuario is not None and valor_usuario.strip() == "":
            continue
        normalizado = default if fija else _normalizar_atajo(valor_usuario)
        if not fija and normalizado is None:
            normalizado = _normalizar_atajo(default)
        if normalizado is None:
            continue
        anterior = teclas_usadas.get(normalizado)
        if anterior is not None:
            conflictos.append((accion, anterior, normalizado))
            continue
        teclas_usadas[normalizado] = accion
    return conflictos


# ── Carga de config.ini ──────────────────────────────────────────────────────

_CONFIG_FALLBACK = config_predeterminada.generar_texto()

_SOUNDS_FALLBACK = """\
[sonidos]
activar = true
volumen = 0.7

# Tema de sonido: carpeta dentro de sounds/themes/ con un WAV por evento,
# nombrado igual que el evento (p. ej. mensaje_nuevo.wav). Para crear tu
# propio tema, copia sounds/themes/default a sounds/themes/mi_tema,
# reemplaza los .wav que quieras y pon aquí:  tema = mi_tema
tema = default

# Opcional (avanzado): puedes forzar un archivo concreto para un evento
# escribiendo su ruta aquí; tiene prioridad sobre el tema. Por ejemplo:
#   superchat = sounds/mis_efectos/caja.wav
"""

_EVENTOS_SONIDO = [
    "app_inicio", "conectando", "conectado", "desconectado",
    "mensaje_nuevo", "superchat", "nuevo_miembro", "error",
    "pausa", "reanudar", "copiar", "voz_cambiada",
    # v0.6 online y acciones que antes reutilizaban otros sonidos:
    "enviado", "comentario", "moderacion", "cola_vaciada",
    "transporte_en_curso",
]

# Carpeta base de temas y tema por defecto.
_TEMAS_DIR   = "themes"
_TEMA_DEFECTO = "default"


def _mk_parser() -> configparser.ConfigParser:
    return configparser.ConfigParser(inline_comment_prefixes=("#", ";"), default_section="__none__")


def _fallback(sec: str, k: str) -> str:
    return config_predeterminada.obtener(sec, k, "")


def _gs(p, sec, k):       return p.get(sec, k, fallback=_fallback(sec, k)).strip()
def _gi(v, d):
    try:    return int(str(v).strip())
    except Exception: return d
def _gf(v, d):
    try:    return float(str(v).strip())
    except Exception: return d
def _pi(p, sec, k, lo=0, hi=None):
    fb = _fallback(sec, k)
    try:
        d = int(fb.strip()) if fb.strip() else 0
    except Exception:
        d = 0
    v = max(lo, _gi(_gs(p, sec, k), d))
    return min(hi, v) if hi is not None else v
def _pf(p, sec, k, lo=0.0, hi=1.0):
    fb = _fallback(sec, k)
    try:
        d = float(fb.strip()) if fb.strip() else 1.0
    except Exception:
        d = 1.0
    return max(lo, min(hi, _gf(_gs(p, sec, k), d)))
def _pb(p, sec, k):
    try:    return p.getboolean(sec, k)
    except Exception: return _fallback(sec, k).strip().lower() in ("true", "yes", "1", "on")
def _lista(v: str) -> list:
    return [x.strip().lower() for x in v.split(",") if x.strip()]


def guardar_opcion(ruta: Path | None, seccion: str, clave: str, valor: str) -> None:
    """Actualiza una clave en el INI preservando comentarios y orden."""
    if ruta is None:
        return
    try:
        txt = ruta.read_text(encoding="utf-8")
    except Exception as exc:
        logger.debug("guardar_opcion: no se pudo leer %s: %s", ruta, exc)
        return

    lines = txt.splitlines(keepends=True)
    sec_lower = seccion.lower()
    clave_lower = clave.lower()
    nueva = f"{clave} = {valor}\n"
    in_sec = False
    insert_pos = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            if in_sec:
                break
            in_sec = stripped.lower() == f"[{sec_lower}]"
            if in_sec:
                insert_pos = i + 1
        elif in_sec:
            # Los blancos y comentarios del final de la sección no mueven el
            # punto de inserción: la clave nueva va tras la última clave, no
            # pegada a la cabecera de la sección siguiente.
            if not stripped or stripped.startswith(("#", ";")):
                continue
            k = stripped.split("=", 1)[0].strip().lower() if "=" in stripped else ""
            if k == clave_lower:
                lines[i] = nueva
                try:    ruta.write_text("".join(lines), encoding="utf-8")
                except Exception as exc:
                    logger.debug("guardar_opcion: no se pudo escribir: %s", exc)
                return
            insert_pos = i + 1

    if in_sec:
        if insert_pos is None:
            insert_pos = len(lines)
        # Si la línea anterior no termina en salto (final de archivo), la
        # clave nueva quedaría pegada a ella.
        if insert_pos > 0 and not lines[insert_pos - 1].endswith("\n"):
            lines[insert_pos - 1] += "\n"
        lines.insert(insert_pos, nueva)
    elif insert_pos is None:
        lines.append(f"\n[{seccion}]\n{nueva}")

    try:    ruta.write_text("".join(lines), encoding="utf-8")
    except Exception as exc:
        logger.debug("guardar_opcion: no se pudo escribir: %s", exc)


# ── Helpers de descargas (formato, bitrate, carpeta, enumerar) ──────────────
# Se leen/escriben del INI con `guardar_opcion` (preserva comentarios). Sirven
# para que `descargas.GestorDescargas` y `gui_descargas` trabajen contra un
# único origen de verdad, sin tener que duplicar la carga de config.ini.
#
# Formato por defecto: mp4 muxed (mejor compat con NVDA, sin audio separado).
# Carpeta por defecto: `app_dir() / "Descargas"` (portable, escribible sin
# permisos de admin). Si el INI trae la clave vacía, también se rellena.

_FORMATOS_VALIDOS = ("mp4", "webm", "mp3", "m4a")
_BITRATES_VALIDOS = (192, 256, 320)


def obtener_opciones_descarga() -> dict:
    """Lee la sección [descargas] del INI y devuelve un dict validado.

    Si la sección no existe o falta alguna clave, se rellena con `guardar_opcion`
    (que conserva comentarios y orden) y se devuelve el dict ya con defaults.
    Funciona standalone: NO requiere haber llamado a `cargar_configuracion`.
    """
    ruta = app_dir() / "config.ini"
    p = _mk_parser()
    if ruta.exists():
        try:    p.read(ruta, encoding="utf-8")
        except configparser.Error: pass

    # Carpeta: si está vacía o no existe, usar app_dir() / "Descargas".
    carpeta_raw = (p.get("descargas", "carpeta", fallback="").strip()
                   if p.has_section("descargas") else "")
    if not carpeta_raw:
        carpeta = str(app_dir() / "Descargas")
    elif not Path(carpeta_raw).anchor:
        # El valor predeterminado es «Descargas» a secas: yt-dlp lo resolvía
        # contra el directorio de trabajo del proceso, que con un acceso
        # directo o desde una consola no es la carpeta de la app.
        carpeta = str(app_dir() / carpeta_raw)
    else:
        carpeta = carpeta_raw

    formato = (p.get("descargas", "formato", fallback="mp4").strip().lower()
               if p.has_section("descargas") else "mp4")
    if formato not in _FORMATOS_VALIDOS:
        formato = "mp4"
        if ruta.exists():
            guardar_opcion(ruta, "descargas", "formato", formato)

    bitrate_raw = (p.get("descargas", "bitrate", fallback="192").strip()
                   if p.has_section("descargas") else "192")
    try:    bitrate = int(bitrate_raw)
    except Exception: bitrate = 192
    if bitrate not in _BITRATES_VALIDOS:
        bitrate = 192
        if ruta.exists():
            guardar_opcion(ruta, "descargas", "bitrate", str(bitrate))

    enumerar_raw = (p.get("descargas", "enumerar", fallback="false").strip().lower()
                    if p.has_section("descargas") else "false")
    enumerar = enumerar_raw in ("true", "1", "yes", "on")

    return {"formato": formato, "bitrate": bitrate,
            "carpeta": carpeta, "enumerar": enumerar}


def guardar_opciones_descarga(op: dict) -> None:
    """Persiste todas las opciones de descarga de una vez. Valida y normaliza
    los valores antes de escribir."""
    ruta = app_dir() / "config.ini"
    if not ruta.exists():
        # Si por algo no existe, crearlo con el fallback y volver a llamar.
        try:    ruta.write_text(_CONFIG_FALLBACK, encoding="utf-8")
        except Exception as exc:
            logger.debug("guardar_opciones_descarga: no se pudo crear config.ini: %s", exc)
            return

    formato = str(op.get("formato", "mp4")).lower().strip()
    if formato not in _FORMATOS_VALIDOS:
        formato = "mp4"
    try:    bitrate = int(op.get("bitrate", 192))
    except Exception: bitrate = 192
    if bitrate not in _BITRATES_VALIDOS:
        bitrate = 192
    carpeta = str(op.get("carpeta") or (app_dir() / "Descargas")).strip()
    enumerar = bool(op.get("enumerar", False))

    guardar_opcion(ruta, "descargas", "formato", formato)
    guardar_opcion(ruta, "descargas", "bitrate", str(bitrate))
    guardar_opcion(ruta, "descargas", "carpeta", carpeta)
    guardar_opcion(ruta, "descargas", "enumerar", "true" if enumerar else "false")


def cargar_configuracion() -> dict:
    ruta = app_dir() / "config.ini"
    if not ruta.exists():
        logger.warning("config.ini no encontrado. Creando con valores por defecto.")
        try:    ruta.write_text(_CONFIG_FALLBACK, encoding="utf-8")
        except Exception as exc: logger.error("No se pudo crear config.ini: %s", exc)

    p = _mk_parser()
    try:
        if not p.read(ruta, encoding="utf-8"):
            logger.error("No se pudo leer config.ini."); sys.exit(1)
    except configparser.Error as exc:
        logger.error("Error de sintaxis en config.ini: %s", exc)
        logger.error("Borra config.ini y vuelve a abrir la aplicación para regenerarlo.")
        sys.exit(1)

    estrategia = _gs(p, "cola", "estrategia").lower()
    if estrategia not in ("todas", "limite"): estrategia = "limite"
    formato = _gs(p, "lectura", "formato_prefijo").lower()
    if formato not in ("nombre_mensaje", "mensaje_nombre", "solo_mensaje", "solo_nombre"): formato = "nombre_mensaje"
    guardar = _gs(p, "sesion", "guardar_historial").lower()
    if guardar not in ("no", "csv", "txt"): guardar = "no"

    atajos_raw = {}
    if p.has_section("atajos"):
        atajos_raw = {k.strip().lower(): (v or "").strip() for k, v in p.items("atajos")}

    # Migración genérica: agregar toda sección o clave ausente desde la fuente
    # canónica, preservando valores existentes incluso vacíos y claves desconocidas.
    _atajos_faltantes = []
    for _sec, _claves in config_predeterminada.datos().items():
        for _clave, _valor_def in _claves.items():
            if not p.has_option(_sec, _clave):
                guardar_opcion(ruta, _sec, _clave, _valor_def)
                if _sec == "atajos":
                    atajos_raw[_clave] = _valor_def
                    _atajos_faltantes.append(_clave)
    if _atajos_faltantes:
        logger.info("Atajos nuevos añadidos a config.ini: %s", ", ".join(_atajos_faltantes))

    desc_op = obtener_opciones_descarga()

    # Estado (F2): un booleano por componente.
    from estado_sesion import COMPONENTES as _EST_COMP
    # Fallback canónico para estado: true donde la fábrica lo marca así.
    _estado_defaults = config_predeterminada.seccion("estado")
    estado_toggles = set()
    for comp in _EST_COMP:
        try:    activo = p.getboolean("estado", comp)
        except Exception: activo = _estado_defaults.get(comp, "false").lower() in ("true", "yes", "1", "on")
        if activo:
            estado_toggles.add(comp)

    filtro_activo = _gs(p, "ui", "filtro_activo").lower()
    if filtro_activo not in ("todos", "texto", "superchat", "miembro"):
        filtro_activo = "todos"

    return {
        "voz": _gs(p, "voz", "voz"),
        "velocidad": _pi(p, "voz", "velocidad", lo=50, hi=500),
        "volumen": _pf(p, "voz", "volumen"),
        "multivoz": _pb(p, "voz", "multivoz"),
        "voz_eventos": _gs(p, "voz", "voz_eventos"),
        "estrategia": estrategia,
        "tamanio_maximo": _pi(p, "cola", "tamanio_maximo", lo=1),
        "umbral_solo_nombre": _pi(p, "cola", "umbral_solo_nombre"),
        "reconectar": _pb(p, "reconexion", "reconectar"),
        "espera_entre_intentos": _pi(p, "reconexion", "espera_entre_intentos", lo=1),
        "max_intentos": _pi(p, "reconexion", "max_intentos"),
        "formato_prefijo": formato,
        "palabras_silenciadas": _lista(_gs(p, "filtros", "palabras_silenciadas")),
        "usuarios_silenciados": _lista(_gs(p, "filtros", "usuarios_silenciados")),
        "limpiar_emojis": _pb(p, "texto", "limpiar_emojis"),
        "eliminar_urls": _pb(p, "texto", "eliminar_urls"),
        "max_longitud_mensaje": _pi(p, "texto", "max_longitud_mensaje"),
        "tamanio_fuente_chat": _pi(p, "ui", "tamanio_fuente_chat", lo=8, hi=24),
        "mostrar_total_superchats": _pb(p, "ui", "mostrar_total_superchats"),
        "autoplay_reproductor": _pb(p, "ui", "autoplay_reproductor"),
        "mostrar_botones_reproductor": _pb(p, "ui", "mostrar_botones_reproductor"),
        "cache_video_mb": _pi(p, "ui", "cache_video_mb", lo=0, hi=20000),
        "mostrar_metadatos": _pb(p, "ui", "mostrar_metadatos"),
        "filtro_activo": filtro_activo,
        "silenciar_sonidos": _pb(p, "ui", "silenciar_sonidos"),
        "guardar_historial": guardar,
        "silenciar_lectura": _pb(p, "sesion", "silenciar_lectura"),
        "tiktok_anunciar_entradas": _pb(p, "tiktok", "anunciar_entradas"),
        "programados_activo": _pb(p, "programados", "activo"),
        "registro_detallado": _pb(p, "diagnostico", "registro_detallado"),  # configurar_logging se adelanta al diccionario.
        "overlay_activo": _pb(p, "overlay", "activo"),
        "overlay_puerto": _pi(p, "overlay", "puerto", lo=1),
        "obs_microfono": _gs(p, "obs", "microfono"),
        "estado_toggles": estado_toggles,
        "atajos_raw": atajos_raw,
        "ruta_config": ruta,
        # Gestor de descargas (GestorDescargas / gui_descargas). Las opciones
        # validadas viven además en `desc_op` por si alguien quiere pasarlas
        # explícitamente sin parsear el INI de nuevo.
        "descargas": desc_op,
        "descargas_formato": desc_op["formato"],
        "descargas_bitrate": desc_op["bitrate"],
        "descargas_carpeta": desc_op["carpeta"],
        "descargas_enumerar": desc_op["enumerar"],
    }


def cargar_sonidos() -> dict:
    """Devuelve dict para `sound_player.cargar()`."""
    base = app_dir()
    ruta = base / "sounds.ini"
    if not ruta.exists():
        logger.warning("sounds.ini no encontrado. Creando con valores por defecto.")
        try:    ruta.write_text(_SOUNDS_FALLBACK, encoding="utf-8")
        except Exception as exc: logger.error("No se pudo crear sounds.ini: %s", exc)

    p = _mk_parser()
    try:
        if not p.read(ruta, encoding="utf-8"):
            return {"activar": False, "volumen": 0.7, "eventos": {}}
    except configparser.Error as exc:
        logger.warning("Error en sounds.ini: %s. Sonidos desactivados.", exc)
        return {"activar": False, "volumen": 0.7, "eventos": {}}

    activar, volumen, tema = True, 0.7, _TEMA_DEFECTO
    if p.has_section("sonidos"):
        try:    activar = p.getboolean("sonidos", "activar", fallback=True)
        except Exception: pass
        try:    volumen = max(0.0, min(1.0, float(p.get("sonidos", "volumen", fallback="0.7"))))
        except Exception: pass
        try:    tema = (p.get("sonidos", "tema", fallback=_TEMA_DEFECTO).strip()
                        or _TEMA_DEFECTO)
        except Exception: pass

    carpeta_tema = base / "sounds" / _TEMAS_DIR / tema

    eventos: dict[str, Path | None] = {}
    for ev in _EVENTOS_SONIDO:
        # 1) Ruta explícita en sounds.ini (override avanzado, máxima prioridad).
        raw = p.get("sonidos", ev, fallback="").strip()
        if raw:
            ruta_ev = Path(raw)
            if not ruta_ev.is_absolute():
                ruta_ev = base / ruta_ev
            eventos[ev] = ruta_ev
            continue
        # 2) Si no, el archivo del tema: sounds/themes/<tema>/<evento>.wav
        eventos[ev] = carpeta_tema / f"{ev}.wav"

    return {"activar": activar, "volumen": volumen, "eventos": eventos}


# ── Helpers de temas de sonido (para el diálogo de Preferencias) ──────────────

def listar_temas_sonido() -> list[str]:
    """Nombres de carpeta dentro de sounds/themes/ (cada una es un tema)."""
    carpeta = app_dir() / "sounds" / _TEMAS_DIR
    try:
        temas = sorted(d.name for d in carpeta.iterdir() if d.is_dir())
    except Exception:
        temas = []
    if _TEMA_DEFECTO not in temas:
        temas.insert(0, _TEMA_DEFECTO)
    return temas


def tema_sonido_actual() -> str:
    """Lee el tema activo de sounds.ini (o el por defecto)."""
    ruta = app_dir() / "sounds.ini"
    p = _mk_parser()
    try:
        p.read(ruta, encoding="utf-8")
        return (p.get("sonidos", "tema", fallback=_TEMA_DEFECTO).strip()
                or _TEMA_DEFECTO)
    except Exception:
        return _TEMA_DEFECTO
