"""Pruebas del formato de las trazas del transporte."""

import itertools
import unittest

from traza_transporte import (
    topologia_medio, traza_busqueda_muestra, traza_busqueda_orden,
    traza_busqueda_desenlace, traza_inicio_muestra, traza_salto, traza_sin_barra,
    traza_transporte,
)


class TestTrazaTransporte(unittest.TestCase):

    def test_traza_transporte_corriente(self):
        self.assertEqual(
            traza_transporte("playing", "pausar", True, True, True, False),
            "TRANSPORTE estado=playing accion=pausar medio=si intencion=si "
            "puede_pausar=si buscable=no")

    def test_traza_transporte_consulta_desconocida(self):
        self.assertEqual(
            traza_transporte("paused", "reanudar", False, False, None, None),
            "TRANSPORTE estado=paused accion=reanudar medio=no intencion=no "
            "puede_pausar=desconocido buscable=desconocido")

    def test_traza_transporte_booleanos_de_vlc(self):
        self.assertIn("puede_pausar=no", traza_transporte(
            "playing", "pausar", True, False, False, True))
        self.assertIn("puede_pausar=si", traza_transporte(
            "playing", "pausar", True, False, True, False))

    def test_traza_salto_corriente(self):
        self.assertEqual(
            traza_salto("relativo", 3000, 5000, -1000, 4000, 10000),
            "SALTO origen=relativo pendiente=3000 pos=5000 delta=-1000 "
            "destino=4000 dur=10000")

    def test_traza_salto_pendiente_nulo_y_destinos_limite(self):
        self.assertEqual(
            traza_salto("porcentaje", None, 0, 0, 0, 10000),
            "SALTO origen=porcentaje pendiente=ninguno pos=0 delta=0 "
            "destino=0 dur=10000")
        self.assertEqual(
            traza_salto("deslizador", 0, 10000, 0, 10000, 10000),
            "SALTO origen=deslizador pendiente=0 pos=10000 delta=0 "
            "destino=10000 dur=10000")

    def test_traza_sin_barra_corriente(self):
        self.assertEqual(traza_sin_barra("relativo", 0),
                         "SALTO_SIN_BARRA origen=relativo dur=0")

    def test_propiedad_sin_saltos_y_campos_en_orden(self):
        for estado, accion, medio, intencion, puede, buscable in itertools.product(
                ("playing", "paused"), ("pausar", "reanudar"),
                (False, True), (False, True), (None, False, True),
                (None, False, True)):
            linea = traza_transporte(
                estado, accion, medio, intencion, puede, buscable)
            self.assertNotIn("\n", linea)
            self.assertEqual(
                [campo.split("=", 1)[0] for campo in linea.split()],
                ["TRANSPORTE", "estado", "accion", "medio", "intencion",
                 "puede_pausar", "buscable"])
        for origen, pendiente, numero in itertools.product(
                ("relativo", "porcentaje", "deslizador"), (None, 0, 1),
                (0, 1)):
            linea = traza_salto(origen, pendiente, numero, -numero, numero, numero)
            self.assertNotIn("\n", linea)
            self.assertEqual(
                [campo.split("=", 1)[0] for campo in linea.split()],
                ["SALTO", "origen", "pendiente", "pos", "delta", "destino", "dur"])
            linea = traza_sin_barra(origen, numero)
            self.assertNotIn("\n", linea)
            self.assertEqual(
                [campo.split("=", 1)[0] for campo in linea.split()],
                ["SALTO_SIN_BARRA", "origen", "dur"])


class TestTopologia(unittest.TestCase):

    def test_topologia_etiquetas(self):
        self.assertEqual(topologia_medio(es_local=True), "local")
        self.assertEqual(topologia_medio(es_flujo=True), "flujo")
        self.assertEqual(topologia_medio(tiene_esclavo=True), "dividida")
        self.assertEqual(topologia_medio(), "unica")
        self.assertEqual(topologia_medio(es_local=True, tiene_esclavo=True), "local")
        self.assertEqual(topologia_medio(es_flujo=True, tiene_esclavo=True), "flujo")
        self.assertEqual(topologia_medio(usa_relevo=True), "relevo")
        self.assertEqual(topologia_medio(usa_relevo=True, tiene_esclavo=True), "relevo")
        self.assertEqual(topologia_medio(es_flujo=True, usa_relevo=True), "flujo")

    def test_traza_busqueda_orden_contiene_topologia_y_numeros_sin_url(self):
        linea = traza_busqueda_orden("dividida", "playing", 1000, 60000, 60000, 123)
        self.assertIn("topologia=dividida", linea)
        self.assertIn("estado=playing", linea)
        self.assertIn("confirmada=1000", linea)
        self.assertIn("destino=60000", linea)
        self.assertIn("muestra=60000", linea)
        self.assertIn("edad=123", linea)
        self.assertNotIn("http", linea)
        self.assertNotIn("://", linea)

    def test_traza_busqueda_desenlace_todos_resultados(self):
        for res in ("confirmado", "fallo", "vencido", "cancelado"):
            linea = traza_busqueda_desenlace("local", "paused", 0, 1000, 0, 10, res)
            self.assertIn(f"BUSQUEDA_{res.upper()}", linea)
            self.assertIn("topologia=local", linea)
            self.assertNotIn("http", linea)

    def test_traza_busqueda_no_filtra_url(self):
        # asegurar que nunca se pasa URL a la traza
        linea = traza_busqueda_orden("unica", "playing", 0, 0, 0, 0)
        for fragmento in ("googlevideo", "ytimg", "m3u8", "signature", "sig="):
            self.assertNotIn(fragmento, linea.lower())

    def test_traza_busqueda_muestra_campos_y_sin_url(self):
        linea = traza_busqueda_muestra("dividida", True, "playing", 1000, 60000, 60000, 120000, 60000, 123)
        self.assertIn("BUSQUEDA_MUESTRA", linea)
        self.assertIn("topologia=dividida", linea)
        self.assertIn("es_directo=si", linea)
        self.assertIn("estado=playing", linea)
        self.assertIn("confirmada=1000", linea)
        self.assertIn("destino=60000", linea)
        self.assertIn("muestra=60000", linea)
        self.assertIn("dur=120000", linea)
        self.assertIn("candidato=60000", linea)
        self.assertIn("edad=123", linea)
        self.assertNotIn("http", linea.lower())
        linea2 = traza_busqueda_muestra("unica", False, "paused", 0, 1000, 0, 10000, None, 0)
        self.assertIn("es_directo=no", linea2)
        self.assertIn("candidato=ninguno", linea2)
        for fragmento in ("googlevideo", "ytimg", "m3u8", "signature", "sig="):
            self.assertNotIn(fragmento, linea2.lower())

    def test_traza_inicio_muestra_campos_y_sin_url(self):
        linea = traza_inicio_muestra("unica", False, "playing", 1000, 1250)
        self.assertIn("INICIO_MUESTRA", linea)
        self.assertIn("topologia=unica", linea)
        self.assertIn("es_directo=no", linea)
        self.assertIn("estado=playing", linea)
        self.assertIn("primera=1000", linea)
        self.assertIn("muestra=1250", linea)
        self.assertNotIn("http", linea.lower())
        linea2 = traza_inicio_muestra("dividida", True, "paused", None, -1)
        self.assertIn("es_directo=si", linea2)
        self.assertIn("primera=ninguna", linea2)
        self.assertIn("muestra=ninguna", linea2)
        for fragmento in ("googlevideo", "ytimg", "m3u8", "signature", "sig="):
            self.assertNotIn(fragmento, linea2.lower())


if __name__ == "__main__":
    unittest.main()
