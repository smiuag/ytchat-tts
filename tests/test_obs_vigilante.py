import unittest
from unittest import mock

import obs_cliente
import obs_vigilante
from obs_vigilante import EstadoObs, PLAZO_FRESCURA, VigilanteObs, dato_fresco


class TestFrescura(unittest.TestCase):

    def test_dato_recien_tomado_sirve(self):
        self.assertTrue(dato_fresco(100.0, 100.1))

    def test_dato_justo_en_el_limite_sirve(self):
        self.assertTrue(dato_fresco(100.0, 100.0 + PLAZO_FRESCURA))

    def test_dato_pasado_no_sirve(self):
        self.assertFalse(dato_fresco(100.0, 100.0 + PLAZO_FRESCURA + 0.1))

    def test_sin_sondeo_previo_no_sirve(self):
        self.assertFalse(dato_fresco(None, 100.0))

    def test_estado_con_sondeo_reciente_devuelve_estado_guardado(self):
        vigilante = VigilanteObs()
        vigilante._estado = EstadoObs(escena="Escena actual")
        vigilante._ultimo_sondeo = 100.0

        self.assertEqual(vigilante.estado(100.1), vigilante._estado)

    def test_estado_con_sondeo_caducado_devuelve_none(self):
        vigilante = VigilanteObs()
        vigilante._estado = EstadoObs(escena="Escena vieja")
        vigilante._ultimo_sondeo = 100.0

        self.assertIsNone(vigilante.estado(100.0 + PLAZO_FRESCURA + 0.1))


class TestParada(unittest.TestCase):

    def _vigilar_con(self, fallo_en_vuelo):
        gestor = mock.Mock(conectado=True)
        vigilante = VigilanteObs(crear_gestor=lambda: gestor)

        def estado_transmision(parada):
            if fallo_en_vuelo:
                vigilante._parada.set()
                raise obs_cliente.ObsError("Operación cancelada.")
            raise RuntimeError("OBS no contesta")

        gestor.estado_transmision.side_effect = estado_transmision
        # El bucle no termina solo: se detiene desde el cierre que sigue al
        # primer fallo.
        gestor.cerrar.side_effect = vigilante._parada.set
        logger = mock.Mock()
        with mock.patch.object(obs_vigilante.diagnostico, "obtener_logger",
                               return_value=logger), \
                mock.patch.object(obs_vigilante, "INTERVALO_SONDEO", 0):
            vigilante._vigilar()
        return logger, gestor

    def test_detener_con_peticion_en_vuelo_no_avisa_que_obs_no_responde(self):
        # Esa advertencia se lee en voz alta: al cerrar la app sonaba
        # «OBS no responde» sin que OBS hubiera fallado.
        logger, gestor = self._vigilar_con(fallo_en_vuelo=True)
        logger.warning.assert_not_called()
        gestor.cerrar.assert_called()

    def test_fallo_real_sigue_avisando(self):
        logger, _ = self._vigilar_con(fallo_en_vuelo=False)
        logger.warning.assert_called_once_with("OBS no responde; se reintentará")
