"""Pruebas de accesibilidad del selector de carpeta."""

import unittest
import threading
from unittest import mock

import descargas
import gui_descargas

try:
    import wx
    _HAY_WX = True
except Exception:
    _HAY_WX = False


class _DobleControl:

    def __init__(self):
        self.etiquetas = []

    def SetLabel(self, texto):
        self.etiquetas.append(texto)


class _DobleSelector:

    def __init__(self):
        self.texto = _DobleControl()
        self.boton = _DobleControl()

    def GetTextCtrl(self):
        return self.texto

    def GetPickerCtrl(self):
        return self.boton


class TestNombrarSelectorCarpeta(unittest.TestCase):

    def test_nombra_campo_y_boton(self):
        selector = _DobleSelector()
        llamadas = []

        def nombrar(control, nombre):
            llamadas.append((control, nombre))

        with mock.patch.object(gui_descargas, "nombre_accesible", nombrar):
            gui_descargas.nombrar_selector_carpeta(selector)

        self.assertEqual(
            llamadas[0], (selector.texto, "Carpeta de destino de las descargas"))
        self.assertEqual(selector.boton.etiquetas, ["Examinar…"])
        self.assertEqual(llamadas[1], (selector.boton, "Examinar…"))
        self.assertTrue(llamadas[1][1].startswith("Examinar"))
        self.assertNotEqual(llamadas[1][1], "Browse")

    def test_acepta_selector_sin_controles_internos(self):
        with mock.patch.object(gui_descargas, "nombre_accesible") as nombrar:
            gui_descargas.nombrar_selector_carpeta(object())

        nombrar.assert_not_called()


@unittest.skipUnless(_HAY_WX, "wxPython no está instalado")
class TestGruposGestorDescargas(unittest.TestCase):

    def setUp(self):
        self.app = wx.App() if not wx.App.Get() else wx.App.Get()
        gui_descargas._registrados.clear()

    def tearDown(self):
        descargas.reiniciar_gestor()
        gui_descargas._registrados.clear()
        gui_descargas._dialogo_activo = None

    def _sin_disco(self):
        """El historial no debe tocar el historial_descargas.json real."""
        return (mock.patch.object(gui_descargas.historial_descargas, "cargar",
                                  return_value=[]),
                mock.patch.object(gui_descargas.historial_descargas, "guardar"))

    def test_listas_en_pestanas_con_nombres_accesibles(self):
        dialogo = gui_descargas.GestorDescargasDialog(None)
        try:
            esperados = {
                "Cola de descargas": "Cola",
                "Lista del historial de descargas": "Historial",
            }
            encontrados = {}
            pendientes = list(dialogo.GetChildren())
            while pendientes:
                control = pendientes.pop()
                pendientes.extend(control.GetChildren())
                if control.GetName() in esperados:
                    encontrados[control.GetName()] = control
            self.assertEqual(set(esperados), set(encontrados))
            self.assertEqual(dialogo.pestanas.GetName(), "PestanasDescargas")
            for nombre, control in encontrados.items():
                indice = 0 if esperados[nombre] == "Cola" else 1
                self.assertIs(control.GetParent(), dialogo.pestanas.GetPage(indice))
        finally:
            dialogo.Destroy()

    def test_columnas_de_la_cola_ponen_el_progreso_primero(self):
        dialogo = gui_descargas.GestorDescargasDialog(None)
        try:
            self.assertEqual(
                [dialogo.lista.GetColumn(indice).GetText()
                 for indice in range(dialogo.lista.GetColumnCount())],
                ["Progreso", "Estado", "Nombre"])
        finally:
            dialogo.Destroy()

    def test_actualizar_progreso_guarda_cada_dato_en_su_columna(self):
        dialogo = gui_descargas.GestorDescargasDialog(None)
        try:
            dialogo.lista.InsertItem(0, "0 %")
            dialogo._items_fila["item"] = 0
            dialogo._actualizar_progreso("item", 42, "archivo.mp4")
            self.assertEqual(dialogo.lista.GetItemText(0, 0), "42 %")
            self.assertEqual(dialogo.lista.GetItemText(0, 2), "archivo.mp4")
        finally:
            dialogo.Destroy()

    def test_progreso_rezagado_despues_de_cerrar_no_lanza(self):
        dialogo = gui_descargas.GestorDescargasDialog(None)
        dialogo.lista.InsertItem(0, "archivo.mp4")
        dialogo._items_fila["item"] = 0
        dialogo._on_cerrar(None)
        wx.Yield()
        dialogo._actualizar_progreso("item", 50, "archivo.mp4")
        dialogo._actualizar_estado("item", "completado", "")

    def test_callbacks_rezagados_despues_de_destruir_no_lanzan(self):
        dialogo = gui_descargas.GestorDescargasDialog(None)
        dialogo.lista.InsertItem(0, "archivo.mp4")
        dialogo._items_fila["item"] = 0
        dialogo.Destroy()
        wx.Yield()
        dialogo._actualizar_progreso("item", 50, "archivo.mp4")
        dialogo._actualizar_estado("item", "completado", "")

    def test_fin_avisado_despues_de_cerrar_el_dialogo(self):
        inicio = threading.Event()
        terminar = threading.Event()
        completada = threading.Event()

        def descarga_simulada(_url, _opciones, _progreso, estado, _cancelar):
            inicio.set()
            terminar.wait(1)
            estado("completado", "")
            completada.set()

        cargar, guardar = self._sin_disco()
        with cargar, guardar as guardar_mock, \
                mock.patch.object(descargas, "analizar_url", return_value={}), \
                mock.patch.object(descargas, "descargar", descarga_simulada), \
                mock.patch.object(gui_descargas, "anunciar") as anunciar, \
                mock.patch.object(gui_descargas._snd, "reproducir") as sonido:
            dialogo = gui_descargas.GestorDescargasDialog(None)
            dialogo._gestor.encolar("https://youtu.be/video", lambda *_: None,
                                    lambda *_: None)
            self.assertTrue(inicio.wait(1))
            dialogo.Destroy()
            terminar.set()
            self.assertTrue(completada.wait(1))
            wx.Yield()

        anunciar.assert_called_once_with("Descarga completada")
        sonido.assert_called_once_with("copiar")
        # Con el diálogo ya cerrado, la descarga entra igual en el historial.
        guardar_mock.assert_called_once()
        entradas = guardar_mock.call_args.args[1]
        self.assertEqual((entradas[0]["url"], entradas[0]["estado"]),
                         ("video", "completado"))

    def test_avisar_fin_descarga_pasa_por_el_hilo_de_la_gui(self):
        # El suscriptor corre en el hilo de descarga: nada de wx directo.
        with mock.patch.object(gui_descargas.wx, "CallAfter") as call_after, \
                mock.patch.object(gui_descargas, "anunciar") as anunciar:
            gui_descargas._avisar_fin_descarga("completado", "", "v.mp4", None)
        call_after.assert_called_once_with(
            gui_descargas._fin_descarga_en_gui, "completado", "", "v.mp4", None)
        anunciar.assert_not_called()

    def test_terminar_descarga_agrega_una_entrada_al_historial(self):
        cargar, guardar = self._sin_disco()
        with cargar, guardar, mock.patch.object(gui_descargas, "anunciar"), \
                mock.patch.object(gui_descargas._snd, "reproducir"):
            dialogo = gui_descargas.GestorDescargasDialog(None)
            try:
                item = descargas.ItemDescarga(
                    "item", "https://www.youtube.com/watch?v=abc&token=secreto",
                    "video", nombre="video.mp4", carpeta="C:/Descargas")
                gui_descargas._fin_descarga_en_gui("completado", "", item.nombre, item)
                self.assertEqual(dialogo.lista_historial.GetItemCount(), 1)
                self.assertEqual(dialogo.lista_historial.GetItemText(0, 0), "video.mp4")
                self.assertEqual(dialogo._historial[0]["url"], "abc")
                self.assertEqual(dialogo._historial[0]["carpeta"], "C:/Descargas")
                # Un segundo aviso del mismo ítem no duplica la entrada.
                gui_descargas._fin_descarga_en_gui("completado", "", item.nombre, item)
                self.assertEqual(dialogo.lista_historial.GetItemCount(), 1)
            finally:
                dialogo.Destroy()

    def test_filas_repobladas_reciben_el_progreso_por_el_temporizador(self):
        # Al reabrir, las filas no tienen callbacks (eran cierres del diálogo
        # anterior): el temporizador vuelca lo que hay en el gestor.
        gestor = descargas.gestor()
        item = descargas.ItemDescarga("item", "https://youtu.be/abc", "video",
                                      nombre="https://youtu.be/abc")
        gestor._items[item.id] = item
        gestor._orden.append(item.id)
        dialogo = gui_descargas.GestorDescargasDialog(None)
        try:
            self.assertEqual(dialogo.lista.GetItemText(0, 0), "0 %")
            self.assertTrue(dialogo._temporizador.IsRunning())
            item.progreso = 42
            item.nombre = "archivo.mp4"
            item.estado = "descargando"
            dialogo._refrescar_desde_gestor()
            self.assertEqual(dialogo.lista.GetItemText(0, 0), "42 %")
            self.assertEqual(dialogo.lista.GetItemText(0, 1), "descargando")
            self.assertEqual(dialogo.lista.GetItemText(0, 2), "archivo.mp4")
            item.estado = "error"
            item.mensaje = "sin espacio"
            dialogo._refrescar_desde_gestor()
            self.assertEqual(dialogo.lista.GetItemText(0, 1), "error: sin espacio")
        finally:
            dialogo.Destroy()

    def test_cerrar_para_el_temporizador_y_suelta_el_dialogo_activo(self):
        dialogo = gui_descargas.GestorDescargasDialog(None)
        try:
            self.assertIs(gui_descargas._dialogo_activo, dialogo)
            dialogo._soltar()
            self.assertFalse(dialogo._temporizador.IsRunning())
            self.assertIsNone(gui_descargas._dialogo_activo)
        finally:
            dialogo.Destroy()

    def test_vaciar_historial_deja_la_lista_sin_filas(self):
        with mock.patch.object(gui_descargas.historial_descargas, "cargar",
                               return_value=[]), \
                mock.patch.object(gui_descargas.historial_descargas, "guardar") as guardar, \
                mock.patch.object(gui_descargas.wx, "MessageBox", return_value=wx.YES), \
                mock.patch.object(gui_descargas, "anunciar") as anunciar:
            dialogo = gui_descargas.GestorDescargasDialog(None)
            try:
                entrada = {"nombre": "video.mp4", "fecha": "2026-08-28T12:00:00",
                           "estado": "completado"}
                dialogo._historial = [entrada]
                dialogo._agregar_fila_historial(entrada)
                dialogo._on_vaciar_historial(None)
                self.assertEqual(dialogo.lista_historial.GetItemCount(), 0)
                guardar.assert_called_once_with(dialogo._ruta_historial, [])
                anunciar.assert_called_once_with("Se borró 1 entrada del historial")
            finally:
                dialogo.Destroy()


if __name__ == "__main__":
    unittest.main()
