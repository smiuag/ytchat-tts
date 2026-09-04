import unittest
from unittest import mock

import gui


class HiloInmediato:
    def __init__(self, funcion):
        self.funcion = funcion

    def start(self):
        self.funcion()


class AccionMicrofonoObsTest(unittest.TestCase):
    def _ejecutar(self, gestor):
        frame = gui.YTChatFrame.__new__(gui.YTChatFrame)
        frame._config = {"obs_microfono": "Audio USB"}
        anuncios = []
        with mock.patch.object(gui, "GestorPanelObs", return_value=gestor), \
                mock.patch.object(gui.diagnostico, "crear_hilo",
                                  side_effect=lambda funcion, nombre: HiloInmediato(funcion)) as crear, \
                mock.patch.object(gui.wx, "CallAfter",
                                  side_effect=lambda funcion, *args: funcion(*args)), \
                mock.patch.object(gui, "anunciar", side_effect=lambda *args: anuncios.append(args)):
            frame._on_obs_micro(None)
        return anuncios, crear

    def test_alterna_la_fuente_elegida_y_anuncia_el_estado(self):
        gestor = mock.Mock()
        gestor.fuentes_audio.return_value = ("Mic/Aux", "Audio USB")
        gestor.alternar_silencio.return_value = True
        anuncios, crear = self._ejecutar(gestor)
        gestor.conectar.assert_called_once_with()
        gestor.alternar_silencio.assert_called_once_with("Audio USB")
        gestor.cerrar.assert_called_once_with()
        crear.assert_called_once()
        self.assertEqual(anuncios, [("Audio USB silenciado",)])

    def test_obs_caido_anuncia_como_activar_el_servidor(self):
        gestor = mock.Mock()
        gestor.conectar.side_effect = RuntimeError()
        anuncios, _ = self._ejecutar(gestor)
        gestor.cerrar.assert_called_once_with()
        self.assertEqual(anuncios, [(
            "OBS no responde. En OBS, menú Herramientas, Configuración del servidor "
            "WebSocket, activa el servidor.",)])


if __name__ == "__main__":
    unittest.main()
