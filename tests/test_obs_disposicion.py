import unittest

import obs_disposicion as obs


class GeometriaTest(unittest.TestCase):
    def test_mascaras_y_coordenadas(self):
        self.assertEqual(obs.ANCLAJES["inferior-izquierda"], 9)
        self.assertEqual(obs.coordenadas("superior-izquierda", 1600, 900), (32, 18, 5))
        self.assertEqual(obs.coordenadas("centro", 1600, 900), (800, 450, 0))
        self.assertEqual(obs.coordenadas("inferior-derecha", 1600, 900), (1568, 882, 10))
        with self.assertRaises(ValueError):
            obs.coordenadas("medio", 1600, 900)

    def test_escala_para_y_fuente_sin_tamano(self):
        self.assertEqual(obs.escala_para(640, 360, 1280, 720), (0.5, 0.5))
        self.assertEqual(obs.escala_para(480, 360, 640, 480), (0.75, 0.75))
        self.assertIsNone(obs.escala_para(640, 360, 0, 720))
        self.assertIsNone(obs.escala_para(640, 360, 1280, -1))

    def test_rectangulo_para_las_nueve_mascaras(self):
        for nombre, mascara in obs.ANCLAJES.items():
            x, y, _ = obs.coordenadas(nombre, 1600, 900)
            rect = obs.rectangulo(x, y, 460, 620, mascara)
            esperado_x = x if "izquierda" in nombre else x - 460 if "derecha" in nombre else x - 230
            esperado_y = y if "superior" in nombre else y - 620 if "inferior" in nombre else y - 310
            self.assertEqual(rect[:2], (esperado_x, esperado_y))

    def test_areas_solape_y_fuera(self):
        self.assertEqual(obs.solape((0, 0, 100, 100), (50, 50, 100, 100)), 25.0)
        self.assertEqual(obs.solape((0, 0, 10, 10), (20, 20, 0, 10)), 0.0)
        self.assertEqual(obs.fuera_del_lienzo((-10, 0, 100, 100), 100, 100), 10.0)
        self.assertEqual(obs.fuera_del_lienzo((0, 0, 0, 100), 100, 100), 0.0)

    def test_reconoce_anclaje_con_tolerancia(self):
        self.assertEqual(obs.anclaje_de((32, 18, 460, 620), 1600, 900), "superior-izquierda")
        self.assertEqual(obs.anclaje_de((41, 18, 460, 620), 1600, 900), "")

    def test_posicion_libre_y_anclajes_personalizados(self):
        snap = obs.SnapshotPanel(conectado=True, izquierda=80, arriba=253, ancho=460, alto=620,
                                 lienzo_ancho=1600, lienzo_alto=900)
        self.assertEqual(obs.describir(snap, ("posicion",)),
                         "A 5% del borde izquierdo y a 3% del borde inferior.")

    def test_posicion_fuera_por_la_izquierda(self):
        snap = obs.SnapshotPanel(conectado=True, izquierda=-300, arriba=262,
                                 ancho=460, alto=620, lienzo_ancho=1600,
                                 lienzo_alto=900)
        self.assertEqual(obs.describir(snap, ("posicion",)),
                         "Se sale del lienzo por la izquierda, y a 2% del borde inferior.")

    def test_posicion_fuera_por_la_derecha(self):
        snap = obs.SnapshotPanel(conectado=True, izquierda=1500, arriba=262,
                                 ancho=460, alto=620, lienzo_ancho=1600,
                                 lienzo_alto=900)
        self.assertEqual(obs.describir(snap, ("posicion",)),
                         "Se sale del lienzo por la derecha, y a 2% del borde inferior.")

    def test_posicion_fuera_por_arriba(self):
        snap = obs.SnapshotPanel(conectado=True, izquierda=32, arriba=-200,
                                 ancho=460, alto=620, lienzo_ancho=1600,
                                 lienzo_alto=900)
        self.assertEqual(obs.describir(snap, ("posicion",)),
                         "Se sale del lienzo por arriba, y a 2% del borde izquierdo.")

    def test_posicion_fuera_por_abajo(self):
        snap = obs.SnapshotPanel(conectado=True, izquierda=32, arriba=500,
                                 ancho=460, alto=620, lienzo_ancho=1600,
                                 lienzo_alto=900)
        self.assertEqual(obs.describir(snap, ("posicion",)),
                         "Se sale del lienzo por abajo, y a 2% del borde izquierdo.")

    def test_posicion_sale_por_la_derecha_y_mantiene_la_distancia_vertical(self):
        snap = obs.SnapshotPanel(conectado=True, izquierda=1500, arriba=45,
                                 ancho=460, alto=300, lienzo_ancho=1600,
                                 lienzo_alto=900)
        self.assertEqual(obs.describir(snap, ("posicion",)),
                         "Se sale del lienzo por la derecha, y a 5% del borde superior.")

    def test_posicion_sale_por_dos_bordes(self):
        snap = obs.SnapshotPanel(conectado=True, izquierda=1500, arriba=800,
                                 ancho=460, alto=300, lienzo_ancho=1600,
                                 lienzo_alto=900)
        self.assertEqual(obs.describir(snap, ("posicion",)),
                         "Se sale del lienzo por la derecha y por abajo.")

    def test_posicion_sin_anclaje_nombra_los_dos_bordes(self):
        snap = obs.SnapshotPanel(conectado=True, izquierda=48, arriba=45,
                                 ancho=460, alto=300, lienzo_ancho=1600,
                                 lienzo_alto=900)
        self.assertEqual(obs.describir(snap, ("posicion",)),
                         "A 3% del borde izquierdo y a 5% del borde superior.")

    def test_posicion_en_los_nueve_anclajes(self):
        lugares = {
            "superior-izquierda": "esquina superior izquierda",
            "superior-centro": "borde superior, centrado",
            "superior-derecha": "esquina superior derecha",
            "centro-izquierda": "borde izquierdo, centrado",
            "centro": "centro",
            "centro-derecha": "borde derecho, centrado",
            "inferior-izquierda": "esquina inferior izquierda",
            "inferior-centro": "borde inferior, centrado",
            "inferior-derecha": "esquina inferior derecha",
        }
        for anclaje, lugar in lugares.items():
            x, y, alineacion = obs.coordenadas(anclaje, 1600, 900)
            izquierda, arriba, ancho, alto = obs.rectangulo(x, y, 460, 300, alineacion)
            snap = obs.SnapshotPanel(conectado=True, izquierda=izquierda, arriba=arriba,
                                     ancho=ancho, alto=alto, lienzo_ancho=1600,
                                     lienzo_alto=900)
            with self.subTest(anclaje=anclaje):
                self.assertEqual(obs.describir(snap, ("posicion",), "largo"),
                                 f"Posición: {lugar}")

    def test_superposicion_nombra_la_otra_fuente_y_su_porcentaje(self):
        snap = obs.SnapshotPanel(conectado=True, solapes=(("Cámara", 30.4),))
        self.assertEqual(obs.describir(snap, ("solape",), "largo"),
                         "Superpone al 30% de Cámara")

    def test_coordenadas_con_margen_cero(self):
        self.assertEqual(obs.coordenadas("superior-derecha", 100, 50, 0), (100, 0, 6))

    def test_rectangulo_centrado(self):
        self.assertEqual(obs.rectangulo(50, 50, 20, 10, 0), (40, 45, 20, 10))

    def test_rectangulo_solo_eje_horizontal(self):
        self.assertEqual(obs.rectangulo(50, 50, 20, 10, 2), (30, 45, 20, 10))

    def test_rectangulo_solo_eje_vertical(self):
        self.assertEqual(obs.rectangulo(50, 50, 20, 10, 8), (40, 40, 20, 10))

    def test_solape_sin_contacto(self):
        self.assertEqual(obs.solape((0, 0, 10, 10), (10, 0, 10, 10)), 0.0)

    def test_solape_completo(self):
        self.assertEqual(obs.solape((0, 0, 20, 20), (2, 2, 4, 4)), 100.0)

    def test_fuera_completo(self):
        self.assertEqual(obs.fuera_del_lienzo((200, 200, 10, 10), 100, 100), 100.0)

    def test_fuera_parcial_vertical(self):
        self.assertEqual(obs.fuera_del_lienzo((0, 90, 100, 20), 100, 100), 50.0)

    def test_anclaje_de_centro(self):
        self.assertEqual(obs.anclaje_de((30, 20, 40, 20), 100, 60, 0), "centro")

    def test_anclaje_de_inferior_derecha(self):
        self.assertEqual(obs.anclaje_de((70, 30, 30, 30), 100, 60, 0), "inferior-derecha")

    def test_anclaje_de_fuera_de_tolerancia_vertical(self):
        self.assertEqual(obs.anclaje_de((32, 24, 460, 620), 1600, 900), "")

    def test_conexion_conectada_corta_es_vacia(self):
        self.assertEqual(obs.describir(obs.SnapshotPanel(conectado=True), ("conexion",)), "")

    def test_sin_conexion_solo_informa_la_conexion(self):
        snap = obs.SnapshotPanel(escena="Juego", solapes=(("Cámara", 12.4),))
        self.assertEqual(obs.describir(snap, obs.ACTIVOS_DEFECTO), "Sin conexión con OBS.")
        self.assertEqual(obs.describir(snap, obs.ACTIVOS_DEFECTO, "largo"),
                         "Sin conexión con OBS")

    def test_escena_fuera_del_aire(self):
        snap = obs.SnapshotPanel(conectado=True, escena="Juego", al_aire=False)
        self.assertEqual(obs.describir(snap, ("escena",)), "Juego, no al aire.")

    def test_tamano_sin_datos(self):
        self.assertEqual(obs.describir(obs.SnapshotPanel(), ("tamano",)), "")

    def test_varios_solapes(self):
        snap = obs.SnapshotPanel(conectado=True,
                                 solapes=(("Cámara", 12.4), ("Juego", 4.1)))
        self.assertEqual(obs.describir(snap, ("solape",)),
                         "Superpone al 12% de Cámara y al 4% de Juego.")

    def test_varios_solapes_sin_conexion_no_se_describen(self):
        snap = obs.SnapshotPanel(solapes=(("Cámara", 12.4), ("Juego", 4.1)))
        self.assertEqual(obs.describir(snap, ("solape",)), "")

    def test_aspecto_parcial(self):
        snap = obs.SnapshotPanel(conectado=True, tamano_letra=18)
        self.assertEqual(obs.describir(snap, ("aspecto",)), "0 mensajes, letra 18.")

    def test_componentes_desconocidos_se_omiten(self):
        self.assertEqual(obs.describir(obs.SnapshotPanel(), ("inexistente",)), "")


class DescripcionTest(unittest.TestCase):

    def test_describir_preparacion_sin_obs(self):
        self.assertEqual(
            obs.describir_preparacion(False, False, None, False),
            "OBS no responde. En OBS, menú Herramientas, Configuración del "
            "servidor WebSocket, activa el servidor.")

    def test_describir_preparacion_falta_panel_y_fuente(self):
        self.assertEqual(
            obs.describir_preparacion(True, False, 8730, False),
            "Falta preparar el panel. El panel de chat está apagado. "
            "La fuente no está en esta escena.")

    def test_describir_preparacion_falta_solo_el_panel(self):
        self.assertEqual(
            obs.describir_preparacion(True, False, 8730, True),
            "Falta preparar el panel. El panel de chat está apagado.")

    def test_describir_preparacion_falta_solo_la_fuente(self):
        self.assertEqual(
            obs.describir_preparacion(True, True, 8730, False),
            "Falta preparar el panel. La fuente no está en esta escena.")

    def test_describir_preparacion_lista(self):
        self.assertEqual(
            obs.describir_preparacion(True, True, 8730, True),
            "Panel de chat encendido en el puerto 8730. "
            "La fuente está en esta escena.")

    def test_describir_fuente_en_corto_y_largo(self):
        snap = obs.SnapshotPanel(conectado=True, escena="Juego", ancho=400, alto=300,
                                 lienzo_ancho=1600, lienzo_alto=900)
        self.assertEqual(obs.describir_fuente("Cámara", snap, ("tamano", "escena")),
                         "Cámara. Juego; 400 por 300, 25% del ancho.")
        self.assertEqual(obs.describir_fuente("Cámara", snap, ("tamano", "escena"), "largo"),
                         "Fuente: Cámara\nEscena: Juego\nTamaño: 400 por 300 píxeles, 25% del ancho de pantalla")

    def test_describir_fuente_vacia_conserva_la_descripcion(self):
        snap = obs.SnapshotPanel(conectado=True, ancho=400, alto=300, lienzo_ancho=1600)
        self.assertEqual(obs.describir_fuente("", snap, ("tamano",)),
                         obs.describir(snap, ("tamano",)))
        self.assertEqual(obs.describir_fuente("", snap, ("tamano",), "largo"),
                         obs.describir(snap, ("tamano",), "largo"))
    def test_constantes_y_inmutabilidad(self):
        with self.assertRaises(Exception):
            obs.SnapshotPanel().escena = "Juego"
        self.assertEqual(len(obs.COMPONENTES), 11)
        self.assertIn("posicion", obs.ACTIVOS_DEFECTO)

    def test_componentes_cortos(self):
        s = obs.SnapshotPanel(conectado=True, escena="Juego", ancho=460, alto=620,
                              lienzo_ancho=1600, lienzo_alto=900, visible=False,
                              bloqueada=True, tapada_por="Cámara", solapes=(("Cámara", 12.4),),
                              fuera=12.4, mensajes_visibles=14, tamano_letra=18)
        self.assertEqual(obs.describir(s, ("escena",)), "Juego.")
        self.assertEqual(obs.describir(s, ("tamano",)), "460 por 620, 29% del ancho.")
        self.assertEqual(obs.describir(s, ("capa",)), "Lo tapa Cámara.")
        self.assertEqual(obs.describir(s, ("solape",)), "Superpone al 12% de Cámara.")
        self.assertEqual(obs.describir(s, ("visible",)), "Oculto.")
        self.assertEqual(obs.describir(s, ("bloqueada",)), "Fijado.")
        self.assertEqual(obs.describir(s, ("fuera",)), "Queda fuera del lienzo el 12% del panel.")
        self.assertEqual(obs.describir(s, ("aspecto",)), "14 mensajes, letra 18.")

    def test_fuera_corto_indica_recorte(self):
        snap = obs.SnapshotPanel(conectado=True, fuera=22.4)
        self.assertEqual(obs.describir(snap, ("fuera",)), "Queda fuera del lienzo el 22% del panel.")

    def test_fuera_largo_indica_recorte(self):
        snap = obs.SnapshotPanel(conectado=True, fuera=22.4)
        self.assertEqual(obs.describir(snap, ("fuera",), "largo"),
                         "Recorte: queda fuera del lienzo el 22% del panel")

    def test_fuera_cero_no_informa(self):
        snap = obs.SnapshotPanel(conectado=True)
        self.assertEqual(obs.describir(snap, ("fuera",)), "")
        self.assertEqual(obs.describir(snap, ("fuera",), "largo"), "")

    def test_posicion_y_recorte_no_colisionan_en_fuera(self):
        snap = obs.SnapshotPanel(conectado=True, izquierda=-300, arriba=262,
                                 ancho=460, alto=620, lienzo_ancho=1600,
                                 lienzo_alto=900, fuera=65.2)
        frase = obs.describir(snap, ("posicion", "fuera"))
        self.assertEqual(frase, "Se sale del lienzo por la izquierda, y a 2% del borde inferior; "
                                "Queda fuera del lienzo el 65% del panel.")
        self.assertEqual(frase.lower().count("fuera"), 1)

    def test_largo_y_union(self):
        s = obs.SnapshotPanel(conectado=True, escena="Juego", al_aire=False,
                              ancho=460, alto=620, lienzo_ancho=1600,
                              mensajes_visibles=14, tamano_letra=18)
        esperado = ("OBS: conectado\nEscena: Juego, no al aire\nTamaño: 460 por 620 píxeles, "
                    "29% del ancho de pantalla\nCapa: no lo tapa nada\n"
                    "No se superpone con ninguna otra fuente\nVisible: sí\n"
                    "Fijado: no\nAspecto: 14 mensajes visibles, tamaño de letra 18\n"
                    "El fondo del panel es transparente. Solo se ven las tarjetas de los mensajes, "
                    "apiladas contra el borde inferior.")
        self.assertEqual(obs.describir(s, obs.COMPONENTES, "largo"), esperado)
        self.assertEqual(obs.describir(obs.SnapshotPanel(), ("transparencia",), "corto"), "")
        self.assertEqual(obs.describir(obs.SnapshotPanel(), ("transparencia",), "largo"), "")


if __name__ == "__main__":
    unittest.main()
