"""Reproductor de vídeo/audio del directo o vídeo, accesible y con imagen.

Backend: yt-dlp obtiene las URLs de los flujos y libVLC (python-vlc) reproduce,
mostrando la imagen embebida (set_hwnd) con audio. Permite elegir calidad y
pantalla completa. Para audio+vídeo en calidades altas (DASH) se reproduce el
flujo de vídeo con el de audio como «input-slave».

Se eligió VLC porque el backend nativo de Windows no reproduce los flujos
`googlevideo`. Todo degrada tras guardas: si falta python-vlc, libVLC o yt-dlp,
el panel muestra un aviso y el resto de la app funciona igual. VLC se importa y
se instancia de forma perezosa (al primer uso) para no frenar el arranque.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import sys
import threading
import time

import wx

import config as _cfg
from busqueda_video import (
    EstadoBusqueda, EstadoInicioReproduccion, OrdenTransporte,
    TOPE_BUSQUEDA_MS, accion_play_pausa, busqueda_permitida, destino_acumulado,
    evaluar_transporte,
)
import iconos
import diagnostico
import progreso
from traza_transporte import (
    topologia_medio, traza_busqueda_desenlace, traza_busqueda_muestra,
    traza_busqueda_orden, traza_inicio_muestra, traza_salto, traza_sin_barra,
    traza_transporte,
)
import ytdlp_bin
import esclavo_audio
import reproductor_ciclo
import relevo_ffmpeg
from gui import anunciar, nombre_accesible, _T, _tc

logger = diagnostico.obtener_logger(__name__)

_vlc = None          # binding python-vlc; se importa perezosamente
_VLC_PREPARADO = False


def _registrar_tiempo_precalentamiento(tramo: str, inicio: float, fin: float) -> None:
    diagnostico.logger.info(
        "VLC_PRECALENTAMIENTO tramo=%s ms=%.0f", tramo, (fin - inicio) * 1000)


def _carpeta_vlc_empaquetada() -> str | None:
    if getattr(sys, "frozen", False):
        base = os.path.join(os.path.dirname(sys.executable), "vlc")
        if os.path.exists(os.path.join(base, "libvlc.dll")):
            return base
    return None


def _preparar_vlc() -> None:
    """Deja listo el entorno para cargar libVLC. En la app empaquetada apunta a
    la copia de VLC junto al .exe y PRECARGA libvlccore para que el cargador de
    PyInstaller no falle al resolver la dependencia."""
    global _VLC_PREPARADO
    inicio = time.monotonic()
    if _VLC_PREPARADO:
        return
    _VLC_PREPARADO = True
    base = _carpeta_vlc_empaquetada()
    if not base:
        _registrar_tiempo_precalentamiento("preparar_dll", inicio, time.monotonic())
        return
    lib = os.path.join(base, "libvlc.dll")
    plugins = os.path.join(base, "plugins")
    os.environ["PYTHON_VLC_LIB_PATH"] = lib
    os.environ["PYTHON_VLC_MODULE_PATH"] = plugins
    # VLC_PLUGIN_PATH es lo que lee libVLC para localizar sus plugins; sin esto
    # la instancia sale None en la app empaquetada.
    os.environ["VLC_PLUGIN_PATH"] = plugins
    os.environ["PATH"] = base + os.pathsep + os.environ.get("PATH", "")
    try:
        os.add_dll_directory(base)
    except Exception:
        pass
    # Precargar el core: así libvlc.dll encuentra su dependencia bajo PyInstaller.
    try:
        import ctypes
        ctypes.CDLL(os.path.join(base, "libvlccore.dll"))
    except Exception as exc:
        logger.debug("preload libvlccore: %s", exc)
    _registrar_tiempo_precalentamiento("preparar_dll", inicio, time.monotonic())


def _cargar_vlc() -> bool:
    """Importa python-vlc de forma perezosa. True si quedó disponible."""
    global _vlc
    if _vlc is not None:
        return True
    _preparar_vlc()
    inicio = time.monotonic()
    try:
        import vlc
        _vlc = vlc
        _registrar_tiempo_precalentamiento("importar_modulo", inicio, time.monotonic())
        return True
    except Exception as exc:
        _registrar_tiempo_precalentamiento("importar_modulo", inicio, time.monotonic())
        logger.warning("No se pudo cargar libVLC: %s", exc)
        return False


def vlc_disponible() -> bool:
    """¿Hay VLC? Sin importarlo (cargar la DLL es lento) para no frenar arranque."""
    if getattr(sys, "frozen", False):
        return _carpeta_vlc_empaquetada() is not None
    try:
        return importlib.util.find_spec("vlc") is not None
    except Exception:
        return False


def ytdlp_disponible() -> bool:
    if getattr(sys, "frozen", False):
        base = os.path.join(os.path.dirname(sys.executable), "_internal", "yt_dlp")
        return os.path.isdir(base)
    try:
        return importlib.util.find_spec("yt_dlp") is not None
    except Exception:
        return False


def disponible() -> bool:
    return vlc_disponible() and ytdlp_disponible()


def aviso_reproductor(hay_reproductor: bool, hay_medio: bool) -> str:
    """Devuelve el aviso adecuado cuando un control no puede actuar."""
    if not hay_reproductor:
        return "El reproductor no está disponible"
    if not hay_medio:
        return "No hay ningún vídeo cargado"
    return ""


# Argumentos de la instancia: solo los imprescindibles. Cualquier opción que
# libVLC no reconozca hace que libvlc_new devuelva NULL (instancia None), así
# que el ajuste de buffer va como opción POR MEDIO (más tolerante), no aquí.
_VLC_ARGS = ("--quiet",)


def opciones_medio(es_directo: bool) -> tuple[str, ...]:
    """Opciones de búfer para un medio grabado o en directo."""
    # El grabado admite más colchón para resistir fluctuaciones de red; el
    # directo conserva menor demora respecto de la emisión.
    red = 1500 if es_directo else 3000
    return (f":network-caching={red}", ":live-caching=1500")


def aviso_de_corte(pct, pct_anterior) -> str:
    """Devuelve avisos solo al empezar y recuperarse un corte de búfer."""
    if pct < 100 and (pct_anterior is None or pct_anterior >= 100):
        return f"VLC_CORTE empezó porcentaje={pct:.0f}"
    if pct >= 100 and pct_anterior is not None and pct_anterior < 100:
        return "VLC_CORTE recuperado"
    return ""


def _registro_detallado_activo() -> bool:
    try:
        parser = _cfg._mk_parser()
        parser.read(_cfg.app_dir() / "config.ini", encoding="utf-8")
        return parser.getboolean("diagnostico", "registro_detallado",
                                 fallback=False)
    except Exception:
        return False


# Alturas de vídeo que ofrecemos como «calidad», de mayor a menor.
_CALIDADES = [2160, 1440, 1080, 720, 480, 360, 240, 144]

# Recargas automáticas seguidas de un directo cuyo relevo se interrumpió.
TOPE_RECARGAS_DIRECTO = 2


def _info_video(video_id: str) -> dict:
    """Datos de yt-dlp del vídeo (bloquea; usar en hilo)."""
    if ytdlp_bin.ruta_ytdlp() is not None:
        # Con programa disponible se confía en él: si falla o agota sus 30 s,
        # repetir con el módulo sumaba otros 20-30 s de «Cargando vídeo…»
        # para acabar en el mismo error.
        info = ytdlp_bin.info_video(video_id)
        if info is None:
            raise RuntimeError("el programa yt-dlp no devolvió datos del vídeo")
        return info
    import yt_dlp
    # socket_timeout: sin él, una red lenta deja la app colgada en «Cargando
    # vídeo…» sin feedback. 20 s es de sobra para la extracción normal (~3-5 s).
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "noplaylist": True, "socket_timeout": 20}
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _preparar_audio_local(info: dict, video_id: str):
    """Actualiza la caché de audio fuera del hilo de interfaz."""
    if info.get("is_live"):
        return None
    try:
        carpeta = _cfg.app_dir() / "cache-audio"
        carpeta.mkdir(parents=True, exist_ok=True)
        entradas = tuple((ruta, ruta.stat().st_mtime) for ruta in carpeta.iterdir()
                         if ruta.is_file())
        for ruta in esclavo_audio.sobrantes_de_cache(entradas, 3):
            ruta.unlink()
        destino = esclavo_audio.ruta_de_cache(carpeta, video_id)
        if esclavo_audio.esclavo_a_usar(destino, ""):
            return destino
        ultimo = None

        def avisar_progreso(porcentaje):
            nonlocal ultimo
            for escalon in esclavo_audio.escalones_de_progreso(ultimo, porcentaje):
                wx.CallAfter(anunciar, f"Preparando el audio, {escalon} por ciento")
            ultimo = porcentaje

        if ytdlp_bin.descargar_audio(video_id, destino, aviso_progreso=avisar_progreso):
            return destino
    except Exception as exc:
        logger.debug("caché de audio: %s", exc)
    return None


def _alturas_disponibles(info: dict) -> list[int]:
    alturas = set()
    for f in info.get("formats", []) or []:
        if f.get("vcodec") not in (None, "none") and f.get("height"):
            alturas.add(int(f["height"]))
    return sorted(alturas, reverse=True)


def _mejor_audio(info: dict) -> str:
    # Preferimos la pista ORIGINAL antes que la de mayor bitrate: cada vez más
    # vídeos traen doblajes y yt-dlp marca la original/«default» con
    # language_preference alto (10). Sin esto, entre dos bitrates parecidos
    # podríamos reproducir el doblaje en vez del audio original. A igualdad de
    # idioma, gana el bitrate (como antes), así que un vídeo de una sola pista
    # se comporta igual que siempre.
    auds = [f for f in info.get("formats", []) or []
            if f.get("acodec") != "none"
            and f.get("vcodec") in (None, "none") and f.get("url")]
    if not auds:
        return ""
    mejor = max(auds, key=lambda x: ((x.get("language_preference") or 0),
                                     (x.get("abr") or 0)))
    return mejor["url"]


def _video_para_altura(info: dict, altura: int) -> tuple[str, bool]:
    """(url, progresivo). Busca el mejor flujo para esa altura; progresivo=True
    si ya trae audio (no hace falta slave)."""
    fmts = info.get("formats", []) or []
    # 1) Progresivo (audio+vídeo) exacto o cercano por debajo.
    prog = [f for f in fmts if f.get("vcodec") not in (None, "none")
            and f.get("acodec") not in (None, "none") and f.get("url") and f.get("height")]
    cand = [f for f in prog if int(f["height"]) <= altura]
    if cand:
        f = max(cand, key=lambda x: int(x["height"]))
        if int(f["height"]) == altura:
            return f["url"], True
    # 2) Vídeo solo a esa altura (se acompañará con audio como slave).
    solo = [f for f in fmts if f.get("vcodec") not in (None, "none")
            and f.get("acodec") in (None, "none") and f.get("url")
            and f.get("height") and int(f["height"]) == altura]
    if solo:
        return max(solo, key=lambda x: x.get("tbr") or 0)["url"], False
    # 3) Lo mejor progresivo que haya.
    if prog:
        return max(prog, key=lambda x: int(x["height"]))["url"], True
    # 4) Si no hay progresivos, se acompañará el mejor vídeo solo con audio.
    solo = [f for f in fmts if f.get("vcodec") not in (None, "none")
            and f.get("acodec") in (None, "none") and f.get("url")
            and f.get("height")]
    if solo:
        cand = [f for f in solo if int(f["height"]) <= altura]
        if cand:
            altura_elegida = max(int(f["height"]) for f in cand)
            cand = [f for f in cand if int(f["height"]) == altura_elegida]
        else:
            altura_elegida = min(int(f["height"]) for f in solo)
            cand = [f for f in solo if int(f["height"]) == altura_elegida]
        return max(cand, key=lambda x: x.get("tbr") or 0)["url"], False
    return "", False


def _preferir_hls(formatos: list) -> list:
    """Para directos, yt-dlp suele traer en la misma lista variantes HLS
    (.m3u8) y variantes «DASH en crudo» (protocol=https/http_dash_segments):
    una URL que exige el manejo de secuencias propio de yt-dlp y que ni VLC
    ni ffmpeg saben leer bien solos («Invalid data found», comprobado). Si
    hay HLS con vídeo, se usa esa familia; si no, se deja la lista igual:
    quedarse con una familia HLS de solo audio dejaría el directo sin imagen
    (y el audio se resuelve aparte, ver fuentes_para_directo)."""
    hls = [f for f in formatos if "m3u8" in (f.get("protocol") or "")]
    if any(f.get("vcodec") not in (None, "none") for f in hls):
        return hls
    return list(formatos)


def fuentes_para_directo(info: dict) -> tuple[str, str]:
    """(url de vídeo, url de audio esclavo). Audio vacío si no hace falta."""
    url = info.get("url") or ""
    if url:
        return url, ""

    info_hls = {**info, "formats": _preferir_hls(info.get("formats") or [])}
    url, progresivo = _video_para_altura(info_hls, 10_000)
    if url:
        # Si la familia HLS trae vídeo pero ningún audio suelto, el directo
        # quedaba mudo: se cae al mejor audio de la lista completa.
        return url, "" if progresivo else (_mejor_audio(info_hls)
                                          or _mejor_audio(info))

    video = audio = ""
    for formato in info.get("requested_formats", []) or []:
        url = formato.get("url") or ""
        if not url:
            continue
        tiene_video = formato.get("vcodec") not in (None, "none")
        tiene_audio = formato.get("acodec") not in (None, "none")
        if tiene_video:
            video = url
            if tiene_audio:
                return video, ""
        elif tiene_audio:
            audio = url
    if video:
        return video, audio
    return "", ""


def _fmt_t(ms) -> str:
    """Compacto para la etiqueta visual: H:MM:SS, o M:SS si dura menos de 1 h."""
    s = max(0, int(ms or 0) // 1000)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _fmt_hablado(ms) -> str:
    """Verboso para el lector, estilo YouTube: «2 horas 16 minutos 35 segundos»."""
    s = max(0, int(ms or 0) // 1000)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    partes = []
    if h:
        partes.append(f"{h} hora" + ("s" if h != 1 else ""))
    if h or m:
        partes.append(f"{m} minuto" + ("s" if m != 1 else ""))
    partes.append(f"{sec} segundo" + ("s" if sec != 1 else ""))
    return " ".join(partes)


# ── Atajos en pantalla completa ───────────────────────────────────────────────
# Traducción de los atajos de config («ctrl+p», «ctrl+left», «f5»…) a lo que
# entrega wx.EVT_CHAR_HOOK: (modificadores, keycode).

_TECLAS_WX = {
    "left": wx.WXK_LEFT, "right": wx.WXK_RIGHT, "up": wx.WXK_UP,
    "down": wx.WXK_DOWN, "enter": wx.WXK_RETURN, "space": wx.WXK_SPACE,
}
_RE_FKEY_WX = re.compile(r"^f(1[0-2]|[1-9])$")


def _combo_wx(texto: str) -> tuple[int, int] | None:
    """«ctrl+p» → (wx.MOD_CONTROL, ord('P')). None si no se puede traducir."""
    partes = (texto or "").lower().split("+")
    if not partes or not partes[-1]:
        return None
    mods = 0
    for p in partes[:-1]:
        m = {"ctrl": wx.MOD_CONTROL, "alt": wx.MOD_ALT, "shift": wx.MOD_SHIFT}.get(p)
        if m is None:
            return None
        mods |= m
    tecla = partes[-1]
    if tecla in _TECLAS_WX:
        return (mods, _TECLAS_WX[tecla])
    if _RE_FKEY_WX.match(tecla):
        return (mods, wx.WXK_F1 + int(tecla[1:]) - 1)
    if len(tecla) == 1:
        return (mods, ord(tecla.upper()))
    return None


class _PosAccesible(wx.Accessible):
    """Hace que NVDA lea la posición como tiempo hablado, no el número crudo."""

    def __init__(self, panel):
        super().__init__()
        self._panel = panel

    def GetName(self, childId):
        return (wx.ACC_OK, "Posición de reproducción")

    def GetValue(self, childId):
        p = self._panel
        if p._dur_ms > 0:
            return (wx.ACC_OK, f"{_fmt_hablado(p._pos_ms)} de {_fmt_hablado(p._dur_ms)}")
        return (wx.ACC_OK, "En directo")   # un live no tiene duración que anunciar


class _PantallaCompleta(wx.Frame):
    """Ventana sin bordes a pantalla completa para el vídeo.

    Antes solo atendía Escape/F11 y era una trampa de teclado: los atajos
    Ctrl+… son aceleradores del menú de la ventana PRINCIPAL y aquí no llegan,
    así que no había ni pausa ni volumen. Ahora la ventana atiende:
      - los atajos del reproductor configurados en Preferencias (Ctrl+…), y
      - las teclas convencionales de los reproductores de vídeo (VLC/YouTube):
        espacio pausa, flechas buscan y ajustan volumen, M silencia,
        F alterna pantalla completa y 0-9 salta al porcentaje.
    """

    def __init__(self, panel):
        # Título = el de la ventana principal (el del vídeo, p. ej. «… — YTChat
        # TTS»), no un genérico «Reproductor»: es lo que anuncia el lector y lo
        # que sale en Alt+Tab al entrar a pantalla completa.
        try:
            principal = wx.GetApp().GetTopWindow()
            titulo = (principal.GetTitle() if principal else "") or _cfg.APP_NAME
        except Exception:
            titulo = _cfg.APP_NAME
        super().__init__(None, title=titulo, name="PantallaCompleta")
        self._panel = panel
        self._atajos = panel._mapa_atajos_fs()
        self.SetBackgroundColour(wx.BLACK)
        self.video = wx.Window(self, name="VideoPantallaCompleta")
        self.video.SetBackgroundColour(wx.BLACK)
        nombre_accesible(
            self.video,
            "Vídeo a pantalla completa. Espacio pausa, flechas buscan y ajustan "
            "volumen, Escape sale.")
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.video.Bind(wx.EVT_LEFT_DCLICK,
                        lambda e: self._panel.alternar_pantalla_completa())
        self.ShowFullScreen(True)
        # Foco a la superficie de vídeo: así EVT_CHAR_HOOK recibe el teclado y
        # el lector de pantalla queda sobre un control con nombre accesible.
        self.video.SetFocus()

    def _on_key(self, event):
        p = self._panel
        k = event.GetKeyCode()
        mods = event.GetModifiers()
        if k in (wx.WXK_ESCAPE, wx.WXK_F11):
            p.alternar_pantalla_completa()
            return
        accion = self._atajos.get((mods, k))
        if accion is not None:
            accion()
            return
        if mods == wx.MOD_NONE:
            if k in (wx.WXK_SPACE, wx.WXK_MEDIA_PLAY_PAUSE):
                p._toggle_play(); return
            if k == wx.WXK_LEFT:
                p._buscar_rel(-10_000); return
            if k == wx.WXK_RIGHT:
                p._buscar_rel(+10_000); return
            if k == wx.WXK_UP:
                p._vol_flecha(+5); return
            if k == wx.WXK_DOWN:
                p._vol_flecha(-5); return
            if k == ord("M"):
                p._toggle_mute(); return
            if k == ord("F"):
                p.alternar_pantalla_completa(); return
            if ord("0") <= k <= ord("9"):
                p._buscar_porcentaje((k - ord("0")) * 10); return
            if wx.WXK_NUMPAD0 <= k <= wx.WXK_NUMPAD9:
                p._buscar_porcentaje((k - wx.WXK_NUMPAD0) * 10); return
        event.Skip()

    def _on_close(self, event):
        # Alt+F4: salir por el mismo camino que Escape/F11. Si se destruyera sin
        # avisar, el panel seguiría apuntando aquí y el vídeo quedaría dibujando
        # en una ventana muerta (y el siguiente toggle petaría).
        self._panel.alternar_pantalla_completa()


class ReproductorPanel(wx.Panel):
    """Reproductor siempre visible (no es una pestaña): imagen + controles."""

    def __init__(self, parent, config):
        super().__init__(parent, name="PanelReproductor")
        self._config = config
        self._video_id = ""
        # URL de flujo directa (HLS de TikTok): reproduce sin pasar por yt-dlp.
        # Excluyente con _video_id: solo una de las dos fuentes está activa.
        self._url_flujo = ""
        self._cargando = False
        # «Generación» de carga: cada stop/desconexión la incrementa, así una
        # carga de yt-dlp que quedó en vuelo se descarta al volver (si no, al
        # desconectar mientras cargaba, rearrancaba la reproducción sola).
        self._gen = 0
        self._listo = disponible()
        self._pos_ms = 0
        self._dur_ms = 0
        self._estado_busqueda = EstadoBusqueda(confirmada=0)
        self._estado_inicio = EstadoInicioReproduccion()
        self._tiene_esclavo = False
        self._usando_cache_local = False
        self._transporte_pendiente = False
        self._orden_transporte = None
        self._intencion_reproducir = False
        self._vol = 80
        self._muted = False
        # Botones de control ocultables (opción minimalista). El estado se guarda
        # en config; la ventana sincroniza el menú y persiste vía on_botones_toggle.
        # El fallback coincide con config_predeterminada (true): un config sin
        # la clave no debe esconder los botones.
        self._botones_visibles = bool(config.get("mostrar_botones_reproductor", True))
        self.on_botones_toggle = None
        self._calidad_sel = None
        self._alturas = []
        self._inst = None
        self._inst_lock = threading.Lock()  # crear la instancia VLC sin carreras
        self._player = None
        self._gestor_eventos_vlc = None
        self._info = None
        self._audio_local = None
        self._tarea_cache_video = None
        self._marca_reproduccion = None
        self._marca_extraccion = None
        self._marca_url = None
        self._inicio_progreso = None
        self._ultimo_aviso_progreso = None
        self._fs = None        # ventana de pantalla completa, si está activa
        self._precalentamiento_cancelado = False
        self._ciclo = reproductor_ciclo.CicloReproductor()
        # Relevo de ffmpeg para directos con vídeo y audio separados (ver
        # relevo_ffmpeg.py): evita el input-slave de VLC, que pierde la
        # sincronía entre dos HLS independientemente en vivo cada 60-90 s.
        self._relevo_ffmpeg = None
        self._relevo_gen = 0
        # Recargas automáticas seguidas tras interrumpirse un directo por
        # relevo (ver _directo_interrumpido). Se reinicia al cambiar de vídeo.
        self._recargas_directo = 0

        self.SetBackgroundColour(_T.bg)
        self.SetForegroundColour(_T.text)
        if self._listo:
            self._build_ui()
        else:
            self._build_aviso()

    # ── Instancia perezosa de VLC ─────────────────────────────────────────────

    def _asegurar_instancia(self) -> bool:
        """Crea (o reutiliza) la instancia de libVLC. Es la parte LENTA: importar
        libvlc.dll y escanear todos los plugins. Depende mucho de la máquina y
        la caché de plugins: en tres arranques en frío midió 56, 92 y 128 s.
        Va con lock para poder precalentarla en segundo plano sin chocar con el hilo de la
        GUI si el usuario conecta justo en ese momento."""
        if self._inst is not None:
            return True
        if not self._listo or not _cargar_vlc():
            return False
        with self._inst_lock:
            if self._inst is None:
                inicio = time.monotonic()
                try:
                    self._inst = _vlc.Instance(*_VLC_ARGS)
                except Exception as exc:
                    _registrar_tiempo_precalentamiento(
                        "crear_instancia", inicio, time.monotonic())
                    logger.warning("No se pudo crear la instancia de VLC: %s", exc)
                    return False
                _registrar_tiempo_precalentamiento(
                    "crear_instancia", inicio, time.monotonic())
        return self._inst is not None

    def _precalentar(self) -> None:
        """Crea la instancia de libVLC después de mostrar la ventana."""
        if self._precalentamiento_cancelado:
            return
        def _run():
            try:
                listo = self._asegurar_instancia()
            except Exception as exc:
                logger.debug("precalentar VLC: %s", exc)
                return
            if listo:
                wx.CallAfter(self._anunciar_precalentamiento_listo)
        anunciar("Preparando el reproductor")
        diagnostico.crear_hilo(_run, "ReproductorWarmup").start()

    def _anunciar_precalentamiento_listo(self) -> None:
        if not self._precalentamiento_cancelado:
            anunciar("Reproductor listo")

    def _asegurar_player(self) -> bool:
        # La instancia (lenta) puede venir ya precalentada; el reproductor y el
        # set_hwnd son rápidos y deben crearse aquí, en el hilo de la GUI.
        if getattr(self, "_ciclo", None) is not None and self._ciclo.en_retirada:
            return False
        if self._player is not None:
            return True
        if not self._asegurar_instancia():
            return False
        try:
            self._player = self._inst.media_player_new()
            self._fijar_salida(self._video.GetHandle())
        except Exception as exc:
            logger.warning("No se pudo crear el reproductor de VLC: %s", exc)
            return False
        logger.debug("PLAYER_NUEVO")
        self._enganchar_eventos_vlc()
        return True

    def _mostrar_estado_cerrando(self, debe_anunciar: bool) -> None:
        try:
            if hasattr(self, "lbl_estado"):
                self._fijar_estado("Cerrando la reproducción anterior.")
        except Exception:
            pass
        if debe_anunciar:
            try:
                anunciar("Cerrando la reproducción anterior")
            except Exception:
                pass

    def _al_retirar(self, rid: int) -> None:
        ciclo = getattr(self, "_ciclo", None)
        if ciclo is None:
            return
        if not ciclo.finalizar_retirada(rid):
            return
        pendiente = ciclo.tomar_pendiente()
        if pendiente is None:
            return
        if pendiente.tipo == "video":
            self.set_video(pendiente.valor, autoplay=pendiente.autoplay)
        elif pendiente.tipo == "flujo":
            self.set_flujo(pendiente.valor, autoplay=pendiente.autoplay)

    def _enganchar_eventos_vlc(self) -> None:
        detallado = _registro_detallado_activo()
        pct_anterior = None
        player_origen = self._player

        def al_buffer(event):
            nonlocal pct_anterior
            try:
                pct = event.u.media_player_buffering.new_cache
                aviso = aviso_de_corte(pct, pct_anterior)
                pct_anterior = pct
                if aviso:
                    logger.debug("%s", aviso)
            except Exception:
                pass

        def al_estado_traza(nombre):
            def callback(_event):
                try:
                    logger.debug("VLC_ESTADO %s", nombre)
                except Exception:
                    pass
            return callback

        def al_transporte(estado_norm, nombre_traza):
            ident = player_origen

            def callback(_event):
                if detallado:
                    try:
                        logger.debug("VLC_ESTADO %s", nombre_traza)
                    except Exception:
                        pass
                try:
                    wx.CallAfter(self._evaluar_transporte_desde_evento, ident, estado_norm)
                except Exception:
                    pass

            return callback

        if _vlc is None or not hasattr(_vlc, "EventType"):
            self._callbacks_vlc = ()
            try:
                self._gestor_eventos_vlc = self._player.event_manager() if self._player is not None else None
            except Exception:
                self._gestor_eventos_vlc = None
            return
        callbacks = []
        callbacks.append((_vlc.EventType.MediaPlayerPlaying, al_transporte("playing", "reproduciendo")))
        callbacks.append((_vlc.EventType.MediaPlayerPaused, al_transporte("paused", "pausado")))
        if detallado:
            callbacks.extend([
                (_vlc.EventType.MediaPlayerStopped, al_estado_traza("detenido")),
                (_vlc.EventType.MediaPlayerEndReached, al_estado_traza("fin")),
                (_vlc.EventType.MediaPlayerEncounteredError, al_estado_traza("error")),
                (_vlc.EventType.MediaPlayerBuffering, al_buffer),
            ])
        self._callbacks_vlc = tuple(callbacks)
        try:
            self._gestor_eventos_vlc = self._player.event_manager()
            for tipo, callback in callbacks:
                self._gestor_eventos_vlc.event_attach(tipo, callback)
        except Exception as exc:
            logger.debug("No se pudieron enganchar los eventos de VLC: %s", exc)

    def _evaluar_transporte_desde_evento(self, player_origen, estado_evento) -> None:
        try:
            if player_origen is not self._player:
                return
        except Exception:
            return
        self._evaluar_transporte(estado_forzado=estado_evento)

    def _cancelar_transporte(self) -> None:
        self._orden_transporte = None
        self._transporte_pendiente = False

    def _evaluar_transporte(self, estado_forzado=None) -> None:
        orden = getattr(self, "_orden_transporte", None)
        if orden is None:
            return
        estado = estado_forzado if estado_forzado is not None else self._estado_vlc_actual()
        estado_norm = (estado or "").lower()
        ahora = time.monotonic()
        desenlace = evaluar_transporte(orden, estado_norm, ahora)
        if desenlace == "pendiente":
            return
        # finaliza la transacción
        intencion_previa = bool(orden.intencion_reproducir)
        edad_ms = int((ahora - float(orden.instante)) * 1000) if orden.instante is not None else 0
        self._cancelar_transporte()
        if desenlace == "confirmada":
            if not intencion_previa:
                # pausa confirmada
                self._intencion_reproducir = False
                try:
                    self._mostrar_pausa(False)
                except Exception:
                    pass
                try:
                    if not getattr(self._estado_busqueda, "pendiente", False):
                        self._timer.Stop()
                except Exception:
                    pass
                anunciar("Pausa")
                logger.debug("TRANSPORTE desenlace=confirmada intencion=pausa estado=%s edad=%d", estado_norm, edad_ms)
            else:
                # reanudación confirmada
                self._intencion_reproducir = True
                try:
                    self._mostrar_pausa(True)
                except Exception:
                    pass
                try:
                    self._timer.Start(500)
                except Exception:
                    pass
                anunciar("Reproduciendo")
                logger.debug("TRANSPORTE desenlace=confirmada intencion=reproducir estado=%s edad=%d", estado_norm, edad_ms)
        else:
            # fallida por plazo o estado final
            # reconciliar con estado real
            estado_real = self._estado_vlc_actual()
            estado_real_norm = (estado_real or "").lower()
            if estado_real_norm == "playing":
                self._intencion_reproducir = True
                try:
                    self._mostrar_pausa(True)
                except Exception:
                    pass
                try:
                    self._timer.Start(500)
                except Exception:
                    pass
            elif estado_real_norm == "paused":
                self._intencion_reproducir = False
                try:
                    self._mostrar_pausa(False)
                except Exception:
                    pass
                try:
                    if not getattr(self._estado_busqueda, "pendiente", False):
                        self._timer.Stop()
                    else:
                        self._timer.Start(500)
                except Exception:
                    pass
            else:
                # estado transitorio o final: mantener botón según estado real si es determinable
                if estado_real_norm == "paused":
                    self._intencion_reproducir = False
                elif estado_real_norm == "playing":
                    self._intencion_reproducir = True
                # si hay búsqueda pendiente, mantener temporizador
                try:
                    if getattr(self._estado_busqueda, "pendiente", False):
                        self._timer.Start(500)
                except Exception:
                    pass
            mensaje = "No se pudo pausar" if not intencion_previa else "No se pudo reanudar"
            anunciar(mensaje)
            logger.debug("TRANSPORTE desenlace=fallida intencion=%s estado=%s edad=%d", "pausa" if not intencion_previa else "reproducir", estado_norm, edad_ms)

    def _fijar_salida(self, hwnd):
        try:
            self._player.set_hwnd(int(hwnd))
        except Exception as exc:
            logger.debug("set_hwnd: %s", exc)

    def _topologia_actual(self) -> str:
        return topologia_medio(
            es_local=bool(getattr(self, "_usando_cache_local", False)),
            tiene_esclavo=bool(getattr(self, "_tiene_esclavo", False)),
            es_flujo=bool(getattr(self, "_url_flujo", "")),
            usa_relevo=bool(getattr(self, "_relevo_ffmpeg", None)),
        )

    def _estado_vlc_actual(self) -> str:
        try:
            st = self._player.get_state() if self._player is not None else None
            nombre = getattr(st, "name", str(st))
            return nombre.rsplit(".", 1)[-1].lower() if nombre else "desconocido"
        except Exception:
            return "desconocido"

    def _es_directo_actual(self) -> bool:
        if getattr(self, "_url_flujo", ""):
            return True
        info = getattr(self, "_info", None)
        if isinstance(info, dict):
            return bool(info.get("is_live"))
        return False

    def _busqueda_permitida_actual(self) -> bool:
        return busqueda_permitida(
            self._es_directo_actual(),
            bool(getattr(self, "_usando_cache_local", False)),
            bool(getattr(self, "_tiene_esclavo", False)),
            usa_relevo=bool(getattr(self, "_relevo_ffmpeg", None)),
        )

    def _cancelar_busqueda(self, motivo: str = "cancelado") -> None:
        bus = getattr(self, "_estado_busqueda", None)
        if bus is None or not bus.pendiente:
            return
        topologia = self._topologia_actual()
        estado = self._estado_vlc_actual()
        confirmada = bus.confirmada
        destino = bus.destino
        try:
            muestra = self._player.get_time() if self._player is not None else -1
        except Exception:
            muestra = -1
        edad = bus.edad_ms(time.monotonic()) if bus.marca_destino is not None else 0
        logger.debug("%s", traza_busqueda_desenlace(
            topologia, estado, confirmada, destino, muestra, edad, motivo))
        bus.cancelar()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_aviso(self):
        box = wx.StaticBoxSizer(wx.HORIZONTAL, self, "Reproductor")
        caja = box.GetStaticBox()
        if not vlc_disponible():
            txt = ("Reproductor no disponible: falta VLC. Instala VLC "
                   "(videolan.org) y la librería python-vlc.")
        else:
            txt = "Reproductor no disponible: falta yt-dlp (pip install yt-dlp)."
        lbl = wx.StaticText(caja, label=txt, name="AvisoReproductor")
        lbl.SetForegroundColour(_T.dim)
        box.Add(lbl, 1, wx.ALL, 8)
        self.SetSizer(box)

    def _build_ui(self):
        box = wx.StaticBoxSizer(wx.VERTICAL, self, "Reproductor")
        caja = box.GetStaticBox()

        # Superficie de vídeo (VLC dibuja aquí vía set_hwnd). Es una ventana
        # genérica: sin nombre accesible reforzado, el lector no dice nada útil
        # al llegar aquí (p. ej. con doble clic para pantalla completa).
        self._video = wx.Window(caja, size=(-1, 160), name="Vídeo")
        self._video.SetMinSize((-1, 160))  # piso: que no lo aplaste el chat
        self._video.SetBackgroundColour(wx.BLACK)
        nombre_accesible(self._video, "Vídeo. Doble clic para pantalla completa.")
        box.Add(self._video, 1, wx.EXPAND | wx.ALL, 6)

        # Fila 1: transporte con iconos (nombre accesible + tooltip).
        self._ic_play  = iconos.icono("play", _T.text, _T.btn)
        self._ic_pause = iconos.icono("pause", _T.text, _T.btn)
        self._ic_mute  = iconos.icono("mute", _T.text, _T.btn)
        self._ic_sound = iconos.icono("sound", _T.text, _T.btn)
        # Sin mnemónicos «&» en estos botones: chocaban entre sí (dos con la misma
        # letra) y el lector los leía como «alt+letra». El control va por los
        # atajos Ctrl+… y por Tab+Espacio.
        self._fila_botones = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_play  = self._btn_icono(self._ic_play, "Reproducir", "Reproducir o pausa")
        self.btn_retro = self._btn_icono(iconos.icono("retro", _T.text, _T.btn),
                                         "Retroceder 1 min", "Retroceder 1 minuto")
        self.btn_avanz = self._btn_icono(iconos.icono("avanz", _T.text, _T.btn),
                                         "Avanzar 1 min", "Avanzar 1 minuto")
        self.btn_stop  = self._btn_icono(iconos.icono("stop", _T.text, _T.btn),
                                         "Detener", "Detener")
        self.btn_mute  = self._btn_icono(self._ic_sound, "Silenciar audio",
                                         "Silenciar o activar audio")
        self.btn_fs    = self._btn_icono(iconos.icono("fullscreen", _T.text, _T.btn),
                                         "Pantalla completa", "Pantalla completa")
        for b in (self.btn_play, self.btn_retro, self.btn_avanz, self.btn_stop,
                  self.btn_mute, self.btn_fs):
            self._fila_botones.Add(b, 0, wx.RIGHT, 6)
        box.Add(self._fila_botones, 0, wx.ALL, 6)

        # Fila 2: posición + tiempo. La calidad va en el menú Reproductor.
        row = wx.BoxSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(self, label="Posición:", name="EtiquetaPosicion")
        lbl.SetForegroundColour(_T.dim)
        row.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.sld_pos = wx.Slider(self, value=0, minValue=0, maxValue=1000,
                                 name="Posición de reproducción")
        _tc(self.sld_pos, bg=_T.surface)
        self.sld_pos.SetToolTip("Flecha derecha avanza 10 s, flecha izquierda retrocede 10 s.")
        self.sld_pos.SetAccessible(_PosAccesible(self))
        row.Add(self.sld_pos, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.lbl_tiempo = wx.StaticText(self, label="0:00 / 0:00", name="Tiempo")
        self.lbl_tiempo.SetForegroundColour(_T.text)
        row.Add(self.lbl_tiempo, 0, wx.ALIGN_CENTER_VERTICAL)
        box.Add(row, 0, wx.EXPAND | wx.ALL, 6)

        # Fila 3: volumen + estado.
        row = wx.BoxSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(self, label="Volumen:", name="EtiquetaVolumenReproductor")
        lbl.SetForegroundColour(_T.dim)
        row.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.sld_vol = wx.Slider(self, value=self._vol, minValue=0, maxValue=100,
                                 name="Volumen del reproductor")
        _tc(self.sld_vol, bg=_T.surface)
        self.sld_vol.SetLineSize(1)
        self.sld_vol.SetToolTip("Flecha arriba sube, flecha abajo baja el volumen de 1 en 1.")
        self.sld_vol.SetMinSize((160, -1))
        # Los deslizadores son justo el caso donde SetName no basta en Windows.
        nombre_accesible(self.sld_vol, "Volumen del reproductor")
        row.Add(self.sld_vol, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        self.lbl_estado = wx.StaticText(self, label="Sin reproducir.", name="EstadoReproductor")
        self._texto_estado = "Sin reproducir."
        self.lbl_estado.SetForegroundColour(_T.accent)
        row.Add(self.lbl_estado, 1, wx.ALIGN_CENTER_VERTICAL)
        box.Add(row, 0, wx.EXPAND | wx.ALL, 6)

        # Fila 4: interruptor para mostrar/ocultar los botones de control. Va el
        # último para no estorbar el recorrido de Tab de los controles de uso;
        # queda siempre visible aunque la fila de botones esté oculta.
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_toggle_botones = wx.Button(self, name="AlternarBotonesReproductor",
                                            label=self._etiqueta_toggle())
        self.btn_toggle_botones.SetBackgroundColour(_T.btn)
        self.btn_toggle_botones.SetForegroundColour(_T.btn_t)
        self.btn_toggle_botones.SetToolTip(
            "Muestra u oculta los botones de control del reproductor. También en "
            "el menú Reproductor. Los atajos funcionan estén o no visibles.")
        row.Add(self.btn_toggle_botones, 0)
        box.Add(row, 0, wx.ALL, 6)

        self.SetSizer(box)

        self.btn_play.Bind(wx.EVT_BUTTON, lambda e: self._toggle_play())
        self.btn_retro.Bind(wx.EVT_BUTTON, lambda e: self._buscar_rel(-60_000))
        self.btn_avanz.Bind(wx.EVT_BUTTON, lambda e: self._buscar_rel(+60_000))
        self.btn_stop.Bind(wx.EVT_BUTTON, lambda e: self._detener())
        self.btn_mute.Bind(wx.EVT_BUTTON, lambda e: self._toggle_mute())
        self.btn_fs.Bind(wx.EVT_BUTTON, lambda e: self.alternar_pantalla_completa())
        self.sld_pos.Bind(wx.EVT_SLIDER, self._on_sld_pos)
        self.sld_pos.Bind(wx.EVT_KEY_DOWN, self._on_pos_key)
        self.sld_vol.Bind(wx.EVT_SLIDER, self._on_sld_vol)
        self.sld_vol.Bind(wx.EVT_KEY_DOWN, self._on_vol_key)
        self._video.Bind(wx.EVT_LEFT_DCLICK, lambda e: self.alternar_pantalla_completa())
        self.btn_toggle_botones.Bind(wx.EVT_BUTTON, lambda e: self.alternar_botones())
        self.Bind(wx.EVT_SIZE, self._on_resize)

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_timer, self._timer)
        self._timer_progreso = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_timer_progreso, self._timer_progreso)

        # Aplicar el estado guardado (por defecto, botones visibles; el usuario
        # los oculta desde el interruptor, el menú o Preferencias).
        self._aplicar_visibilidad_botones()

    def _on_resize(self, event):
        event.Skip()
        self._ajustar_ancho_estado()

    def _ajustar_ancho_estado(self) -> None:
        """Reajusta el salto de línea de lbl_estado al ancho disponible: sin
        esto, un aviso largo (p. ej. el de espera al cargar) se salía de la
        ventana en vez de bajar de línea."""
        if not hasattr(self, "lbl_estado"):
            return
        try:
            ancho = max(150, self.GetClientSize().Width - 40)
            # Wrap() mete saltos de línea literales en la etiqueta y solo
            # estrecha, nunca ensancha: al agrandar la ventana el texto seguía
            # partido. Se parte siempre desde el texto original.
            texto = getattr(self, "_texto_estado", None)
            if texto is None:
                texto = self.lbl_estado.GetLabel()
            self.lbl_estado.SetLabel(texto)
            self.lbl_estado.Wrap(ancho)
        except Exception:
            pass

    def _fijar_estado(self, texto: str) -> None:
        self._texto_estado = texto
        self.lbl_estado.SetLabel(texto)
        self._ajustar_ancho_estado()

    def _btn_icono(self, bmp, etiqueta, tooltip):
        # Icono + TEXTO: el texto es el nombre accesible que lee el lector (un
        # botón solo-icono lo leería como «botón»). El icono da el aire moderno.
        b = wx.Button(self, label=etiqueta, name=etiqueta.replace("&", ""))
        b.SetBackgroundColour(_T.btn)
        b.SetForegroundColour(_T.btn_t)
        b.SetBitmap(bmp)
        b.SetBitmapMargins((4, 0))
        b.SetToolTip(tooltip)
        return b

    # ── Atajos para la ventana de pantalla completa ───────────────────────────

    def _mapa_atajos_fs(self) -> dict:
        """(modificadores, keycode) → acción, para los atajos del reproductor
        configurados por el usuario. La ventana de pantalla completa lo usa
        para que Ctrl+P, Ctrl+flechas, etc. sigan funcionando allí (donde los
        aceleradores del menú de la ventana principal no llegan)."""
        acciones = {
            "rep_play":      self._toggle_play,
            "rep_retro":     lambda: self._buscar_rel(-60_000),
            "rep_avanz":     lambda: self._buscar_rel(+60_000),
            "rep_detener":   self._detener,
            "rep_mute":      self._toggle_mute,
            "rep_vol_menos": lambda: self.ajustar_volumen(-20),
            "rep_vol_mas":   lambda: self.ajustar_volumen(+20),
        }
        atajos = _cfg.parsear_atajos(self._config.get("atajos_raw", {}))
        mapa = {}
        for accion, fn in acciones.items():
            at = atajos.get(accion)
            if at:
                combo = _combo_wx(at.texto)
                if combo:
                    mapa[combo] = fn
        return mapa

    # ── API pública (la ventana la llama al conectar) ─────────────────────────

    def anclar_foco(self) -> None:
        # Llevar el foco a algo útil: si los botones están visibles, a Reproducir;
        # si no, al deslizador de Posición (primer control navegable del panel).
        try:
            if self._listo:
                destino = self.btn_play if self._botones_visibles else self.sld_pos
                destino.SetFocus()
        except Exception:
            pass

    # ── Botones ocultables (interruptor / menú) ───────────────────────────────

    def _etiqueta_toggle(self) -> str:
        return ("Ocultar botones del reproductor" if self._botones_visibles
                else "Mostrar botones del reproductor")

    def botones_visibles(self) -> bool:
        return self._botones_visibles

    def _aplicar_visibilidad_botones(self) -> None:
        """Muestra u oculta la fila de botones y reajusta el layout. Ocultos,
        salen además del recorrido de Tab (wx omite las ventanas no visibles)."""
        sizer = self.GetSizer()
        if sizer is None or not hasattr(self, "_fila_botones"):
            return
        sizer.Show(self._fila_botones, self._botones_visibles, recursive=True)
        self.btn_toggle_botones.SetLabel(self._etiqueta_toggle())
        self.Layout()

    def set_botones_visibles(self, visibles: bool) -> None:
        """Fija la visibilidad y avisa a la ventana (para el menú y persistir)."""
        self._botones_visibles = bool(visibles)
        self._aplicar_visibilidad_botones()
        if self.on_botones_toggle:
            try:    self.on_botones_toggle(self._botones_visibles)
            except Exception: pass

    def alternar_botones(self) -> None:
        self.set_botones_visibles(not self._botones_visibles)
        anunciar("Botones del reproductor visibles" if self._botones_visibles
                 else "Botones del reproductor ocultos")

    def set_video(self, video_id: str, autoplay: bool = True) -> None:
        self._video_id = video_id or ""
        self._url_flujo = ""
        if not self._listo:
            return
        ciclo = getattr(self, "_ciclo", None)
        if ciclo is not None and ciclo.en_retirada:
            debe = ciclo.diferir_video(video_id or "", autoplay)
            self._mostrar_estado_cerrando(debe)
            return
        self._detener(silencioso=True)
        self._info = None
        self._calidad_sel = None
        self._alturas = []
        self._recargas_directo = 0
        if self._video_id and autoplay:
            self.cargar(reproducir=True)
        else:
            self._fijar_estado("Listo. Pulsa Reproducir.")

    def set_flujo(self, url: str, autoplay: bool = True) -> None:
        """Reproduce una URL de flujo directa (el HLS de un directo de TikTok).
        Sin yt-dlp ni calidades: la URL ya viene resuelta por quien conecta."""
        self._video_id = ""
        self._url_flujo = (url or "").strip()
        if not self._listo:
            return
        ciclo = getattr(self, "_ciclo", None)
        if ciclo is not None and ciclo.en_retirada:
            debe = ciclo.diferir_flujo(url or "", autoplay)
            self._mostrar_estado_cerrando(debe)
            return
        self._detener(silencioso=True)
        self._info = None
        self._calidad_sel = None
        self._alturas = []
        if self._url_flujo and autoplay:
            self._reproducir_flujo()
        elif self._url_flujo:
            self._fijar_estado("Listo. Pulsa Reproducir.")
        else:
            self._fijar_estado("Este directo no trae vídeo reproducible.")

    def detener_todo(self) -> None:
        self._precalentamiento_cancelado = True
        # Olvidar el vídeo actual: al desconectar el reproductor queda en blanco,
        # como recién abierta la app (sin un id viejo que pudiera relanzarse).
        self._video_id = ""
        self._url_flujo = ""
        if self._listo:
            if self._fs:
                self.alternar_pantalla_completa()
            ciclo = getattr(self, "_ciclo", None)
            if ciclo is not None and ciclo.en_retirada:
                ciclo.cancelar_pendiente()
            # Parada en segundo plano: stop() de un flujo en vivo puede tardar
            # varios segundos y, al llamarse desde el hilo de la GUI (desconexión),
            # congelaba la ventana hasta que terminaba.
            self._detener(silencioso=True, en_segundo_plano=True)

    # ── Getters para el gestor de descargas (gui_descargas) ──────────────────
    # NO acoplan con `descargas.py`: este módulo sigue con sus llamadas yt-dlp
    # propias, y el gestor usa estos getters solo para decidir QUÉ descargar
    # (URL actual + si es YouTube no-live). El _info_listo es asíncrono, así
    # que `get_es_live` se evalúa contra el último `_info` cacheado o devuelve
    # False si aún no se cargó.

    def get_url_para_descarga(self) -> str | None:
        """URL o id de YouTube del vídeo actual. None si no hay o es flujo de
        TikTok (que se gatingea en gui.py)."""
        if self._video_id:
            return "https://www.youtube.com/watch?v=" + self._video_id
        return None

    def get_plataforma(self) -> str:
        """Plataforma del vídeo en reproducción: 'youtube' (el panel es siempre
        YouTube; TikTok usa set_flujo y se gatingea en gui.py)."""
        return "youtube"

    def get_es_live(self) -> bool:
        """¿El vídeo actual es un directo en curso? True si yt-dlp ya lo
        clasificó como live. False si aún no se cargó, si es VOD/programado,
        o si la reproducción viene de un flujo HLS de TikTok."""
        if self._info is None:
            return False
        try:    return bool(self._info.get("is_live"))
        except Exception: return False

    # ── Carga / reproducción ──────────────────────────────────────────────────

    def cargar(self, reproducir: bool = True):
        ciclo = getattr(self, "_ciclo", None)
        if ciclo is not None and ciclo.en_retirada:
            debe = ciclo.diferir_video(self._video_id or "", reproducir)
            self._mostrar_estado_cerrando(debe)
            return
        if not self._listo or not self._asegurar_player():
            anunciar("El reproductor no está disponible.")
            return
        if not self._video_id:
            return
        if self._cargando:
            anunciar("Cargando vídeo")
            return
        logger.debug("CARGA video=%s reproducir=%s", self._video_id,
                     "si" if reproducir else "no")
        self._cancelar_busqueda()
        if hasattr(self, "_estado_inicio"):
            self._estado_inicio.cancelar()
        self._estado_busqueda = EstadoBusqueda(confirmada=0)
        self._tiene_esclavo = False
        self._usando_cache_local = False
        self._cancelar_transporte()
        self._intencion_reproducir = reproducir
        self._cargando = True
        self._fijar_estado("Cargando vídeo…")
        anunciar("Cargando vídeo")
        vid = self._video_id
        gen = self._gen   # si cambia al volver, esta carga ya no vale
        marca_inicio = time.monotonic()
        self._marca_reproduccion = marca_inicio
        self._inicio_progreso = marca_inicio
        self._ultimo_aviso_progreso = None
        self._timer_progreso.Start(250)

        def _run():
            try:
                info = _info_video(vid)
                marca_extraccion = time.monotonic()
            except Exception as exc:
                logger.warning("info vídeo: %s", exc)
                wx.CallAfter(self._error_carga, gen)
                return
            audio_local = _preparar_audio_local(info, vid)
            wx.CallAfter(self._info_listo, info, reproducir, vid, gen,
                         marca_inicio, marca_extraccion, audio_local)

        diagnostico.crear_hilo(_run, "ReproductorInfo").start()

    def _info_listo(self, info, reproducir, vid, gen, marca_inicio=None,
                    marca_extraccion=None, audio_local=None):
        if gen != self._gen or vid != self._video_id:
            self._timer_progreso.Stop()
            return  # se detuvo/desconectó o cambió de vídeo mientras cargaba
        self._info = info
        self._audio_local = audio_local
        self._alturas = [a for a in _CALIDADES if a in _alturas_disponibles(info)]
        self._cargando = False
        self._timer_progreso.Stop()
        self._marca_reproduccion = marca_inicio
        self._marca_extraccion = marca_extraccion
        self._reproducir_calidad(self._calidad_sel, reproducir)
        if not info.get("is_live"):
            self._descargar_video_cache(vid, gen)

    def _podar_cache_video(self, carpeta):
        tope = int(self._config.get("cache_video_mb", 1024)) * 1024 * 1024
        entradas = tuple(
            (ruta, ruta.stat().st_size, ruta.stat().st_mtime)
            for ruta in carpeta.iterdir() if ruta.is_file())
        for ruta in esclavo_audio.sobrantes_por_tamanio(entradas, tope):
            try:
                ruta.unlink()
            except OSError:
                pass

    def _descargar_video_cache(self, video_id, gen):
        if int(getattr(self, "_config", {}).get("cache_video_mb", 1024)) <= 0:
            return
        carpeta = _cfg.app_dir() / "cache-video"
        destino = carpeta / f"{video_id}.mp4"
        vigente = getattr(self, "_tarea_cache_video", None)
        if vigente is not None:
            vigente.cancelacion.set()
        from tarea_cache_video import TareaCacheVideo
        tarea = TareaCacheVideo(video_id, gen, destino)
        self._tarea_cache_video = tarea

        def descargar():
            try:
                carpeta.mkdir(parents=True, exist_ok=True)
                self._podar_cache_video(carpeta)
                completa = ytdlp_bin.descargar_video_cache(
                    video_id, destino, cancel_event=tarea.cancelacion)
            except Exception as exc:
                logger.debug("caché de vídeo: %s", exc)
                completa = False
            wx.CallAfter(self._cache_video_lista, tarea, completa)

        diagnostico.crear_hilo(descargar, "ReproductorCacheVideo").start()

    def _cache_video_lista(self, tarea, completa):
        if getattr(self, "_tarea_cache_video", None) is not tarea:
            return
        self._tarea_cache_video = None
        if (not completa or tarea.generacion != self._gen
                or tarea.video_id != self._video_id
                or not tarea.destino.is_file()):
            return
        self._podar_cache_video(tarea.destino.parent)
        if not tarea.destino.is_file():
            return
        bus = getattr(self, "_estado_busqueda", None)
        if bus is None:
            bus = EstadoBusqueda(confirmada=0)
            self._estado_busqueda = bus
        posicion = bus.confirmada
        pausado = not self._intencion_reproducir
        try:
            media = self._inst.media_new(str(tarea.destino))
            for opcion in opciones_medio(False):
                media.add_option(opcion)
            self._player.set_media(media)
            self._player.audio_set_volume(self._vol)
            self._player.audio_set_mute(self._muted)
            self._usando_cache_local = True
            self._tiene_esclavo = False
            self._player.play()
            self._player.set_time(posicion)
            if pausado:
                self._player.set_pause(1)
            self._marcar_destino(posicion, anunciar_usuario=False)
            import sound_player as _snd
            _snd.reproducir("transporte_en_curso")
        except Exception as exc:
            logger.debug("cambio a caché de vídeo: %s", exc)

    def _detener_relevo_ffmpeg(self) -> None:
        relevo = getattr(self, "_relevo_ffmpeg", None)
        self._relevo_ffmpeg = None
        if relevo is not None:
            relevo.detener()

    def _reproducir_calidad(self, altura, reproducir):
        if self._info is None or not self._asegurar_player():
            return
        self._cancelar_busqueda()
        self._tiene_esclavo = False
        self._usando_cache_local = False
        self._detener_relevo_ffmpeg()
        es_directo = self._info.get("is_live")
        if altura is None or es_directo:
            # Auto / directo: el formato combinado que elija yt-dlp.
            url, slave = fuentes_para_directo(self._info)
            if not url:
                logger.warning(
                    "reproducir directo sin fuentes: url_superior=%s formats=%d "
                    "requested_formats=%d is_live=%s",
                    "sí" if self._info.get("url") else "no",
                    len(self._info.get("formats", []) or []),
                    len(self._info.get("requested_formats", []) or []), es_directo)
        else:
            url, prog = _video_para_altura(self._info, altura)
            slave = None if prog else _mejor_audio(self._info)
        if not url:
            self._error_carga()
            return

        if es_directo and slave:
            # Vídeo y audio en vivo por separado: en vez de darle las dos
            # fuentes a VLC como input-slave (pierde la sincronía entre
            # ambas cada 60-90 s, comprobado con un directo real), un
            # relevo de ffmpeg las remuxa antes en un único flujo. Arrancar
            # el proceso y esperar a que su listener esté arriba no debe
            # congelar la GUI, así que va en un hilo aparte.
            self._relevo_gen = getattr(self, "_relevo_gen", 0) + 1
            relevo_gen = self._relevo_gen
            gen = self._gen
            video_id_actual = self._video_id
            # Mientras el relevo se prepara la carga sigue en curso: sin esto,
            # pulsar Reproducir en ese segundo veía «sin medio», relanzaba
            # yt-dlp y mataba el relevo recién arrancado.
            self._cargando = True
            self._fijar_estado("Cargando vídeo…")

            def _preparar_relevo(video_url=url, audio_url=slave):
                relevo = relevo_ffmpeg.RelevoFfmpeg(video_url, audio_url)
                direccion = relevo.iniciar()
                # Esperar a que ffmpeg escuche de verdad (sondea el puerto),
                # no un tiempo fijo: VLC hace una única conexión y, si llega
                # antes que el listener, queda en «error» sin reintentar.
                if direccion and not relevo.esperar_listo():
                    relevo.detener()
                    direccion = None
                wx.CallAfter(self._relevo_listo, relevo, direccion, relevo_gen,
                            gen, video_id_actual, video_url, audio_url, reproducir)

            diagnostico.crear_hilo(_preparar_relevo, "ReproductorRelevo").start()
            return

        self._tiene_esclavo = bool(slave)
        self._continuar_reproducir_calidad(url, slave, es_directo, reproducir)

    def _relevo_listo(self, relevo, direccion, relevo_gen, gen, video_id_actual,
                      url, slave, reproducir) -> None:
        if relevo_gen != self._relevo_gen or gen != self._gen \
                or video_id_actual != self._video_id:
            relevo.detener()
            return
        self._cargando = False
        if direccion is not None and not relevo.activo():
            # ffmpeg murió entre el listener y este callback (403 de
            # googlevideo, playlist inválida): no darle a VLC una dirección
            # donde nadie escucha.
            relevo.detener()
            direccion = None
        if direccion is None:
            # No se pudo levantar el relevo (sin ffmpeg, puerto, etc.): se
            # sigue con input-slave directo, como antes de tener el relevo.
            self._relevo_ffmpeg = None
            self._tiene_esclavo = bool(slave)
            self._continuar_reproducir_calidad(url, slave, True, reproducir)
            return
        self._relevo_ffmpeg = relevo
        self._relevo_reintentos = 0
        self._tiene_esclavo = False
        self._continuar_reproducir_calidad(direccion, "", True, reproducir)

    def _continuar_reproducir_calidad(self, url, slave, es_directo, reproducir):
        try:
            media = self._inst.media_new(url)
            for opt in opciones_medio(es_directo):
                media.add_option(opt)
            if slave:
                if not es_directo:
                    slave = esclavo_audio.esclavo_a_usar(self._audio_local, slave)
                media.add_option(f":input-slave={slave}")
                # recalcular tras resolver esclavo local
                self._tiene_esclavo = bool(slave)
            self._player.set_media(media)
            self._marca_url = time.monotonic()
            self._player.audio_set_volume(self._vol)
            self._player.audio_set_mute(self._muted)
            if reproducir:
                self._player.play()
                self._mostrar_pausa(True)
                self._timer.Start(500)
        except Exception as exc:
            logger.warning("reproducir: %s", exc)
            if hasattr(self, "_estado_inicio"):
                self._estado_inicio.cancelar()
            self._detener_relevo_ffmpeg()
            self._error_carga()
            return
        self._pos_ms = self._dur_ms = 0
        if reproducir:
            if hasattr(self, "_estado_inicio"):
                self._estado_inicio.iniciar()
            self._fijar_estado("Cargando vídeo…")
        else:
            if hasattr(self, "_estado_inicio"):
                self._estado_inicio.cancelar()
            self._fijar_estado("Listo.")

    def _reproducir_flujo(self, reproducir: bool = True):
        """Arranca la URL de flujo directa en VLC (mismo camino final que
        _reproducir_calidad, pero sin pasar por la info de yt-dlp)."""
        ciclo = getattr(self, "_ciclo", None)
        if ciclo is not None and ciclo.en_retirada:
            debe = ciclo.diferir_flujo(self._url_flujo or "", reproducir)
            self._mostrar_estado_cerrando(debe)
            return
        if not self._url_flujo or not self._asegurar_player():
            anunciar("El reproductor no está disponible.")
            return
        self._cancelar_busqueda()
        self._tiene_esclavo = False
        self._usando_cache_local = False
        self._cancelar_transporte()
        self._intencion_reproducir = reproducir
        try:
            media = self._inst.media_new(self._url_flujo)
            for opt in opciones_medio(True):
                media.add_option(opt)
            self._player.set_media(media)
            self._marca_reproduccion = time.monotonic()
            self._marca_extraccion = self._marca_reproduccion
            self._marca_url = self._marca_reproduccion
            self._player.audio_set_volume(self._vol)
            self._player.audio_set_mute(self._muted)
            if reproducir:
                self._player.play()
                self._mostrar_pausa(True)
                self._timer.Start(500)
        except Exception as exc:
            logger.warning("reproducir flujo: %s", exc)
            if hasattr(self, "_estado_inicio"):
                self._estado_inicio.cancelar()
            self._error_carga()
            return
        self._pos_ms = self._dur_ms = 0
        if reproducir:
            if hasattr(self, "_estado_inicio"):
                self._estado_inicio.iniciar()
            self._fijar_estado("Cargando vídeo…")
        else:
            if hasattr(self, "_estado_inicio"):
                self._estado_inicio.cancelar()
            self._fijar_estado("Listo.")

    def set_calidad(self, altura):
        """altura=None → automática; si no hay info aún, se aplica al cargar."""
        self._calidad_sel = altura
        anunciar("Calidad automática" if altura is None else f"Calidad {altura}p")
        if self._info is not None:
            self._reproducir_calidad(altura, reproducir=True)

    def alturas_disponibles(self) -> list[int]:
        return list(self._alturas)

    def _error_carga(self, gen=None):
        if gen is not None and gen != self._gen:
            return  # error de una carga ya descartada (stop/desconexión)
        self._cargando = False
        if hasattr(self, "_estado_inicio"):
            self._estado_inicio.cancelar()
        self._detener_relevo_ffmpeg()
        self._timer_progreso.Stop()
        import sound_player as _snd
        _snd.reproducir("error")
        self._fijar_estado("No se pudo cargar el vídeo.")
        anunciar("No se pudo cargar el vídeo")

    def _on_timer_progreso(self, _event):
        if not self._cargando:
            self._timer_progreso.Stop()
            return
        segundos = time.monotonic() - self._inicio_progreso
        frase = progreso.aviso_de_espera(segundos, self._ultimo_aviso_progreso)
        if frase:
            self._ultimo_aviso_progreso = segundos
            self._fijar_estado(frase)
            # Se repite durante la carga y no debe cortar lo que se está oyendo.
            anunciar(frase, urgente=False)

    # ── Transporte ──────────────────────────────────────────────────────────────

    def _mostrar_pausa(self, reproduciendo: bool):
        """Pone icono + texto del botón play/pausa según el estado."""
        self.btn_play.SetBitmap(self._ic_pause if reproduciendo else self._ic_play)
        self.btn_play.SetLabel("Pausa" if reproduciendo else "Reproducir")

    def _toggle_play(self):
        if not self._asegurar_player():
            aviso = aviso_reproductor(
                self._listo, bool(self._video_id or self._url_flujo))
            if aviso:
                anunciar(aviso)
            return
        estado = self._estado_vlc_actual()
        orden = getattr(self, "_orden_transporte", None)
        if orden is not None:
            desenlace_prev = evaluar_transporte(orden, estado, time.monotonic())
            if desenlace_prev == "pendiente":
                try:
                    puede_pausar = bool(self._player.can_pause())
                except Exception:
                    puede_pausar = None
                try:
                    es_buscable = bool(self._player.is_seekable())
                except Exception:
                    es_buscable = None
                logger.debug("%s", traza_transporte(
                    estado, "en_curso", bool(self._video_id or self._url_flujo),
                    self._intencion_reproducir, puede_pausar, es_buscable))
                import sound_player as _snd
                _snd.reproducir("transporte_en_curso")
                return
            else:
                # finaliza la transacción pendiente antes de solicitar otra
                self._evaluar_transporte()
                estado = self._estado_vlc_actual()
        accion = accion_play_pausa(
            estado, bool(self._video_id or self._url_flujo),
            self._intencion_reproducir,
            False)
        try:
            puede_pausar = bool(self._player.can_pause())
        except Exception:
            puede_pausar = None
        try:
            es_buscable = bool(self._player.is_seekable())
        except Exception:
            es_buscable = None
        logger.debug("%s", traza_transporte(
            estado, accion, bool(self._video_id or self._url_flujo),
            self._intencion_reproducir, puede_pausar, es_buscable))
        if accion == "en_curso":
            import sound_player as _snd
            _snd.reproducir("transporte_en_curso")
        elif accion == "pausar":
            self._player.set_pause(1)
            self._orden_transporte = OrdenTransporte(intencion_reproducir=False, instante=time.monotonic())
            self._transporte_pendiente = True
            try:
                self._timer.Start(500)
            except Exception:
                pass
            anunciar("Pausando")
        elif accion == "reanudar":
            # En un directo de TikTok (flujo en vivo, sin línea de tiempo)
            # «reanudar» dejaría el vídeo retrasado; recargamos para volver al
            # momento actual del directo.
            if self._url_flujo:
                self._reproducir_flujo()
            else:
                self._player.set_pause(0)
                self._orden_transporte = OrdenTransporte(intencion_reproducir=True, instante=time.monotonic())
                self._transporte_pendiente = True
                try:
                    self._timer.Start(500)
                except Exception:
                    pass
                anunciar("Reanudando")
        elif accion == "cargar":
            if self._video_id:
                self._recargas_directo = 0   # recarga manual: cuenta desde cero
                self.cargar(reproducir=True)
            elif self._url_flujo:
                self._reproducir_flujo()
            else:
                aviso = aviso_reproductor(
                    self._listo, bool(self._video_id or self._url_flujo))
                if aviso:
                    anunciar(aviso)

    def _detener(self, silencioso: bool = False, en_segundo_plano: bool = False):
        # Invalida cualquier carga en vuelo (yt-dlp) y desbloquea futuras cargas:
        # sin esto, una carga que termina tras detener/desconectar rearrancaba la
        # reproducción al volver por wx.CallAfter.
        self._gen += 1
        self._cargando = False
        self._cancelar_busqueda()
        if hasattr(self, "_estado_inicio"):
            self._estado_inicio.cancelar()
        self._tiene_esclavo = False
        self._usando_cache_local = False
        self._cancelar_transporte()
        tarea = getattr(self, "_tarea_cache_video", None)
        if tarea is not None:
            tarea.cancelacion.set()
            self._tarea_cache_video = None
        self._detener_relevo_ffmpeg()
        self._intencion_reproducir = False
        self._timer_progreso.Stop()
        if self._player is not None:
            if en_segundo_plano:
                ciclo = getattr(self, "_ciclo", None)
                if ciclo is not None and ciclo.en_retirada:
                    try:
                        self._player.stop()
                    except Exception:
                        pass
                else:
                    ciclo_local = ciclo
                    rid = ciclo_local.iniciar_retirada() if ciclo_local is not None else 0
                    player = self._player
                    gestor_eventos = self._gestor_eventos_vlc
                    # El hilo de cierre no debe tocar la ventana de wx.
                    try:
                        player.set_hwnd(0)
                    except Exception as exc:
                        logger.debug("set_hwnd al cerrar: %s", exc)
                    self._player = None
                    self._gestor_eventos_vlc = None

                    def _cerrar(gestor=gestor_eventos, rid=rid):
                        try:
                            player.stop()
                        except Exception:
                            pass
                        try:
                            player.release()
                        except Exception:
                            pass
                        # Mientras libVLC pueda llamar callbacks, el gestor conserva
                        # vivo el trampolín de ctypes que usa python-vlc.
                        _ = gestor
                        try:
                            app = wx.GetApp()
                        except Exception:
                            app = None
                        if app is not None:
                            try:
                                wx.CallAfter(self._al_retirar, rid)
                            except Exception:
                                pass

                    diagnostico.crear_hilo(_cerrar, "ReproductorStop").start()
            else:
                try:    self._player.stop()
                except Exception: pass
        if hasattr(self, "_timer"):
            self._timer.Stop()
        if hasattr(self, "btn_play"):
            self._mostrar_pausa(False)
            self._fijar_tiempo(0, 0, mover_slider=True, anunciar_t=False)
        if not silencioso:
            anunciar("Detenido")

    def _aviso_sin_barra(self) -> None:
        # En un directo de TikTok no hay línea de tiempo; en un directo de
        # YouTube sí (se puede retroceder dentro del margen que da YouTube).
        if self._url_flujo:
            anunciar("En un directo de TikTok no se puede adelantar ni retroceder")
        else:
            anunciar("No se puede buscar en este momento")

    def _toggle_mute(self):
        if self._player is None:
            aviso = aviso_reproductor(
                self._listo, bool(self._video_id or self._url_flujo))
            if aviso:
                anunciar(aviso)
            return
        self._muted = not self._muted
        self._player.audio_set_mute(self._muted)
        self.btn_mute.SetBitmap(self._ic_mute if self._muted else self._ic_sound)
        self.btn_mute.SetLabel("Activar audio" if self._muted else "Silenciar audio")
        anunciar("Audio silenciado" if self._muted else "Audio activado")

    def _aplicar_volumen(self, delta: int) -> int:
        """Ajusta el volumen (slider + VLC) y devuelve el valor nuevo. Común al
        atajo Ctrl+Arriba/Abajo y a las flechas sobre el deslizador."""
        self._vol = max(0, min(100, self._vol + delta))
        self.sld_vol.SetValue(self._vol)
        if self._player is not None:
            self._player.audio_set_volume(self._vol)
        return self._vol

    def ajustar_volumen(self, delta: int):
        anunciar(f"Volumen reproductor {self._aplicar_volumen(delta)} por ciento")

    # ── Pantalla completa ──────────────────────────────────────────────────────

    def alternar_pantalla_completa(self):
        if not self._asegurar_player():
            aviso = aviso_reproductor(
                self._listo, bool(self._video_id or self._url_flujo))
            if aviso:
                anunciar(aviso)
            return
        if self._fs is None:
            self._fs = _PantallaCompleta(self)
            self._fijar_salida(self._fs.video.GetHandle())
            anunciar("Pantalla completa. Espacio pausa, flechas buscan y ajustan "
                     "volumen, Escape sale.")
        else:
            self._fijar_salida(self._video.GetHandle())
            self._fs.Destroy()
            self._fs = None
            # Devolver el foco al panel: al cerrarse la ventana de pantalla
            # completa, el foco quedaba en el aire (el lector se perdía). Va a un
            # control con nombre accesible del reproductor.
            try:    self.anclar_foco()
            except Exception: pass
            anunciar("Pantalla completa desactivada")

    # ── Tiempo / sliders ──────────────────────────────────────────────────────


    def _fijar_tiempo(self, pos_ms, dur_ms, mover_slider, anunciar_t):
        self._pos_ms = int(pos_ms or 0)
        self._dur_ms = int(dur_ms or 0)
        if self._dur_ms > 0 and self._pos_ms <= self._dur_ms:
            self.lbl_tiempo.SetLabel(f"{_fmt_t(self._pos_ms)} / {_fmt_t(self._dur_ms)}")
        elif self._dur_ms > 0:
            # VLC da a veces una duración menor que la posición en directos
            # (visto: 2:08:57 con dur=15:00): no fiarse del total ni sacar
            # el deslizador de su rango 0-1000.
            self.lbl_tiempo.SetLabel(_fmt_t(self._pos_ms))
        else:
            self.lbl_tiempo.SetLabel("En directo")
        if mover_slider and self._dur_ms > 0:
            self.sld_pos.SetValue(max(0, min(1000, int(self._pos_ms / self._dur_ms * 1000))))
        if anunciar_t:
            anunciar(_fmt_hablado(self._pos_ms))

    def _lectura_cruda(self) -> int:
        try:
            return int(self._player.get_time())
        except Exception:
            return -1

    def _marcar_destino(self, destino, anunciar_usuario=True):
        bus = getattr(self, "_estado_busqueda", None)
        if bus is None:
            self._estado_busqueda = EstadoBusqueda(confirmada=0)
            bus = self._estado_busqueda
        ahora = time.monotonic()
        topologia = self._topologia_actual()
        estado_v = self._estado_vlc_actual()
        muestra_pre = self._lectura_cruda()
        logger.debug("%s", traza_busqueda_orden(
            topologia, estado_v, bus.confirmada, destino, muestra_pre, 0))
        bus.solicitar(destino, ahora)
        gen = bus.generacion
        if anunciar_usuario:
            anunciar(f"Moviendo a {_fmt_hablado(destino)}")
        dur = int(self._player.get_length()) if self._player else 0
        self._fijar_tiempo(bus.confirmada, dur, mover_slider=True, anunciar_t=False)
        # asegurar observación periódica aunque el medio esté pausado
        try:
            if bus.pendiente:
                self._timer.Start(500)
        except Exception:
            pass
        bus_ref = bus
        def caducar():
            if bus_ref.generacion != gen:
                return
            if not bus_ref.pendiente:
                return
            self._evaluar_busqueda()
        if wx.GetApp() is not None:
            wx.CallLater(TOPE_BUSQUEDA_MS + 10, caducar)

    def _evaluar_busqueda(self):
        bus = getattr(self, "_estado_busqueda", None)
        if bus is None:
            return
        muestra = self._lectura_cruda()
        dur = int(self._player.get_length()) if self._player else 0
        estado = self._estado_vlc_actual()
        ahora = time.monotonic()
        # traza de muestra mientras está pendiente, con topología y condición de directo
        if bus.pendiente:
            topologia = self._topologia_actual()
            es_directo = self._es_directo_actual()
            candidato = bus.candidato
            edad = bus.edad_ms(ahora) if bus.marca_destino is not None else 0
            logger.debug("%s", traza_busqueda_muestra(
                topologia, es_directo, estado, bus.confirmada, bus.destino,
                muestra, dur, candidato, edad))
        destino_previo = bus.destino
        confirmada_previa = bus.confirmada
        edad_previa = bus.edad_ms(ahora) if bus.marca_destino is not None else 0
        evento, valor = bus.observar(muestra, dur, estado, ahora,
                                     es_directo=self._es_directo_actual())
        if evento == "candidato":
            pos_mostrar = bus.confirmada
            mover = wx.Window.FindFocus() is not self.sld_pos
            self._fijar_tiempo(pos_mostrar, dur, mover_slider=mover, anunciar_t=False)
            return
        if evento == "confirmado":
            logger.debug("%s", traza_busqueda_desenlace(
                self._topologia_actual(), estado, confirmada_previa, destino_previo, muestra, edad_previa, "confirmado"))
            anunciar(f"Posición {_fmt_hablado(int(valor))}")
        elif evento in ("fallo", "vencido"):
            logger.debug("%s", traza_busqueda_desenlace(
                self._topologia_actual(), estado, confirmada_previa, destino_previo, muestra, edad_previa, evento))
            anunciar("No se pudo mover el vídeo")
        pos_mostrar = bus.confirmada
        mover = wx.Window.FindFocus() is not self.sld_pos
        self._fijar_tiempo(pos_mostrar, dur, mover_slider=mover, anunciar_t=False)

    def _on_sld_pos(self, event):
        if self._player is None:
            return
        if not self._busqueda_permitida_actual():
            self._aviso_busqueda_no_permitida()
            return
        dur = self._player.get_length()
        if dur <= 0:
            logger.debug("%s", traza_sin_barra("deslizador", dur))
            return
        bus = self._estado_busqueda
        destino = int(self.sld_pos.GetValue() / 1000.0 * dur)
        destino = max(0, min(destino, dur))
        pendiente_prev = bus.destino
        pos = bus.confirmada
        logger.debug("%s", traza_salto(
            "deslizador", pendiente_prev, pos,
            destino - pos, destino, dur))
        self._player.set_time(destino)
        self._marcar_destino(destino, anunciar_usuario=True)

    def _on_pos_key(self, event):
        k = event.GetKeyCode()
        if k in (wx.WXK_RIGHT, wx.WXK_UP):
            self._buscar_rel(+10_000)
        elif k in (wx.WXK_LEFT, wx.WXK_DOWN):
            self._buscar_rel(-10_000)
        elif ord("0") <= k <= ord("9"):
            self._buscar_porcentaje((k - ord("0")) * 10)
        elif wx.WXK_NUMPAD0 <= k <= wx.WXK_NUMPAD9:
            self._buscar_porcentaje((k - wx.WXK_NUMPAD0) * 10)
        else:
            event.Skip()

    def _buscar_porcentaje(self, pct):
        if self._player is None:
            return
        if not self._busqueda_permitida_actual():
            self._aviso_busqueda_no_permitida()
            return
        dur = self._player.get_length()
        if dur <= 0:
            logger.debug("%s", traza_sin_barra("porcentaje", dur))
            self._aviso_sin_barra()
            return
        bus = self._estado_busqueda
        destino = int(dur * pct / 100)
        destino = max(0, min(destino, dur))
        pendiente_prev = bus.destino
        pos = bus.confirmada
        logger.debug("%s", traza_salto(
            "porcentaje", pendiente_prev, pos,
            destino - pos, destino, dur))
        self._player.set_time(destino)
        self._marcar_destino(destino, anunciar_usuario=True)

    def _on_vol_key(self, event):
        k = event.GetKeyCode()
        if k in (wx.WXK_UP, wx.WXK_RIGHT):
            self._vol_flecha(+1)
        elif k in (wx.WXK_DOWN, wx.WXK_LEFT):
            self._vol_flecha(-1)
        else:
            event.Skip()

    def _vol_flecha(self, delta):
        anunciar(f"Volumen {self._aplicar_volumen(delta)}")

    def _on_sld_vol(self, event):
        self._vol = self.sld_vol.GetValue()
        if self._player is not None:
            self._player.audio_set_volume(self._vol)

    def _on_timer(self, event):
        if self._player is None:
            return
        try:
            estado_actual = self._estado_vlc_actual()
            reproduciendo = estado_actual == "playing"
        except Exception:
            estado_actual = "desconocido"
            reproduciendo = False
        if not self._muted and reproduciendo:
            try:
                actual = self._player.audio_get_volume()
                if actual >= 0 and actual != self._vol:
                    self._player.audio_set_volume(self._vol)
            except Exception:
                pass
        inicio = getattr(self, "_estado_inicio", None)
        if inicio is not None and inicio.requiere:
            estado_inicio = self._estado_vlc_actual()
            muestra_inicio = self._lectura_cruda()
            topologia = self._topologia_actual()
            es_directo = self._es_directo_actual()
            primera = inicio.primera
            logger.debug("%s", traza_inicio_muestra(
                topologia, es_directo, estado_inicio, primera, muestra_inicio))
            if inicio.observar(estado_inicio, muestra_inicio):
                if self._marca_url is not None:
                    diagnostico.logger.info(
                        "REPRODUCCIÓN tramos_ms=%.0f,%.0f,%.0f",
                        (self._marca_extraccion - self._marca_reproduccion) * 1000
                        if self._marca_extraccion and self._marca_reproduccion else 0,
                        (self._marca_url - self._marca_extraccion) * 1000
                        if self._marca_extraccion else 0,
                        (time.monotonic() - self._marca_url) * 1000)
                    self._marca_url = None
                if getattr(self, "_url_flujo", ""):
                    self._fijar_estado("En directo (sin barra de tiempo).")
                    anunciar("En directo")
                else:
                    self._fijar_estado("Reproduciendo.")
                    anunciar("Reproduciendo")
        self._evaluar_transporte()
        self._evaluar_busqueda()
        try:
            estado_final = self._estado_vlc_actual()
        except Exception:
            estado_final = ""
        if estado_final == "paused" and getattr(self, "_orden_transporte", None) is None and not getattr(self._estado_busqueda, "pendiente", False):
            try:
                self._timer.Stop()
            except Exception:
                pass
        if estado_final == "ended":
            if getattr(self, "_relevo_ffmpeg", None) is not None \
                    and self._es_directo_actual():
                self._directo_interrumpido()
            else:
                self._detener(silencioso=True)
                anunciar("Fin del vídeo")
        elif estado_final == "error":
            self._fallo_reproduccion()

    def _directo_interrumpido(self) -> None:
        """El relevo de ffmpeg terminó (fin del directo, URL de googlevideo
        caducada a las ~6 h, corte de red) y VLC vio un fin de archivo:
        anunciarlo como «Fin del vídeo» engañaba. Se avisa y se recarga una
        vez sola (cargar() resuelve URLs frescas), con tope de recargas
        seguidas para no entrar en bucle si el directo de verdad acabó."""
        recargas = getattr(self, "_recargas_directo", 0)
        self._detener(silencioso=True)
        anunciar("El directo se interrumpió")
        if recargas >= TOPE_RECARGAS_DIRECTO:
            logger.warning("DIRECTO_INTERRUMPIDO sin recargar recargas=%d", recargas)
            self._fijar_estado("El directo se interrumpió.")
            return
        self._recargas_directo = recargas + 1
        logger.warning("DIRECTO_INTERRUMPIDO recarga=%d", self._recargas_directo)
        self.cargar(reproducir=True)

    def _fallo_reproduccion(self) -> None:
        """VLC quedó en «error» (no pudo abrir la fuente). Antes no se
        trataba: el temporizador seguía muestreando y el usuario oía
        «Cargando vídeo» y luego nada. Con el relevo de ffmpeg se reintenta
        la conexión unas veces mientras ffmpeg siga vivo; si no, se para y
        se avisa."""
        relevo = getattr(self, "_relevo_ffmpeg", None)
        reintentos = getattr(self, "_relevo_reintentos", 0)
        if relevo is not None and relevo.activo() and reintentos < 3:
            self._relevo_reintentos = reintentos + 1
            logger.warning("REPRODUCCION_ERROR relevo reintento=%d",
                           self._relevo_reintentos)
            try:
                self._player.play()
                return
            except Exception as exc:
                logger.debug("reintento tras error: %s", exc)
        logger.warning("REPRODUCCION_ERROR topologia=%s relevo_activo=%s",
                       self._topologia_actual(),
                       relevo.activo() if relevo is not None else "no")
        self._detener(silencioso=True)
        import sound_player as _snd
        _snd.reproducir("error")
        self._fijar_estado("No se pudo reproducir el vídeo.")
        anunciar("No se pudo reproducir el vídeo")

    def _aviso_busqueda_no_permitida(self) -> None:
        if getattr(self, "_relevo_ffmpeg", None) is not None:
            anunciar("En este directo no se puede adelantar ni retroceder")
        else:
            anunciar("No se puede mover este vídeo mientras usa la fuente de internet")

    def _buscar_rel(self, delta_ms: int):
        if self._player is None:
            aviso = aviso_reproductor(
                self._listo, bool(self._video_id or self._url_flujo))
            if aviso:
                anunciar(aviso)
            return
        # La permisión va antes que la duración: con el relevo de ffmpeg VLC
        # devuelve length=0 y, mirando primero dur, el aviso específico de
        # «no se puede buscar en este directo» no llegaba nunca.
        if not self._busqueda_permitida_actual():
            self._aviso_busqueda_no_permitida()
            return
        dur = self._player.get_length()
        if dur <= 0:
            logger.debug("%s", traza_sin_barra("relativo", dur))
            self._aviso_sin_barra()
            return
        bus = self._estado_busqueda
        pos = bus.confirmada
        destino = destino_acumulado(bus.destino, pos, delta_ms, dur)
        pendiente_prev = bus.destino
        logger.debug("%s", traza_salto(
            "relativo", pendiente_prev, pos,
            delta_ms, destino, dur))
        self._player.set_time(destino)
        self._marcar_destino(destino, anunciar_usuario=True)
