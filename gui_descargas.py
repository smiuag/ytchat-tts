"""Diálogo «Gestor de descargas» (yt-dlp) — accesible y nativo.

Diálogo modal que deja al usuario pegar URLs de YouTube, elegir formato/bitrate/
carpeta/enumerar, y ver la cola con progreso y botón «Cancelar» por ítem. El
motor puro está en `descargas.py` (sin wx, testeable en Linux); este módulo
solo monta la UI y empuja progreso al `wx.ListCtrl` con `wx.CallAfter`.

Accesibilidad (regla de oro NVDA):
  - Cada control interactivo tiene `name=` accesible.
  - Sin color personalizado en casillas ni radios (en Windows rompe su rol).
  - Errores 3-vías: `_snd.reproducir("error")` + `anunciar()` + texto en la
    columna Estado del `ListCtrl`. Nunca se re-lanza una excepción fuera del
    hilo de descarga.
  - Toda mutación de la GUI desde el hilo de descarga va con `wx.CallAfter`.

Apertura: `abrir(parent, url_inicial=None)` desde `gui._abrir_descargas`.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime

import wx

import diagnostico
import config as cfg
from descargas import frase_aviso_descarga, gestor, recortar_url_registro
import historial_descargas
from gui import anunciar, nombre_accesible, caja_de_grupo, _T, _tc
import sound_player as _snd

logger = diagnostico.obtener_logger(__name__)


# Paleta neutral para el diálogo (no la de la ventana principal): misma lógica
# que `gui_preferencias._T` — apariencia nativa para no romper NVDA en Windows.


# Etiquetas legibles para el Choice de formato. mp3/m4a abren el bitrate.
_FORMATOS_OPCIONES = [
    ("Vídeo MP4 (muxed)", "mp4"),
    ("Vídeo WebM",        "webm"),
    ("Audio MP3",         "mp3"),
    ("Audio M4A",         "m4a"),
]
_BITRATE_OPCIONES = [192, 256, 320]


def _es_formato_audio(formato: str) -> bool:
    return (formato or "").lower() in ("mp3", "m4a")


def _texto_estado(estado: str, mensaje: str) -> str:
    """Celda «Estado» de la cola: el motivo solo acompaña a error/cancelado."""
    if mensaje and estado in ("error", "cancelado"):
        return f"{estado}: {mensaje[:80]}"[:200]
    return (estado or "")[:200]


def nombrar_selector_carpeta(selector) -> None:
    if hasattr(selector, "GetTextCtrl"):
        nombre_accesible(
            selector.GetTextCtrl(),
            "Carpeta de destino de las descargas")
    if hasattr(selector, "GetPickerCtrl"):
        boton_carpeta = selector.GetPickerCtrl()
        boton_carpeta.SetLabel("Examinar…")
        nombre_accesible(boton_carpeta, "Examinar…")


_ESTADOS_FINALES = ("completado", "cancelado", "error")
# Cada 500 ms el diálogo abierto vuelca el estado del gestor a sus filas.
INTERVALO_REFRESCO_MS = 500

# El diálogo abierto (si lo hay) y los ítems ya llevados al historial. Viven a
# nivel de módulo porque las descargas sobreviven al diálogo: una que termina
# con el gestor cerrado también tiene que entrar en el historial.
_dialogo_activo = None
_registrados: set[str] = set()


def _ruta_historial():
    return cfg.app_dir() / "historial_descargas.json"


def registrar_historial(item, estado: str, ruta=None) -> dict | None:
    """Persiste el fin de una descarga en el historial. Devuelve la entrada,
    o None si ese ítem ya estaba registrado."""
    if item is None or item.id in _registrados:
        return None
    _registrados.add(item.id)
    ruta = ruta or _ruta_historial()
    entrada = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "nombre": item.nombre or item.url,
        "url": recortar_url_registro(item.url),
        "estado": estado,
        "carpeta": item.carpeta or cfg.obtener_opciones_descarga().get("carpeta", ""),
    }
    entradas = historial_descargas.agregar(historial_descargas.cargar(ruta), entrada)
    historial_descargas.guardar(ruta, entradas)
    return entrada


def _fin_descarga_en_gui(estado: str, mensaje: str, nombre: str, item) -> None:
    """Parte del aviso de fin que toca wx: corre en el hilo de la GUI."""
    frase = frase_aviso_descarga(estado, mensaje, nombre)
    if not frase:
        return
    try:
        _snd.reproducir("error" if estado == "error" else "copiar")
    except Exception:
        pass
    anunciar(frase)
    if estado not in _ESTADOS_FINALES:
        return
    entrada = registrar_historial(item, estado)
    dialogo = _dialogo_activo
    if entrada is not None and dialogo is not None and dialogo._alive:
        dialogo._mostrar_entrada_historial(entrada)


def _avisar_fin_descarga(estado: str, mensaje: str, nombre: str, item=None) -> None:
    # Llega desde el hilo de descarga: el sonido, el anuncio y el historial
    # (que toca el ListCtrl del diálogo) van al hilo de la GUI.
    wx.CallAfter(_fin_descarga_en_gui, estado, mensaje, nombre, item)


def _suscribir_al_gestor() -> None:
    gestor().suscribir_fin(_avisar_fin_descarga)


class GestorDescargasDialog(wx.Dialog):
    """Diálogo principal del gestor de descargas."""

    def __init__(self, parent, url_inicial: str | None = None):
        global _dialogo_activo
        super().__init__(parent, title="Gestor de descargas",
                         size=(720, 560),
                         name="DialogoGestorDescargas")
        self.SetBackgroundColour(_T.bg)
        self._alive = True
        self._opciones = cfg.obtener_opciones_descarga()
        self._gestor = gestor()
        _suscribir_al_gestor()
        self._items_fila: dict[str, int] = {}   # item_id -> índice en ListCtrl
        self._fila_items: dict[int, str] = {}   # índice -> item_id
        self._ruta_historial = _ruta_historial()
        self._historial = historial_descargas.cargar(self._ruta_historial)
        self._build_ui()
        self._repoblar_lista()
        self._repoblar_historial()
        self.Bind(wx.EVT_CLOSE, self._on_cerrar)
        # Las filas repobladas al reabrir no tienen callbacks (eran cierres del
        # diálogo anterior): un temporizador vuelca el estado del gestor.
        self._temporizador = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_refresco, self._temporizador)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._al_destruir)
        self._temporizador.Start(INTERVALO_REFRESCO_MS)
        _dialogo_activo = self
        if url_inicial:
            self.txt_url.SetValue(url_inicial)
        self.Centre()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self):
        panel = wx.Panel(self, name="PanelGestorDescargas")
        panel.SetBackgroundColour(_T.bg)
        panel.SetForegroundColour(_T.text)
        vs = wx.BoxSizer(wx.VERTICAL)

        vs.Add(self._seccion_opciones(panel), 0, wx.EXPAND | wx.ALL, 10)
        vs.Add(self._seccion_anadir(panel), 0, wx.EXPAND | wx.ALL, 10)
        vs.Add(self._seccion_listas(panel), 1, wx.EXPAND | wx.ALL, 10)
        vs.Add(self._seccion_botones(panel), 0, wx.EXPAND | wx.ALL, 10)
        panel.SetSizer(vs)

    def _seccion_opciones(self, parent):
        box, padre = caja_de_grupo(parent, "Opciones de descarga")
        # Formato (Choice, no RadioBox: menos carga cognitiva y mejor con NVDA).
        fila_fmt = wx.BoxSizer(wx.HORIZONTAL)
        lbl_fmt = wx.StaticText(padre, label="&Formato:", name="EtiquetaFormato")
        lbl_fmt.SetForegroundColour(_T.text)
        fila_fmt.Add(lbl_fmt, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        etiquetas = [et for et, _ in _FORMATOS_OPCIONES]
        valores = [v for _, v in _FORMATOS_OPCIONES]
        self.cho_formato = wx.Choice(padre, choices=etiquetas, name="Formato")
        _tc(self.cho_formato)
        actual = self._opciones.get("formato", "mp4")
        try:    self.cho_formato.SetSelection(valores.index(actual))
        except ValueError: self.cho_formato.SetSelection(0)
        self.cho_formato.Bind(wx.EVT_CHOICE, self._on_formato)
        fila_fmt.Add(self.cho_formato, 1, wx.EXPAND)
        box.Add(fila_fmt, 0, wx.EXPAND | wx.ALL, 6)

        # Bitrate (solo se habilita si formato es audio).
        fila_bit = wx.BoxSizer(wx.HORIZONTAL)
        lbl_bit = wx.StaticText(padre, label="&Bitrate (kbps):", name="EtiquetaBitrate")
        lbl_bit.SetForegroundColour(_T.text)
        fila_bit.Add(lbl_bit, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.cho_bitrate = wx.Choice(padre,
                                     choices=[str(b) for b in _BITRATE_OPCIONES],
                                     name="Bitrate")
        _tc(self.cho_bitrate)
        try:    self.cho_bitrate.SetSelection(
                    _BITRATE_OPCIONES.index(int(self._opciones.get("bitrate", 192))))
        except ValueError: self.cho_bitrate.SetSelection(0)
        fila_bit.Add(self.cho_bitrate, 1, wx.EXPAND)
        box.Add(fila_bit, 0, wx.EXPAND | wx.ALL, 6)

        # Carpeta destino.
        fila_carp = wx.BoxSizer(wx.HORIZONTAL)
        lbl_carp = wx.StaticText(padre, label="Carpeta &destino:", name="EtiquetaCarpeta")
        lbl_carp.SetForegroundColour(_T.text)
        fila_carp.Add(lbl_carp, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.dir_carpeta = wx.DirPickerCtrl(
            padre, path=self._opciones.get("carpeta") or str(cfg.app_dir() / "Descargas"),
            name="Carpeta destino", message="Elige la carpeta de descargas")
        _tc(self.dir_carpeta)
        nombrar_selector_carpeta(self.dir_carpeta)
        fila_carp.Add(self.dir_carpeta, 1, wx.EXPAND)
        box.Add(fila_carp, 0, wx.EXPAND | wx.ALL, 6)

        # Enumerar playlist (casilla, sin color).
        self.chk_enumerar = wx.CheckBox(
            padre, name="EnumerarPlaylist",
            label="&Enumerar ítems de playlist (01_, 02_…)")
        self.chk_enumerar.SetValue(bool(self._opciones.get("enumerar", False)))
        box.Add(self.chk_enumerar, 0, wx.ALL, 6)

        self._on_formato()   # ajusta habilitación del bitrate
        return box

    def _seccion_anadir(self, parent):
        box, padre = caja_de_grupo(parent, "Añadir URL")
        fila = wx.BoxSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(padre, label="&URL del vídeo o playlist:",
                            name="EtiquetaURL")
        lbl.SetForegroundColour(_T.text)
        fila.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.txt_url = wx.TextCtrl(padre, value="",
                                   style=wx.TE_PROCESS_ENTER,
                                   name="URL del vídeo o playlist")
        _tc(self.txt_url)
        self.txt_url.SetToolTip("Pega un enlace de YouTube (vídeo o playlist).")
        self.txt_url.Bind(wx.EVT_TEXT_ENTER, lambda e: self._on_anadir(None))
        fila.Add(self.txt_url, 1, wx.EXPAND)
        self.btn_anadir = wx.Button(padre, label="Aña&dir", name="AnadirURL")
        self.btn_anadir.SetBackgroundColour(_T.btn)
        self.btn_anadir.SetForegroundColour(_T.btn_t)
        self.btn_anadir.Bind(wx.EVT_BUTTON, self._on_anadir)
        fila.Add(self.btn_anadir, 0, wx.LEFT, 6)
        box.Add(fila, 0, wx.EXPAND | wx.ALL, 6)
        return box

    def _seccion_listas(self, parent):
        self.pestanas = wx.Notebook(parent, name="PestanasDescargas")
        cola = wx.Panel(self.pestanas)
        vs_cola = wx.BoxSizer(wx.VERTICAL)
        self.lista = wx.ListCtrl(cola, style=wx.LC_REPORT | wx.LC_SINGLE_SEL,
                                 name="ColaDescargas")
        nombre_accesible(self.lista, "Cola de descargas", msaa=False)
        self.lista.InsertColumn(0, "Progreso", width=100)
        self.lista.InsertColumn(1, "Estado", width=160)
        self.lista.InsertColumn(2, "Nombre", width=320)
        vs_cola.Add(self.lista, 1, wx.EXPAND | wx.ALL, 6)

        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_cancelar = wx.Button(cola, label="&Cancelar seleccionado",
                                      name="CancelarDescarga")
        self.btn_cancelar.SetBackgroundColour(_T.btn)
        self.btn_cancelar.SetForegroundColour(_T.btn_t)
        self.btn_cancelar.Bind(wx.EVT_BUTTON, self._on_cancelar)
        fila.Add(self.btn_cancelar, 0)
        vs_cola.Add(fila, 0, wx.ALL, 6)
        cola.SetSizer(vs_cola)

        pagina_historial = wx.Panel(self.pestanas)
        vs_historial = wx.BoxSizer(wx.VERTICAL)
        self.lista_historial = wx.ListCtrl(
            pagina_historial, style=wx.LC_REPORT | wx.LC_SINGLE_SEL,
            name="Lista del historial de descargas")
        nombre_accesible(self.lista_historial, "Lista del historial de descargas",
                         msaa=False)
        self.lista_historial.InsertColumn(0, "Nombre", width=360)
        self.lista_historial.InsertColumn(1, "Fecha", width=180)
        self.lista_historial.InsertColumn(2, "Estado", width=140)
        vs_historial.Add(self.lista_historial, 1, wx.EXPAND | wx.ALL, 6)
        self.btn_vaciar_historial = wx.Button(
            pagina_historial, label="&Vaciar el historial",
            name="Vaciar el historial")
        self.btn_vaciar_historial.SetBackgroundColour(_T.btn)
        self.btn_vaciar_historial.SetForegroundColour(_T.btn_t)
        self.btn_vaciar_historial.Bind(wx.EVT_BUTTON, self._on_vaciar_historial)
        vs_historial.Add(self.btn_vaciar_historial, 0, wx.ALL, 6)
        pagina_historial.SetSizer(vs_historial)
        self.pestanas.AddPage(cola, "Cola")
        self.pestanas.AddPage(pagina_historial, "Historial")
        return self.pestanas

    def _seccion_botones(self, parent):
        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_cerrar = wx.Button(parent, wx.ID_CANCEL, "&Cerrar",
                                    name="CerrarGestorDescargas")
        self.btn_cerrar.SetBackgroundColour(_T.btn)
        self.btn_cerrar.SetForegroundColour(_T.btn_t)
        self.btn_cerrar.Bind(wx.EVT_BUTTON, self._on_cerrar)
        fila.Add(self.btn_cerrar, 0, wx.RIGHT, 6)
        return fila

    # ── Callbacks de UI ──────────────────────────────────────────────────────

    def _on_formato(self, _event=None):
        idx = self.cho_formato.GetSelection()
        if idx < 0 or idx >= len(_FORMATOS_OPCIONES):
            return
        _, valor = _FORMATOS_OPCIONES[idx]
        es_audio = _es_formato_audio(valor)
        self.cho_bitrate.Enable(es_audio)
        # Si pasó de audio a vídeo, no escondemos el valor: el usuario lo
        # verá gris. Si era vídeo y pasa a audio, ya está en 192/256/320.

    def _opciones_actuales(self) -> dict:
        idx = self.cho_formato.GetSelection()
        formato = (_FORMATOS_OPCIONES[idx][1]
                   if 0 <= idx < len(_FORMATOS_OPCIONES) else "mp4")
        try:    bitrate = _BITRATE_OPCIONES[self.cho_bitrate.GetSelection()]
        except Exception: bitrate = 192
        carpeta = self.dir_carpeta.GetPath() or str(cfg.app_dir() / "Descargas")
        enumerar = bool(self.chk_enumerar.GetValue())
        return {"formato": formato, "bitrate": bitrate,
                "carpeta": carpeta, "enumerar": enumerar}

    def _on_anadir(self, _event):
        url = self.txt_url.GetValue().strip()
        if not url:
            wx.MessageBox("Pega una URL de YouTube (vídeo o playlist) antes de añadir.",
                          "Falta la URL", wx.OK | wx.ICON_INFORMATION, self)
            return
        # Persistimos las opciones elegidas antes de encolar (así el Gestor
        # las ve). Si luego el usuario cambia el formato en medio, la nueva
        # descarga usará la nueva config.
        op = self._opciones_actuales()
        try:    cfg.guardar_opciones_descarga(op)
        except Exception as exc: logger.debug("guardar opciones: %s", exc)
        self._opciones = op
        self._gestor.set_opciones(op)

        # Inserción optimista en la cola (estado «en_cola»), luego el hilo
        # actualiza estado/progreso vía CallAfter.
        idx = self.lista.InsertItem(self.lista.GetItemCount(), "0 %")
        self.lista.SetItem(idx, 1, "en cola")
        self.lista.SetItem(idx, 2, url[:300])

        def _cb_progreso(item_id, pct, _vel, _eta, nombre):
            wx.CallAfter(self._actualizar_progreso, item_id, pct, nombre)

        def _cb_estado(item_id, estado, mensaje):
            wx.CallAfter(self._actualizar_estado, item_id, estado, mensaje)

        def _registrar_fila(item_id):
            self._items_fila[item_id] = idx
            self._fila_items[idx] = item_id

        self._gestor.encolar(url, _cb_progreso, _cb_estado, _registrar_fila)
        self.txt_url.SetValue("")
        anunciar("Añadido a la cola")

    def _repoblar_lista(self) -> None:
        for item in self._gestor.lista():
            idx = self.lista.InsertItem(self.lista.GetItemCount(), f"{item.progreso:.0f} %")
            self.lista.SetItem(idx, 2, item.nombre[:300])
            self.lista.SetItem(idx, 1, _texto_estado(item.estado, item.mensaje))
            self._items_fila[item.id] = idx
            self._fila_items[idx] = item.id

    def _on_refresco(self, _event) -> None:
        if not self or not self._alive or not self.lista:
            return
        self._refrescar_desde_gestor()

    def _refrescar_desde_gestor(self) -> None:
        """Vuelca a cada fila el estado actual de su ítem. Solo escribe lo que
        cambió: reescribir celdas iguales hace hablar al lector sin motivo."""
        for item in self._gestor.lista():
            idx = self._items_fila.get(item.id)
            if idx is None:
                continue
            celdas = {0: f"{item.progreso:.0f} %",
                      1: _texto_estado(item.estado, item.mensaje)}
            if item.nombre:
                celdas[2] = item.nombre[:300]
            for columna, texto in celdas.items():
                if self.lista.GetItemText(idx, columna) != texto:
                    self.lista.SetItem(idx, columna, texto)

    def _repoblar_historial(self) -> None:
        for entrada in self._historial:
            self._agregar_fila_historial(entrada)

    def _agregar_fila_historial(self, entrada: dict) -> None:
        nombre, fecha, estado = historial_descargas.formatear(entrada)
        idx = self.lista_historial.InsertItem(self.lista_historial.GetItemCount(), nombre)
        self.lista_historial.SetItem(idx, 1, fecha)
        self.lista_historial.SetItem(idx, 2, estado)

    def _mostrar_entrada_historial(self, entrada: dict) -> None:
        """Refleja en la pestaña Historial una entrada recién persistida."""
        if not self or not self._alive or not self.lista_historial:
            return
        self._historial = historial_descargas.agregar(self._historial, entrada)
        nombre, fecha, estado = historial_descargas.formatear(entrada)
        self.lista_historial.InsertItem(0, nombre)
        self.lista_historial.SetItem(0, 1, fecha)
        self.lista_historial.SetItem(0, 2, estado)

    def _on_vaciar_historial(self, _event) -> None:
        cantidad = len(self._historial)
        mensaje = ("Borra las entradas del historial. No borra ningún archivo "
                   "descargado del disco, solo la lista. ¿Deseas continuar?")
        if wx.MessageBox(mensaje, "Vaciar el historial",
                         wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self) != wx.YES:
            return
        self._historial = []
        historial_descargas.guardar(self._ruta_historial, self._historial)
        self.lista_historial.DeleteAllItems()
        if cantidad == 1:
            anunciar("Se borró 1 entrada del historial")
        else:
            anunciar(f"Se borraron {cantidad} entradas del historial")

    def _on_cancelar(self, _event):
        idx = self.lista.GetFirstSelected()
        if idx < 0:
            wx.MessageBox("Selecciona una descarga de la cola para cancelar.",
                          "Nada seleccionado", wx.OK | wx.ICON_INFORMATION, self)
            return
        item_id = self._fila_items.get(idx)
        if item_id is None:
            return
        self._gestor.cancelar(item_id)
        # El estado lo confirmará el propio hilo («cancelado»).
        anunciar("Cancelando descarga")

    def _on_cerrar(self, _event):
        self._alive = False
        self._soltar()
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()

    def _al_destruir(self, event):
        if event.GetEventObject() is self:
            self._alive = False
            self._soltar()
        event.Skip()

    def _soltar(self) -> None:
        global _dialogo_activo
        try:
            self._temporizador.Stop()
        except Exception:
            pass
        if _dialogo_activo is self:
            _dialogo_activo = None

    # ── Callbacks del hilo de descarga (CallAfter) ──────────────────────────

    def _actualizar_progreso(self, item_id: str, pct: float, nombre: str) -> None:
        # _alive cubre el cierre ordenado, pero wx invalida controles al destruirlos.
        if not self or not self._alive or not self.lista:
            return
        idx = self._items_fila.get(item_id)
        if idx is None:
            return
        texto = f"{pct:.0f} %"
        if nombre:
            self.lista.SetItem(idx, 2, nombre[:300])
        self.lista.SetItem(idx, 0, texto)

    def _actualizar_estado(self, item_id: str, estado: str, mensaje: str) -> None:
        # _alive cubre el cierre ordenado, pero wx invalida controles al destruirlos.
        if not self or not self._alive or not self.lista:
            return
        idx = self._items_fila.get(item_id)
        if idx is None:
            return
        self.lista.SetItem(idx, 1, _texto_estado(estado, mensaje))
        if estado == "descargando":
            try:
                _snd.reproducir("copiar")
            except Exception:
                pass


def abrir(parent, url_inicial: str | None = None) -> bool:
    """Abre el gestor como modal y devuelve True si el usuario lo usó (siempre,
    salvo que falle la apertura). El diálogo persiste las opciones al cerrarse
    vía `cfg.guardar_opciones_descarga` desde los callbacks."""
    dlg = GestorDescargasDialog(parent, url_inicial=url_inicial)
    try:
        dlg.ShowModal()
    finally:
        dlg.Destroy()
    return True
