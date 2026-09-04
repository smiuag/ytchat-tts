"""Diálogo de Preferencias por categorías (accesible).

Reúne en un solo sitio lo que antes solo se editaba a mano en config.ini y
sounds.ini: interfaz (fuente, tema de sonido), lectura, filtros de palabras y
usuarios, y un editor de atajos. Persiste con `config.guardar_opcion` (que
conserva comentarios y orden del INI) y actualiza el dict de config en memoria.
La configuración de API/OAuth sigue en su propio diálogo (Herramientas).
"""

from __future__ import annotations

import logging
import threading
import webbrowser

import wx

import diagnostico
import config as cfg
import atajos_captura
import estado_sesion
import obs_cliente
import obs_activacion
import programados
import sound_player as _snd
import credenciales
import youtube_api
from config import APP_NAME
from gui import ContadorAccesible, anunciar, caja_de_grupo, nombre_accesible
from obs_panel import GestorPanelObs

logger = diagnostico.obtener_logger(__name__)


# El diálogo de Preferencias usa apariencia NATIVA (sin el tema oscuro de la
# ventana principal). Motivo de accesibilidad: en Windows, poner un color
# personalizado a una casilla o radio la convierte en un control «owner-drawn»
# que NVDA anuncia como botón y sin su estado (marcada/no marcada). Sombreamos
# aquí el tema y el helper de color para que TODAS las llamadas existentes
# dejen los controles con los colores por defecto del sistema.

class _T:
    bg = surface = field = border = text = dim = accent = gold = green = red = \
        btn = btn_t = wx.NullColour


def _tc(w, bg=None, fg=None):
    pass


URL_GUIA = "https://github.com/miguel-cinsfran/ytchat-tts/blob/main/docs/CONFIGURACION_API.md"

# Ancho al que se parten las notas de cada página. Con 560 desbordaban el área
# visible (unos 490 px) y no hay desplazamiento horizontal.
ANCHO_NOTA = 450
TAMANO_DIALOGO = (720, 600)

_FORMATOS = [
    ("Nombre y mensaje", "nombre_mensaje"),
    ("Mensaje y después el nombre", "mensaje_nombre"),
    ("Solo el mensaje",  "solo_mensaje"),
    ("Solo el nombre",   "solo_nombre"),
]


# ── Captura de atajos (pulsar en vez de escribir) ─────────────────────────────
# Idea tomada del proyecto bellbird del dueño: en vez de teclear el atajo (con
# riesgo de escribirlo mal), se pulsa un botón, se captura la combinación real y
# se valida al vuelo (área correcta y sin conflicto). Así no hay atajos inválidos.

_TECLA_WX_A_TEXTO = {
    wx.WXK_LEFT: "left", wx.WXK_RIGHT: "right", wx.WXK_UP: "up", wx.WXK_DOWN: "down",
    wx.WXK_RETURN: "enter", wx.WXK_NUMPAD_ENTER: "enter", wx.WXK_SPACE: "space",
}
_AREA_AYUDA = {
    "ctrl": "Debe ser Ctrl y una tecla (por ejemplo Ctrl+P).",
    "alt":  "Debe ser Alt y una tecla (por ejemplo Alt+C).",
    "f":    "Debe ser una tecla de función, de F1 a F12.",
}


def _tecla_texto(keycode: int) -> str | None:
    """Nombre de tecla en nuestro formato («left», «f5», «p»…) desde un keycode
    de wx. None si no es una tecla admitida como atajo."""
    if keycode in _TECLA_WX_A_TEXTO:
        return _TECLA_WX_A_TEXTO[keycode]
    if wx.WXK_F1 <= keycode <= wx.WXK_F12:
        return f"f{keycode - wx.WXK_F1 + 1}"
    if 33 <= keycode < 127:   # letras, dígitos y símbolos ASCII
        return chr(keycode).lower()
    return None


def _combo_a_texto(mods: int, keycode: int) -> str | None:
    """(modificadores, keycode) de wx → texto tipo «ctrl+p», «alt+enter», «f5».
    None si la tecla no sirve como atajo. Deja que config valide el resto."""
    tecla = _tecla_texto(keycode)
    if not tecla:
        return None
    partes = []
    if mods & wx.MOD_CONTROL: partes.append("ctrl")
    if mods & wx.MOD_ALT:     partes.append("alt")
    if mods & wx.MOD_SHIFT:   partes.append("shift")
    return "+".join(partes + [tecla]) if partes else tecla


class PreferenciasDialog(wx.Dialog):

    def __init__(self, parent, config: dict):
        # Redimensionable: quien ve poco puede agrandarlo; las páginas se
        # desplazan solas si no caben.
        super().__init__(parent, title="Preferencias", size=TAMANO_DIALOGO,
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
                         name="DialogoPreferencias")
        self._config = config
        self._ruta = cfg.app_dir() / "config.ini"
        self._capturando_atajo = None
        self._iniciar_programados()
        self._cambios = False
        self.SetBackgroundColour(_T.bg)
        self._build_ui()
        self._ajustar_minimo()
        self.Centre()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self):
        panel = wx.Panel(self, name="PanelPreferencias")
        panel.SetBackgroundColour(_T.bg)
        panel.SetForegroundColour(_T.text)
        vs = wx.BoxSizer(wx.VERTICAL)

        # La lista se anuncia sola al recorrerla, a diferencia de las pestañas.
        self.nb = wx.Listbook(panel, name="Categorías de preferencias")
        self.lista_categorias = self.nb.GetListView()
        nombre_accesible(self.lista_categorias, "Categorías")
        _tc(self.lista_categorias, bg=_T.surface)
        self.nb.AddPage(self._pag_voz(self.nb), "Voz")
        self.nb.AddPage(self._pag_lectura(self.nb), "Lectura")
        self.nb.AddPage(self._pag_cola(self.nb), "Cola de lectura")
        self.nb.AddPage(self._pag_interfaz(self.nb), "Interfaz y sonidos")
        self.nb.AddPage(self._pag_reproductor(self.nb), "Reproductor")
        self.nb.AddPage(self._pag_conexion(self.nb), "Conexion")
        self.nb.AddPage(self._pag_filtros(self.nb), "Filtros")
        self.nb.AddPage(self._pag_estado(self.nb), "Estado (F2)")
        self.nb.AddPage(self._pag_atajos(self.nb), "Atajos")
        self.nb.AddPage(self._pag_api(self.nb), "API y sesión")
        self.nb.AddPage(self._pag_programados(self.nb), "Mensajes automáticos")
        self.nb.AddPage(self._pag_transmision(self.nb), "Transmisión")
        self.nb.AddPage(self._pag_diagnostico(self.nb), "Diagnóstico")
        # Mínimo explícito: si no, el libro pide el «mejor tamaño» de la página
        # más alta (Atajos, más de 1200 px) y el sizer lo desbordaría en vez
        # de dejar que la página se desplace.
        self.nb.SetMinSize((320, 240))
        vs.Add(self.nb, 1, wx.EXPAND | wx.ALL, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        btn_guardar = wx.Button(panel, wx.ID_OK, "&Guardar", name="GuardarPreferencias")
        btn_cancelar = wx.Button(panel, wx.ID_CANCEL, "&Cancelar", name="CancelarPreferencias")
        for b in (btn_guardar, btn_cancelar):
            b.SetBackgroundColour(_T.btn)
            b.SetForegroundColour(_T.btn_t)
            row.Add(b, 0, wx.RIGHT, 6)
        vs.Add(row, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        panel.SetSizer(vs)
        btn_guardar.Bind(wx.EVT_BUTTON, self._on_guardar)
        self.lista_categorias.SetFocus()

    def _make_panel(self, parent, name):
        # Página desplazable (solo vertical): la de Atajos mide más de 1200 px
        # y en un wx.Panel fijo dos tercios de sus botones quedaban fuera del
        # alcance del ratón. El foco (Tab) desplaza solo hasta el control.
        p = wx.ScrolledWindow(parent, name=name, style=wx.TAB_TRAVERSAL | wx.VSCROLL)
        p.SetScrollRate(0, 20)
        p.SetBackgroundColour(_T.bg)
        p.SetForegroundColour(_T.text)
        return p

    def _paginas(self):
        return [self.nb.GetPage(i) for i in range(self.nb.GetPageCount())]

    def _ajustar_minimo(self):
        """Ancho mínimo del diálogo: el que deja a la página más ancha entera
        (más la barra de desplazamiento). No hay desplazamiento horizontal,
        así que más angosto se cortarían controles."""
        try:
            self.Layout()
            visible = self.nb.GetPage(0).GetClientSize().width
            necesario = max(p.GetSizer().GetMinSize().width for p in self._paginas())
            barra = wx.SystemSettings.GetMetric(wx.SYS_VSCROLL_X)
            ancho = self.GetSize().width - visible + necesario + barra
            alto = 480
            self.SetMinSize((ancho, alto))
            actual = self.GetSize()
            if actual.width < ancho or actual.height < alto:
                self.SetSize((max(actual.width, ancho), max(actual.height, alto)))
        except Exception as exc:
            logger.debug("mínimo del diálogo de preferencias: %s", exc)

    def _pag_interfaz(self, parent):
        p = self._make_panel(parent, "PagInterfaz")
        vs = wx.BoxSizer(wx.VERTICAL)

        vs.Add(self._fila_label(p, "Tamaño de &fuente del chat (8 a 24):"),
               0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.sp_fuente = ContadorAccesible(p, min=8, max=24,
                                     initial=int(self._config.get("tamanio_fuente_chat", 12)),
                                     name="Tamaño de fuente del chat")
        _tc(self.sp_fuente)
        vs.Add(self.sp_fuente, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        vs.Add(self._fila_label(p, "&Tema de sonido:"), 0, wx.LEFT | wx.RIGHT, 10)
        temas = cfg.listar_temas_sonido()
        self.cho_tema = wx.Choice(p, choices=temas, name="Tema de sonido")
        _tc(self.cho_tema)
        actual = cfg.tema_sonido_actual()
        self.cho_tema.SetSelection(temas.index(actual) if actual in temas else 0)
        vs.Add(self.cho_tema, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.chk_total_sc = wx.CheckBox(p, label="Mostrar el total de &Super Chats en la barra de estado",
                                        name="MostrarTotalSuperChats")
        self.chk_total_sc.SetForegroundColour(_T.text)
        self.chk_total_sc.SetValue(bool(self._config.get("mostrar_total_superchats", True)))
        vs.Add(self.chk_total_sc, 0, wx.ALL, 10)

        self.chk_metadatos = wx.CheckBox(p, label="Mostrar la pestaña de &información del vídeo (canal, vistas, descripción)",
                                         name="MostrarMetadatos")
        self.chk_metadatos.SetForegroundColour(_T.text)
        self.chk_metadatos.SetValue(bool(self._config.get("mostrar_metadatos", True)))
        vs.Add(self.chk_metadatos, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        p.SetSizer(vs)
        return p

    def _pag_cola(self, parent):
        p = self._make_panel(parent, "PagCola")
        vs = wx.BoxSizer(wx.VERTICAL)

        self.rb_estrategia = wx.RadioBox(
            p, label="&Estrategia de la cola", majorDimension=1,
            choices=["Leer todos los mensajes",
                     "Descartar los más viejos si se acumulan"],
            style=wx.RA_SPECIFY_COLS, name="Estrategia de la cola")
        self.rb_estrategia.SetSelection(
            0 if self._config.get("estrategia", "limite") == "todas" else 1)
        vs.Add(self.rb_estrategia, 0, wx.ALL, 10)

        vs.Add(self._fila_label(p, "Tamaño &máximo de la cola"),
               0, wx.LEFT | wx.RIGHT, 10)
        self.sp_cola_maxima = ContadorAccesible(
            p, min=1, max=500,
            initial=int(self._config.get("tamanio_maximo", 15)),
            name="Tamaño máximo de la cola")
        vs.Add(self.sp_cola_maxima, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        vs.Add(self._fila_label(p, "Leer solo el &nombre a partir de"),
               0, wx.LEFT | wx.RIGHT, 10)
        self.sp_umbral_nombre = ContadorAccesible(
            p, min=0, max=500,
            initial=int(self._config.get("umbral_solo_nombre", 0)),
            name="Leer solo el nombre a partir de")
        vs.Add(self.sp_umbral_nombre, 0, wx.LEFT | wx.RIGHT, 10)
        vs.Add(wx.StaticText(p, label="Con 0, esta opción queda apagada."),
               0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        p.SetSizer(vs)
        return p

    def _pag_conexion(self, parent):
        p = self._make_panel(parent, "PagConexion")
        vs = wx.BoxSizer(wx.VERTICAL)

        self.chk_reconectar = wx.CheckBox(
            p, label="&Reconectar automáticamente si se corta",
            name="Reconectar automáticamente si se corta")
        self.chk_reconectar.SetValue(bool(self._config.get("reconectar", True)))
        vs.Add(self.chk_reconectar, 0, wx.ALL, 10)

        vs.Add(self._fila_label(p, "&Espera entre intentos, en segundos"),
               0, wx.LEFT | wx.RIGHT, 10)
        self.sp_espera_reconexion = ContadorAccesible(
            p, min=1, max=300,
            initial=int(self._config.get("espera_entre_intentos", 10)),
            name="Espera entre intentos, en segundos")
        vs.Add(self.sp_espera_reconexion, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        vs.Add(self._fila_label(p, "Número máximo de &intentos"),
               0, wx.LEFT | wx.RIGHT, 10)
        self.sp_max_intentos = ContadorAccesible(
            p, min=0, max=100,
            initial=int(self._config.get("max_intentos", 5)),
            name="Número máximo de intentos")
        vs.Add(self.sp_max_intentos, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        p.SetSizer(vs)
        return p

    def _pag_transmision(self, parent):
        p = self._make_panel(parent, "PagTransmision")
        vs = wx.BoxSizer(wx.VERTICAL)

        vs.Add(self._fila_label(p, "&Puerto del panel de chat"),
               0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.sp_puerto_overlay = ContadorAccesible(
            p, min=1024, max=65535,
            initial=int(self._config.get("overlay_puerto", 8730)),
            name="Puerto del panel de chat")
        vs.Add(self.sp_puerto_overlay, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        vs.Add(self._fila_label(p, "&Micrófono de OBS"),
               0, wx.LEFT | wx.RIGHT, 10)
        guardado = str(self._config.get("obs_microfono", ""))
        opciones = ["Elegir automáticamente"] + ([guardado] if guardado else [])
        self.cho_microfono_obs = wx.Choice(
            p, choices=opciones, name="Micrófono de OBS")
        self.cho_microfono_obs.SetSelection(1 if guardado else 0)
        vs.Add(self.cho_microfono_obs, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.btn_buscar_microfonos = wx.Button(
            p, label="&Buscar los micrófonos en OBS",
            name="Buscar los micrófonos en OBS")
        vs.Add(self.btn_buscar_microfonos, 0, wx.ALL, 10)
        self.btn_buscar_microfonos.Bind(wx.EVT_BUTTON, self._buscar_microfonos)

        self.btn_activar_websocket_obs = wx.Button(
            p, label="&Activar el servidor websocket de OBS",
            name="Activar el servidor websocket de OBS")
        vs.Add(self.btn_activar_websocket_obs, 0, wx.ALL, 10)
        self.btn_activar_websocket_obs.Bind(
            wx.EVT_BUTTON, self._activar_servidor_websocket_obs)

        p.SetSizer(vs)
        return p

    def _pag_diagnostico(self, parent):
        p = self._make_panel(parent, "PagDiagnostico")
        vs = wx.BoxSizer(wx.VERTICAL)
        self.chk_registro_detallado = wx.CheckBox(
            p, label="Guardar un registro &detallado para diagnosticar fallos",
            name="Guardar un registro detallado para diagnosticar fallos")
        self.chk_registro_detallado.SetValue(
            bool(self._config.get("registro_detallado", False)))
        vs.Add(self.chk_registro_detallado, 0, wx.ALL, 10)
        p.SetSizer(vs)
        return p

    def _buscar_microfonos(self, event):
        # Consultar OBS puede tardar o no responder, por eso nunca corre en la interfaz.
        def consultar():
            gestor = None
            try:
                gestor = GestorPanelObs(ajustes=obs_cliente.leer_ajustes())
                gestor.conectar()
                wx.CallAfter(self._microfonos_encontrados, gestor.fuentes_audio())
            except Exception as exc:
                wx.CallAfter(anunciar, obs_cliente.mensaje_de_fallo_obs(exc))
            finally:
                if gestor is not None:
                    try:
                        gestor.cerrar()
                    except Exception:
                        pass

        diagnostico.crear_hilo(consultar, "MicrofonosPrefs").start()

    def _microfonos_encontrados(self, fuentes):
        if not self:   # el diálogo pudo cerrarse mientras OBS respondía
            return
        elegido = self.cho_microfono_obs.GetStringSelection()
        opciones = ["Elegir automáticamente"]
        # La fuente guardada se conserva aunque OBS no responda o ya no la vea.
        for fuente in (elegido, *fuentes):
            if fuente and fuente not in opciones:
                opciones.append(fuente)
        self.cho_microfono_obs.Set(opciones)
        self.cho_microfono_obs.SetStringSelection(elegido or opciones[0])
        anunciar(f"Se encontraron {len(fuentes)} micrófonos en OBS")

    def _activar_servidor_websocket_obs(self, event):
        def activar():
            try:
                accion, mensaje = obs_activacion.decidir_activacion(
                    obs_activacion.obs_esta_en_ejecucion(),
                    obs_cliente.leer_ajustes())
                if accion == obs_activacion.ACTIVAR:
                    mensaje = obs_activacion.activar_servidor(
                        obs_cliente.RUTA_CONFIG_OBS)
            except Exception as exc:
                logger.warning("No se pudo activar el servidor websocket de OBS: %s", exc)
                mensaje = f"No se pudo activar el servidor websocket de OBS: {exc}"
            wx.CallAfter(anunciar, mensaje)

        diagnostico.crear_hilo(activar, "ActivarWebsocketObs").start()

    def _pag_reproductor(self, parent):
        p = self._make_panel(parent, "PagReproductor")
        vs = wx.BoxSizer(wx.VERTICAL)

        self.chk_autoplay = wx.CheckBox(p, label="&Reproducir el audio automáticamente al conectar",
                                        name="AutoplayReproductor")
        self.chk_autoplay.SetForegroundColour(_T.text)
        self.chk_autoplay.SetValue(bool(self._config.get("autoplay_reproductor", True)))
        vs.Add(self.chk_autoplay, 0, wx.ALL, 10)

        self.chk_botones_rep = wx.CheckBox(p, label="Mostrar los &botones del reproductor (también con su interruptor y el menú Reproductor)",
                                           name="MostrarBotonesReproductor")
        self.chk_botones_rep.SetForegroundColour(_T.text)
        self.chk_botones_rep.SetValue(bool(self._config.get("mostrar_botones_reproductor", True)))
        vs.Add(self.chk_botones_rep, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        etiqueta_cache = wx.StaticText(
            p, label="&Tamaño máximo de la caché de vídeo, en megabytes:")
        self.sp_cache_video = wx.SpinCtrl(
            p, min=0, max=20000,
            initial=int(self._config.get("cache_video_mb", 1024)),
            name="Tamaño máximo de la caché de vídeo en megabytes")
        vs.Add(etiqueta_cache, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        vs.Add(self.sp_cache_video, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        p.SetSizer(vs)
        return p

    def _pag_voz(self, parent):
        p = self._make_panel(parent, "PagVoz")
        vs = wx.BoxSizer(wx.VERTICAL)

        # Voz SAPI5. También está en el menú Voz → Seleccionar voz; aquí queda
        # junto al resto de ajustes de lectura para encontrarla más fácil.
        vs.Add(self._fila_label(p, "&Voz de lectura:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        from gui import _listar_voces_sapi5, _resolver_idx_voz
        self._voces = _listar_voces_sapi5()
        self.cho_voz = wx.Choice(p, choices=self._voces or ["(no hay voces disponibles)"],
                                 name="Voz de lectura")
        _tc(self.cho_voz)
        if self._voces:
            self.cho_voz.SetSelection(
                _resolver_idx_voz(self._config.get("voz", "0"), self._voces))
        else:
            self.cho_voz.SetSelection(0)
            self.cho_voz.Disable()
        vs.Add(self.cho_voz, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Multi-voz: una voz distinta para los eventos (Super Chats, regalos,
        # miembros, entradas). Desactivada por defecto.
        self.chk_multivoz = wx.CheckBox(
            p, name="MultiVoz",
            label="Usar una voz &distinta para los eventos (Super Chats, regalos, "
                  "miembros y entradas)")
        self.chk_multivoz.SetForegroundColour(_T.text)
        self.chk_multivoz.SetValue(bool(self._config.get("multivoz", False)))
        vs.Add(self.chk_multivoz, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        vs.Add(self._fila_label(p, "Voz para los &eventos:"), 0, wx.LEFT | wx.RIGHT, 10)
        self.cho_voz_eventos = wx.Choice(
            p, choices=self._voces or ["(no hay voces disponibles)"],
            name="Voz para los eventos")
        _tc(self.cho_voz_eventos)
        if self._voces:
            self.cho_voz_eventos.SetSelection(
                _resolver_idx_voz(self._config.get("voz_eventos", "0"), self._voces))
        else:
            self.cho_voz_eventos.SetSelection(0)
        self.cho_voz_eventos.Enable(bool(self._voces) and self.chk_multivoz.GetValue())
        self.chk_multivoz.Bind(
            wx.EVT_CHECKBOX,
            lambda e: self.cho_voz_eventos.Enable(bool(self._voces) and e.IsChecked()))
        vs.Add(self.cho_voz_eventos, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        p.SetSizer(vs)
        return p

    def _pag_lectura(self, parent):
        p = self._make_panel(parent, "PagLectura")
        vs = wx.BoxSizer(wx.VERTICAL)

        vs.Add(self._fila_label(p, "Qué leer de cada mensaje:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.rb_formato = wx.RadioBox(
            p, choices=[f[0] for f in _FORMATOS], majorDimension=1,
            style=wx.RA_SPECIFY_COLS, name="Formato de lectura")
        self.rb_formato.SetForegroundColour(_T.text)
        self.rb_formato.SetBackgroundColour(_T.bg)
        fa = self._config.get("formato_prefijo", "nombre_mensaje")
        for i, (_, v) in enumerate(_FORMATOS):
            if v == fa:
                self.rb_formato.SetSelection(i)
                break
        vs.Add(self.rb_formato, 0, wx.ALL, 10)

        self.chk_emojis = wx.CheckBox(p, label="&Quitar emojis (no mostrarlos en la lista ni leerlos)",
                                      name="LimpiarEmojis")
        self.chk_urls   = wx.CheckBox(p, label="Quitar &URLs al leer", name="EliminarURLs")
        for c in (self.chk_emojis, self.chk_urls):
            c.SetForegroundColour(_T.text)
        self.chk_emojis.SetValue(bool(self._config.get("limpiar_emojis", True)))
        self.chk_urls.SetValue(bool(self._config.get("eliminar_urls", True)))
        vs.Add(self.chk_emojis, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        vs.Add(self.chk_urls, 0, wx.ALL, 10)

        self.chk_entradas = wx.CheckBox(
            p, name="AnunciarEntradas",
            label="Leer quién &entra al directo (solo TikTok; en directos grandes "
                  "puede ser muchísimo)")
        self.chk_entradas.SetForegroundColour(_T.text)
        self.chk_entradas.SetValue(bool(self._config.get("tiktok_anunciar_entradas", False)))
        vs.Add(self.chk_entradas, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        vs.Add(self._fila_label(p, "&Longitud máxima del mensaje (caracteres):"),
               0, wx.LEFT | wx.RIGHT, 10)
        self.sp_long = ContadorAccesible(p, min=20, max=1000,
                                   initial=int(self._config.get("max_longitud_mensaje", 200)),
                                   name="Longitud máxima del mensaje")
        _tc(self.sp_long)
        vs.Add(self.sp_long, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        p.SetSizer(vs)
        return p

    def _pag_estado(self, parent):
        """Una casilla por componente del anuncio de estado (tecla F2). Sin
        colores en las casillas: en Windows eso rompe su rol accesible."""
        p = self._make_panel(parent, "PagEstado")
        vs = wx.BoxSizer(wx.VERTICAL)

        nota = wx.StaticText(p, name="NotaEstado", label=(
            "Elige qué dice la tecla F2 (estado de sesión). Marca lo que quieras "
            "oír; por defecto, los datos del vídeo y del chat. El orden en que se "
            "dice es fijo."))
        nota.SetForegroundColour(_T.dim)
        nota.Wrap(ANCHO_NOTA)
        vs.Add(nota, 0, wx.ALL, 10)

        activos = self._config.get("estado_toggles") or estado_sesion.ACTIVOS_DEFECTO
        self._chk_estado: dict = {}
        for comp in estado_sesion.COMPONENTES:
            chk = wx.CheckBox(p, label=estado_sesion.ETIQUETAS.get(comp, comp),
                              name=f"EstadoComponente_{comp}")
            chk.SetForegroundColour(_T.text)
            chk.SetValue(comp in activos)
            self._chk_estado[comp] = chk
            vs.Add(chk, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        p.SetSizer(vs)
        return p

    def _pag_filtros(self, parent):
        p = self._make_panel(parent, "PagFiltros")
        vs = wx.BoxSizer(wx.VERTICAL)

        vs.Add(self._fila_label(p, "&Palabras silenciadas (separadas por comas):"),
               0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.txt_palabras = wx.TextCtrl(
            p, value=", ".join(self._config.get("palabras_silenciadas", [])),
            name="Palabras silenciadas")
        _tc(self.txt_palabras)
        vs.Add(self.txt_palabras, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        vs.Add(self._fila_label(p, "&Usuarios silenciados (separados por comas):"),
               0, wx.LEFT | wx.RIGHT, 10)
        self.txt_usuarios = wx.TextCtrl(
            p, value=", ".join(self._config.get("usuarios_silenciados", [])),
            name="Usuarios silenciados")
        _tc(self.txt_usuarios)
        vs.Add(self.txt_usuarios, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        nota = wx.StaticText(p, label=(
            "Estos filtros ocultan y no leen los mensajes que contengan esas "
            "palabras o de esos usuarios. Se aplican a partir del próximo mensaje."),
            name="NotaFiltros")
        nota.SetForegroundColour(_T.dim)
        nota.Wrap(ANCHO_NOTA)
        vs.Add(nota, 0, wx.ALL, 10)

        p.SetSizer(vs)
        return p

    def _pag_atajos(self, parent):
        p = self._make_panel(parent, "PagAtajos")
        vs = wx.BoxSizer(wx.VERTICAL)

        nota = wx.StaticText(p, label=(
            "Cada área tiene su modificador: Ctrl para el reproductor, Alt para "
            "conexión y chat, y teclas F para la voz. Pulsa un botón y luego la "
            "combinación que quieras: se comprueba sola que sea válida y que no "
            "choque con otra. F9 a F12, Alt+F4, F6 y Shift+F6 son fijas. "
            "Las fijas se muestran para que no se puedan pisar."),
            name="NotaAtajos")
        nota.SetForegroundColour(_T.dim)
        nota.Wrap(ANCHO_NOTA)
        vs.Add(nota, 0, wx.ALL, 10)

        # Valores normalizados en memoria (lo que se edita y se guarda).
        raw = self._config.get("atajos_raw", {})
        self._valores_atajo: dict[str, str] = {}
        self._botones_atajo: dict[str, wx.Button] = {}
        for accion, default in cfg.todos_los_atajos_default().items():
            crudo = raw.get(accion, default)
            self._valores_atajo[accion] = (
                default if accion in cfg.ATAJOS_FIJOS
                else cfg._normalizar_atajo(crudo) or "")

        for titulo, acciones in cfg.ATAJOS_GRUPOS:
            box, padre = caja_de_grupo(p, titulo)
            for accion in acciones:
                etiqueta = etiqueta_de_accion(accion)
                fija = accion in cfg.ATAJOS_FIJOS
                valor = self._valores_atajo.get(accion, "")
                sufijo = " (fija)" if fija else ""
                btn = wx.Button(
                    padre, name=f"Atajo_{accion}",
                    label=atajos_captura.etiqueta_boton(etiqueta, valor) + sufijo)
                btn.SetBackgroundColour(_T.btn); btn.SetForegroundColour(_T.btn_t)
                if fija:
                    btn.Disable()
                else:
                    btn.SetToolTip("Pulsa para capturar una nueva combinación.")
                    btn.Bind(wx.EVT_BUTTON,
                             lambda e, a=accion, et=etiqueta: self._capturar_atajo(a, et))
                    btn.Bind(wx.EVT_KILL_FOCUS, self._atajo_perdio_foco)
                self._botones_atajo[accion] = btn
                box.Add(btn, 0, wx.EXPAND | wx.ALL, 4)
            vs.Add(box, 0, wx.EXPAND | wx.ALL, 8)

        btn_restablecer = wx.Button(
            p, label="&Restablecer los atajos a los valores de fábrica",
            name="RestablecerAtajos")
        btn_restablecer.SetBackgroundColour(_T.btn)
        btn_restablecer.SetForegroundColour(_T.btn_t)
        btn_restablecer.Bind(wx.EVT_BUTTON, self._restablecer_atajos)
        vs.Add(btn_restablecer, 0, wx.ALL, 10)

        p.Bind(wx.EVT_CHAR_HOOK, self._on_tecla_captura)
        p.SetSizer(vs)
        return p

    def _capturar_atajo(self, accion, etiqueta):
        self._capturando_atajo = (accion, etiqueta)
        boton = self._botones_atajo[accion]
        boton.SetLabel(f"{etiqueta}: pulsa la combinación")
        anunciar(atajos_captura.texto_de_espera(
            etiqueta, _AREA_AYUDA.get(cfg.ATAJOS_AREA.get(accion), "")))

    def _restaurar_etiqueta_atajo(self, accion, etiqueta):
        valor = self._valores_atajo.get(accion, "")
        sufijo = " (fija)" if accion in cfg.ATAJOS_FIJOS else ""
        self._botones_atajo[accion].SetLabel(
            atajos_captura.etiqueta_boton(etiqueta, valor) + sufijo)

    def _salir_captura_atajo(self, anunciar_cambio=False):
        if self._capturando_atajo is None:
            return
        accion, etiqueta = self._capturando_atajo
        self._capturando_atajo = None
        self._restaurar_etiqueta_atajo(accion, etiqueta)
        if anunciar_cambio:
            anunciar("Sin cambios")

    def _restablecer_atajos(self, event):
        import config_predeterminada as _pred
        for accion, valor in _pred.seccion("atajos").items():
            if accion in cfg.ATAJOS_FIJOS:
                continue
            self._valores_atajo[accion] = valor
            self._restaurar_etiqueta_atajo(accion, etiqueta_de_accion(accion))
        anunciar("Atajos restablecidos a los valores de fábrica")

    def _atajo_perdio_foco(self, event):
        self._salir_captura_atajo()
        event.Skip()

    def _on_tecla_captura(self, event):
        if self._capturando_atajo is None:
            event.Skip()
            return
        k = event.GetKeyCode()
        mods = event.GetModifiers()
        if k == wx.WXK_ESCAPE:
            self._salir_captura_atajo(True)
            return
        if k in (wx.WXK_SHIFT, wx.WXK_CONTROL, wx.WXK_ALT, wx.WXK_RAW_CONTROL):
            return
        if k == wx.WXK_TAB and mods == wx.MOD_NONE:
            self._salir_captura_atajo()
            event.Skip()
            return
        accion, etiqueta = self._capturando_atajo
        if k in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and mods == wx.MOD_NONE:
            estado, valor, texto = atajos_captura.resolver(
                accion, None, self._valores_atajo)
        else:
            combo = _combo_a_texto(mods, k)
            estado, valor, texto = atajos_captura.resolver(
                accion, combo, self._valores_atajo)
        anunciar(texto)
        if estado == "rechazado":
            wx.MessageBox(texto, APP_NAME, wx.OK | wx.ICON_ERROR, self)
            boton = self._botones_atajo[accion]
            boton.SetFocus()
            self._capturar_atajo(accion, etiqueta)
            return
        self._valores_atajo[accion] = valor
        self._capturando_atajo = None
        self._restaurar_etiqueta_atajo(accion, etiqueta)

    def _pag_api(self, parent):
        p = self._make_panel(parent, "PagApi")
        self._login_en_curso = False
        vs = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(p, name="IntroApi", label=(
            "La API key permite LEER comentarios (sin iniciar sesión). El cliente "
            "OAuth e iniciar sesión permiten MODERAR el chat, enviar mensajes al "
            "directo y publicar o responder comentarios."))
        intro.SetForegroundColour(_T.dim)
        intro.Wrap(ANCHO_NOTA)
        vs.Add(intro, 0, wx.ALL, 10)

        if not youtube_api.google_disponible():
            aviso = wx.StaticText(p, name="AvisoLibreriasApi", label=(
                "AVISO: faltan las librerías de la API. Instálalas con:\n"
                "pip install google-api-python-client google-auth-oauthlib"))
            aviso.SetForegroundColour(_T.red)
            vs.Add(aviso, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        datos = credenciales.cargar()
        grid = wx.FlexGridSizer(3, 2, 8, 8)
        grid.AddGrowableCol(1, 1)
        self.txt_api = self._fila_api(p, grid, "&API key:", "API key de YouTube",
                                      datos.get("api_key", ""))
        self.txt_cid = self._fila_api(p, grid, "ID de &cliente OAuth:",
                                      "ID de cliente OAuth", datos.get("oauth_client_id", ""))
        self.txt_secret = self._fila_api(p, grid, "&Secreto de cliente OAuth:",
                                         "Secreto de cliente OAuth",
                                         datos.get("oauth_client_secret", ""), password=True)
        vs.Add(grid, 0, wx.EXPAND | wx.ALL, 10)

        self.lbl_estado_api = wx.StaticText(p, name="EstadoSesion", label="")
        self.lbl_estado_api.SetForegroundColour(_T.accent)
        vs.Add(self.lbl_estado_api, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_api_guardar = wx.Button(p, label="&Guardar claves", name="GuardarClaves")
        self.btn_api_login   = wx.Button(p, label="&Iniciar sesión", name="IniciarSesion")
        self.btn_api_logout  = wx.Button(p, label="Cerrar s&esión", name="CerrarSesion")
        self.btn_api_guia    = wx.Button(p, label="Abrir g&uía", name="AbrirGuia")
        for b in (self.btn_api_guardar, self.btn_api_login, self.btn_api_logout, self.btn_api_guia):
            b.SetBackgroundColour(_T.btn)
            b.SetForegroundColour(_T.btn_t)
            row.Add(b, 0, wx.RIGHT, 6)
        vs.Add(row, 0, wx.ALL, 10)

        p.SetSizer(vs)
        self.btn_api_guardar.Bind(wx.EVT_BUTTON, self._api_guardar)
        self.btn_api_login.Bind(wx.EVT_BUTTON, self._api_login)
        self.btn_api_logout.Bind(wx.EVT_BUTTON, self._api_logout)
        self.btn_api_guia.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open(URL_GUIA))
        self._api_refrescar_estado()
        return p

    def _iniciar_programados(self):
        self._ruta_programados = cfg.app_dir() / "mensajes_programados.json"
        self._mensajes_programados = programados.cargar(self._ruta_programados)

    def _pag_programados(self, parent):
        p = self._make_panel(parent, "PagProgramados")
        vs = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(p, name="IntroProgramados", label=(
            "Envía mensajes al chat de tu directo cada cierto tiempo. Necesita "
            "sesión de Google iniciada y un directo de YouTube conectado. El "
            "intervalo mínimo son 5 minutos y cada mensaje admite 200 caracteres. "
            "YouTube suele bloquear los enlaces en el chat en vivo: conviene "
            "escribir el nombre de usuario en vez de la dirección completa."))
        intro.SetForegroundColour(_T.dim)
        intro.Wrap(ANCHO_NOTA)
        vs.Add(intro, 0, wx.ALL, 10)

        self.chk_programados = wx.CheckBox(
            p, label="&Activar los mensajes automáticos", name="ActivarProgramados")
        self.chk_programados.SetValue(bool(self._config.get("programados_activo", False)))
        vs.Add(self.chk_programados, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.lista_programados = wx.ListBox(p, choices=[
            programados.describir_mensaje(m) for m in self._mensajes_programados
        ], name="ListaProgramados")
        vs.Add(self.lista_programados, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        vs.Add(self._fila_label(p, "&Texto del mensaje"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.txt_programado = wx.TextCtrl(p, name="TextoProgramado")
        self.txt_programado.SetMaxLength(200)
        vs.Add(self.txt_programado, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        vs.Add(self._fila_label(p, "Cada, &mínimo (minutos)"), 0, wx.LEFT | wx.RIGHT, 10)
        self.sp_min_programado = ContadorAccesible(
            p, min=5, max=240, initial=10, name="MinutosMin")
        vs.Add(self.sp_min_programado, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        vs.Add(self._fila_label(p, "y &máximo (minutos)"), 0, wx.LEFT | wx.RIGHT, 10)
        self.sp_max_programado = ContadorAccesible(
            p, min=5, max=240, initial=10, name="MinutosMax")
        vs.Add(self.sp_max_programado, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.chk_mensaje_activo = wx.CheckBox(
            p, label="&Enviar este mensaje", name="MensajeActivo")
        vs.Add(self.chk_mensaje_activo, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_programado_agregar = wx.Button(p, label="&Agregar", name="AgregarProgramado")
        self.btn_programado_guardar = wx.Button(
            p, label="&Guardar cambios", name="GuardarProgramado")
        self.btn_programado_quitar = wx.Button(p, label="&Quitar", name="QuitarProgramado")
        for boton in (self.btn_programado_agregar, self.btn_programado_guardar,
                      self.btn_programado_quitar):
            boton.SetBackgroundColour(_T.btn)
            boton.SetForegroundColour(_T.btn_t)
            fila.Add(boton, 0, wx.RIGHT, 6)
        vs.Add(fila, 0, wx.ALL, 10)

        p.SetSizer(vs)
        self.lista_programados.Bind(wx.EVT_LISTBOX, self._programado_elegido)
        self.btn_programado_agregar.Bind(wx.EVT_BUTTON, self._agregar_programado)
        self.btn_programado_guardar.Bind(wx.EVT_BUTTON, self._guardar_programado)
        self.btn_programado_quitar.Bind(wx.EVT_BUTTON, self._quitar_programado)
        return p

    def _programado_elegido(self, event):
        indice = self.lista_programados.GetSelection()
        if indice != wx.NOT_FOUND:
            mensaje = self._mensajes_programados[indice]
            self.txt_programado.SetValue(mensaje.get("texto", ""))
            self.sp_min_programado.SetValue(mensaje.get("minutos_min", 10))
            self.sp_max_programado.SetValue(mensaje.get("minutos_max", 10))
            self.chk_mensaje_activo.SetValue(mensaje.get("activo", False))
            anunciar(programados.describir_mensaje(mensaje))
        event.Skip()

    def _datos_programado(self):
        return {
            "texto": self.txt_programado.GetValue(),
            "minutos_min": self.sp_min_programado.GetValue(),
            "minutos_max": self.sp_max_programado.GetValue(),
            "activo": self.chk_mensaje_activo.GetValue(),
            "proximo": 0.0,
        }

    def _validar_programado(self, mensaje):
        error, aviso = programados.validar_mensaje(
            mensaje["texto"], mensaje["minutos_min"], mensaje["minutos_max"])
        if error:
            anunciar(error)
            if not mensaje["texto"].strip() or len(mensaje["texto"]) > programados.MAX_CARACTERES:
                self.txt_programado.SetFocus()
            elif mensaje["minutos_min"] < programados.MINUTOS_MINIMOS:
                self.sp_min_programado.SetFocus()
            else:
                self.sp_max_programado.SetFocus()
            return False
        if aviso:
            anunciar(aviso)
        return True

    def _refrescar_programados(self, indice=-1):
        self.lista_programados.Set([programados.describir_mensaje(m)
                                    for m in self._mensajes_programados])
        if indice >= 0:
            self.lista_programados.SetSelection(indice)

    def _agregar_programado(self, event):
        mensaje = self._datos_programado()
        if not self._validar_programado(mensaje):
            return
        self._mensajes_programados.append(mensaje)
        programados.guardar(self._ruta_programados, self._mensajes_programados)
        self._refrescar_programados(len(self._mensajes_programados) - 1)
        anunciar("Mensaje agregado")

    def _guardar_programado(self, event):
        indice = self.lista_programados.GetSelection()
        if indice == wx.NOT_FOUND:
            anunciar("Elige primero un mensaje de la lista")
            return
        mensaje = self._datos_programado()
        if not self._validar_programado(mensaje):
            return
        mensaje["proximo"] = self._mensajes_programados[indice].get("proximo", 0.0)
        self._mensajes_programados[indice] = mensaje
        programados.guardar(self._ruta_programados, self._mensajes_programados)
        self._refrescar_programados(indice)
        anunciar("Mensaje guardado")

    def _quitar_programado(self, event):
        indice = self.lista_programados.GetSelection()
        if indice == wx.NOT_FOUND:
            anunciar("Elige primero un mensaje de la lista")
            return
        self._mensajes_programados.pop(indice)
        programados.guardar(self._ruta_programados, self._mensajes_programados)
        self._refrescar_programados(min(indice, len(self._mensajes_programados) - 1))
        anunciar("Mensaje quitado")

    def _fila_api(self, p, grid, etiqueta, nombre, valor, password=False):
        lbl = wx.StaticText(p, label=etiqueta)
        lbl.SetForegroundColour(_T.text)
        estilo = wx.TE_PASSWORD if password else 0
        txt = wx.TextCtrl(p, value=valor or "", style=estilo, name=nombre)
        _tc(txt)
        grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(txt, 1, wx.EXPAND)
        return txt

    def _api_refrescar_estado(self):
        if credenciales.hay_sesion():
            texto = "Estado: sesión iniciada. Moderación y comentarios activos."
            self.btn_api_logout.Enable()
        else:
            texto = "Estado: sin sesión. Solo lectura de comentarios (si hay API key)."
            self.btn_api_logout.Disable()
        if not youtube_api.google_disponible():
            self.btn_api_login.Disable()
        self.lbl_estado_api.SetLabel(texto)

    def _api_guardar(self, event):
        credenciales.guardar_campo("api_key", self.txt_api.GetValue().strip())
        credenciales.guardar_campo("oauth_client_id", self.txt_cid.GetValue().strip())
        credenciales.guardar_campo("oauth_client_secret", self.txt_secret.GetValue().strip())
        _snd.reproducir("copiar")
        anunciar("Claves guardadas")
        self._api_refrescar_estado()

    def _api_login(self, event):
        if self._login_en_curso:
            return
        cid = self.txt_cid.GetValue().strip()
        secret = self.txt_secret.GetValue().strip()
        if not (cid and secret):
            wx.MessageBox("Rellena el ID y el secreto de cliente OAuth antes de "
                          "iniciar sesión.", "Faltan datos", wx.OK | wx.ICON_WARNING, self)
            return
        self._api_guardar(None)
        self._login_en_curso = True
        self.btn_api_login.Disable()
        anunciar("Abriendo el navegador para iniciar sesión. Autoriza y vuelve aquí.")

        def _run():
            try:
                token = youtube_api.iniciar_sesion(cid, secret)
                credenciales.guardar_campo("token", token)
                wx.CallAfter(self._api_login_ok)
            except Exception as exc:
                logger.warning("Login OAuth falló: %s", exc)
                wx.CallAfter(self._api_login_err, exc)

        diagnostico.crear_hilo(_run, "OAuthLogin").start()

    def _api_login_ok(self):
        if not self:   # el diálogo pudo cerrarse mientras se autorizaba
            return
        self._login_en_curso = False
        self.btn_api_login.Enable()
        _snd.reproducir("conectado")
        anunciar("Sesión iniciada correctamente.")
        self._api_refrescar_estado()

    def _api_login_err(self, exc):
        if not self:
            return
        self._login_en_curso = False
        self.btn_api_login.Enable()
        _snd.reproducir("error")
        anunciar("No se pudo iniciar sesión.")
        wx.MessageBox(f"No se pudo iniciar sesión:\n\n{exc}", "Error de inicio de sesión",
                      wx.OK | wx.ICON_ERROR, self)

    def _api_logout(self, event):
        credenciales.cerrar_sesion()
        _snd.reproducir("desconectado")
        anunciar("Sesión cerrada.")
        self._api_refrescar_estado()

    def _fila_label(self, p, texto):
        lbl = wx.StaticText(p, label=texto)
        lbl.SetForegroundColour(_T.accent)
        return lbl

    # ── Guardar ───────────────────────────────────────────────────────────────

    def _set(self, seccion, clave, valor):
        cfg.guardar_opcion(self._ruta, seccion, clave, valor)
        self._cambios = True

    def _on_guardar(self, event):
        c = self._config
        registro_detallado_inicial = bool(c.get("registro_detallado", False))
        # Los atajos ya vienen validados desde la captura (área + conflicto), así
        # que aquí solo se guardan; no hace falta revalidar por escritura.

        # Interfaz
        programados_activo = self.chk_programados.GetValue()
        self._set("programados", "activo", "true" if programados_activo else "false")
        c["programados_activo"] = programados_activo

        fuente = str(self.sp_fuente.GetValue())
        self._set("ui", "tamanio_fuente_chat", fuente)
        c["tamanio_fuente_chat"] = int(fuente)

        total_sc = self.chk_total_sc.GetValue()
        self._set("ui", "mostrar_total_superchats", "true" if total_sc else "false")
        c["mostrar_total_superchats"] = total_sc

        autoplay = self.chk_autoplay.GetValue()
        self._set("ui", "autoplay_reproductor", "true" if autoplay else "false")
        c["autoplay_reproductor"] = autoplay

        metadatos = self.chk_metadatos.GetValue()
        self._set("ui", "mostrar_metadatos", "true" if metadatos else "false")
        c["mostrar_metadatos"] = metadatos

        botones_rep = self.chk_botones_rep.GetValue()
        self._set("ui", "mostrar_botones_reproductor", "true" if botones_rep else "false")
        c["mostrar_botones_reproductor"] = botones_rep

        cache_video = self.sp_cache_video.GetValue()
        self._set("ui", "cache_video_mb", str(cache_video))
        c["cache_video_mb"] = cache_video

        tema = self.cho_tema.GetStringSelection()
        if tema and tema != cfg.tema_sonido_actual():
            cfg.guardar_opcion(cfg.app_dir() / "sounds.ini", "sonidos", "tema", tema)
            try:    _snd.cargar(cfg.cargar_sonidos())
            except Exception as exc: logger.warning("recargar sonidos: %s", exc)
            self._cambios = True

        # Lectura
        if self._voces:
            idx_voz = max(0, self.cho_voz.GetSelection())
            self._set("voz", "voz", str(idx_voz))
            c["voz"] = str(idx_voz)
            idx_ev = max(0, self.cho_voz_eventos.GetSelection())
            self._set("voz", "voz_eventos", str(idx_ev))
            c["voz_eventos"] = str(idx_ev)

        multivoz = self.chk_multivoz.GetValue()
        self._set("voz", "multivoz", "true" if multivoz else "false")
        c["multivoz"] = multivoz

        formato = _FORMATOS[self.rb_formato.GetSelection()][1]
        self._set("lectura", "formato_prefijo", formato)
        c["formato_prefijo"] = formato

        emojis = self.chk_emojis.GetValue()
        self._set("texto", "limpiar_emojis", "true" if emojis else "false")
        c["limpiar_emojis"] = emojis
        urls = self.chk_urls.GetValue()
        self._set("texto", "eliminar_urls", "true" if urls else "false")
        c["eliminar_urls"] = urls

        entradas = self.chk_entradas.GetValue()
        self._set("tiktok", "anunciar_entradas", "true" if entradas else "false")
        c["tiktok_anunciar_entradas"] = entradas
        longitud = str(self.sp_long.GetValue())
        self._set("texto", "max_longitud_mensaje", longitud)
        c["max_longitud_mensaje"] = int(longitud)

        # Se guarda la clave, no la etiqueta, porque config.ini solo admite estas claves.
        estrategia = ("todas", "limite")[self.rb_estrategia.GetSelection()]
        self._set("cola", "estrategia", estrategia)
        c["estrategia"] = estrategia
        tamanio_maximo = int(self.sp_cola_maxima.GetValue())
        self._set("cola", "tamanio_maximo", str(tamanio_maximo))
        c["tamanio_maximo"] = tamanio_maximo
        umbral_solo_nombre = int(self.sp_umbral_nombre.GetValue())
        self._set("cola", "umbral_solo_nombre", str(umbral_solo_nombre))
        c["umbral_solo_nombre"] = umbral_solo_nombre

        reconectar = self.chk_reconectar.GetValue()
        self._set("reconexion", "reconectar", "true" if reconectar else "false")
        c["reconectar"] = reconectar
        espera_entre_intentos = int(self.sp_espera_reconexion.GetValue())
        self._set("reconexion", "espera_entre_intentos", str(espera_entre_intentos))
        c["espera_entre_intentos"] = espera_entre_intentos
        max_intentos = int(self.sp_max_intentos.GetValue())
        self._set("reconexion", "max_intentos", str(max_intentos))
        c["max_intentos"] = max_intentos

        registro_detallado = self.chk_registro_detallado.GetValue()
        self._set("diagnostico", "registro_detallado",
                  "true" if registro_detallado else "false")
        c["registro_detallado"] = registro_detallado
        puerto_anterior = int(c.get("overlay_puerto", 8730))
        puerto_overlay = int(self.sp_puerto_overlay.GetValue())
        self._set("overlay", "puerto", str(puerto_overlay))
        c["overlay_puerto"] = puerto_overlay
        microfono_obs = ("" if self.cho_microfono_obs.GetSelection() == 0
                         else self.cho_microfono_obs.GetStringSelection())
        self._set("obs", "microfono", microfono_obs)
        c["obs_microfono"] = microfono_obs

        # Estado (F2): una clave por componente + el set en memoria.
        activos = set()
        for comp, chk in self._chk_estado.items():
            on = chk.GetValue()
            self._set("estado", comp, "true" if on else "false")
            if on:
                activos.add(comp)
        c["estado_toggles"] = activos

        # Filtros
        palabras = self.txt_palabras.GetValue().strip()
        self._set("filtros", "palabras_silenciadas", palabras)
        c["palabras_silenciadas"] = _lista(palabras)
        usuarios = self.txt_usuarios.GetValue().strip()
        self._set("filtros", "usuarios_silenciados", usuarios)
        c["usuarios_silenciados"] = _lista(usuarios)

        # Atajos: los valores capturados (ya normalizados y validados).
        raw = c.setdefault("atajos_raw", {})
        for accion, valor in self._valores_atajo.items():
            if accion in cfg.ATAJOS_FIJOS:
                continue
            self._set("atajos", accion, valor)
            raw[accion] = valor

        _snd.reproducir("copiar")
        anunciar("Preferencias guardadas")
        if registro_detallado != registro_detallado_inicial:
            anunciar("El cambio del registro detallado se aplica al reiniciar la aplicación")
        # El servidor del panel ya escucha en el puerto viejo; no se reinicia
        # solo, así que se avisa dónde se aplica.
        if puerto_overlay != puerto_anterior and c.get("overlay_activo", False):
            anunciar("El puerto nuevo del panel de chat se aplica al apagarlo y "
                     "volver a encenderlo desde el panel de transmisión")
        self.EndModal(wx.ID_OK)

    def hubo_cambios(self) -> bool:
        return self._cambios


_ETIQUETAS_ATAJO = {
    # Reproductor
    "rep_play":          "Reproducir o pausa",
    "rep_retro":         "Retroceder 1 minuto",
    "rep_avanz":         "Avanzar 1 minuto",
    "rep_detener":       "Detener vídeo",
    "rep_mute":          "Silenciar o activar audio",
    "rep_vol_menos":     "Bajar volumen del reproductor",
    "rep_vol_mas":       "Subir volumen del reproductor",
    "descargas_abrir":   "Abrir el gestor de descargas",
    "pantalla_completa": "Pantalla completa",
    "abrir_preferencias": "Abrir Preferencias",
    "abrir_historial":    "Abrir el historial de directos",
    "marcar_incidencia":  "Marcar incidencia",
    "abrir_transmision":  "Abrir Transmisión",
    "obs_micro":          "Silenciar el micrófono de OBS",
    # Conexión y chat
    "conectar":          "Conectar",
    "desconectar":       "Desconectar",
    "enviar_chat":       "Enviar mensaje al chat",
    "ir_lista":          "Ir a la lista del panel actual",
    "salir":             "Salir de la aplicación",
    # Voz / lectura
    "pausa":             "Pausar o reanudar lectura",
    "detener_tts":       "Detener voz actual",
    "velocidad_menos":   "Bajar velocidad (fija)",
    "velocidad_mas":     "Subir velocidad (fija)",
    "volumen_menos":     "Bajar volumen del TTS (fijo)",
    "volumen_mas":       "Subir volumen del TTS (fijo)",
    "silenciar_lectura": "Silenciar lectura TTS",
    "silenciar_sonidos": "Silenciar sonidos",
    "anunciar_estado":   "Anunciar estado",
    "region_siguiente":  "Región siguiente",
    "region_anterior":   "Región anterior",
}
_mostrar_atajo = atajos_captura.mostrar_atajo


def etiqueta_de_accion(accion: str) -> str:
    try:
        etiqueta = _ETIQUETAS_ATAJO.get(accion)
        if etiqueta is not None:
            return etiqueta
        return str(accion).replace("_", " ").capitalize()
    except Exception:
        return ""


def _lista(v: str) -> list:
    return [x.strip().lower() for x in v.split(",") if x.strip()]


def abrir_preferencias(parent, config: dict) -> bool:
    """Devuelve True si se guardaron cambios (para aplicarlos en caliente)."""
    dlg = PreferenciasDialog(parent, config)
    try:
        res = dlg.ShowModal()
        return res == wx.ID_OK and dlg.hubo_cambios()
    finally:
        dlg.Destroy()
