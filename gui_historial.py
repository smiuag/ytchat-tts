"""Diálogo de historial de directos y vídeos vistos (accesible).

Dos pestañas —YouTube y TikTok— con lo que se ha ido viendo. Enter (o el botón
Conectar) vuelve a ese directo/vídeo; Suprimir (o Quitar) borra la entrada. La
reconexión la hace la ventana principal vía el callback `on_conectar(url)`.
"""

from __future__ import annotations

import logging

import diagnostico
import wx

import historial
from gui import anunciar, nombre_accesible, _T, _pintar

logger = diagnostico.obtener_logger(__name__)

_PLATAFORMAS = [("YouTube", "youtube"), ("TikTok", "tiktok")]


class HistorialDialog(wx.Dialog):

    def __init__(self, parent, ruta, on_conectar):
        super().__init__(parent, title="Historial de directos", size=(600, 480),
                         name="DialogoHistorial")
        self._ruta = ruta
        self._on_conectar = on_conectar
        self._lista = historial.cargar(ruta)
        _pintar(self, bg=_T.bg)
        self._build_ui()
        self.Centre()

    def _build_ui(self):
        panel = wx.Panel(self, name="PanelHistorial")
        _pintar(panel, _T.bg, _T.text)
        vs = wx.BoxSizer(wx.VERTICAL)

        nota = wx.StaticText(panel, name="NotaHistorial", label=(
            "Directos y vídeos vistos. Enter o «Conectar» vuelve a uno; Suprimir "
            "lo quita. Los marcados «· directo» eran emisiones en vivo: los de "
            "TikTok se reconectan si el usuario está en vivo; un directo de "
            "YouTube ya terminado no volverá, pero un vídeo normal sí."))
        _pintar(nota, fg=_T.dim)
        nota.Wrap(560)
        vs.Add(nota, 0, wx.ALL, 10)

        self.nb = wx.Notebook(panel, name="PestanasHistorial")
        self._listas: dict[str, wx.ListBox] = {}
        self._entradas: dict[str, list] = {}
        for titulo, plat in _PLATAFORMAS:
            pag = wx.Panel(self.nb, name=f"PagHistorial_{plat}")
            _pintar(pag, bg=_T.bg)
            pvs = wx.BoxSizer(wx.VERTICAL)
            lb = wx.ListBox(pag, style=wx.LB_SINGLE | wx.LB_HSCROLL,
                            name=f"Historial de {titulo}")
            _pintar(lb, _T.field, _T.text)
            nombre_accesible(lb, f"Historial de {titulo}")
            lb.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._conectar())
            lb.Bind(wx.EVT_KEY_DOWN, self._on_key)
            pvs.Add(lb, 1, wx.EXPAND | wx.ALL, 8)
            pag.SetSizer(pvs)
            self.nb.AddPage(pag, titulo)
            self._listas[plat] = lb
        self.nb.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._on_pestana)
        vs.Add(self.nb, 1, wx.EXPAND | wx.ALL, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_conectar = wx.Button(panel, label="&Conectar", name="ConectarHistorial")
        self.btn_quitar   = wx.Button(panel, label="&Quitar", name="QuitarHistorial")
        btn_cerrar        = wx.Button(panel, wx.ID_CANCEL, "C&errar", name="CerrarHistorial")
        for b in (self.btn_conectar, self.btn_quitar, btn_cerrar):
            _pintar(b, _T.btn, _T.btn_t)
            row.Add(b, 0, wx.RIGHT, 6)
        vs.Add(row, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        panel.SetSizer(vs)
        self.btn_conectar.Bind(wx.EVT_BUTTON, lambda e: self._conectar())
        self.btn_quitar.Bind(wx.EVT_BUTTON, lambda e: self._quitar())

        self._poblar()

    # ── Datos ──────────────────────────────────────────────────────────────

    def _plat_actual(self) -> str:
        return _PLATAFORMAS[max(0, self.nb.GetSelection())][1]

    def _poblar(self):
        for _titulo, plat in _PLATAFORMAS:
            lb = self._listas[plat]
            entradas = historial.de_plataforma(self._lista, plat)
            self._entradas[plat] = entradas
            lb.Clear()
            for e in entradas:
                lb.Append(historial.etiqueta(e))
            if entradas:
                lb.SetSelection(0)
        hay = any(self._entradas.values())
        self.btn_conectar.Enable(hay)
        self.btn_quitar.Enable(hay)

    def _seleccionada(self):
        plat = self._plat_actual()
        lb = self._listas[plat]
        i = lb.GetSelection()
        entradas = self._entradas.get(plat, [])
        if i == wx.NOT_FOUND or i >= len(entradas):
            return None
        return entradas[i]

    # ── Acciones ───────────────────────────────────────────────────────────

    def _on_pestana(self, event):
        idx = event.GetSelection()
        if 0 <= idx < self.nb.GetPageCount():
            anunciar(self.nb.GetPageText(idx))
        event.Skip()

    def _on_key(self, event):
        k = event.GetKeyCode()
        if k in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._conectar()
        elif k == wx.WXK_DELETE:
            self._quitar()
        else:
            event.Skip()

    def _conectar(self):
        e = self._seleccionada()
        if not e:
            anunciar("Sin selección")
            return
        url = e.get("url") or ""
        if not url:
            return
        self.EndModal(wx.ID_OK)
        if self._on_conectar:
            self._on_conectar(url)

    def _quitar(self):
        e = self._seleccionada()
        if not e:
            return
        self._lista = [x for x in self._lista if x is not e]
        historial.guardar(self._ruta, self._lista)
        anunciar("Entrada quitada del historial")
        self._poblar()


def abrir_historial(parent, ruta, on_conectar) -> None:
    dlg = HistorialDialog(parent, ruta, on_conectar)
    try:
        dlg.ShowModal()
    finally:
        dlg.Destroy()
