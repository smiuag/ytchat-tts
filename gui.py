"""Interfaz wxPython accesible: barra de menú nativa + paneles en notebook.

Rediseño: una sola ventana con barra de menú (que NVDA lee de forma nativa y
que muestra los atajos), barra superior con URL+Conectar, y un notebook con los
paneles Chat en vivo, Comentarios y Reproductor. Al conectar se detecta si la
URL es un directo o un vídeo subido y se ajustan los paneles.
"""

from __future__ import annotations

import logging
import random
import re
import shutil
import threading
import time
import webbrowser
from datetime import datetime

import wx

from config import (
    APP_NAME, APP_VERSION,
    TIPO_TEXTO, TIPO_SUPERCHAT, TIPO_STICKER, TIPO_MIEMBRO, TIPO_ENTRADA,
    FILTROS,
)
from config import (parsear_atajos, detectar_conflictos_atajos, ATAJOS_DEFAULTS,
                    app_dir, guardar_opcion)
import deteccion
import metadatos
import estado_sesion
import historial
from lista_chat import ListaChat, MensajeChat
from busqueda_lista import buscar_prefijo, coincide
import sound_player as _snd
import credenciales
import youtube_api
import diagnostico
import ytdlp_bin
import apagado
import overlay_servidor
import programados
import descartes
import redaccion
import alias
import obs_audio
import obs_estado
import obs_vigilante
from obs_panel import GestorPanelObs
from gui_redactar import PanelRedactar

# Mapeo entre índice de FILTROS y clave persistida en config.ini.
_NOMBRES_FILTRO = ("todos", "texto", "superchat", "miembro")
_IDX_FILTRO     = {"todos": 0, "texto": 1, "superchat": 2, "miembro": 3}


MAX_ITEMS_CHAT  = 500
TIMER_STATUS_MS = 1000
TIMER_DIAGNOSTICO_MS = 100
# Ráfagas de mensajes del chat: en vez de un Append/Delete por mensaje (mucho
# repintado en el hilo de GUI mientras NVDA navega la lista), se agrupan y se
# vuelcan juntos cada tanto. Ver agregar_mensaje_chat / _volcar_pendientes.
MS_VOLCADO_CHAT = 120
ANCHO_DEFECTO   = 860
ALTO_DEFECTO    = 700

# Mensaje bajo la barra de URL cuando no hay conexión. Breve pero completo:
# qué se puede pegar y cómo conectar.
MENSAJE_INICIAL = ("Sin conectar. Pega un enlace de YouTube (directo o vídeo) o "
                   "de un directo de TikTok y pulsa Conectar (Alt+C). En YouTube "
                   "podrás leer el chat y los comentarios; en TikTok, el chat del "
                   "directo.")
RUTA_CONFIG = None  # se asigna en iniciar_gui() con app_dir()
_URL_RE         = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)

# Índices de las páginas del notebook (solo chat y comentarios; el reproductor
# es una región fija, no una pestaña).
PAG_CHAT = 0
PAG_COMENTARIOS = 1

# Regiones que recorre F6 / Shift+F6.
REG_CONEXION = 0
REG_CONTENIDO = 1
REG_REPRODUCTOR = 2
_NOMBRE_REGION = ("Conexión", "Contenido", "Reproductor")

logger = diagnostico.obtener_logger(__name__)
_OBS_COMPONENTES = frozenset(("obs_transmision", "obs_grabacion", "obs_escena"))


# ── accessible_output2 (opcional) ───────────────────────────────────────────
# Si no está instalado o no hay un lector de pantalla activo, los
# `anunciar()` son no-ops silenciosos; la app funciona igual.

_ao2 = None


def _ao2_init():
    global _ao2
    try:
        from accessible_output2.outputs.auto import Auto
        candidate = Auto()
        for out in getattr(candidate, "outputs", []):
            try:
                if out.is_active() and "sapi" not in type(out).__name__.lower():
                    _ao2 = candidate
                    return
            except Exception:
                pass
    except (AttributeError, ImportError):
        try:
            import win32com
            shutil.rmtree(win32com.__gen_path__, ignore_errors=True)
            from accessible_output2.outputs.auto import Auto
            candidate = Auto()
            for out in getattr(candidate, "outputs", []):
                try:
                    if out.is_active() and "sapi" not in type(out).__name__.lower():
                        _ao2 = candidate
                        return
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("La aplicación se quedó sin salida para lector de pantalla: %s", exc)
    except Exception as exc:
        logger.warning("La aplicación se quedó sin salida para lector de pantalla: %s", exc)


def anunciar(texto: str, urgente: bool = True) -> None:
    if _ao2 is None:
        return
    try:
        # Casi todos responden a una tecla y deben llegar antes del próximo foco.
        _ao2.speak(texto, interrupt=urgente)
    except Exception as exc:
        logger.warning("No se pudo anunciar con voz: %s", exc)
    # También a la línea braille, como hace TWBlue (output.speak): quien usa
    # pantalla braille sin voz recibe igualmente los anuncios de la app.
    try:
        _ao2.braille(texto)
    except Exception:
        pass


def anunciar_conflictos_atajos(raw: dict | None) -> None:
    for perdedora, conservada, combinacion in detectar_conflictos_atajos(raw):
        anunciar(
            f"Conflicto de atajos: {perdedora} se quedó sin atajo porque "
            f"{conservada} usa {combinacion}.")


# ── Nombre accesible reforzado (MSAA) ─────────────────────────────────────────
# Patrón tomado de eleven-tts-studio: en Windows, `SetName` por sí solo no
# siempre lo anuncian NVDA/JAWS de forma fiable (sobre todo en deslizadores y en
# ventanas genéricas como la superficie de vídeo). Reforzamos con un
# `wx.Accessible` explícito que expone el nombre por MSAA. Solo se usa en los
# controles donde el nombre flojea; los estándar (botones, casillas) ya se leen
# bien con `name=` y no hace falta.

class _NombreAccesible(wx.Accessible):
    """Expone el nombre del control por MSAA. Solo nombra el control en sí
    (childId 0); las filas/hijos (p. ej. cada línea de una lista) las deja al
    proveedor por defecto, o todas se anunciarían con el nombre de la lista."""

    def __init__(self, nombre: str):
        super().__init__()
        self._nombre = nombre

    def GetName(self, childId):
        if childId == 0:
            return (wx.ACC_OK, self._nombre)
        return (wx.ACC_NOT_IMPLEMENTED, "")


def nombre_accesible(ctrl, nombre: str, msaa: bool = True) -> None:
    """Refuerza el nombre accesible de un control. Mantiene los tooltips ricos
    que ya tengamos (solo pone uno si falta) y no altera el rol ni el valor: el
    `wx.Accessible` solo sobrescribe el nombre y delega el resto.

    `msaa=False` se salta el `wx.Accessible` (deja SetName/tooltip/HelpText
    igual). Úsalo en listas de CONTENIDO DINÁMICO (chat, comentarios): al
    instalar un `wx.Accessible` en Python, TODAS las consultas MSAA de NVDA
    sobre ese control (también las de cada fila al navegar con flechas) pasan
    por el proxy de wx y el hilo de GUI. Con la lista recibiendo Append/Delete
    constantes por los mensajes que llegan, esas consultas se quedan esperando
    y la navegación se traba a trompicones. Las listas estáticas (voces,
    historial…) no sufren esto y siguen con el refuerzo."""
    ctrl.SetName(nombre)
    if not ctrl.GetToolTip():
        ctrl.SetToolTip(nombre)
    try:    ctrl.SetHelpText(nombre)   # JAWS lee el help text en algunos controles
    except Exception: pass
    if not msaa:
        return
    try:
        acc = _NombreAccesible(nombre)
        ctrl.SetAccessible(acc)
        ctrl._nombre_accesible = acc   # evita que el GC se lo lleve
    except Exception:
        pass  # fuera de Windows o sin MSAA: el name/tooltip siguen aplicando


def caja_de_grupo(panel, titulo):
    """Crea una caja y devuelve el sizer junto al padre de sus controles."""
    caja = wx.StaticBox(panel, label=titulo)
    return wx.StaticBoxSizer(caja, wx.VERTICAL), caja


# ── Búsqueda por prefijo (type-ahead) en listas de texto ────────────────────
# Estando en el chat o en comentarios, escribir letras seguidas salta al
# primer mensaje cuyo texto MOSTRADO («autor: mensaje…») empiece por eso, con
# buffer multiletra («mig» → «Miguel», no una letra a la vez) que se resetea
# solo tras un rato sin teclear. La lógica de búsqueda vive en
# `busqueda_lista.py` (pura, sin wx); esto solo engancha el evento y lleva el
# buffer/temporizador.

_MS_RESET_BUSQUEDA = 900


class _EstadoBusqueda:
    """Buffer de teclas y temporizador de reseteo de una lista. Uno por
    control (instalar_busqueda_tipo lo crea y lo cierra en un closure)."""

    def __init__(self):
        self.buffer = ""
        self.timer = None


def instalar_busqueda_tipo(listbox: wx.ListBox, obtener_textos) -> None:
    """Engancha en `listbox` el type-ahead sobre EVT_CHAR (aparte de
    EVT_KEY_DOWN, que ya usan estas listas para Enter/Ctrl+C/menú, para no
    pelearse con esos keycodes). `obtener_textos` es una función sin
    argumentos que devuelve, en orden de fila, el texto mostrado de cada
    ítem (normalmente `[listbox.GetString(i) for i in range(GetCount())]`).
    """
    estado = _EstadoBusqueda()

    def _resetear_buffer():
        estado.buffer = ""
        estado.timer = None

    def _on_char(event):
        # Combinaciones con Ctrl/Alt son atajos, no texto de búsqueda.
        if event.ControlDown() or event.AltDown():
            event.Skip()
            return
        code = event.GetUnicodeKey()
        if code == wx.WXK_NONE:
            event.Skip()
            return
        ch = chr(code)
        if not ch.isprintable():
            event.Skip()
            return
        if ch == " " and not estado.buffer:
            # Espacio con el buffer vacío: no es inicio de búsqueda, que se
            # comporte como en cualquier lista (no lo consumimos).
            event.Skip()
            return

        estado.buffer += ch
        if estado.timer is not None:
            try:    estado.timer.Stop()
            except Exception: pass
        estado.timer = wx.CallLater(_MS_RESET_BUSQUEDA, _resetear_buffer)

        textos = obtener_textos()
        if not textos:
            return
        actual = listbox.GetSelection()
        if (len(estado.buffer) > 1 and actual != wx.NOT_FOUND
                and 0 <= actual < len(textos)
                and coincide(textos[actual], estado.buffer)):
            return   # el seleccionado ya cumple: no mover nada
        desde = (actual + 1) if actual != wx.NOT_FOUND else 0
        idx = buscar_prefijo(textos, desde, estado.buffer)
        if idx is not None:
            listbox.SetSelection(idx)
            # NVDA no siempre anuncia una selección puesta por programa.
            anunciar(textos[idx])
        else:
            # Que quien busca sepa que se buscó (en toda la lista, dando la
            # vuelta) y no hubo nada; se descarta la última letra para poder
            # seguir completando la búsqueda anterior.
            anunciar(f"No hay coincidencias con {estado.buffer}")
            estado.buffer = estado.buffer[:-1]

    listbox.Bind(wx.EVT_CHAR, _on_char)


# ── Paleta «crema + salvia» (PALETA-COLORES.md, modo claro tal cual) ────────
# Fondo crema y salvia como color de marca, igual que en el md de origen.
# `accent`/`accent2`/`gold`/`green`/`red` son texto (secciones, estados),
# no fondos: el md no da variantes de texto para esos tonos porque en su app
# solo se usan como fondo/relleno, así que aquí se oscurecieron lo justo para
# llegar a 4.5:1 sobre el fondo. Contraste comprobado con la fórmula WCAG en
# cada par texto/fondo real de la app; todos dan 4.5:1 o más.

class _T:
    bg      = wx.Colour(247, 244, 238)  # #F7F4EE  crema (fondo de marca)
    surface = wx.Colour(255, 255, 255)  # #FFFFFF  paneles, grupos, pestañas
    field   = wx.Colour(233, 225, 211)  # #E9E1D3  campos (secundario/beige)
    border  = wx.Colour(227, 220, 207)  # #E3DCCF
    text    = wx.Colour(51,  51,  51)   # #333333  texto principal
    dim     = wx.Colour(107, 107, 107)  # #6B6B6B  texto secundario
    accent  = wx.Colour(63,  91,  58)   # #3F5B3A  salvia oscurecida (primario, texto)
    accent2 = wx.Colour(138, 90,  82)   # #8A5A52  rosa oscurecida (secundario, texto)
    gold    = wx.Colour(131, 99,  11)   # #83630B  Super Chats
    green   = wx.Colour(46,  107, 50)   # #2E6B32  conectado / éxito
    red     = wx.Colour(179, 38,  30)   # #B3261E  error
    btn     = wx.Colour(233, 225, 211)  # botones secundarios (= field)
    btn_t   = wx.Colour(51,  51,  51)
    # Botón primario (Conectar): salvia tal cual del md, texto oscuro encima.
    primary   = wx.Colour(202, 215, 197)  # #CAD7C5  salvia (marca, sin oscurecer)
    primary_t = wx.Colour(51,  51,  51)


def _tc(w, bg=None, fg=None):
    w.SetBackgroundColour(bg or _T.field)
    w.SetForegroundColour(fg or _T.text)


class ContadorAccesible(wx.SpinCtrl):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.Bind(wx.EVT_SET_FOCUS, self._on_focus)

    def _on_focus(self, event):
        # Selecciona el valor para reemplazarlo sin borrarlo antes.
        self.SetSelection(0, len(self.GetTextValue()))
        event.Skip()


def _titulo(w, color=None):
    """Etiqueta de sección: color de acento y seminegrita, para jerarquía."""
    w.SetForegroundColour(color or _T.accent)
    w.SetFont(w.GetFont().Bold())


_ACCEL_NOMBRES = {
    "ctrl": "Ctrl", "alt": "Alt", "shift": "Shift",
    "enter": "Enter", "left": "Left", "right": "Right",
    "up": "Up", "down": "Down", "space": "Space",
}


def _fmt_accel(texto: str) -> str:
    """'f5'->'F5', 'ctrl+left'->'Ctrl+Left', 'alt+enter'->'Alt+Enter'.

    Formato que entiende wx para los aceleradores de menú.
    """
    if not texto:
        return ""
    partes = []
    for p in texto.split("+"):
        partes.append(_ACCEL_NOMBRES.get(p, p.upper()))
    return "+".join(partes)


class WxAnnouncingHandler(logging.Handler):
    """Reenvía los mensajes del logger al lector de pantalla."""

    def __init__(self):
        super().__init__()
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record):
        if not registro_es_anunciable(record.name):
            return
        try:    anunciar(self.format(record))
        except Exception: pass


# Lista blanca: solo estos loggers llegan al lector. Lo no listado se registra
# pero no se habla, para que un logger.info nuevo no se convierta en voz por descuido.
_LOGGERS_ANUNCIABLES = frozenset({
    "ytchat.obs_vigilante",  # avisa cuando OBS vuelve a responder
})


def registro_es_anunciable(nombre_logger: str | None) -> bool:
    """Decide si un registro del log debe llegar al lector de pantalla."""
    # Lista blanca: solo lo explicitamente permitido se habla; lo desconocido se calla.
    return bool(nombre_logger) and nombre_logger in _LOGGERS_ANUNCIABLES


class _LogWx(wx.Log):
    """Reenvia el log de wx al logger del modulo sin recortar el texto."""

    def DoLogRecord(self, level, msg, info):
        try:
            # Mensaje entero, sin recortar: es lo unico para diagnosticar
            if level in (wx.LOG_FatalError, wx.LOG_Error, wx.LOG_Warning):
                logger.warning("wx: %s", msg)
            else:
                logger.debug("wx: %s", msg)
        except Exception:
            pass


# ── Frame principal ──────────────────────────────────────────────────────────

class YTChatFrame(wx.Frame):

    def __init__(self, parent, config, cola, stats, worker, parada):
        super().__init__(
            parent,
            title=f"{APP_NAME} v{APP_VERSION}",
            size=(ANCHO_DEFECTO, ALTO_DEFECTO),
            name="VentanaPrincipal",
        )
        # Piso de la ventana: sin esto, se podía achicar hasta el punto de
        # aplastar el chat, el reproductor y los textos, cortándolos.
        try:
            self.SetMinSize((640, 480))
        except Exception:
            pass
        self._config    = config
        self._cola      = cola
        self._stats     = stats
        self._worker    = worker
        self._parada    = parada
        self._alive     = True
        self._apagando  = False
        self._conectado = False
        self._titulo_stream = ""
        self._tipo_video = deteccion.DESCONOCIDO
        self._es_tiktok = False   # para que F2 distinga TikTok de YouTube (ambos LIVE)
        self._descartes_avisado = False

        self._chat = ListaChat(MAX_ITEMS_CHAT)
        self._filtro = None
        # Cola de mensajes entrantes aún no volcados a lb_chat/self._chat, y el
        # temporizador que programa el volcado agrupado (ver MS_VOLCADO_CHAT).
        self._pendientes: list[MensajeChat] = []
        self._pendientes_timer = None

        self._sc_totales: dict[str, float] = {}
        self._live_chat_id = ""
        self._causa_sin_chat = ""
        self._mensajes_programados = programados.cargar(
            app_dir() / "mensajes_programados.json")
        self._programados_reloj_iniciado = False
        self._programados_ultimo_envio = None
        self._programado_en_curso = False

        # Voz activa (antes era un wx.Choice; ahora es un submenú de radio).
        self._voz_idx = 0
        self._voz_nombre = "—"

        self.on_conectar_cb    = None
        self.on_desconectar_cb = None

        self._atajos = parsear_atajos(config.get("atajos_raw", {}))
        anunciar_conflictos_atajos(config.get("atajos_raw", {}))
        self._diagnostico_marca = time.monotonic()
        self._diagnostico_censo = self._diagnostico_marca
        self._diagnostico_parada = threading.Event()
        self._obs_vigilante = None

        self.SetBackgroundColour(_T.bg)
        self._build_menubar()
        if self._config.get("overlay_activo", False):
            self._cambiar_overlay(True)
        self._build_ui()
        self._bind_events()
        self._init_timer()
        self._actualizar_vigilante_obs()
        diagnostico.crear_hilo(
            lambda: diagnostico.vigilar_hilo_interfaz(
                lambda: self._diagnostico_marca, self._diagnostico_parada),
            "VigilanteInterfaz").start()
        self.Centre()

    # ── Barra de menú ────────────────────────────────────────────────────────

    def _accel(self, accion: str) -> str:
        at = self._atajos.get(accion)
        return ("\t" + _fmt_accel(at.texto)) if at else ""

    def _bind_menu(self, item, fn, *args):
        """Difiere el anuncio hasta que el menú se cerró y volvió el foco."""
        if isinstance(item, tuple):
            menu, identificador = item
            menu.Bind(wx.EVT_MENU, lambda e: wx.CallAfter(fn, *args), id=identificador)
        else:
            self.Bind(wx.EVT_MENU, lambda e: wx.CallAfter(fn, *args), item)

    def _build_menubar(self):
        mb = wx.MenuBar()

        # Archivo
        m = wx.Menu()
        self.mi_conectar = m.Append(wx.ID_ANY, "&Conectar" + self._accel("conectar"))
        self.mi_desconectar = m.Append(wx.ID_ANY, "&Desconectar" + self._accel("desconectar"))
        m.AppendSeparator()
        mi_historial = m.Append(
            wx.ID_ANY, "&Historial de directos…" + self._accel("abrir_historial"))
        m.AppendSeparator()
        mi_salir = m.Append(wx.ID_EXIT, "&Salir\tAlt+F4")
        mb.Append(m, "&Archivo")
        self.Bind(wx.EVT_MENU, lambda e: wx.CallAfter(self._conectar_si_procede), self.mi_conectar)
        self.Bind(wx.EVT_MENU, lambda e: self._desconectar_si_procede(), self.mi_desconectar)
        self.Bind(wx.EVT_MENU, lambda e: wx.CallAfter(self._on_historial), mi_historial)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), mi_salir)

        # Ver
        m = wx.Menu()
        mi_sig = m.Append(wx.ID_ANY, "Región &siguiente\tF6")
        mi_ant = m.Append(wx.ID_ANY, "Región &anterior\tShift+F6")
        m.AppendSeparator()
        mi_conx = m.Append(wx.ID_ANY, "Ir a co&nexión (URL)")
        mi_lista = m.Append(wx.ID_ANY, "Ir a la &lista del panel actual" + self._accel("ir_lista"))
        mi_chat = m.Append(wx.ID_ANY, "Ir a &Chat en vivo")
        mi_com  = m.Append(wx.ID_ANY, "Ir a Co&mentarios")
        mi_rep  = m.Append(wx.ID_ANY, "Ir al &Reproductor")
        m.AppendSeparator()
        mi_estado = m.Append(wx.ID_ANY, "Anunciar &estado" + self._accel("anunciar_estado"))
        mb.Append(m, "&Ver")
        self.Bind(wx.EVT_MENU, lambda e: self._navegar_region(+1), mi_sig)
        self.Bind(wx.EVT_MENU, lambda e: self._navegar_region(-1), mi_ant)
        self.Bind(wx.EVT_MENU, lambda e: self._ir_region(REG_CONEXION), mi_conx)
        self.Bind(wx.EVT_MENU, lambda e: self._ir_lista(), mi_lista)
        self.Bind(wx.EVT_MENU, lambda e: self._ir_pestana(PAG_CHAT), mi_chat)
        self.Bind(wx.EVT_MENU, lambda e: self._ir_pestana(PAG_COMENTARIOS), mi_com)
        self.Bind(wx.EVT_MENU, lambda e: self._ir_region(REG_REPRODUCTOR), mi_rep)
        self._bind_menu(mi_estado, self._anunciar_estado)
        # De «Ver», solo tiene sentido con conexión la navegación por paneles;
        # «Ir a conexión (URL)» y «Anunciar estado» quedan siempre disponibles.
        self._mi_ver_conexion = [mi_sig, mi_ant, mi_lista, mi_chat, mi_com, mi_rep]

        # Chat
        m = wx.Menu()
        self.mi_enviar_live = m.Append(
            wx.ID_ANY,
            "&Enviar mensaje al chat del directo (solo YouTube)…" + self._accel("enviar_chat"))
        m.AppendSeparator()
        sub_f = wx.Menu()
        self.fi_items = []
        for i, (nombre, _) in enumerate(FILTROS):
            it = sub_f.AppendRadioItem(wx.ID_ANY, nombre)
            self.fi_items.append(it)
            self._bind_menu(it, self._aplicar_filtro, i)
        self._mi_filtro_sub = m.AppendSubMenu(sub_f, "&Filtro de mensajes")
        mb.Append(m, "&Chat")
        self.Bind(wx.EVT_MENU, self._on_enviar_live, self.mi_enviar_live)

        # Voz (TTS)
        m = wx.Menu()
        self.mi_pausa = m.Append(wx.ID_ANY, "&Pausar lectura" + self._accel("pausa"))
        mi_det = m.Append(wx.ID_ANY, "&Detener voz" + self._accel("detener_tts"))
        mi_vac = m.Append(wx.ID_ANY, "&Vaciar cola")
        # Estas tres actúan sobre una lectura en curso: sin conexión no hay nada
        # que pausar/detener/vaciar. Los ajustes de voz de abajo sí quedan libres.
        self._mi_voz_conexion = [self.mi_pausa, mi_det, mi_vac]
        m.AppendSeparator()
        mi_vmenos = m.Append(wx.ID_ANY, "Hablar más &lento" + self._accel("velocidad_menos"))
        mi_vmas   = m.Append(wx.ID_ANY, "Hablar más &rápido" + self._accel("velocidad_mas"))
        mi_volm   = m.Append(wx.ID_ANY, "&Bajar volumen de la voz" + self._accel("volumen_menos"))
        mi_volM   = m.Append(wx.ID_ANY, "&Subir volumen de la voz" + self._accel("volumen_mas"))
        m.AppendSeparator()
        self.mi_sil_lectura = m.AppendCheckItem(
            wx.ID_ANY, "S&ilenciar lectura TTS" + self._accel("silenciar_lectura"))
        self.mi_sil_sonidos = m.AppendCheckItem(
            wx.ID_ANY, "Silenciar s&onidos" + self._accel("silenciar_sonidos"))
        m.AppendSeparator()
        self.voz_submenu = wx.Menu()
        m.AppendSubMenu(self.voz_submenu, "Seleccionar vo&z")
        mb.Append(m, "Vo&z")
        self._bind_menu(self.mi_pausa, self._on_pausa, None)
        self._bind_menu(mi_det, self._on_detener_tts, None)
        self._bind_menu(mi_vac, self._on_vaciar, None)
        self._bind_menu(mi_vmenos, self._ajustar_rate, -1)
        self._bind_menu(mi_vmas, self._ajustar_rate, +1)
        self._bind_menu(mi_volm, self._ajustar_volume, -5)
        self._bind_menu(mi_volM, self._ajustar_volume, +5)
        self._bind_menu(self.mi_sil_lectura, self._toggle_silenciar_lectura)
        self._bind_menu(self.mi_sil_sonidos, self._toggle_silenciar_sonidos)

        # Reproductor
        m = wx.Menu()
        mi_rep_play  = m.Append(wx.ID_ANY, "&Reproducir o pausa" + self._accel("rep_play"))
        mi_rep_retro = m.Append(wx.ID_ANY, "R&etroceder 1 minuto" + self._accel("rep_retro"))
        mi_rep_avanz = m.Append(wx.ID_ANY, "&Avanzar 1 minuto" + self._accel("rep_avanz"))
        mi_rep_stop  = m.Append(wx.ID_ANY, "De&tener reproducción" + self._accel("rep_detener"))
        mi_rep_mute  = m.Append(wx.ID_ANY, "&Silenciar o activar audio" + self._accel("rep_mute"))
        mi_rep_fs    = m.Append(wx.ID_ANY, "Pantalla &completa" + self._accel("pantalla_completa"))
        # Submenú de calidad (radio). Se elige la disponible más cercana.
        sub_cal = wx.Menu()
        for etiqueta, altura in (("Automática", None), ("1080p", 1080), ("720p", 720),
                                 ("480p", 480), ("360p", 360), ("240p", 240), ("144p", 144)):
            it = sub_cal.AppendRadioItem(wx.ID_ANY, etiqueta)
            self._bind_menu(it, self._rep_accion, "set_calidad", altura)
        m.AppendSubMenu(sub_cal, "Ca&lidad del vídeo")
        m.AppendSeparator()
        # Descargar este vídeo (solo YouTube, no live). Se habilita en
        # `_actualizar_menus_por_conexion` cuando hay URL reproducible.
        self.mi_descargar_este = m.Append(
            wx.ID_ANY, "Descargar este &vídeo")
        m.AppendSeparator()
        mi_rep_volm  = m.Append(wx.ID_ANY, "&Bajar volumen del reproductor" + self._accel("rep_vol_menos"))
        mi_rep_volM  = m.Append(wx.ID_ANY, "S&ubir volumen del reproductor" + self._accel("rep_vol_mas"))
        m.AppendSeparator()
        self.mi_rep_botones = m.AppendCheckItem(wx.ID_ANY, "Mostrar botones en &pantalla")
        self.mi_rep_botones.Check(bool(self._config.get("mostrar_botones_reproductor", False)))
        self._bind_menu(self.mi_rep_botones, self._toggle_botones_rep)
        mb.Append(m, "&Reproductor")
        self._bind_menu(mi_rep_play, self._rep_accion, "_toggle_play")
        self._bind_menu(mi_rep_retro, self._rep_accion, "_buscar_rel", -60_000)
        self._bind_menu(mi_rep_avanz, self._rep_accion, "_buscar_rel", +60_000)
        self._bind_menu(mi_rep_stop, self._rep_accion, "_detener")
        self._bind_menu(mi_rep_mute, self._rep_accion, "_toggle_mute")
        self._bind_menu(mi_rep_fs, self._rep_accion, "alternar_pantalla_completa")
        self.Bind(wx.EVT_MENU, lambda e: wx.CallAfter(
            self._abrir_descargas,
            url=self._rep_panel.get_url_para_descarga() if self._rep_panel else None),
            self.mi_descargar_este)
        self._bind_menu(mi_rep_volm, self._rep_accion, "ajustar_volumen", -20)
        self._bind_menu(mi_rep_volM, self._rep_accion, "ajustar_volumen", +20)

        # Transmisión
        m = wx.Menu()
        self.mi_transmision = m.Append(
            wx.ID_ANY, "&Panel de transmisión…" + self._accel("abrir_transmision"))
        self.mi_obs_micro = m.Append(
            wx.ID_ANY, "Silenciar el &micrófono de OBS" + self._accel("obs_micro"))
        mb.Append(m, "&Transmisión")
        self.Bind(wx.EVT_MENU,
                  lambda e: wx.CallAfter(self._on_transmision, None),
                  self.mi_transmision)
        self.Bind(wx.EVT_MENU, self._on_obs_micro, self.mi_obs_micro)

        # Herramientas
        m = wx.Menu()
        # Gestor de descargas: SIEMPRE habilitado (funciona sin conexión de
        # chat, abriendo una URL pegada a mano). Ctrl+S es el atajo.
        self.mi_descargas = m.Append(
            wx.ID_ANY, "Gestor de &descargas…" + self._accel("descargas_abrir"))
        self.mi_actualizar_ytdlp = m.Append(wx.ID_ANY, "&Actualizar yt-dlp")
        m.AppendSeparator()
        mi_pref = m.Append(
            wx.ID_ANY, "&Preferencias…" + self._accel("abrir_preferencias"))
        mb.Append(m, "&Herramientas")
        self.Bind(wx.EVT_MENU, lambda e: wx.CallAfter(self._abrir_descargas), self.mi_descargas)
        self.Bind(wx.EVT_MENU, lambda e: wx.CallAfter(self._on_actualizar_ytdlp, None),
                  self.mi_actualizar_ytdlp)
        self.Bind(wx.EVT_MENU, lambda e: wx.CallAfter(self._on_preferencias, None), mi_pref)

        # Ayuda
        m = wx.Menu()
        mi_guia = m.Append(wx.ID_ANY, "&Guía de configuración de la API…")
        mi_incidente = m.Append(
            wx.ID_ANY, "&Marcar incidencia" + self._accel("marcar_incidencia"))
        mi_about = m.Append(wx.ID_ABOUT, "&Acerca de")
        mb.Append(m, "A&yuda")
        self.Bind(wx.EVT_MENU, lambda e: webbrowser.open(
            "https://github.com/miguel-cinsfran/ytchat-tts/blob/main/docs/CONFIGURACION_API.md"),
            mi_guia)
        self.Bind(wx.EVT_MENU, lambda e: wx.CallAfter(
            self._on_marcar_incidencia, None), mi_incidente)
        self.Bind(wx.EVT_MENU, lambda e: wx.CallAfter(self._on_about, None), mi_about)

        self.SetMenuBar(mb)

    def _cambiar_overlay(self, encender):
        puerto = self._config.get("overlay_puerto", 8730)
        if encender:
            try:
                overlay_servidor.encender(puerto)
            except overlay_servidor.OverlayPuertoOcupadoError:
                anunciar(f"No se pudo activar el panel, el puerto {puerto} está ocupado")
                # El puerto ocupado solo afecta esta sesión, no la preferencia guardada.
                self._config["overlay_activo"] = False
                return False
            self._config["overlay_activo"] = True
            guardar_opcion(RUTA_CONFIG, "overlay", "activo", "true")
            anunciar(f"Panel de chat activo en el puerto {puerto}")
            return True
        overlay_servidor.apagar()
        self._config["overlay_activo"] = False
        guardar_opcion(RUTA_CONFIG, "overlay", "activo", "false")
        anunciar("Panel de chat apagado")
        return False

    def _on_actualizar_ytdlp(self, event):
        anunciar("Buscando la última versión de yt-dlp")
        cancelado = threading.Event()
        dialogo = None
        terminado = threading.Event()
        ultimo_texto = None

        def _crear_dialogo():
            nonlocal dialogo
            dialogo = wx.ProgressDialog(
                APP_NAME, "Descargando yt-dlp", 100, self,
                style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT)

            def _comprobar_cancelacion():
                ytdlp_bin.sondear_cancelacion(
                    terminado, dialogo, cancelado,
                    lambda: wx.CallLater(100, _comprobar_cancelacion))

            _comprobar_cancelacion()

        def _progreso(porcentaje, _descargado, _total):
            wx.CallAfter(_actualizar_progreso, porcentaje)

        def _actualizar_progreso(porcentaje):
            nonlocal ultimo_texto
            if dialogo is None:
                return
            texto = "Descargando yt-dlp"
            if ytdlp_bin.debe_actualizar_texto_progreso(ultimo_texto, porcentaje):
                ultimo_texto = porcentaje
                texto = f"Descargando yt-dlp: {porcentaje} por ciento"
            dialogo.Update(porcentaje if porcentaje is not None else 0, texto)

        def _run():
            try:
                estado, version_actual, version_nueva = ytdlp_bin.actualizar_ytdlp(
                    lambda: wx.CallAfter(_crear_dialogo),
                    _progreso, cancelado.is_set)
                texto = ytdlp_bin.mensaje_de_actualizacion(
                    estado, version_actual, version_nueva)
            except Exception as exc:
                logger.warning("actualización de yt-dlp: %s", exc)
                estado = "otro_fallo"
                texto = ytdlp_bin.mensaje_de_actualizacion(
                    "otro_fallo", motivo=str(exc))
            icono = (wx.ICON_ERROR if ytdlp_bin.resultado_actualizacion_es_fallo(estado)
                     else wx.ICON_INFORMATION)
            def _terminar():
                terminado.set()
                if dialogo is not None:
                    dialogo.Destroy()
                wx.MessageBox(texto, APP_NAME, wx.OK | icono, self)

            wx.CallAfter(_terminar)

        diagnostico.crear_hilo(_run, "ActualizarYtdlp").start()

    # ── Construcción de la UI ────────────────────────────────────────────────

    def _build_ui(self):
        # Importes diferidos para evitar el ciclo (esos módulos importan de gui).
        from gui_comentarios import ComentariosPanel
        from reproductor import ReproductorPanel

        panel = wx.Panel(self, name="PanelPrincipal")
        panel.SetBackgroundColour(_T.bg)
        panel.SetForegroundColour(_T.text)
        vs = wx.BoxSizer(wx.VERTICAL)

        # ── Barra superior: URL + tipo + Conectar ──
        row = wx.BoxSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(panel, label="&URL/ID:", name="EtiquetaURL")
        _titulo(lbl)
        row.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.txt_url = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER, name="URL del directo o vídeo")
        _tc(self.txt_url)
        self.txt_url.SetToolTip(
            "Enlace de YouTube (directo o vídeo) o de un directo de TikTok "
            "(tiktok.com/@usuario/live). También vale el ID de 11 caracteres de "
            "YouTube. Pulsa Enter para conectar.")
        row.Add(self.txt_url, 1, wx.EXPAND | wx.RIGHT, 8)
        self.btn_conectar = wx.Button(panel, label="&Conectar", name="Conectar")
        self.btn_conectar.SetBackgroundColour(_T.primary)
        self.btn_conectar.SetForegroundColour(_T.primary_t)
        self.btn_conectar.SetFont(self.btn_conectar.GetFont().Bold())
        row.Add(self.btn_conectar, 0, wx.ALIGN_CENTER_VERTICAL)
        vs.Add(row, 0, wx.EXPAND | wx.ALL, 12)

        self.lbl_tipo = wx.StaticText(panel, label=MENSAJE_INICIAL, name="TipoVideo")
        self.lbl_tipo.SetForegroundColour(_T.dim)
        self.lbl_tipo.Wrap(ANCHO_DEFECTO - 40)
        vs.Add(self.lbl_tipo, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # ── Zona de contenido: notebook + reproductor. Se oculta hasta que hay
        # conexión y se vuelve a ocultar al desconectar (queda solo la barra
        # superior), para que no aparezca todo a medio cargar. ──
        self._zona = wx.Panel(panel, name="ZonaContenido")
        self._zona.SetBackgroundColour(_T.bg)
        zvs = wx.BoxSizer(wx.VERTICAL)

        self.nb = wx.Notebook(self._zona, name="Paneles")
        _tc(self.nb, bg=_T.surface)
        self._pag_chat = self._build_pagina_chat(self.nb)
        self._com_panel = ComentariosPanel(self.nb, self._cola, self._config)
        self.nb.AddPage(self._pag_chat, "Chat en vivo")
        self.nb.AddPage(self._com_panel, "Comentarios")
        # Pestaña de información del vídeo (solo lectura). Se añade SIEMPRE al
        # final, para no alterar los índices de Chat/Comentarios, y se puede
        # ocultar por preferencia. La rellena set_metadatos con lo de yt-dlp.
        self._pag_info = self._build_pagina_info(self.nb)
        self._metadatos = {}
        if bool(self._config.get("mostrar_metadatos", True)):
            self.nb.AddPage(self._pag_info, "Información")
        else:
            self._pag_info.Hide()
        # Piso para que la lista del chat, los comentarios y la información no
        # queden aplastados por el reproductor en ventanas bajas: 170 dejaba
        # ver 2-3 mensajes; con esto se ven varios más sin tocar el reproductor.
        self.nb.SetMinSize((-1, 260))
        zvs.Add(self.nb, 3, wx.EXPAND | wx.BOTTOM, 10)

        # Proporción 3/2 (antes el reproductor iba fijo en 0): chat y reproductor
        # comparten el alto sobrante con algo más de peso para el chat —que tiene
        # menos mínimo— para que queden equilibrados; el vídeo crece al agrandar la
        # ventana en vez de quedar fijo y comerse el espacio del chat.
        self._rep_panel = ReproductorPanel(self._zona, self._config)
        # Al alternar los botones del reproductor (desde su interruptor o el menú),
        # sincronizamos la casilla del menú y persistimos la preferencia.
        self._rep_panel.on_botones_toggle = self._on_botones_rep_cambio
        zvs.Add(self._rep_panel, 2, wx.EXPAND)

        self._zona.SetSizer(zvs)
        vs.Add(self._zona, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self._zona.Hide()

        panel.SetSizer(vs)
        self._panel_principal = panel

        # Regiones que recorre F6 / Shift+F6.
        self._region_idx = REG_CONTENIDO
        self._regiones = [
            lambda: self.txt_url.SetFocus(),
            self._foco_contenido,
            self._rep_panel.anclar_foco,
        ]

        # 7 campos: estado, velocidad, voz, cola, leídos, volumen, total SC.
        self.sb = self.CreateStatusBar(7, name="BarraEstado")
        self.sb.SetBackgroundColour(_T.surface)
        self.sb.SetForegroundColour(_T.dim)
        self.sb.SetStatusWidths([-3, -1, -3, -1, -1, -1, -2])
        self._actualizar_sb()
        self._set_conectado_ui(False)   # estado inicial: desconectado

    def _build_pagina_chat(self, parent) -> wx.Panel:
        pag = wx.Panel(parent, name="PaginaChat")
        pag.SetBackgroundColour(_T.bg)
        pag.SetForegroundColour(_T.text)
        vs = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(pag, label="Mensajes del chat:", name="EtiquetaChat")
        _titulo(lbl)
        vs.Add(lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)

        self.lb_chat = wx.ListBox(
            pag, style=wx.LB_SINGLE | wx.LB_HSCROLL, name="Chat en vivo")
        _tc(self.lb_chat)
        pt = int(self._config.get("tamanio_fuente_chat", 12))
        self.lb_chat.SetFont(wx.Font(
            pt, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.lb_chat.SetToolTip(
            "Mensajes del chat. Enter copia el mensaje. "
            "Tecla aplicaciones abre el menú contextual.")
        # msaa=False: ver el porqué en nombre_accesible() (lista dinámica).
        nombre_accesible(self.lb_chat, "Chat en vivo", msaa=False)
        vs.Add(self.lb_chat, 1, wx.EXPAND | wx.ALL, 8)

        self._panel_redactar = PanelRedactar(
            pag, "&Mensaje:", redaccion.MAXIMO_CHAT, self._enviar_live_redactado)
        vs.Add(self._panel_redactar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        pag.SetSizer(vs)
        self._actualizar_motivo_redaccion()
        return pag

    def _build_pagina_info(self, parent) -> wx.Panel:
        pag = wx.Panel(parent, name="PaginaInfo")
        pag.SetBackgroundColour(_T.bg)
        pag.SetForegroundColour(_T.text)
        vs = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(pag, label="Información del vídeo:", name="EtiquetaInfo")
        _titulo(lbl)
        vs.Add(lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)

        # Solo lectura y multilínea. TE_AUTO_URL (con TE_RICH2, necesario en
        # Windows) hace clicables los enlaces de la descripción SIN romper la
        # lectura con NVDA, que recorre el cuadro como texto normal (flechas,
        # selección, copiar). Es la opción accesible frente a un wx.html.
        self.txt_info = wx.TextCtrl(
            pag, value="", name="Información del vídeo",
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_AUTO_URL | wx.TE_RICH2)
        _tc(self.txt_info)
        self.txt_info.SetToolTip(
            "Datos del vídeo: canal, vistas, descripción. Solo lectura. Los "
            "enlaces se abren con clic o se copian y pegan en el navegador.")
        vs.Add(self.txt_info, 1, wx.EXPAND | wx.ALL, 8)

        pag.SetSizer(vs)
        self.txt_info.Bind(wx.EVT_TEXT_URL, self._on_info_url)
        return pag

    def _on_info_url(self, event):
        # TE_AUTO_URL dispara este evento para CADA movimiento del ratón sobre el
        # enlace; abrir solo al soltar el botón izquierdo (si no, abriría a cada
        # paso del cursor).
        mouse = event.GetMouseEvent()
        if mouse.LeftUp():
            url = self.txt_info.GetRange(event.GetURLStart(), event.GetURLEnd())
            if url:
                webbrowser.open(url)
        else:
            event.Skip()

    # ── Enlaces de eventos ───────────────────────────────────────────────────

    def _bind_events(self):
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_ACTIVATE, self._on_activate)
        self.Bind(wx.EVT_SIZE, self._on_resize)
        self.btn_conectar.Bind(wx.EVT_BUTTON, self._on_conectar)
        self.txt_url.Bind(wx.EVT_TEXT_ENTER,  self._on_conectar)
        self.nb.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._on_nb_page)
        self.lb_chat.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._copiar_mensaje())
        self._enlazar_eventos_chat()
        instalar_busqueda_tipo(
            self.lb_chat,
            lambda: [self.lb_chat.GetString(i) for i in range(self.lb_chat.GetCount())])

    def _enlazar_eventos_chat(self):
        self.lb_chat.Bind(wx.EVT_KEY_DOWN, self._on_chat_key)
        self.lb_chat.Bind(wx.EVT_CHAR_HOOK, self._on_chat_char_hook)
        self.lb_chat.Bind(wx.EVT_CONTEXT_MENU, self._on_chat_menu)

    def _on_nb_page(self, event):
        # No hay anuncio nativo del cambio de pestaña: lo decimos a mano.
        idx = event.GetSelection()
        if 0 <= idx < self.nb.GetPageCount():
            anunciar(self.nb.GetPageText(idx))
        event.Skip()

    def _on_resize(self, event):
        event.Skip()
        self._ajustar_ancho_tipo()

    def _ajustar_ancho_tipo(self) -> None:
        """Reajusta el salto de línea de lbl_tipo al ancho disponible: con
        Wrap() fijo, ensanchar o angostar la ventana dejaba el texto cortado
        o con un hueco de sobra en vez de acomodarse."""
        if not hasattr(self, "lbl_tipo"):
            return
        try:
            ancho = max(200, self.lbl_tipo.GetParent().GetClientSize().Width - 20)
            self.lbl_tipo.Wrap(ancho)
        except Exception:
            pass

    def _fijar_tipo(self, texto: str) -> None:
        self.lbl_tipo.SetLabel(texto)
        self._ajustar_ancho_tipo()

    def _on_activate(self, event):
        # Al volver el foco a la app, llevarlo al contenido (chat/comentarios);
        # si aún no hay conexión, al campo de URL.
        if event.GetActive() and self._alive:
            if self._conectado:
                wx.CallAfter(self._foco_contenido)
            else:
                wx.CallAfter(self.txt_url.SetFocus)
        event.Skip()

    def _init_timer(self):
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_timer, self._timer)
        self._timer.Start(TIMER_STATUS_MS)
        self._diagnostico_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_diagnostico_timer, self._diagnostico_timer)
        self._diagnostico_timer.Start(TIMER_DIAGNOSTICO_MS)

    def _arrancar_precalentamiento(self) -> None:
        if self._alive:
            self._rep_panel._precalentar()

    # ── Navegación de paneles ────────────────────────────────────────────────

    def _navegar_region(self, delta: int):
        if not self._conectado:
            self.txt_url.SetFocus()
            anunciar("Conéctate primero para usar los paneles")
            return
        self._region_idx = (self._region_idx + delta) % len(self._regiones)
        self._ir_region(self._region_idx)

    def _ir_region(self, idx: int):
        if not (0 <= idx < len(self._regiones)):
            return
        if idx != REG_CONEXION and not self._conectado:
            anunciar("Conéctate primero para usar los paneles")
            return
        self._region_idx = idx
        try:    self._regiones[idx]()
        except Exception as exc: logger.debug("ir_region %d: %s", idx, exc)
        nombre = _NOMBRE_REGION[idx]
        if idx == REG_CONTENIDO:
            nombre += f": {self.nb.GetPageText(self.nb.GetSelection())}"
        anunciar(nombre)

    def _ir_lista(self):
        """Alt+L: foco directo a la lista de la pestaña actual (chat o comentarios)."""
        if not self._conectado:
            anunciar("Conéctate primero")
            return
        self._region_idx = REG_CONTENIDO
        self._foco_contenido()

    def _foco_contenido(self):
        pag = self.nb.GetCurrentPage()
        if pag is self._pag_chat:
            self.lb_chat.SetFocus()
        elif pag is self._com_panel:
            self._com_panel.anclar_foco()
        elif pag is self._pag_info:
            self.txt_info.SetFocus()
        else:
            self.nb.SetFocus()

    def _ir_pestana(self, idx: int):
        """Selecciona una pestaña del notebook y deja el foco en su contenido."""
        if 0 <= idx < self.nb.GetPageCount():
            self.nb.SetSelection(idx)
            self._region_idx = REG_CONTENIDO
            self._foco_contenido()
            anunciar(self.nb.GetPageText(idx))

    def _rep_accion(self, metodo: str, *args):
        try:
            getattr(self._rep_panel, metodo)(*args)
        except Exception as exc:
            logger.debug("acción reproductor %s: %s", metodo, exc)

    def _toggle_botones_rep(self):
        """Desde el menú: alterna los botones del reproductor. El panel avisa de
        vuelta (on_botones_toggle → _on_botones_rep_cambio) para sincronizar."""
        try:    self._rep_panel.alternar_botones()
        except Exception as exc:
            logger.debug("alternar botones reproductor: %s", exc)

    def _on_botones_rep_cambio(self, visibles: bool):
        """El panel cambió la visibilidad de los botones (por su interruptor o por
        el menú): sincronizar la casilla del menú y guardar la preferencia."""
        try:    self.mi_rep_botones.Check(bool(visibles))
        except Exception: pass
        self._config["mostrar_botones_reproductor"] = bool(visibles)
        guardar_opcion(RUTA_CONFIG, "ui", "mostrar_botones_reproductor",
                       "true" if visibles else "false")

    # ── Historial de directos ────────────────────────────────────────────────

    def _ruta_historial(self):
        return app_dir() / "historial_lives.json"

    def registrar_historial(self, plataforma: str, clave: str, url: str,
                            titulo: str, canal: str, directo: bool = False) -> None:
        """Guarda (o actualiza) una entrada del historial al conectar con éxito.
        Lo llama main vía wx.CallAfter cuando ya tiene título y canal."""
        if not self._alive or not clave:
            return
        try:
            ruta = self._ruta_historial()
            lista = historial.upsert(historial.cargar(ruta), plataforma, clave,
                                     url, titulo, canal, directo=directo)
            historial.guardar(ruta, lista)
        except Exception as exc:
            logger.debug("registrar historial: %s", exc)

    def _on_historial(self):
        from gui_historial import abrir_historial
        abrir_historial(self, self._ruta_historial(),
                        self._reconectar_desde_historial)

    def _reconectar_desde_historial(self, url: str) -> None:
        """Desde el historial: si hay una sesión, desconecta; luego pone la URL
        elegida y conecta."""
        if not url:
            return
        if self._conectado:
            if self.on_desconectar_cb:
                try:    self.on_desconectar_cb()
                except Exception: pass
            self.set_conectado(False)
        self.txt_url.SetValue(url)
        wx.CallAfter(self._on_conectar, None)

    # ── Handlers de conexión ─────────────────────────────────────────────────

    def _conectar_si_procede(self):
        if not self._conectado:
            self._on_conectar(None)

    def _desconectar_si_procede(self):
        if self._conectado:
            self._on_conectar(None)

    def _on_conectar(self, event):
        if self._conectado:
            if self.on_desconectar_cb:
                self.on_desconectar_cb()
            self.set_conectado(False)
        else:
            url = self.txt_url.GetValue().strip()
            if not url:
                wx.MessageBox("Introduce una URL o ID de YouTube.",
                              "Falta URL", wx.OK | wx.ICON_WARNING, self)
                self.txt_url.SetFocus()
                return
            self.btn_conectar.SetLabel("Conectando...")
            self.btn_conectar.Disable()
            self.mi_conectar.Enable(False)
            self.txt_url.Disable()
            _snd.reproducir("conectando")
            anunciar("Conectando")
            if self.on_conectar_cb:
                self.on_conectar_cb(url)

    def url_invalida(self):
        """La URL/ID no es válida: restaurar la UI y avisar (sin esperas)."""
        if not self._alive:
            return
        _snd.reproducir("error")
        self._set_conectado_ui(False)
        anunciar("La URL o el ID de YouTube no es válido")
        self.txt_url.SetFocus()
        wx.MessageBox("La URL o el ID de YouTube no es válido. Revisa lo que pegaste.",
                      "URL no válida", wx.OK | wx.ICON_WARNING, self)

    def _on_preferencias(self, event):
        try:
            from gui_preferencias import abrir_preferencias
            if abrir_preferencias(self, self._config):
                self._aplicar_preferencias_en_caliente()
        except Exception as exc:
            logger.warning("No se pudo abrir preferencias: %s", exc)
            wx.MessageBox(f"No se pudo abrir Preferencias:\n{exc}",
                          "Error", wx.OK | wx.ICON_ERROR, self)
        # La pestaña API puede haber cambiado la sesión: refrescar.
        self._actualizar_estado_online()

    def _on_transmision(self, event):
        from gui_transmision import abrir_transmision
        abrir_transmision(self, self._cambiar_overlay)

    def _on_obs_micro(self, event):
        def _alternar():
            gestor = None
            try:
                gestor = GestorPanelObs()
                gestor.conectar()
                fuente = obs_audio.elegir_microfono(
                    gestor.fuentes_audio(), self._config.get("obs_microfono", ""))
                silenciada = gestor.alternar_silencio(fuente) if fuente else False
                texto = obs_audio.frase_microfono(fuente, silenciada)
            except Exception:
                texto = ("OBS no responde. En OBS, menú Herramientas, Configuración "
                         "del servidor WebSocket, activa el servidor.")
            finally:
                if gestor is not None:
                    try:
                        gestor.cerrar()
                    except Exception:
                        pass
            wx.CallAfter(anunciar, texto, "microfono")

        diagnostico.crear_hilo(_alternar, "MicrofonoObs").start()

    # ── Gestor de descargas (gui_descargas) ──────────────────────────────────
    # Abre el diálogo siempre (no requiere conexión). Si le llega una URL, la
    # precarga (caso "Descargar este vídeo"). Importamos gui_descargas perezoso
    # para que el ciclo de imports (gui → gui_descargas → gui) no se queje.

    def _abrir_descargas(self, url: str | None = None) -> None:
        try:
            from gui_descargas import abrir
        except Exception as exc:
            logger.warning("No se pudo abrir el gestor de descargas: %s", exc)
            wx.MessageBox(f"No se pudo abrir el gestor de descargas:\n{exc}",
                          "Error", wx.OK | wx.ICON_ERROR, self)
            return
        try:
            abrir(self, url_inicial=url)
        except Exception as exc:
            logger.warning("gestor de descargas: %s", exc)
            wx.MessageBox(f"Error en el gestor de descargas:\n{exc}",
                          "Error", wx.OK | wx.ICON_ERROR, self)

    def _aplicar_preferencias_en_caliente(self):
        # Reconstruir atajos y menú por si cambiaron las teclas.
        self._atajos = parsear_atajos(self._config.get("atajos_raw", {}))
        try:
            # Solo los radio items: si no había voces, el submenú tiene un item
            # deshabilitado «(no disponible)» que no debe repoblarse como voz.
            voces_actuales = [it.GetItemLabelText()
                              for it in self.voz_submenu.GetMenuItems()
                              if it.GetKind() == wx.ITEM_RADIO]
        except Exception:
            voces_actuales = []
        self._build_menubar()
        # Restaurar submenú de voz y filtro tras reconstruir (con lista vacía,
        # poblar_voces repone el item «(no disponible)»).
        self.poblar_voces(voces_actuales, self._voz_idx)
        if voces_actuales:
            # Preferencias puede haber cambiado la voz: aplicarla en caliente.
            try:
                idx_cfg = _resolver_idx_voz(self._config.get("voz", "0"), voces_actuales)
                if idx_cfg != self._voz_idx:
                    self._aplicar_voz(idx_cfg)
            except Exception as exc:
                logger.debug("aplicar voz desde preferencias: %s", exc)
        self._marcar_filtro()
        self._sincronizar_checks()
        # Reconstruir la lista por si cambió "quitar emojis" o el filtro.
        self._rebuild_listbox()
        # Restaurar estado de los items de conexión y del envío al chat tras
        # reconstruir el menú.
        self._set_conectado_ui(self._conectado)
        self._actualizar_estado_online()
        # Tamaño de fuente del chat.
        try:
            pt = int(self._config.get("tamanio_fuente_chat", 12))
            self.lb_chat.SetFont(wx.Font(pt, wx.FONTFAMILY_DEFAULT,
                                         wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        except Exception:
            pass
        # Panel de información del vídeo: mostrar u ocultar la pestaña.
        try:
            self.set_metadatos_visible(bool(self._config.get("mostrar_metadatos", True)))
        except Exception:
            pass
        # Botones del reproductor: aplicar la preferencia al panel (que a su vez
        # sincroniza la casilla del menú vía on_botones_toggle).
        try:
            self._rep_panel.set_botones_visibles(
                bool(self._config.get("mostrar_botones_reproductor", False)))
        except Exception:
            pass
        self._actualizar_vigilante_obs()
        anunciar("Preferencias aplicadas")

    def _actualizar_vigilante_obs(self):
        activos = set(self._config.get("estado_toggles") or ())
        if _OBS_COMPONENTES.intersection(activos):
            if self._obs_vigilante is None:
                self._obs_vigilante = obs_vigilante.VigilanteObs()
                self._obs_vigilante.iniciar()
        elif self._obs_vigilante is not None:
            self._obs_vigilante.detener()
            self._obs_vigilante = None

    def _on_about(self, event):
        wx.MessageBox(
            f"{APP_NAME} v{APP_VERSION}\n\n"
            "Lector accesible del chat de YouTube Live con voz SAPI5.",
            "Acerca de", wx.OK | wx.ICON_INFORMATION, self)

    def _on_marcar_incidencia(self, event):
        diagnostico.marcar_incidencia()
        anunciar("La marca de incidencia se guardó")

    # ── Handlers de voz / TTS ────────────────────────────────────────────────

    def _on_pausa(self, event):
        self._worker.toggle_pausa()
        pausado = self._worker.esta_pausado()
        self.mi_pausa.SetItemLabel(
            ("&Reanudar lectura" if pausado else "&Pausar lectura") + self._accel("pausa"))
        _snd.reproducir("pausa" if pausado else "reanudar")
        anunciar("Pausado" if pausado else "Reanudado")

    def _on_vaciar(self, event):
        self._worker.vaciar_cola()
        _snd.reproducir("cola_vaciada")
        anunciar("Cola vaciada")

    def _on_detener_tts(self, event):
        self._worker.detener_actual()
        anunciar("TTS detenido")

    def _aplicar_voz(self, idx: int):
        self._worker.cambiar_voz(idx)
        self._voz_idx = idx
        try:    self._voz_nombre = self._nombre_voz(idx)
        except Exception: self._voz_nombre = "—"
        # Marcar el radio del submenú: al clicar lo hace wx solo, pero si
        # llegamos aquí desde Preferencias hay que marcarlo a mano.
        try:    self.voz_submenu.FindItemByPosition(idx).Check(True)
        except Exception: pass
        self._config["voz"] = str(idx)
        guardar_opcion(RUTA_CONFIG, "voz", "voz", str(idx))
        _snd.reproducir("voz_cambiada")
        anunciar(f"Voz: {self._voz_nombre}")

    def _nombre_voz(self, idx: int) -> str:
        it = self.voz_submenu.FindItemByPosition(idx)
        return it.GetItemLabelText() if it else "—"

    def _aplicar_filtro(self, idx: int):
        self._filtro = FILTROS[idx][1] if idx < len(FILTROS) else None
        self._rebuild_listbox()
        guardar_opcion(RUTA_CONFIG, "ui", "filtro_activo",
                       _NOMBRES_FILTRO[idx] if idx < len(_NOMBRES_FILTRO) else "todos")
        anunciar(f"Filtro: {FILTROS[idx][0]}. {self.lb_chat.GetCount()} mensajes")

    def _ajustar_rate(self, delta):
        # El worker actualiza su contador al instante (aplica a SAPI en su hilo),
        # así que get_rate() ya devuelve el valor nuevo sin predecirlo aquí.
        self._worker.cambiar_rate(delta)
        r = self._worker.get_rate()
        wpm = max(50, min(500, r * 20 + 180))
        guardar_opcion(RUTA_CONFIG, "voz", "velocidad", str(wpm))
        anunciar(f"Velocidad de la voz: {r:+d}")

    def _ajustar_volume(self, delta):
        self._worker.cambiar_volumen(delta)
        v = self._worker.get_volume()
        guardar_opcion(RUTA_CONFIG, "voz", "volumen", f"{v / 100:.2f}")
        anunciar(f"Volumen de la voz: {v}%")

    def _toggle_silenciar_sonidos(self):
        nuevo = not _snd.esta_silenciado()
        _snd.silenciar_todo(nuevo)
        self._config["silenciar_sonidos"] = nuevo
        self.mi_sil_sonidos.Check(nuevo)
        guardar_opcion(RUTA_CONFIG, "ui", "silenciar_sonidos", "true" if nuevo else "false")
        anunciar("Sonidos silenciados" if nuevo else "Sonidos activados")

    def _toggle_silenciar_lectura(self):
        nuevo = not self._config.get("silenciar_lectura", False)
        self._config["silenciar_lectura"] = nuevo
        self.mi_sil_lectura.Check(nuevo)
        guardar_opcion(RUTA_CONFIG, "sesion", "silenciar_lectura", "true" if nuevo else "false")
        anunciar("Lectura TTS silenciada" if nuevo else "Lectura TTS activada")

    def _snapshot_sesion(self) -> estado_sesion.SnapshotSesion:
        """Reúne el estado actual para F2. Los datos del vídeo salen de los
        metadatos capturados al conectar (título, canal, espectadores)."""
        # Tipo: hay que distinguir TikTok de YouTube (ambos son LIVE por dentro).
        if self._conectado and self._es_tiktok:
            tipo = "live_tiktok"
        elif self._tipo_video == deteccion.LIVE:
            tipo = "live_youtube"
        elif self._tipo_video == deteccion.VOD:
            tipo = "vod"
        elif self._tipo_video == deteccion.UPCOMING:
            tipo = "upcoming"
        else:
            tipo = ""
        meta = self._metadatos or {}
        espectadores = meta.get("vistas")
        try:    espectadores = int(espectadores) if espectadores is not None else None
        except (TypeError, ValueError): espectadores = None
        def _seguro(fn, defecto):
            try:    return fn()
            except Exception: return defecto
        vigilante = getattr(self, "_obs_vigilante", None)
        estado_obs = _seguro(lambda: vigilante.estado(), None) if vigilante else None
        transmision = estado_obs.transmision if estado_obs else None
        grabacion = estado_obs.grabacion if estado_obs else None
        return estado_sesion.SnapshotSesion(
            conectado=self._conectado,
            tipo=tipo,
            titulo=self._titulo_stream,
            canal=(meta.get("canal") or "").strip(),
            espectadores=espectadores,
            segundos_directo=_seguro(lambda: int(time.time() - datetime.fromisoformat(
                meta["comienzo_directo"].replace("Z", "+00:00")).timestamp()), None),
            mensajes_leidos=_seguro(lambda: self._stats.leidos, 0),
            aportes=_seguro(lambda: self._stats.superchats, 0),
            total_aportes=self._total_aportes_texto(),
            en_cola=_seguro(lambda: self._cola.qsize(), 0),
            voz_velocidad=_seguro(lambda: self._worker.get_rate(), 0),
            voz_volumen=_seguro(lambda: self._worker.get_volume(), 0),
            lectura_silenciada=bool(self._config.get("silenciar_lectura", False)),
            overlay_puerto=overlay_servidor.puerto_actual(),
            overlay_clientes=overlay_servidor.cuantos_miran(),
            programados_proximo=(
                programados.describir_proximo(self._mensajes_programados, time.time())
                if self._config.get("programados_activo", False) else ""),
            descartados=descartes.frase_estado(
                _seguro(lambda: self._stats.descartados, 0)),
            obs_transmision=(obs_estado.frase_transmision(
                transmision["outputActive"], transmision["outputDuration"],
                transmision["outputSkippedFrames"], transmision["outputTotalFrames"])
                if transmision else ""),
            obs_grabacion=(obs_estado.frase_grabacion(
                grabacion["outputActive"], grabacion["outputPaused"],
                grabacion["outputTimecode"]) if grabacion else ""),
            obs_escena=(obs_estado.frase_escena_al_aire(estado_obs.escena)
                        if estado_obs else ""),
        )

    def _total_aportes_texto(self) -> str:
        """Solo el importe acumulado de Super Chats (sin el «SC: n»), para F2."""
        if not self._sc_totales:
            return ""
        if len(self._sc_totales) == 1:
            d, t = next(iter(self._sc_totales.items()))
            return f"{d}{t:.2f}"
        return ", ".join(f"{d}{t:.0f}" for d, t in self._sc_totales.items())

    def _anunciar_estado(self):
        toggles = self._config.get("estado_toggles") or estado_sesion.ACTIVOS_DEFECTO
        texto = estado_sesion.formatear_estado(self._snapshot_sesion(), toggles)
        anunciar(texto or "Sin información de estado.")

    # ── Enviar al chat del directo (API oficial) ─────────────────────────────

    def _on_enviar_live(self, event):
        self._panel_redactar.enfocar()

    def _enviar_live_redactado(self, texto):
        lcid = self._live_chat_id
        self._accion_api(lambda cli: cli.enviar_mensaje_live(lcid, texto),
                         "Mensaje enviado al chat")

    def _puede_escribir_live(self) -> bool:
        if not (youtube_api.google_disponible() and credenciales.hay_sesion()):
            anunciar("Inicia sesión en Configuración de API para usar esta función")
            return False
        if not self._live_chat_id:
            anunciar("No hay un chat en vivo activo en este directo")
            return False
        return True

    def _accion_api(self, accion, mensaje_ok: str, sonido: str = "enviado") -> None:
        anunciar("Enviando")

        def _run():
            try:
                cli = youtube_api.ClienteYouTube(credenciales.cargar())
                accion(cli)
                if cli.token_actualizado():
                    credenciales.guardar_campo("token", cli.token_actualizado())
                wx.CallAfter(self._api_ok, mensaje_ok, sonido)
            except Exception as exc:
                logger.warning("acción API: %s", exc)
                wx.CallAfter(self._api_err, exc)

        import threading
        diagnostico.crear_hilo(_run, "AccionAPI").start()

    def _api_ok(self, mensaje, sonido: str = "enviado"):
        _snd.reproducir(sonido)
        anunciar(mensaje)

    def _api_err(self, exc):
        _snd.reproducir("error")
        msg = youtube_api.mensaje_error_api(exc)
        anunciar(msg)
        wx.MessageBox(msg, "Error de la API", wx.OK | wx.ICON_ERROR, self)

    def _actualizar_estado_online(self):
        self._actualizar_motivo_redaccion()
        try:    self._com_panel.actualizar_estado()
        except Exception: pass

    def _actualizar_motivo_redaccion(self):
        try:
            motivo = redaccion.motivo_chat(
                self._conectado, self._es_tiktok, self._tipo_video == deteccion.LIVE,
                youtube_api.google_disponible(), self._sesion_api_disponible(),
                bool(self._live_chat_id), self._causa_sin_chat)
            self._panel_redactar.establecer_motivo(motivo)
        except Exception:
            pass

    def _sesion_api_disponible(self) -> bool:
        return bool(youtube_api.google_disponible() and credenciales.hay_sesion())

    def _iniciar_programados_si_corresponde(self, ahora: float) -> None:
        if self._programados_reloj_iniciado:
            return
        if not self._config.get("programados_activo", False):
            return
        programados.iniciar_reloj(self._mensajes_programados, ahora, random.randint)
        self._programados_reloj_iniciado = True

    def _enviar_programado(self, mensaje: dict, ahora: float) -> None:
        self._programado_en_curso = True
        lcid = self._live_chat_id
        texto = mensaje.get("texto", "")

        def _run():
            try:
                cli = youtube_api.ClienteYouTube(credenciales.cargar())
                cli.enviar_mensaje_live(lcid, texto)
                if cli.token_actualizado():
                    credenciales.guardar_campo("token", cli.token_actualizado())
                wx.CallAfter(self._programado_enviado, mensaje)
            except Exception as exc:
                logger.warning("mensaje automático: error del servicio: %s", type(exc).__name__)
                wx.CallAfter(self._programado_fallo, exc)

        diagnostico.crear_hilo(_run, "MensajeProgramado").start()

    def _programado_enviado(self, mensaje: dict) -> None:
        self._programado_en_curso = False
        ahora = time.time()
        mensaje["proximo"] = programados.calcular_proximo(
            mensaje.get("minutos_min", 10),
            mensaje.get("minutos_max", mensaje.get("minutos_min", 10)),
            ahora, random.randint)
        self._programados_ultimo_envio = ahora

    def _programado_fallo(self, exc) -> None:
        self._programado_en_curso = False
        if not self._config.get("programados_activo", False):
            return
        self._config["programados_activo"] = False
        anunciar("Los mensajes automáticos se detuvieron por un error del servicio.")

    def _procesar_programado(self) -> None:
        ahora = time.time()
        self._iniciar_programados_si_corresponde(ahora)
        if not self._config.get("programados_activo", False):
            self._programados_reloj_iniciado = False
            return
        if not self._conectado or self._es_tiktok or not self._live_chat_id:
            return
        if not self._sesion_api_disponible():
            return
        if self._programado_en_curso:
            return
        mensaje = programados.elegir_envio(
            self._mensajes_programados, ahora, self._programados_ultimo_envio)
        if mensaje is not None:
            self._enviar_programado(mensaje, ahora)

    def _moderar(self, autor: str, canal_id: str, segundos: int | None) -> None:
        accion = "expulsar 5 minutos a" if segundos else "banear permanentemente a"
        if wx.MessageBox(f"¿Seguro que quieres {accion} {autor}?",
                         "Confirmar moderación",
                         wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
            return
        lcid = self._live_chat_id
        ok = f"{autor} expulsado 5 minutos" if segundos else f"{autor} baneado del directo"
        self._accion_api(
            lambda cli: cli.banear_usuario(lcid, canal_id, segundos), ok,
            sonido="moderacion")

    # ── Atajos sobre la lista de chat ────────────────────────────────────────

    def _copiar_atajo(self):
        if self.lb_chat.GetSelection() == wx.NOT_FOUND:
            anunciar("Sin mensaje seleccionado")
        else:
            self._copiar_mensaje()

    # ── Chat: teclado, menú, copiar, silenciar ───────────────────────────────

    def _on_chat_key(self, event):
        k = event.GetKeyCode()
        if k == ord('C') and event.ControlDown():
            self._copiar_mensaje()
        elif k == wx.WXK_WINDOWS_MENU:
            self._mostrar_menu_chat()
        else:
            # Enter se atiende en EVT_CHAR_HOOK porque wx no lo entrega aquí.
            event.Skip()

    def _on_chat_char_hook(self, event):
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._copiar_mensaje()
        else:
            event.Skip()

    def _on_chat_menu(self, event):
        self._mostrar_menu_chat()

    def _mostrar_menu_chat(self):
        idx = self.lb_chat.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        menu = wx.Menu()

        id_copiar   = wx.NewIdRef()
        id_copiar2  = wx.NewIdRef()
        id_releer   = wx.NewIdRef()
        id_link     = wx.NewIdRef()
        id_sil_tts  = wx.NewIdRef()
        id_sil_full = wx.NewIdRef()
        id_rehab    = wx.NewIdRef()
        id_alias    = wx.NewIdRef()

        menu.Append(id_copiar,  "Copiar mensaje")
        menu.Append(id_copiar2, "Copiar todo (autor: mensaje, hora)")
        menu.Append(id_releer,  "Releer con TTS")
        menu.AppendSeparator()
        menu.Append(id_link,    "Abrir enlace")
        menu.AppendSeparator()

        registro_sel = self._get_selected_data()
        autor = registro_sel.autor if registro_sel else ""
        if autor:
            autor_mostrado = alias.visible(autor)
            if self._autor_esta_silenciado(autor):
                menu.Append(id_rehab, f"Rehabilitar a {autor_mostrado} (dejar de silenciar)")
            else:
                menu.Append(id_sil_tts,  f"Silenciar a {autor_mostrado} (solo TTS)")
                menu.Append(id_sil_full, f"Silenciar a {autor_mostrado} (ocultar y TTS)")
            if alias.clave(autor) not in alias.vigente():
                menu.Append(id_alias, f"Poner &alias a {autor_mostrado}…")
            else:
                menu.Append(id_alias, f"Cambiar el &alias de {autor_mostrado}…")

        id_ban     = wx.NewIdRef()
        id_timeout = wx.NewIdRef()
        plataforma_sel = registro_sel.plataforma if registro_sel else ""
        identificador_sel = registro_sel.identificador if registro_sel else ""
        moderable = bool(autor and plataforma_sel == "youtube" and identificador_sel
                         and self._live_chat_id
                         and youtube_api.google_disponible() and credenciales.hay_sesion())
        if moderable:
            menu.AppendSeparator()
            menu.Append(id_timeout, f"Expulsar 5 min a {autor_mostrado} (timeout)")
            menu.Append(id_ban,     f"Banear a {autor_mostrado} del directo (permanente)")
            menu.Bind(wx.EVT_MENU, lambda e: self._moderar(autor, identificador_sel, 300), id=id_timeout)
            menu.Bind(wx.EVT_MENU, lambda e: self._moderar(autor, identificador_sel, None), id=id_ban)

        # Los handlers van sobre el propio menú (no sobre la ventana): así mueren
        # con él y no se acumulan bindings en cada apertura del menú contextual.
        self._bind_menu((menu, id_copiar), self._copiar_mensaje)
        self._bind_menu((menu, id_copiar2), self._copiar_todo)
        self._bind_menu((menu, id_releer), self._releer_mensaje)
        self._bind_menu((menu, id_link), self._abrir_enlace)
        self._bind_menu((menu, id_sil_tts), self._silenciar_autor, autor, False)
        self._bind_menu((menu, id_sil_full), self._silenciar_autor, autor, True)
        self._bind_menu((menu, id_rehab), self._rehabilitar_autor, autor)
        self._bind_menu((menu, id_alias), self._editar_alias_autor, autor)

        self.lb_chat.PopupMenu(menu)
        menu.Destroy()

    def _editar_alias_autor(self, autor: str) -> None:
        mapa = alias.vigente()
        actual = mapa.get(alias.clave(autor), "")
        dialogo = wx.TextEntryDialog(
            self, f"Alias para {autor}. Dejar vacío para quitarlo.",
            "Alias del usuario", value=actual)
        try:
            if dialogo.ShowModal() != wx.ID_OK:
                return
            nuevo = dialogo.GetValue()
        finally:
            dialogo.Destroy()
            self.lb_chat.SetFocus()

        actualizado = alias.poner(mapa, autor, nuevo)
        alias.guardar(app_dir() / "alias.json", actualizado)
        alias.usar(actualizado)
        self._rebuild_listbox()
        anunciar(f"Alias guardado, {actualizado[alias.clave(autor)]}"
                 if nuevo.strip() else "Alias quitado")

    def _copiar_mensaje(self):
        data = self._get_selected_data()
        if data is None:
            return
        mensaje = data.texto
        self._clipboard_set(mensaje)
        _snd.reproducir("copiar")
        anunciar("Mensaje copiado")

    def _copiar_todo(self):
        data = self._get_selected_data()
        if data is None:
            return
        linea = f"{data.autor}: {data.texto}, {data.hora}"
        if data.monto:
            linea += f" [{data.monto}]"
        self._clipboard_set(linea)
        _snd.reproducir("copiar")
        anunciar("Línea copiada")

    def _releer_mensaje(self):
        data = self._get_selected_data()
        if data is None:
            return
        from tts_worker import construir_tts
        self._cola.put({"texto_tts": construir_tts(data.autor, data.texto, self._config)})

    def _abrir_enlace(self):
        data = self._get_selected_data()
        if data is None:
            return
        urls = _URL_RE.findall(data.texto)
        if not urls:
            anunciar("No se encontró ningún enlace")
            wx.MessageBox("No se encontró ningún enlace en este mensaje.",
                          "Sin enlace", wx.OK | wx.ICON_INFORMATION, self)
            return
        webbrowser.open(urls[0])
        anunciar("Abriendo enlace")

    # ── Silenciado en caliente ───────────────────────────────────────────────

    def _silenciar_autor(self, autor: str, ocultar: bool) -> None:
        if not autor:
            return
        al = autor.lower().strip()
        self._config.setdefault("silenciados_runtime", set()).add(al)
        sil_oculto = self._config.setdefault("silenciados_ocultar", set())
        if ocultar:
            sil_oculto.add(al)
            self._rebuild_listbox()
        else:
            sil_oculto.discard(al)
        anunciar(f"{autor} silenciado")

    def _rehabilitar_autor(self, autor: str) -> None:
        if not autor:
            return
        al = autor.lower().strip()
        self._config.setdefault("silenciados_runtime", set()).discard(al)
        self._config.setdefault("silenciados_ocultar", set()).discard(al)
        self._rebuild_listbox()
        anunciar(f"{autor} rehabilitado")

    def _autor_esta_silenciado(self, autor: str) -> bool:
        return autor.lower().strip() in self._config.get("silenciados_runtime", set())

    def _autor_esta_oculto(self, autor: str) -> bool:
        return autor.lower().strip() in self._config.get("silenciados_ocultar", set())

    def _autor_seleccionado(self) -> str | None:
        data = self._get_selected_data()
        return data.autor if data else None

    # ── Selección y portapapeles ─────────────────────────────────────────────

    def _get_selected_data(self):
        idx = self.lb_chat.GetSelection()
        if idx == wx.NOT_FOUND:
            return None
        return self._chat.dato_en_fila(idx)

    def _clipboard_set(self, text: str) -> None:
        copiar_al_portapapeles(text)

    # ── Cierre y timer ───────────────────────────────────────────────────────

    def _on_close(self, event):
        if self._apagando:
            return
        self._apagando = True
        self._alive = False
        self._diagnostico_parada.set()
        self._actualizar_vigilante_obs_cierre()
        try:    self._timer.Stop()
        except Exception: pass
        if self._pendientes_timer is not None:
            try:    self._pendientes_timer.Stop()
            except Exception: pass
            self._pendientes_timer = None
        hilos_previos = diagnostico.hilos_vivos_de_la_aplicacion()
        if apagado.hilos_captura_vivos(hilos_previos):
            anunciar("Cerrando")
        try:    self.Hide()
        except Exception: pass
        if self.on_desconectar_cb:
            try:    self.on_desconectar_cb()
            except Exception: pass
        self._parada.set()
        overlay_servidor.apagar()
        try:
            self._rep_panel.detener_todo()
        except Exception: pass
        try:
            # Interrumpir lo que se esté leyendo (purga) antes de parar, para que
            # el cierre sea inmediato y no termine el mensaje en curso.
            self._worker.detener_actual()
            self._worker.detener()
        except Exception: pass
        try:    _snd.cerrar()
        except Exception: pass
        self._cierre_inicio = time.monotonic()
        self._cierre_tope = apagado.TOPE_ESPERA_CIERRE
        self._comprobar_cierre()

    def _actualizar_vigilante_obs_cierre(self):
        vigilante = getattr(self, "_obs_vigilante", None)
        if vigilante is not None:
            vigilante.detener()
            self._obs_vigilante = None

    def _comprobar_cierre(self):
        nombres = diagnostico.hilos_vivos_de_la_aplicacion()
        transcurrido = time.monotonic() - self._cierre_inicio
        if apagado.hay_que_seguir_esperando(nombres, transcurrido, self._cierre_tope):
            wx.CallLater(200, self._comprobar_cierre)
            return
        diagnostico.logger.log(apagado.nivel_registro_cierre(nombres),
            "%s", apagado.componer_resultado_cierre(nombres, self._cierre_tope))
        if not nombres:
            diagnostico.registrar_cierre_fallos()
        self.Destroy()

    def _on_timer(self, event):
        if self._alive:
            try:    self._actualizar_sb()
            except Exception: pass
            try:    self._procesar_programado()
            except Exception: pass
            try:    self._avisar_descartes()
            except Exception: pass

    def _avisar_descartes(self) -> None:
        if descartes.hay_que_avisar(self._stats.descartados,
                                    self._descartes_avisado):
            anunciar(descartes.frase_aviso(
                self._config.get("umbral_solo_nombre", 0)))
            self._descartes_avisado = True

    def _on_diagnostico_timer(self, event):
        if not self._alive:
            return
        ahora = time.monotonic()
        self._diagnostico_marca = ahora
        censo = diagnostico.debe_censar_hilos(self._diagnostico_censo, ahora)
        if censo:
            self._diagnostico_censo, texto = censo
            diagnostico.logger.info("%s", texto)

    # ── API pública (main.py la invoca vía wx.CallAfter) ─────────────────────

    def agregar_mensaje_chat(self, autor: str, mensaje: str, hora: str,
                             tipo: str = TIPO_TEXTO, monto: str = "",
                             canal_id: str = "", plataforma: str = "") -> None:
        if not self._alive:
            return
        # Si ya no estamos conectados, descartar: puede ser un mensaje rezagado
        # de un hilo de captura anterior (bloqueado en una lectura de red) que
        # llega tras desconectar. Si no, se solaparía con el directo siguiente.
        # La captura solo emite mensajes tras «conectado», así que en uso normal
        # esto no descarta nada legítimo.
        if not self._conectado:
            return
        # No tocar self._chat/lb_chat aquí: se encola y se procesa en el
        # volcado agrupado (ver _volcar_pendientes) para no disparar un
        # Append/Delete por mensaje mientras NVDA navega la lista.
        registro = MensajeChat(
            plataforma=plataforma, autor=autor, identificador=canal_id,
            texto=mensaje, hora=hora, tipo=tipo, monto=monto)
        self._pendientes.append(registro)
        # Si el temporizador ya corre, NO reiniciarlo: con un chat activo
        # (mensajes cada menos de MS_VOLCADO_CHAT) reiniciar pospondría el
        # volcado indefinidamente y no aparecería nada hasta una pausa.
        if self._pendientes_timer is None:
            self._pendientes_timer = wx.CallLater(MS_VOLCADO_CHAT, self._volcar_pendientes)

    def _procesar_mensaje_chat(self, registro: MensajeChat) -> bool:
        """Aplica UN mensaje ya desencolado al modelo y a lb_chat. Devuelve si
        quedó visible (se le hizo Append). Solo lo llama _volcar_pendientes."""
        if self._autor_esta_oculto(registro.autor):
            return False

        # El modelo (lista_chat) recorta el historial y nos dice cuántas filas
        # viejas borrar por arriba, manteniendo fila ↔ mensaje siempre alineados
        # (antes se descontaba dos veces y, pasados 500 mensajes, copiar o
        # banear caían sobre el mensaje equivocado).
        visible = self._filtro is None or registro.tipo == self._filtro
        borrar = self._chat.agregar(registro, visible)
        for _ in range(borrar):
            self.lb_chat.Delete(0)

        if registro.tipo in (TIPO_SUPERCHAT, TIPO_STICKER):
            _snd.reproducir("superchat")
            self._sumar_superchat(registro.monto)
        elif registro.tipo == TIPO_MIEMBRO:
            _snd.reproducir("nuevo_miembro")
        else:
            _snd.reproducir("mensaje_nuevo")

        if visible:
            self.lb_chat.Append(self._format_display(
                registro.autor, registro.texto, registro.hora, registro.tipo, registro.monto))
        return visible

    def _volcar_pendientes(self) -> None:
        """Procesa TODOS los mensajes en espera de una vez: modelo y vista se
        mutan juntos aquí (nunca al encolar), así que fila↔mensaje se mantienen
        alineados igual que antes. Con más de un pendiente, Freeze/Thaw evita
        repintar fila a fila."""
        self._pendientes_timer = None
        pendientes, self._pendientes = self._pendientes, []
        if not pendientes or not self._alive or not self._conectado:
            return
        freeze = len(pendientes) > 1
        if freeze:
            self.lb_chat.Freeze()
        hubo_visible = False
        try:
            for registro in pendientes:
                if self._procesar_mensaje_chat(registro):
                    hubo_visible = True
        finally:
            if freeze:
                self.lb_chat.Thaw()
        # Un solo SetFirstItem al final (no uno por mensaje), y solo si el foco
        # no está en la lista (si el usuario está navegando, no le movemos la
        # vista) y algo se añadió de verdad.
        if hubo_visible and wx.Window.FindFocus() is not self.lb_chat:
            self.lb_chat.SetFirstItem(self.lb_chat.GetCount() - 1)

    def _flush_pendientes_ahora(self) -> None:
        """Vuelca ya lo encolado, sin esperar el temporizador. Se usa antes de
        leer/reconstruir la lista desde self._chat (cambio de filtro) para que
        no falte lo más reciente todavía sin procesar."""
        if self._pendientes_timer is not None:
            try:    self._pendientes_timer.Stop()
            except Exception: pass
            self._pendientes_timer = None
        self._volcar_pendientes()

    def _descartar_pendientes(self) -> None:
        """Tira lo encolado sin procesarlo. Se usa donde hoy se limpia la lista
        entera (desconectar, cambiar de vídeo): esos mensajes pertenecen a la
        sesión que se está borrando."""
        if self._pendientes_timer is not None:
            try:    self._pendientes_timer.Stop()
            except Exception: pass
            self._pendientes_timer = None
        self._pendientes.clear()

    def set_conectado(self, conectado: bool) -> None:
        if not self._alive:
            return
        estaba = self._conectado
        self._conectado = conectado
        if conectado:
            if not estaba:
                self._mostrar_zona(True)
                self._region_idx = REG_CONTENIDO
                self._anunciar_conectado()
                wx.CallAfter(self._foco_contenido)
        else:
            self._reiniciar_datos_sesion()
            # Solo si veníamos de una conexión real: ocultar, sonar y avisar.
            # (Un fallo de conexión nunca llegó a "conectado", así que no suena.)
            if estaba:
                self._mostrar_zona(False)
                self.set_titulo_stream("")
                self._fijar_tipo(MENSAJE_INICIAL)
                _snd.reproducir("desconectado")
                anunciar("Desconectado")
                # Sacar el foco del panel del reproductor ANTES de que quede
                # oculto: si el foco sigue dentro, wx tarda en repintar y el
                # panel «se queda» visible hasta que tabulas. Al campo URL.
                wx.CallAfter(self.txt_url.SetFocus)
        self._set_conectado_ui(conectado)
        self._actualizar_estado_online()

    def _reiniciar_datos_sesion(self) -> None:
        """Borra TODO el estado de la sesión para que volver a conectar sea como
        recién abierta la app y nada del directo anterior se solape: chat,
        comentarios, reproductor, cola de lectura, super chats y contadores. NO
        toca las preferencias del usuario (filtro, voz, sonidos, tema)."""
        self._live_chat_id = ""
        self._causa_sin_chat = ""
        self._tipo_video = deteccion.DESCONOCIDO
        self._es_tiktok = False
        self._descartes_avisado = False
        # Chat: datos, lista visible y lo que aún estaba en cola sin volcar (es
        # de la sesión que se cierra; no debe colarse en la siguiente).
        self._descartar_pendientes()
        self._chat.limpiar()
        try:    self.lb_chat.Clear()
        except Exception: pass
        # Super Chats acumulados de la sesión.
        self._sc_totales.clear()
        # Panel de información del vídeo.
        self._metadatos = {}
        try:    self.txt_info.SetValue("")
        except Exception: pass
        # Reproductor y panel de comentarios.
        try:    self._rep_panel.detener_todo()
        except Exception: pass
        try:    self._com_panel.limpiar()
        except Exception: pass
        # Cola de lectura y lo que se esté leyendo ahora mismo.
        try:
            self._worker.vaciar_cola()
            self._worker.detener_actual()
        except Exception: pass
        # Contadores a cero.
        try:    self._stats.reset()
        except Exception: pass
        self._actualizar_sb()

    def _mostrar_zona(self, mostrar: bool) -> None:
        self._zona.Show(mostrar)
        self._panel_principal.Layout()

    def _anunciar_conectado(self) -> None:
        t = self._tipo_video
        if t == deteccion.LIVE:
            msg = "Conectado al directo. Leyendo el chat en vivo."
        elif t == deteccion.UPCOMING:
            msg = "Directo programado. Aún no hay chat; puedes ver los comentarios."
        elif t == deteccion.VOD:
            msg = "Vídeo conectado. Comentarios y reproductor disponibles."
        else:
            msg = "Conectado."
        anunciar(msg)

    def set_live_chat_id(self, live_chat_id: str, causa: str = "") -> None:
        if not self._alive:
            return
        self._live_chat_id = live_chat_id or ""
        self._causa_sin_chat = causa or ""
        self._actualizar_estado_online()

    def set_espectadores(self, n: int) -> None:
        """Actualiza el conteo de espectadores en vivo (TikTok lo refresca cada
        pocos segundos). Así F2 dice cuántos hay AHORA, no solo al conectar."""
        if not self._alive:
            return
        try:    self._metadatos["vistas"] = int(n)
        except Exception: pass

    def set_inicio_directo(self, comienzo: str) -> None:
        if not self._alive:
            return
        self._metadatos["comienzo_directo"] = comienzo or ""

    def set_tipo_video(self, tipo: str, video_id: str) -> None:
        if not self._alive:
            return
        self._tipo_video = tipo
        self._es_tiktok = False   # esta ruta es la de YouTube
        # Empezar el chat en limpio en cada conexión: el reset al desconectar ya
        # lo hace, pero así garantizamos que nunca quede nada del vídeo anterior.
        self._descartar_pendientes()
        self._chat.limpiar()
        self._sc_totales.clear()
        try:    self.lb_chat.Clear()
        except Exception: pass
        es_live = deteccion.tiene_chat_en_vivo(tipo)
        autoplay = bool(self._config.get("autoplay_reproductor", True))
        # Comentarios: autocargar solo cuando no hay chat en vivo (en un directo
        # no queremos saturar). Reproductor: siempre, con autoplay según prefs.
        try:    self._com_panel.set_video(video_id, autocargar=not es_live)
        except Exception: pass
        try:    self._rep_panel.set_video(video_id, autoplay=autoplay)
        except Exception: pass

        if tipo == deteccion.LIVE:
            self._fijar_tipo("Directo en vivo: leyendo el chat.")
            self.nb.SetSelection(PAG_CHAT)
        elif tipo == deteccion.UPCOMING:
            self._fijar_tipo("Directo programado: aún sin chat. Hay comentarios.")
            self.nb.SetSelection(PAG_COMENTARIOS)
        elif tipo == deteccion.VOD:
            self._fijar_tipo("Vídeo subido: comentarios y reproductor.")
            self.nb.SetSelection(PAG_COMENTARIOS)
        else:
            self._fijar_tipo("Tipo no determinado: intentando leer el chat.")

    def configurar_tiktok(self, usuario: str, url_flujo: str) -> None:
        """Prepara la ventana para un directo de TikTok: chat en limpio, pestaña
        de chat al frente, comentarios fuera (TikTok no los tiene aquí) y el
        reproductor con la URL HLS directa. Lo llama main vía wx.CallAfter."""
        if not self._alive:
            return
        self._tipo_video = deteccion.LIVE
        self._es_tiktok = True
        self._descartar_pendientes()
        self._chat.limpiar()
        self._sc_totales.clear()
        try:    self.lb_chat.Clear()
        except Exception: pass
        try:    self._com_panel.mostrar_no_disponible(
                    "Los comentarios no están disponibles en los directos de TikTok.")
        except Exception: pass
        autoplay = bool(self._config.get("autoplay_reproductor", True))
        try:    self._rep_panel.set_flujo(url_flujo, autoplay=autoplay)
        except Exception as exc: logger.debug("reproductor tiktok: %s", exc)
        self._fijar_tipo(f"Directo de TikTok de @{usuario}: leyendo el chat.")
        self.nb.SetSelection(PAG_CHAT)

    def set_url(self, url: str) -> None:
        self.txt_url.SetValue(url)

    def set_metadatos(self, meta: dict) -> None:
        """Rellena el panel de información con lo que trae yt-dlp. Se llama desde
        el hilo de conexión vía wx.CallAfter; el panel puede estar oculto por
        preferencia (igual guardamos el texto, para que aparezca ya hecho si lo
        muestran)."""
        if not self._alive:
            return
        self._metadatos = meta or {}
        try:
            self.txt_info.SetValue(metadatos.formatear(self._metadatos))
            self.txt_info.SetInsertionPoint(0)   # que el lector empiece arriba
        except Exception as exc:
            logger.debug("set_metadatos: %s", exc)

    def _idx_pag_info(self) -> int:
        for i in range(self.nb.GetPageCount()):
            if self.nb.GetPage(i) is self._pag_info:
                return i
        return -1

    def set_metadatos_visible(self, visible: bool) -> None:
        """Añade o quita la pestaña de Información según la preferencia. Al
        ocultarla NO se destruye el panel, así reaparece con su contenido."""
        idx = self._idx_pag_info()
        if visible and idx == -1:
            self.nb.AddPage(self._pag_info, "Información")
            self._pag_info.Show()
        elif not visible and idx != -1:
            self.nb.RemovePage(idx)
            self._pag_info.Hide()
        self._zona.Layout()

    def set_titulo_stream(self, titulo: str) -> None:
        if not self._alive:
            return
        self._titulo_stream = (titulo or "").strip()
        if self._titulo_stream:
            # Formato tipo navegador: «Nombre del vídeo — YTChat TTS».
            self.SetTitle(f"{self._titulo_stream} — {APP_NAME}")
        else:
            self.SetTitle(f"{APP_NAME} v{APP_VERSION}")

    def auto_conectar(self) -> None:
        self._on_conectar(None)

    def poblar_voces(self, voces: list, idx_actual: int = 0) -> None:
        # Vaciar el submenú de voz y reconstruir con radio items.
        for it in list(self.voz_submenu.GetMenuItems()):
            self.voz_submenu.Delete(it)
        if not voces:
            it = self.voz_submenu.Append(wx.ID_ANY, "(no disponible)")
            it.Enable(False)
            self._voz_nombre = "—"
            return
        for i, nombre in enumerate(voces):
            it = self.voz_submenu.AppendRadioItem(wx.ID_ANY, nombre)
            self._bind_menu(it, self._aplicar_voz, i)
        idx_actual = idx_actual if 0 <= idx_actual < len(voces) else 0
        self.voz_submenu.FindItemByPosition(idx_actual).Check(True)
        self._voz_idx = idx_actual
        self._voz_nombre = voces[idx_actual]

    def _marcar_filtro(self):
        idx = _IDX_FILTRO.get(
            _NOMBRES_FILTRO[0] if self._filtro is None else "", 0)
        # Buscar el índice cuyo valor coincide con self._filtro.
        for i, (_, val) in enumerate(FILTROS):
            if val == self._filtro:
                idx = i
                break
        if 0 <= idx < len(self.fi_items):
            self.fi_items[idx].Check(True)

    def _sincronizar_checks(self):
        try:    self.mi_sil_sonidos.Check(_snd.esta_silenciado())
        except Exception: pass
        try:    self.mi_sil_lectura.Check(self._config.get("silenciar_lectura", False))
        except Exception: pass

    # ── Formato y helpers ────────────────────────────────────────────────────

    def _format_display(self, autor, msg, hora, tipo, monto):
        autor = alias.visible(autor)
        # Si "quitar emojis" está activo, también se ocultan en la lista (incluye
        # los shortcodes :nombre: de YouTube). Los marcadores 💲🎨⭐ se conservan.
        if self._config.get("limpiar_emojis", True):
            from tts_worker import quitar_emojis
            msg = quitar_emojis(msg)
        if tipo == TIPO_SUPERCHAT and monto:
            return f"💲 [{monto}] {autor}: {msg}, {hora}"
        if tipo == TIPO_STICKER and monto:
            return f"🎨 [{monto}] {autor}, {hora}"
        if tipo == TIPO_MIEMBRO:
            return f"⭐ NUEVO MIEMBRO: {autor}, {hora}"
        if tipo == TIPO_ENTRADA:
            return f"👋 {autor} entró, {hora}"
        return f"{autor}: {msg}, {hora}"

    def _rebuild_listbox(self) -> None:
        # Que lo que acaba de llegar (aún en cola, sin pasar por self._chat) no
        # se pierda del recuento/reconstrucción: se procesa YA con el estado
        # vigente antes de leer el modelo.
        self._flush_pendientes_ahora()
        self.lb_chat.Clear()
        visibles = self._chat.reconstruir(
            lambda it: not self._autor_esta_oculto(it.autor)
            and (self._filtro is None or it.tipo == self._filtro))
        for registro in visibles:
            self.lb_chat.Append(self._format_display(
                registro.autor, registro.texto, registro.hora, registro.tipo, registro.monto))

    def _set_conectado_ui(self, conectado: bool) -> None:
        # Botón (toggle), items de menú Conectar/Desconectar y campo URL. El
        # resto (ocultar zona, sonido, título) lo gestiona set_conectado.
        self.btn_conectar.SetLabel("&Desconectar" if conectado else "&Conectar")
        self.btn_conectar.Enable()
        self.mi_conectar.Enable(not conectado)
        self.mi_desconectar.Enable(conectado)
        self.txt_url.Enable(not conectado)
        self._actualizar_menus_por_conexion()

    def _actualizar_menus_por_conexion(self) -> None:
        """Deshabilita en la barra de menú lo que solo aplica con una conexión
        activa: navegar por paneles, el filtro y las acciones de voz sobre una
        lectura en curso. Así el usuario no llega por el menú a paneles que no
        existen aún. Los ajustes de voz y «Ir a URL» /
        «Anunciar estado» quedan siempre disponibles.

        El ítem «Descargar este vídeo» sigue las reglas del diseño: solo se
        habilita con conexión YouTube NO-live (TikTok y live están deshabilitados
        en v1). Si la URL no se puede obtener del reproductor, se deshabilita."""
        con = bool(self._conectado)
        for it in getattr(self, "_mi_ver_conexion", []):
            try:    it.Enable(con)
            except Exception: pass
        try:    self._mi_filtro_sub.Enable(con)
        except Exception: pass
        for it in getattr(self, "_mi_voz_conexion", []):
            try:    it.Enable(con)
            except Exception: pass

        # Descargar este vídeo: YouTube + conexión + no live + URL disponible.
        # El panel del reproductor gestiona sus propios avisos, pero afinamos
        # el ítem para que:
        #   - TikTok → off (es TikTok, no YouTube)
        #   - Live   → off (out of scope v1, ver spec R: Live y TikTok off)
        #   - sin URL → off (no hay nada que descargar)
        try:
            descargar_este_on = False
            if con and not self._es_tiktok and getattr(self, "_rep_panel", None):
                try:
                    if not self._rep_panel.get_es_live():
                        descargar_este_on = bool(self._rep_panel.get_url_para_descarga())
                except Exception:
                    descargar_este_on = False
            if hasattr(self, "mi_descargar_este"):
                self.mi_descargar_este.Enable(descargar_este_on)
        except Exception as exc:
            logger.debug("enable mi_descargar_este: %s", exc)

    def _actualizar_sb(self) -> None:
        sin_tts = " [sin TTS]" if self._config.get("silenciar_lectura", False) else ""
        if self._conectado and self._titulo_stream:
            estado = f"Conectado: {self._titulo_stream[:35]}{sin_tts}"
        elif self._conectado:
            estado = f"Conectado{sin_tts}"
        else:
            estado = f"Desconectado{sin_tts}"
        self.sb.SetStatusText(estado, 0)

        try:    self.sb.SetStatusText(f"Voz vel: {self._worker.get_rate():+d}", 1)
        except Exception: self.sb.SetStatusText("Voz vel: --", 1)

        nombre = self._voz_nombre or "—"
        if len(nombre) > 28:
            nombre = nombre[:25] + "..."
        self.sb.SetStatusText(f"Voz: {nombre}", 2)

        try:    self.sb.SetStatusText(f"Cola: {self._cola.qsize()}", 3)
        except Exception: self.sb.SetStatusText("Cola: —", 3)
        try:    self.sb.SetStatusText(f"Leídos: {self._stats.leidos}", 4)
        except Exception: self.sb.SetStatusText("Leídos: —", 4)

        try:    self.sb.SetStatusText(f"Voz vol: {self._worker.get_volume()}%", 5)
        except Exception: self.sb.SetStatusText("Voz vol: --", 5)

        if self._config.get("mostrar_total_superchats", True):
            self.sb.SetStatusText(self._formato_total_sc(), 6)
        else:
            self.sb.SetStatusText("", 6)

    # ── Acumulación de Super Chats ───────────────────────────────────────────

    def _sumar_superchat(self, monto: str) -> None:
        from montos import parsear_monto
        r = parsear_monto(monto)
        if r is None:
            return
        divisa, valor = r
        self._sc_totales[divisa] = self._sc_totales.get(divisa, 0.0) + valor

    def _formato_total_sc(self) -> str:
        try:    n = self._stats.superchats
        except Exception: n = 0
        if not self._sc_totales:
            return f"SC: {n}"
        if len(self._sc_totales) == 1:
            d, t = next(iter(self._sc_totales.items()))
            return f"SC: {n} ({d}{t:.2f})"
        partes = [f"{d}{t:.0f}" for d, t in self._sc_totales.items()]
        return f"SC: {n} ({', '.join(partes)})"


# ── Portapapeles ─────────────────────────────────────────────────────────────
# Compartido con el panel de comentarios: primero wx y, si falla (p. ej. otro
# proceso tiene el portapapeles abierto), la vía Win32 directa como respaldo.

def copiar_al_portapapeles(text: str) -> None:
    try:
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(text))
                wx.TheClipboard.Flush()
            finally:
                wx.TheClipboard.Close()
            return
    except Exception:
        pass
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        u32 = ctypes.windll.user32
        if not u32.OpenClipboard(0):
            return
        try:
            u32.EmptyClipboard()
            encoded = text.encode("utf-16-le") + b"\x00\x00"
            h = k32.GlobalAlloc(0x0042, len(encoded))
            if not h:
                return
            p = k32.GlobalLock(h)
            if not p:
                k32.GlobalFree(h)
                return
            ctypes.memmove(p, encoded, len(encoded))
            k32.GlobalUnlock(h)
            if not u32.SetClipboardData(13, h):  # CF_UNICODETEXT
                k32.GlobalFree(h)
        finally:
            u32.CloseClipboard()
    except Exception:
        pass


# ── Helpers de voces ─────────────────────────────────────────────────────────

def _listar_voces_sapi5() -> list:
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass
    try:
        import win32com.client
        tts   = win32com.client.Dispatch("SAPI.SpVoice")
        voces = tts.GetVoices()
        return [voces.Item(i).GetDescription() for i in range(voces.Count)]
    except Exception:
        return []


def _resolver_idx_voz(cfg: str, voces: list) -> int:
    try:
        idx = int(cfg)
        return idx if 0 <= idx < len(voces) else 0
    except ValueError:
        t = str(cfg).lower()
        for i, v in enumerate(voces):
            if t in v.lower():
                return i
        return 0


# ── Entrada ──────────────────────────────────────────────────────────────────

_gui_frame: YTChatFrame | None = None


class AplicacionYTChat(wx.App):
    def OnInit(self):
        self.Bind(wx.EVT_END_SESSION, self._on_fin_sesion)
        # Hay que guardar la referencia en la app, si el recolector la libera
        # wx queda llamando a memoria liberada
        try:
            self._wx_log = _LogWx()
            wx.Log.SetActiveTarget(self._wx_log)
        except Exception as exc:
            logger.warning("No se pudo instalar el registro de wx: %s", exc)
        return True

    def OnAssert(self, archivo, linea, condicion, mensaje):
        # En un ejecutable empaquetado las aserciones de wx se pierden enteras.
        logger.warning("wx aserción archivo=%s línea=%s condición=%s mensaje=%s",
                       archivo, linea, condicion, mensaje)

    def _on_fin_sesion(self, event):
        if _gui_frame is not None:
            _gui_frame._on_close(event)


def iniciar_gui(config, cola, stats, worker, parada,
                url_inicial: str = "",
                iniciar_captura_cb=None,
                detener_captura_cb=None) -> None:
    global _gui_frame, RUTA_CONFIG

    RUTA_CONFIG = app_dir() / "config.ini"
    _ao2_init()

    app = AplicacionYTChat(redirect=False)
    frame = YTChatFrame(None, config, cola, stats, worker, parada)
    _gui_frame = frame
    frame.on_conectar_cb    = iniciar_captura_cb
    frame.on_desconectar_cb = detener_captura_cb

    h = WxAnnouncingHandler()
    h.setLevel(logging.INFO)
    logging.getLogger().addHandler(h)

    voces = _listar_voces_sapi5()
    frame.poblar_voces(voces, _resolver_idx_voz(config.get("voz", "0"), voces))

    # Restaurar filtro de la sesión anterior.
    fa = config.get("filtro_activo", "todos")
    idx_f = _IDX_FILTRO.get(fa, 0)
    if 0 <= idx_f < len(FILTROS):
        frame._filtro = FILTROS[idx_f][1]
        frame._marcar_filtro()

    # Restaurar silenciado de sonidos si la sesión anterior lo tenía activo.
    if config.get("silenciar_sonidos", False):
        _snd.silenciar_todo(True)
    frame._sincronizar_checks()

    if url_inicial:
        frame.set_url(url_inicial)

    frame.Show()
    try:
        frame.Raise()
        frame.txt_url.SetFocus()
    except Exception:
        pass
    diagnostico.crear_hilo(
        lambda: _snd.reproducir("app_inicio"), "SonidoInicio").start()
    wx.CallAfter(frame._arrancar_precalentamiento)

    if url_inicial and iniciar_captura_cb:
        wx.CallAfter(frame.auto_conectar)

    app.MainLoop()
    _gui_frame = None

    try:    logging.getLogger().removeHandler(h)
    except Exception: pass
