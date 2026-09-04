import unittest

import obs_estado


class FrasesObsTest(unittest.TestCase):
    def test_transmision_inactiva(self):
        self.assertEqual(obs_estado.frase_transmision(False, 0, 0, 0),
                         "No estás transmitiendo")

    def test_transmision_activa_sin_fotogramas_perdidos(self):
        self.assertEqual(obs_estado.frase_transmision(True, 61, 0, 100),
                         "Transmitiendo desde hace 1 min")

    def test_transmision_activa_con_fotogramas_perdidos(self):
        self.assertEqual(obs_estado.frase_transmision(True, 3_600, 4, 100),
                         "Transmitiendo desde hace 1 h 0 min, 4 de 100 fotogramas perdidos")

    def test_fotogramas_perdidos_sin_total_omite_la_proporcion(self):
        self.assertEqual(obs_estado.frase_transmision(True, 3_600, 4, 0),
                         "Transmitiendo desde hace 1 h 0 min, 4 fotogramas perdidos")

    def test_grabacion_inactiva(self):
        self.assertEqual(obs_estado.frase_grabacion(False, False, "00:00:00.000"),
                         "No estás grabando")

    def test_grabacion_en_pausa_recorta_las_milesimas(self):
        self.assertEqual(obs_estado.frase_grabacion(True, True, "01:02:03.456"),
                         "Grabación en pausa, 01:02:03")

    def test_grabacion_activa(self):
        self.assertEqual(obs_estado.frase_grabacion(True, False, "00:01:02.000"),
                         "Grabando, 00:01:02")

    def test_escena_al_aire_con_nombre(self):
        self.assertEqual(obs_estado.frase_escena_al_aire("Escena"), "Al aire: Escena")

    def test_escena_al_aire_sin_nombre(self):
        self.assertEqual(obs_estado.frase_escena_al_aire(""),
                         "No se pudo saber que escena está al aire")

    def test_frases_de_resultado(self):
        esperadas = {
            "transmision_iniciada": "Transmisión iniciada",
            "transmision_detenida": "Transmisión detenida",
            "grabacion_iniciada": "Grabación iniciada",
            "grabacion_detenida": "Grabación detenida",
            "grabacion_en_pausa": "Grabación en pausa",
            "grabacion_reanudada": "Grabación reanudada",
            "escena_cambiada": "Escena puesta al aire",
        }
        self.assertEqual({accion: obs_estado.frase_resultado(accion)
                          for accion in esperadas}, esperadas)


if __name__ == "__main__":
    unittest.main()
