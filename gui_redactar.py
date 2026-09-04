"""Controles accesibles para redactar mensajes de varias líneas."""

from __future__ import annotations

import wx

import redaccion


def _anunciar(texto: str) -> None:
    from gui import anunciar
    anunciar(texto)


class PanelRedactar(wx.Panel):
    def __init__(self, parent, etiqueta, maximo, al_enviar):
        super().__init__(parent, name="PanelRedactar")
        self._maximo = maximo
        self._al_enviar = al_enviar
        self._motivo = ""

        vs = wx.BoxSizer(wx.VERTICAL)
        self.etiqueta = wx.StaticText(self, label=etiqueta, name="EtiquetaRedaccion")
        vs.Add(self.etiqueta, 0, wx.BOTTOM, 4)
        fila = wx.BoxSizer(wx.HORIZONTAL)
        self.texto = wx.TextCtrl(
            self, style=wx.TE_MULTILINE, name="Mensaje para el chat")
        self.texto.SetMinSize((-1, 3 * self.texto.GetCharHeight() + 12))
        fila.Add(self.texto, 1, wx.EXPAND | wx.RIGHT, 6)
        self.boton = wx.Button(self, label="&Enviar", name="Enviar mensaje al chat")
        fila.Add(self.boton, 0, wx.ALIGN_BOTTOM)
        vs.Add(fila, 1, wx.EXPAND)
        self.SetSizer(vs)
        self.boton.Bind(wx.EVT_BUTTON, self._on_enviar)
        self.texto.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

    def establecer_motivo(self, motivo: str) -> None:
        self._motivo = motivo or ""
        base = self.boton.GetLabel().split(" (")[0]
        self.boton.SetLabel(redaccion.etiqueta_con_motivo(base, self._motivo))

    def motivo(self) -> str:
        """Por qué no se puede enviar ahora («» si se puede)."""
        return self._motivo

    def enfocar(self) -> None:
        self.texto.SetFocus()

    def _on_char_hook(self, event) -> None:
        if (event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
                and not event.ShiftDown()):
            self._on_enviar(event)
            return
        event.Skip()

    def _on_enviar(self, _event) -> None:
        if self._motivo:
            _anunciar(self._motivo)
            self.enfocar()
            return
        motivo = redaccion.validar(self.texto.GetValue(), self._maximo)
        if motivo:
            _anunciar(motivo)
            self.enfocar()
            return
        texto = redaccion.limpiar(self.texto.GetValue())
        self._al_enviar(texto)
        self.texto.Clear()
        self.enfocar()


class DialogoRedactar(wx.Dialog):
    def __init__(self, parent, etiqueta, maximo, al_enviar,
                 titulo="Redactar", motivo="", nombre_texto="Texto del comentario",
                 nombre_boton="Publicar"):
        super().__init__(parent, title=titulo, name="DialogoRedactar")
        self._al_enviar = al_enviar
        self.texto_enviado = ""
        vs = wx.BoxSizer(wx.VERTICAL)
        self.panel = PanelRedactar(self, etiqueta, maximo, self._enviar)
        self.panel.texto.SetName(nombre_texto)
        self.panel.boton.SetLabel("&" + nombre_boton)
        self.panel.boton.SetName(nombre_boton)
        self.panel.establecer_motivo(motivo)
        vs.Add(self.panel, 1, wx.EXPAND | wx.ALL, 10)
        cancelar = wx.Button(self, wx.ID_CANCEL, "&Cancelar", name="Cancelar")
        vs.Add(cancelar, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizerAndFit(vs)
        self.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL), cancelar)

    def _enviar(self, texto) -> None:
        self.texto_enviado = texto
        if self._al_enviar:
            self._al_enviar(texto)
        self.EndModal(wx.ID_OK)
