"""Pruebas de las decisiones puras del reproductor."""

import unittest
import time
from unittest import mock
from types import SimpleNamespace

from busqueda_video import (
    CADUCIDAD_DESTINO_MS, EstadoBusqueda, PROGRESO_MINIMO_MS,
    TOLERANCIA_ATRAS_MS, TOLERANCIA_DESTINO_MS, TOPE_BUSQUEDA_MS,
    accion_play_pausa, destino_acumulado, destino_alcanzado, destino_vigente,
    posicion_a_mostrar, posicion_confiable, transporte_confirmado,
)


class TestDestinoAcumulado(unittest.TestCase):

    def test_empieza_en_la_posicion_real_si_no_hay_salto_pendiente(self):
        self.assertEqual(destino_acumulado(None, 10_000, 10_000, 60_000), 20_000)

    def test_acumula_sobre_el_salto_pendiente(self):
        self.assertEqual(destino_acumulado(20_000, 10_000, 10_000, 60_000), 30_000)

    def test_recorta_en_los_dos_extremos(self):
        self.assertEqual(destino_acumulado(None, 1_000, -10_000, 60_000), 0)
        self.assertEqual(destino_acumulado(None, 59_000, 10_000, 60_000), 60_000)

    def test_caso_real_sin_destino_pendiente_con_duracion_atrasada_conserva_base(self):
        self.assertEqual(destino_acumulado(None, 3_615_868, 60_000, 3_600_000), 3_615_868)

    def test_caso_real_con_destino_pendiente_con_duracion_atrasada_conserva_base(self):
        self.assertEqual(destino_acumulado(3_615_868, 3_000_000, 60_000, 3_600_000), 3_615_868)

    def test_avance_con_duracion_por_delante_recorta_a_duracion(self):
        self.assertEqual(destino_acumulado(None, 50_000, 20_000, 60_000), 60_000)

    def test_avance_con_destino_pendiente_y_duracion_por_delante_recorta(self):
        self.assertEqual(destino_acumulado(50_000, 10_000, 20_000, 60_000), 60_000)

    def test_avance_no_retrocede_monotonia(self):
        for base, delta, dur in [
            (3_615_868, 60_000, 3_600_000),
            (50_000, 20_000, 60_000),
            (10_000, 5_000, 60_000),
            (0, 10_000, 5_000),
        ]:
            with self.subTest(base=base, delta=delta, dur=dur):
                destino = destino_acumulado(None, base, delta, dur)
                self.assertGreaterEqual(destino, base)

    def test_retroceso_no_avanza_monotonia(self):
        for base, delta, dur in [
            (3_615_868, -10_000, 3_600_000),
            (50_000, -20_000, 60_000),
            (10_000, -5_000, 60_000),
        ]:
            with self.subTest(base=base, delta=delta, dur=dur):
                destino = destino_acumulado(None, base, delta, dur)
                self.assertLessEqual(destino, base)

    def test_retroceso_con_duracion_atrasada_no_recorta_por_duracion(self):
        # La duración que da VLC va por detrás de la posición: el retroceso
        # pedido se respeta en vez de saltar hasta esa duración.
        self.assertEqual(destino_acumulado(None, 3_615_868, -10_000, 3_600_000), 3_605_868)

    def test_retroceso_en_directo_con_duracion_falsa(self):
        # Caso real del registro: pos 2:08:57, VLC decía dur=15:00 y un
        # retroceso de 1 min acababa en 15:00 (casi dos horas atrás).
        self.assertEqual(destino_acumulado(None, 7_737_861, -60_000, 900_000), 7_677_861)

    def test_avance_con_duracion_falsa_no_pasa_de_la_base(self):
        self.assertEqual(destino_acumulado(None, 7_737_861, 60_000, 900_000), 7_737_861)

    def test_retroceso_respeta_limite_cero(self):
        self.assertEqual(destino_acumulado(None, 5_000, -10_000, 60_000), 0)

    def test_acumulacion_sobre_destino_pendiente_respeta_monotonia_avance(self):
        destino = destino_acumulado(3_615_868, 3_600_000, 60_000, 3_600_000)
        self.assertGreaterEqual(destino, 3_615_868)


class TestDestinoAlcanzado(unittest.TestCase):

    def test_sin_destino_pendiente_esta_alcanzado(self):
        self.assertTrue(destino_alcanzado(None, 0, TOLERANCIA_DESTINO_MS))

    def test_acepta_la_tolerancia_en_ambos_sentidos(self):
        self.assertTrue(destino_alcanzado(10_000, 8_500, TOLERANCIA_DESTINO_MS))
        self.assertTrue(destino_alcanzado(10_000, 11_500, TOLERANCIA_DESTINO_MS))
        self.assertFalse(destino_alcanzado(10_000, 8_499, TOLERANCIA_DESTINO_MS))


class TestPosicionAMostrar(unittest.TestCase):

    def test_prioriza_el_destino_pendiente(self):
        self.assertEqual(posicion_a_mostrar(20_000, 10_000), 20_000)

    def test_usa_la_posicion_real_sin_destino(self):
        self.assertEqual(posicion_a_mostrar(None, 10_000), 10_000)


class TestAccionPlayPausa(unittest.TestCase):

    def test_sin_medio_carga(self):
        self.assertEqual(accion_play_pausa("playing", False, True), "cargar")

    def test_estados_estables(self):
        self.assertEqual(accion_play_pausa("playing", True, True), "pausar")
        self.assertEqual(accion_play_pausa("paused", True, False), "reanudar")

    def test_estados_finales_recargan(self):
        for estado in ("ended", "stopped", "error", "nothingspecial"):
            with self.subTest(estado=estado):
                self.assertEqual(accion_play_pausa(estado, True, False), "cargar")

    def test_estados_transitorios_siguen_la_intencion(self):
        for estado in ("opening", "buffering", "futuro"):
            with self.subTest(estado=estado):
                self.assertEqual(accion_play_pausa(estado, True, True), "pausar")
                self.assertEqual(accion_play_pausa(estado, True, False), "reanudar")

    def test_orden_pendiente_contraria_en_reproduccion(self):
        self.assertEqual(accion_play_pausa("playing", True, False, True), "en_curso")

    def test_orden_pendiente_contraria_en_pausa(self):
        self.assertEqual(accion_play_pausa("paused", True, True, True), "en_curso")

    def test_orden_vencida_devuelve_el_estado_real(self):
        self.assertEqual(accion_play_pausa("playing", True, False, False), "pausar")

    def test_propiedad_valores_conocidos(self):
        estados = ("playing", "paused", "opening", "buffering", "ended", "stopped", "error", "nothingspecial", "otro")
        for estado in estados:
            for intencion in (False, True):
                for reciente in (False, True):
                    with self.subTest(estado=estado, intencion=intencion, reciente=reciente):
                        self.assertIn(accion_play_pausa(estado, True, intencion, reciente),
                                      {"cargar", "pausar", "reanudar", "en_curso"})


class TestTransporteConfirmado(unittest.TestCase):

    def test_pausa_solo_paused_confirma(self):
        self.assertTrue(transporte_confirmado("paused", False))
        self.assertFalse(transporte_confirmado("playing", False))
        self.assertFalse(transporte_confirmado("opening", False))
        self.assertFalse(transporte_confirmado("buffering", False))
        for estado in ("ended", "stopped", "error", "nothingspecial", "otro"):
            with self.subTest(estado=estado):
                self.assertFalse(transporte_confirmado(estado, False))

    def test_reanudacion_solo_playing_confirma(self):
        self.assertTrue(transporte_confirmado("playing", True))
        self.assertFalse(transporte_confirmado("paused", True))
        self.assertFalse(transporte_confirmado("opening", True))
        self.assertFalse(transporte_confirmado("buffering", True))
        for estado in ("ended", "stopped", "error", "nothingspecial", "otro"):
            with self.subTest(estado=estado):
                self.assertFalse(transporte_confirmado(estado, True))


class TestOrdenTransporte(unittest.TestCase):

    def test_confirmacion_simetrica_y_limite(self):
        from busqueda_video import OrdenTransporte, evaluar_transporte, PLAZO_TRANSPORTE_MS
        self.assertEqual(PLAZO_TRANSPORTE_MS, 8000)
        base = 100.0
        orden_pausa = OrdenTransporte(intencion_reproducir=False, instante=base)
        orden_play = OrdenTransporte(intencion_reproducir=True, instante=base)
        # justo antes
        self.assertEqual(evaluar_transporte(orden_pausa, "paused", base + 7.999), "confirmada")
        self.assertEqual(evaluar_transporte(orden_play, "playing", base + 7.999), "confirmada")
        # en el límite
        self.assertEqual(evaluar_transporte(orden_pausa, "paused", base + 8.0), "confirmada")
        self.assertEqual(evaluar_transporte(orden_play, "playing", base + 8.0), "confirmada")
        # después
        self.assertEqual(evaluar_transporte(orden_pausa, "playing", base + 8.001), "fallida")
        self.assertEqual(evaluar_transporte(orden_play, "paused", base + 8.001), "fallida")
        # estado contrario dentro del plazo permanece pendiente
        self.assertEqual(evaluar_transporte(orden_pausa, "playing", base + 1), "pendiente")
        self.assertEqual(evaluar_transporte(orden_play, "paused", base + 1), "pendiente")
        # transitorios pendientes hasta vencer
        for est in ("opening", "buffering", "otro"):
            self.assertEqual(evaluar_transporte(orden_pausa, est, base + 1), "pendiente")
            self.assertEqual(evaluar_transporte(orden_play, est, base + 1), "pendiente")
            self.assertEqual(evaluar_transporte(orden_pausa, est, base + 8.001), "fallida")

    def test_fallo_inmediato_por_estado_final(self):
        from busqueda_video import OrdenTransporte, evaluar_transporte
        base = 200.0
        for est in ("ended", "stopped", "error", "nothingspecial"):
            orden = OrdenTransporte(intencion_reproducir=False, instante=base)
            self.assertEqual(evaluar_transporte(orden, est, base + 0.1), "fallida")
            orden2 = OrdenTransporte(intencion_reproducir=True, instante=base)
            self.assertEqual(evaluar_transporte(orden2, est, base + 0.1), "fallida")

    def test_inmutable(self):
        from busqueda_video import OrdenTransporte
        orden = OrdenTransporte(intencion_reproducir=True, instante=1.0)
        with self.assertRaises(Exception):
            orden.intencion_reproducir = False  # type: ignore

    def test_playing_solo_confirma_reproducir(self):
        from busqueda_video import OrdenTransporte, evaluar_transporte
        base = 300.0
        orden_pausa = OrdenTransporte(intencion_reproducir=False, instante=base)
        orden_play = OrdenTransporte(intencion_reproducir=True, instante=base)
        self.assertEqual(evaluar_transporte(orden_play, "playing", base + 0.5), "confirmada")
        self.assertEqual(evaluar_transporte(orden_pausa, "playing", base + 0.5), "pendiente")
        self.assertEqual(evaluar_transporte(orden_pausa, "paused", base + 0.5), "confirmada")
        self.assertEqual(evaluar_transporte(orden_play, "paused", base + 0.5), "pendiente")

    def test_fronteras_en_ocho_segundos(self):
        from busqueda_video import OrdenTransporte, evaluar_transporte
        base = 100.0
        orden_pausa = OrdenTransporte(intencion_reproducir=False, instante=base)
        orden_play = OrdenTransporte(intencion_reproducir=True, instante=base)
        self.assertEqual(evaluar_transporte(orden_pausa, "paused", base + 8.0), "confirmada")
        self.assertEqual(evaluar_transporte(orden_play, "playing", base + 8.0), "confirmada")
        self.assertEqual(evaluar_transporte(orden_pausa, "playing", base + 8.0), "fallida")
        self.assertEqual(evaluar_transporte(orden_play, "paused", base + 8.0), "fallida")
        for est in ("opening", "buffering", "otro"):
            self.assertEqual(evaluar_transporte(orden_pausa, est, base + 8.0), "fallida")
            self.assertEqual(evaluar_transporte(orden_play, est, base + 8.0), "fallida")


class TestAccionConPendiente(unittest.TestCase):

    def test_pendiente_pausa_con_playing_da_en_curso(self):
        self.assertEqual(accion_play_pausa("playing", True, False, True), "en_curso")

    def test_pendiente_reanudar_con_paused_da_en_curso(self):
        self.assertEqual(accion_play_pausa("paused", True, True, True), "en_curso")

    def test_transitorio_con_pendiente_da_en_curso(self):
        for estado in ("opening", "buffering", "otro"):
            with self.subTest(estado=estado):
                self.assertEqual(accion_play_pausa(estado, True, True, True), "en_curso")
                self.assertEqual(accion_play_pausa(estado, True, False, True), "en_curso")

    def test_pendiente_no_bloquea_estados_finales(self):
        for estado in ("ended", "stopped", "error", "nothingspecial"):
            with self.subTest(estado=estado):
                self.assertEqual(accion_play_pausa(estado, True, False, True), "cargar")
                self.assertEqual(accion_play_pausa(estado, True, True, True), "cargar")

    def test_pendiente_confirmado_no_bloquea(self):
        self.assertEqual(accion_play_pausa("paused", True, False, True), "reanudar")
        self.assertEqual(accion_play_pausa("playing", True, True, True), "pausar")

    def test_sin_pendiente_transitorio_sigue_intencion(self):
        self.assertEqual(accion_play_pausa("opening", True, True, False), "pausar")
        self.assertEqual(accion_play_pausa("buffering", True, False, False), "reanudar")


class TestPosicionConfiable(unittest.TestCase):

    def test_retroceso_a_cero_se_descarta(self):
        self.assertEqual(posicion_confiable(31038, 0, 2000), 31038)

    def test_retroceso_grande_se_descarta(self):
        self.assertEqual(posicion_confiable(31038, 18812, 2000), 31038)

    def test_retroceso_dentro_de_tolerancia_se_conserva(self):
        self.assertEqual(posicion_confiable(31038, 30000, 2000), 30000)

    def test_avance_se_conserva(self):
        self.assertEqual(posicion_confiable(31038, 41000, 2000), 41000)

    def test_sin_ultima_lectura_acepta_cero(self):
        self.assertEqual(posicion_confiable(None, 0, 2000), 0)


class TestDestinoVigente(unittest.TestCase):

    def test_destino_vencido_caduca(self):
        self.assertIsNone(destino_vigente(776139, 43000, 5000))

    def test_destino_reciente_se_conserva(self):
        self.assertEqual(destino_vigente(776139, 1200, 5000), 776139)

    def test_sin_destino_sigue_vacio(self):
        self.assertIsNone(destino_vigente(None, 43000, 5000))


class TestCableadoBusqueda(unittest.TestCase):

    def test_pulsaciones_rapidas_acumulan_desde_el_destino_pendiente(self):
        import reproductor

        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._player = mock.Mock()
        panel._player.get_length.return_value = 60_000
        panel._player.get_time.return_value = 10_000
        panel._estado_busqueda = reproductor.EstadoBusqueda(confirmada=10_000)
        panel._tiene_esclavo = False
        panel._usando_cache_local = False
        panel._url_flujo = ""
        panel._fijar_tiempo = mock.Mock()
        panel.sld_pos = mock.Mock()

        with mock.patch.object(reproductor, "anunciar"):
            panel._buscar_rel(10_000)
            panel._buscar_rel(10_000)

        self.assertEqual(panel._player.set_time.call_args_list,
                         [mock.call(20_000), mock.call(30_000)])

    def test_salto_no_vuelve_a_cero_con_lectura_atrasada(self):
        import reproductor

        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._player = mock.Mock()
        panel._player.get_length.return_value = 60_000
        panel._player.get_time.return_value = 0
        panel._estado_busqueda = reproductor.EstadoBusqueda(confirmada=31_038)
        panel._tiene_esclavo = False
        panel._usando_cache_local = False
        panel._url_flujo = ""
        panel._fijar_tiempo = mock.Mock()

        panel._buscar_rel(-10_000)

        panel._player.set_time.assert_called_once_with(21_038)

    def test_salto_siguiente_conserva_como_referencia_el_destino_anterior(self):
        import reproductor

        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._player = mock.Mock()
        panel._player.get_length.return_value = 60_000
        panel._estado_busqueda = reproductor.EstadoBusqueda(confirmada=5_000)
        panel._tiene_esclavo = False
        panel._usando_cache_local = False
        panel._url_flujo = ""
        panel._fijar_tiempo = mock.Mock()

        panel._buscar_rel(20_000)
        # aún pendiente, acumula sobre destino anterior
        panel._buscar_rel(10_000)

        self.assertEqual(panel._player.set_time.call_args_list,
                         [mock.call(25_000), mock.call(35_000)])

    def test_on_timer_con_salto_en_vuelo_conserva_el_destino_pendiente(self):
        import reproductor

        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._player = mock.Mock()
        panel._player.get_length.return_value = 60_000
        panel._player.get_time.return_value = 10_000
        panel._player.get_state.return_value = SimpleNamespace(name="playing")
        panel._estado_busqueda = reproductor.EstadoBusqueda(confirmada=0)
        panel._estado_busqueda.destino = 30_000
        panel._estado_busqueda.marca_destino = __import__("time").monotonic()
        panel._estado_busqueda._gen = 1
        panel._muted = False
        panel._marca_url = None
        panel._fijar_tiempo = mock.Mock()
        panel.sld_pos = mock.Mock()
        panel._tiene_esclavo = False
        panel._usando_cache_local = False
        panel._url_flujo = ""

        estado_vlc = SimpleNamespace(State=SimpleNamespace(
            Playing="playing", Ended="ended"))
        with mock.patch.object(reproductor, "_vlc", estado_vlc):
            with mock.patch.object(reproductor.wx.Window, "FindFocus",
                                   return_value=None):
                panel._on_timer(None)

        self.assertEqual(panel._estado_busqueda.destino, 30_000)
        panel._fijar_tiempo.assert_called_once_with(
            0, 60_000, mover_slider=True, anunciar_t=False)

    def test_on_timer_al_alcanzar_el_salto_limpia_el_destino_pendiente(self):
        import reproductor

        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._player = mock.Mock()
        panel._player.get_length.return_value = 60_000
        panel._player.get_time.return_value = 29_000
        panel._player.get_state.return_value = SimpleNamespace(name="playing")
        panel._muted = False
        panel._marca_url = None
        panel._fijar_tiempo = mock.Mock()
        panel.sld_pos = mock.Mock()
        panel._tiene_esclavo = False
        panel._usando_cache_local = False
        panel._url_flujo = ""
        bus = reproductor.EstadoBusqueda(confirmada=0)
        bus.solicitar(30_000, __import__("time").monotonic() - 0.1)
        bus.candidato = 29_000
        panel._estado_busqueda = bus

        estado_vlc = SimpleNamespace(State=SimpleNamespace(
            Playing="playing", Ended="ended"))
        with mock.patch.object(reproductor, "_vlc", estado_vlc):
            with mock.patch.object(reproductor.wx.Window, "FindFocus",
                                   return_value=None):
                with mock.patch.object(reproductor, "anunciar") as anunciar:
                    panel._player.get_time.return_value = 29_300
                    panel._player.get_state.return_value = SimpleNamespace(name="playing")
                    panel._on_timer(None)

        self.assertIsNone(panel._estado_busqueda.destino)
        self.assertEqual(panel._estado_busqueda.confirmada, 29_300)
        anunciar.assert_called_once()
        self.assertIn("Posición", anunciar.call_args[0][0])

    def test_buscar_rel_caso_real_con_duracion_atrasada_no_retrocede(self):
        import reproductor

        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._player = mock.Mock()
        panel._player.get_length.return_value = 3_600_000
        panel._player.get_time.return_value = 3_615_868
        panel._estado_busqueda = reproductor.EstadoBusqueda(confirmada=3_615_868)
        panel._tiene_esclavo = False
        panel._usando_cache_local = False
        panel._url_flujo = ""
        panel._fijar_tiempo = mock.Mock()
        panel.sld_pos = mock.Mock()
        panel._tiene_esclavo = False

        with mock.patch.object(reproductor, "anunciar"):
            panel._buscar_rel(60_000)

        panel._player.set_time.assert_called_once_with(3_615_868)
        self.assertEqual(panel._estado_busqueda.destino, 3_615_868)
        self.assertEqual(panel._fijar_tiempo.call_args[0][0], 3_615_868)
        self.assertEqual(panel._fijar_tiempo.call_args[0][1], 3_600_000)

    def test_deslizador_con_busqueda_pendiente_es_absoluto(self):
        import reproductor
        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._player = mock.Mock()
        panel._player.get_length.return_value = 100_000
        panel._player.get_time.return_value = 10_000
        panel._estado_busqueda = reproductor.EstadoBusqueda(confirmada=10_000)
        panel._estado_busqueda.solicitar(20_000, time.monotonic())
        panel._tiene_esclavo = False
        panel._usando_cache_local = False
        panel._url_flujo = ""
        panel._fijar_tiempo = mock.Mock()
        panel.sld_pos = mock.Mock()
        panel.sld_pos.GetValue.return_value = 300
        with mock.patch.object(reproductor, "anunciar"):
            panel._on_sld_pos(None)
        panel._player.set_time.assert_called_once_with(30_000)
        self.assertEqual(panel._estado_busqueda.destino, 30_000)

    def test_porcentaje_con_busqueda_pendiente_es_absoluto(self):
        import reproductor
        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._player = mock.Mock()
        panel._player.get_length.return_value = 100_000
        panel._estado_busqueda = reproductor.EstadoBusqueda(confirmada=10_000)
        panel._estado_busqueda.solicitar(20_000, time.monotonic())
        panel._tiene_esclavo = False
        panel._usando_cache_local = False
        panel._url_flujo = ""
        panel._fijar_tiempo = mock.Mock()
        panel.sld_pos = mock.Mock()
        with mock.patch.object(reproductor, "anunciar"):
            panel._buscar_porcentaje(30)
        panel._player.set_time.assert_called_once_with(30_000)
        self.assertEqual(panel._estado_busqueda.destino, 30_000)


class TestCableadoPlayPausa(unittest.TestCase):

    def test_orden_en_curso_no_invierte_ni_anuncia(self):
        import reproductor
        import time as _t
        from busqueda_video import OrdenTransporte

        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._player = mock.Mock()
        panel._player.get_state.return_value = SimpleNamespace(name="playing")
        panel._video_id = "video-cargado"
        panel._url_flujo = ""
        panel._intencion_reproducir = True
        panel._orden_transporte = OrdenTransporte(intencion_reproducir=False, instante=_t.monotonic())
        panel._transporte_pendiente = True
        panel._asegurar_player = mock.Mock(return_value=True)
        panel._timer = mock.Mock()
        panel._mostrar_pausa = mock.Mock()

        with mock.patch.object(reproductor, "anunciar") as anunciar, \
                mock.patch("sound_player.reproducir") as sonido:
            panel._toggle_play()

        panel._player.set_pause.assert_not_called()
        anunciar.assert_not_called()
        sonido.assert_called_once_with("transporte_en_curso")

    def test_buffering_pausa_sin_recargar_el_video(self):
        import reproductor

        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._player = mock.Mock()
        panel._player.get_state.return_value = SimpleNamespace(name="Buffering")
        panel._video_id = "video-cargado"
        panel._url_flujo = ""
        panel._intencion_reproducir = True
        panel._transporte_pendiente = False
        panel._asegurar_player = mock.Mock(return_value=True)
        panel._mostrar_pausa = mock.Mock()
        panel._timer = mock.Mock()
        panel.cargar = mock.Mock()

        with mock.patch.object(reproductor, "anunciar"):
            panel._toggle_play()

        panel._player.set_pause.assert_called_once_with(1)
        panel.cargar.assert_not_called()


class TestPendienteSecuencial(unittest.TestCase):

    def _panel_pausa(self):
        import reproductor
        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._player = mock.Mock()
        panel._player.get_state.return_value = SimpleNamespace(name="playing")
        panel._player.can_pause.return_value = 1
        panel._player.is_seekable.return_value = 1
        panel._listo = True
        panel._video_id = "video-cargado"
        panel._url_flujo = ""
        panel._intencion_reproducir = True
        panel._transporte_pendiente = False
        panel._asegurar_player = mock.Mock(return_value=True)
        panel._mostrar_pausa = mock.Mock()
        panel._timer = mock.Mock()
        panel.cargar = mock.Mock()
        panel._reproducir_flujo = mock.Mock()
        return panel

    def _panel_reanudar(self):
        import reproductor
        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._player = mock.Mock()
        panel._player.get_state.return_value = SimpleNamespace(name="paused")
        panel._player.can_pause.return_value = 1
        panel._player.is_seekable.return_value = 1
        panel._listo = True
        panel._video_id = "video-cargado"
        panel._url_flujo = ""
        panel._intencion_reproducir = False
        panel._transporte_pendiente = False
        panel._asegurar_player = mock.Mock(return_value=True)
        panel._mostrar_pausa = mock.Mock()
        panel._timer = mock.Mock()
        panel.cargar = mock.Mock()
        panel._reproducir_flujo = mock.Mock()
        return panel

    def test_secuencia_pausa_vence_a_los_ocho_segundos_y_permite_reintentar(self):
        import reproductor
        panel = self._panel_pausa()
        inicio = reproductor.time.monotonic()
        with mock.patch.object(reproductor, "anunciar") as anunciar, \
                mock.patch("sound_player.reproducir") as sonido:
            panel._toggle_play()
            self.assertEqual(panel._player.set_pause.call_count, 1)
            self.assertEqual(panel._player.set_pause.call_args[0][0], 1)
            # la intención aún no cambia hasta confirmar
            self.assertTrue(panel._intencion_reproducir)
            self.assertTrue(panel._transporte_pendiente)
            self.assertIsNotNone(panel._orden_transporte)
            anunciar.assert_called_once_with("Pausando")
            panel._mostrar_pausa.assert_not_called()
            anunciar.reset_mock()
            panel._mostrar_pausa.reset_mock()
            sonido.reset_mock()
            # dentro del plazo sigue en curso
            panel._player.set_pause.reset_mock()
            with mock.patch.object(reproductor.time, "monotonic", return_value=inicio + 1):
                panel._toggle_play()
            panel._player.set_pause.assert_not_called()
            anunciar.assert_not_called()
            panel._mostrar_pausa.assert_not_called()
            sonido.assert_called_once_with("transporte_en_curso")
            self.assertTrue(panel._transporte_pendiente)
            sonido.reset_mock()
            # después de 8 s vence y permite reintentar
            panel._player.set_pause.reset_mock()
            with mock.patch.object(reproductor.time, "monotonic", return_value=inicio + 9):
                panel._toggle_play()
                # venció y volvió a solicitar
                self.assertEqual(panel._player.set_pause.call_count, 1)
                self.assertEqual(panel._player.set_pause.call_args[0][0], 1)

    def test_secuencia_reanudar_vence_a_los_ocho_segundos_y_permite_reintentar(self):
        import reproductor
        panel = self._panel_reanudar()
        inicio = reproductor.time.monotonic()
        with mock.patch.object(reproductor, "anunciar") as anunciar, \
                mock.patch("sound_player.reproducir") as sonido:
            panel._toggle_play()
            self.assertEqual(panel._player.set_pause.call_args[0][0], 0)
            self.assertFalse(panel._intencion_reproducir)
            self.assertTrue(panel._transporte_pendiente)
            anunciar.assert_called_once_with("Reanudando")
            anunciar.reset_mock()
            panel._mostrar_pausa.reset_mock()
            sonido.reset_mock()
            panel._player.set_pause.reset_mock()
            # dentro del plazo sigue en curso
            with mock.patch.object(reproductor.time, "monotonic", return_value=inicio + 1):
                panel._toggle_play()
            panel._player.set_pause.assert_not_called()
            anunciar.assert_not_called()
            sonido.assert_called_once_with("transporte_en_curso")
            sonido.reset_mock()
            # después de 8 s vence y permite reintentar
            panel._player.get_state.return_value = SimpleNamespace(name="paused")
            panel._player.set_pause.reset_mock()
            with mock.patch.object(reproductor.time, "monotonic", return_value=inicio + 9):
                panel._toggle_play()
                self.assertEqual(panel._player.set_pause.call_count, 1)

    def test_transitorio_no_confirma_y_mantiene_en_curso(self):
        import reproductor
        panel = self._panel_pausa()
        inicio = reproductor.time.monotonic()
        with mock.patch.object(reproductor, "anunciar"), \
                mock.patch("sound_player.reproducir"):
            panel._toggle_play()
        self.assertTrue(panel._transporte_pendiente)
        panel._player.get_state.return_value = SimpleNamespace(name="opening")
        panel._player.set_pause.reset_mock()
        with mock.patch.object(reproductor.time, "monotonic", return_value=inicio + 1), \
                mock.patch.object(reproductor, "anunciar") as anunciar, \
                mock.patch("sound_player.reproducir") as sonido:
            panel._toggle_play()
        panel._player.set_pause.assert_not_called()
        anunciar.assert_not_called()
        sonido.assert_called_once_with("transporte_en_curso")
        # buffering tampoco confirma dentro del plazo
        panel._player.get_state.return_value = SimpleNamespace(name="buffering")
        panel._player.set_pause.reset_mock()
        sonido.reset_mock()
        with mock.patch.object(reproductor.time, "monotonic", return_value=inicio + 2), \
                mock.patch.object(reproductor, "anunciar") as anunciar, \
                mock.patch("sound_player.reproducir") as sonido:
            panel._toggle_play()
        panel._player.set_pause.assert_not_called()
        sonido.assert_called_once_with("transporte_en_curso")

    def test_cancelacion_al_detener_y_cargar(self):
        import reproductor
        # Al detener
        panel = self._panel_pausa()
        with mock.patch.object(reproductor, "anunciar"), \
                mock.patch("sound_player.reproducir"):
            panel._toggle_play()
        self.assertTrue(panel._transporte_pendiente)
        panel._timer_progreso = mock.Mock()
        panel._gen = 0
        panel._tarea_cache_video = None
        panel.lbl_estado = mock.Mock()
        panel.btn_play = mock.Mock()
        panel._fijar_tiempo = mock.Mock()
        panel._detener(silencioso=True)
        self.assertFalse(panel._transporte_pendiente)
        # Siguiente toggle sin pendiente debe actuar normal
        panel._player.get_state.return_value = SimpleNamespace(name="paused")
        panel._intencion_reproducir = False
        panel._transporte_pendiente = False
        panel._orden_transporte = None
        panel._player.set_pause.reset_mock()
        with mock.patch.object(reproductor, "anunciar") as anunciar, \
                mock.patch("sound_player.reproducir") as sonido:
            panel._toggle_play()
        panel._player.set_pause.assert_called_once_with(0)
        anunciar.assert_called_once_with("Reanudando")
        # Al cargar otro medio
        panel2 = self._panel_pausa()
        with mock.patch.object(reproductor, "anunciar"), \
                mock.patch("sound_player.reproducir"):
            panel2._toggle_play()
        self.assertTrue(panel2._transporte_pendiente)
        panel2._cargando = False
        panel2._gen = 0
        panel2.lbl_estado = mock.Mock()
        panel2._timer_progreso = mock.Mock()
        panel2._asegurar_player = mock.Mock(return_value=True)
        # restaurar el método real de cargar para probar la cancelación
        panel2.cargar = reproductor.ReproductorPanel.cargar.__get__(panel2, reproductor.ReproductorPanel)
        with mock.patch.object(reproductor, "anunciar"), \
                mock.patch.object(reproductor.diagnostico, "crear_hilo") as crear:
            crear.return_value.start = mock.Mock()
            panel2.cargar(reproducir=True)
        self.assertFalse(panel2._transporte_pendiente)

    def test_estado_final_no_queda_bloqueado_por_pendiente(self):
        import reproductor
        panel = self._panel_pausa()
        with mock.patch.object(reproductor, "anunciar"), \
                mock.patch("sound_player.reproducir"):
            panel._toggle_play()
        self.assertTrue(panel._transporte_pendiente)
        for estado in ("ended", "stopped", "error", "nothingspecial"):
            panel._player.get_state.return_value = SimpleNamespace(name=estado)
            panel.cargar = mock.Mock()
            with mock.patch.object(reproductor, "anunciar"), \
                    mock.patch("sound_player.reproducir") as sonido:
                panel._toggle_play()
            panel.cargar.assert_called_once_with(reproducir=True)
            sonido.assert_not_called()
            panel.cargar.reset_mock()


class TestTransporteContratos(unittest.TestCase):

    def _panel(self, estado="playing", intencion=True):
        import reproductor
        from busqueda_video import EstadoBusqueda, EstadoInicioReproduccion
        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._player = mock.Mock()
        panel._player.get_state.return_value = SimpleNamespace(name=estado)
        panel._player.get_time.return_value = 0
        panel._player.get_length.return_value = 100000
        panel._player.can_pause.return_value = 1
        panel._player.is_seekable.return_value = 1
        panel._player.audio_get_volume.return_value = 80
        panel._listo = True
        panel._video_id = "video-cargado"
        panel._url_flujo = ""
        panel._intencion_reproducir = intencion
        panel._transporte_pendiente = False
        panel._orden_transporte = None
        panel._estado_busqueda = EstadoBusqueda(confirmada=0)
        panel._estado_inicio = EstadoInicioReproduccion()
        panel._muted = False
        panel._vol = 80
        panel._marca_url = None
        panel._marca_reproduccion = None
        panel._marca_extraccion = None
        panel._asegurar_player = mock.Mock(return_value=True)
        panel._mostrar_pausa = mock.Mock()
        panel._timer = mock.Mock()
        panel._timer.IsRunning.return_value = False
        panel._fijar_tiempo = mock.Mock()
        panel.sld_pos = mock.Mock()
        panel.lbl_estado = mock.Mock()
        panel.cargar = mock.Mock()
        panel._reproducir_flujo = reproductor.ReproductorPanel._reproducir_flujo.__get__(panel, reproductor.ReproductorPanel)
        panel._gen = 0
        panel._cargando = False
        panel._config = {"cache_video_mb": 1024}
        panel._tarea_cache_video = None
        panel._timer_progreso = mock.Mock()
        panel._inst = mock.Mock()
        return panel

    def test_solicitud_sin_anuncio_optimista(self):
        import reproductor
        panel = self._panel(estado="playing", intencion=True)
        with mock.patch.object(reproductor, "anunciar") as anunciar, mock.patch("sound_player.reproducir"):
            panel._toggle_play()
            anunciar.assert_called_once_with("Pausando")
            panel._mostrar_pausa.assert_not_called()
            self.assertTrue(panel._intencion_reproducir)  # aún no cambia
            self.assertTrue(panel._transporte_pendiente)
            panel._player.set_pause.assert_called_once_with(1)

    def test_confirmacion_por_evento_trasladado(self):
        import reproductor
        import types
        panel = self._panel(estado="playing", intencion=True)
        panel._player.get_state.return_value = SimpleNamespace(name="playing")
        with mock.patch.object(reproductor, "anunciar"), mock.patch("sound_player.reproducir"):
            panel._toggle_play()
        ident = panel._player
        pausa_tipo = object()
        play_tipo = object()
        tipos = types.SimpleNamespace(MediaPlayerPaused=pausa_tipo, MediaPlayerPlaying=play_tipo)
        gestor_falso = mock.Mock()
        panel._player.event_manager = mock.Mock(return_value=gestor_falso)
        vlc_falso = types.SimpleNamespace(EventType=tipos)
        with mock.patch.object(reproductor, "_vlc", vlc_falso), \
             mock.patch.object(reproductor, "_registro_detallado_activo", return_value=False):
            panel._enganchar_eventos_vlc()
        cb_pausado = None
        for tipo, fn in panel._callbacks_vlc:
            if tipo is pausa_tipo:
                cb_pausado = fn
                break
        self.assertIsNotNone(cb_pausado, "callback de pausa no enganchado")
        with mock.patch.object(reproductor.wx, "CallAfter") as call_after:
            cb_pausado(mock.Mock())
            call_after.assert_called_once()
            fn_trasladada, ident_trasladado, estado_trasladado = call_after.call_args[0]
            self.assertIs(fn_trasladada.__self__, panel)
            self.assertIs(fn_trasladada.__func__, panel._evaluar_transporte_desde_evento.__func__)
            self.assertIs(ident_trasladado, ident)
            self.assertEqual(estado_trasladado, "paused")
            with mock.patch.object(reproductor, "anunciar") as anunciar:
                fn_trasladada(ident_trasladado, estado_trasladado)
                anunciar.assert_called_once_with("Pausa")
                panel._mostrar_pausa.assert_called_with(False)
                self.assertIsNone(panel._orden_transporte)
                self.assertFalse(panel._transporte_pendiente)
                self.assertFalse(panel._intencion_reproducir)
        # callback de un player anterior llega a CallAfter pero no altera la orden actual
        panel2 = self._panel(estado="playing", intencion=True)
        panel2._player.get_state.return_value = SimpleNamespace(name="playing")
        with mock.patch.object(reproductor, "anunciar"), mock.patch("sound_player.reproducir"):
            panel2._toggle_play()
        ident_viejo = panel2._player
        pausa_tipo2 = object()
        play_tipo2 = object()
        tipos2 = types.SimpleNamespace(MediaPlayerPaused=pausa_tipo2, MediaPlayerPlaying=play_tipo2)
        gestor2 = mock.Mock()
        panel2._player.event_manager = mock.Mock(return_value=gestor2)
        vlc_falso2 = types.SimpleNamespace(EventType=tipos2)
        with mock.patch.object(reproductor, "_vlc", vlc_falso2), \
             mock.patch.object(reproductor, "_registro_detallado_activo", return_value=False):
            panel2._enganchar_eventos_vlc()
        cb_viejo = None
        for tipo, fn in panel2._callbacks_vlc:
            if tipo is pausa_tipo2:
                cb_viejo = fn
                break
        self.assertIsNotNone(cb_viejo)
        nuevo_player = mock.Mock()
        nuevo_player.get_state.return_value = SimpleNamespace(name="playing")
        panel2._player = nuevo_player
        with mock.patch.object(reproductor.wx, "CallAfter") as call_after:
            cb_viejo(mock.Mock())
            call_after.assert_called_once()
            fn_v, ident_v, estado_v = call_after.call_args[0]
            self.assertIs(ident_v, ident_viejo)
            self.assertEqual(estado_v, "paused")
            self.assertIs(fn_v.__self__, panel2)
            with mock.patch.object(reproductor, "anunciar") as anunciar:
                fn_v(ident_v, estado_v)
                anunciar.assert_not_called()
                self.assertIsNotNone(panel2._orden_transporte)
                self.assertTrue(panel2._transporte_pendiente)

    def test_confirmacion_por_timer_sin_evento(self):
        import reproductor
        panel = self._panel(estado="playing", intencion=True)
        with mock.patch.object(reproductor, "anunciar"), mock.patch("sound_player.reproducir"):
            panel._toggle_play()
        panel._player.get_state.return_value = SimpleNamespace(name="paused")
        # sin evento, el timer evalúa
        with mock.patch.object(reproductor, "anunciar") as anunciar:
            with mock.patch.object(reproductor.wx.Window, "FindFocus", return_value=None):
                panel._on_timer(None)
            anunciar.assert_any_call("Pausa")
            self.assertIsNone(panel._orden_transporte)

    def test_vencimiento_reconcilia_y_permite_reintentar(self):
        import reproductor
        panel = self._panel(estado="playing", intencion=True)
        with mock.patch.object(reproductor, "anunciar"), mock.patch("sound_player.reproducir"):
            panel._toggle_play()
        orden = panel._orden_transporte
        self.assertIsNotNone(orden)
        # vencer
        futuro = orden.instante + 9
        panel._player.get_state.return_value = SimpleNamespace(name="playing")
        with mock.patch.object(reproductor.time, "monotonic", return_value=futuro), \
             mock.patch.object(reproductor, "anunciar") as anunciar:
            with mock.patch.object(reproductor.wx.Window, "FindFocus", return_value=None):
                panel._on_timer(None)
            anunciar.assert_called_with("No se pudo pausar")
            self.assertIsNone(panel._orden_transporte)
            self.assertTrue(panel._intencion_reproducir)
        # nuevo intento debe funcionar
        panel._player.set_pause.reset_mock()
        with mock.patch.object(reproductor, "anunciar") as anunciar, mock.patch("sound_player.reproducir"):
            panel._toggle_play()
            panel._player.set_pause.assert_called_once_with(1)
            anunciar.assert_called_with("Pausando")

    def test_pulsacion_repetida_solo_sonido(self):
        import reproductor
        panel = self._panel(estado="playing", intencion=True)
        with mock.patch.object(reproductor, "anunciar"), mock.patch("sound_player.reproducir"):
            panel._toggle_play()
        panel._player.set_pause.reset_mock()
        with mock.patch.object(reproductor, "anunciar") as anunciar, mock.patch("sound_player.reproducir") as sonido:
            panel._toggle_play()
            panel._player.set_pause.assert_not_called()
            anunciar.assert_not_called()
            sonido.assert_called_once_with("transporte_en_curso")
            panel._player.set_pause.assert_not_called()

    def test_evento_player_anterior_no_hace_nada(self):
        import reproductor
        panel = self._panel(estado="playing", intencion=True)
        with mock.patch.object(reproductor, "anunciar"), mock.patch("sound_player.reproducir"):
            panel._toggle_play()
        viejo = panel._player
        nuevo = mock.Mock()
        nuevo.get_state.return_value = SimpleNamespace(name="paused")
        panel._player = nuevo
        with mock.patch.object(reproductor, "anunciar") as anunciar:
            panel._evaluar_transporte_desde_evento(viejo, "paused")
            anunciar.assert_not_called()
            self.assertIsNotNone(panel._orden_transporte)

    def test_evento_posterior_a_cancelar_no_hace_nada(self):
        import reproductor
        panel = self._panel(estado="playing", intencion=True)
        with mock.patch.object(reproductor, "anunciar"), mock.patch("sound_player.reproducir"):
            panel._toggle_play()
        ident = panel._player
        panel._cancelar_transporte()
        with mock.patch.object(reproductor, "anunciar") as anunciar:
            panel._evaluar_transporte_desde_evento(ident, "paused")
            anunciar.assert_not_called()

    def test_cancelar_al_detener_cargar_y_flujo(self):
        import reproductor
        for modo in ("detener", "cargar", "flujo"):
            panel = self._panel(estado="playing", intencion=True)
            with mock.patch.object(reproductor, "anunciar"), mock.patch("sound_player.reproducir"):
                panel._toggle_play()
            self.assertIsNotNone(panel._orden_transporte)
            if modo == "detener":
                panel._timer_progreso = mock.Mock()
                panel._gen = 0
                panel.lbl_estado = mock.Mock()
                panel.btn_play = mock.Mock()
                panel._fijar_tiempo = mock.Mock()
                panel._detener(silencioso=True)
            elif modo == "cargar":
                panel._cargando = False
                panel._gen = 0
                panel.lbl_estado = mock.Mock()
                panel._timer_progreso = mock.Mock()
                panel._asegurar_player = mock.Mock(return_value=True)
                panel.cargar = reproductor.ReproductorPanel.cargar.__get__(panel, reproductor.ReproductorPanel)
                with mock.patch.object(reproductor, "anunciar"), mock.patch.object(reproductor.diagnostico, "crear_hilo") as crear:
                    crear.return_value.start = mock.Mock()
                    panel.cargar(reproducir=True)
            else:
                panel._url_flujo = "http://example.com/stream.m3u8"
                panel._asegurar_player = mock.Mock(return_value=True)
                panel._inst = mock.Mock()
                panel._inst.media_new.return_value = mock.Mock()
                panel._player.set_media = mock.Mock()
                panel._player.audio_set_volume = mock.Mock()
                panel._player.audio_set_mute = mock.Mock()
                panel._player.play = mock.Mock()
                panel._mostrar_pausa = mock.Mock()
                panel._timer = mock.Mock()
                with mock.patch.object(reproductor, "anunciar"):
                    panel._reproducir_flujo()
            self.assertIsNone(panel._orden_transporte)
            self.assertFalse(panel._transporte_pendiente)
            # evento posterior no hace nada
            with mock.patch.object(reproductor, "anunciar") as anunciar:
                panel._evaluar_transporte_desde_evento(panel._player, "paused")
                anunciar.assert_not_called()

    def test_busqueda_durante_pausa_mantiene_muestras(self):
        import reproductor
        panel = self._panel(estado="paused", intencion=False)
        panel._estado_busqueda = reproductor.EstadoBusqueda(confirmada=0)
        panel._player.get_length.return_value = 100000
        panel._player.get_time.return_value = 0
        panel._timer = mock.Mock()
        panel._timer.IsRunning.return_value = False
        # iniciar pausa confirmada? simular que estamos pausados con timer detenido
        panel._timer.reset_mock()
        with mock.patch.object(reproductor, "anunciar"):
            panel._buscar_rel(10000)
        # _marcar_destino debe haber arrancado el timer aunque está pausado
        panel._timer.Start.assert_called()

    def test_finalizar_pausa_no_detiene_timer_si_busqueda_pendiente(self):
        import reproductor
        import time as _t
        panel = self._panel(estado="playing", intencion=True)
        # crear búsqueda pendiente real
        panel._estado_busqueda.solicitar(50000, _t.monotonic())
        panel._timer = mock.Mock()
        panel._timer.IsRunning.return_value = True
        with mock.patch.object(reproductor, "anunciar"), mock.patch("sound_player.reproducir"):
            panel._toggle_play()  # solicita pausa
        panel._player.get_state.return_value = SimpleNamespace(name="paused")
        with mock.patch.object(reproductor, "anunciar"):
            with mock.patch.object(reproductor.wx.Window, "FindFocus", return_value=None):
                panel._on_timer(None)  # confirma pausa
            # timer no debe detenerse por búsqueda pendiente
            panel._timer.Stop.assert_not_called()
            self.assertTrue(panel._estado_busqueda.pendiente)

    def test_busqueda_confirmada_en_pausa_detiene_timer(self):
        import reproductor
        import time as _t
        panel = self._panel(estado="paused", intencion=False)
        panel._orden_transporte = None
        panel._transporte_pendiente = False
        panel._estado_busqueda = reproductor.EstadoBusqueda(confirmada=0)
        panel._estado_busqueda.solicitar(50000, _t.monotonic() - 0.5)
        panel._estado_busqueda.candidato = 50000
        panel._player.get_length.return_value = 100000
        panel._player.get_time.return_value = 50300
        llamadas = []
        def fake_estado():
            llamadas.append(1)
            if len(llamadas) == 2:
                return "playing"
            return "paused"
        panel._estado_vlc_actual = fake_estado
        panel._timer = mock.Mock()
        with mock.patch.object(reproductor, "anunciar"):
            with mock.patch.object(reproductor.wx.Window, "FindFocus", return_value=None):
                panel._on_timer(None)
        self.assertFalse(panel._estado_busqueda.pendiente)
        panel._timer.Stop.assert_called_once()

    def test_busqueda_vencida_en_pausa_detiene_timer(self):
        import reproductor
        import time as _t
        panel = self._panel(estado="paused", intencion=False)
        panel._orden_transporte = None
        panel._transporte_pendiente = False
        panel._estado_busqueda = reproductor.EstadoBusqueda(confirmada=1000)
        panel._estado_busqueda.solicitar(50000, _t.monotonic() - 9)
        panel._player.get_length.return_value = 100000
        panel._player.get_time.return_value = 1000
        panel._player.get_state.return_value = SimpleNamespace(name="paused")
        panel._timer = mock.Mock()
        with mock.patch.object(reproductor, "anunciar"):
            with mock.patch.object(reproductor.wx.Window, "FindFocus", return_value=None):
                panel._on_timer(None)
        self.assertFalse(panel._estado_busqueda.pendiente)
        panel._timer.Stop.assert_called_once()

    def test_busqueda_pendiente_en_pausa_no_detiene_timer(self):
        import reproductor
        import time as _t
        panel = self._panel(estado="paused", intencion=False)
        panel._orden_transporte = None
        panel._transporte_pendiente = False
        panel._estado_busqueda = reproductor.EstadoBusqueda(confirmada=0)
        panel._estado_busqueda.solicitar(50000, _t.monotonic())
        panel._player.get_length.return_value = 100000
        panel._player.get_time.return_value = 0
        panel._player.get_state.return_value = SimpleNamespace(name="paused")
        panel._timer = mock.Mock()
        with mock.patch.object(reproductor, "anunciar"):
            with mock.patch.object(reproductor.wx.Window, "FindFocus", return_value=None):
                panel._on_timer(None)
        self.assertTrue(panel._estado_busqueda.pendiente)
        panel._timer.Stop.assert_not_called()

class TestEstadoBusquedaFronteras(unittest.TestCase):

    def test_muestra_igual_no_confirma(self):
        bus = EstadoBusqueda(confirmada=10_000)
        ahora = time.monotonic()
        bus.solicitar(60_000, ahora)
        ev, _ = bus.observar(60_000, 300_000, "playing", ahora + 0.5)
        self.assertEqual(ev, "candidato")
        self.assertEqual(bus.confirmada, 10_000)
        ev, _ = bus.observar(60_000, 300_000, "playing", ahora + 1.0)
        self.assertIsNone(ev)
        self.assertEqual(bus.confirmada, 10_000)
        self.assertIsNotNone(bus.destino)

    def test_dos_muestras_con_250_confirman(self):
        bus = EstadoBusqueda(confirmada=5_000)
        ahora = time.monotonic()
        bus.solicitar(60_000, ahora)
        ev, _ = bus.observar(60_000, 300_000, "playing", ahora + 0.2)
        self.assertEqual(ev, "candidato")
        ev, valor = bus.observar(60_300, 300_000, "playing", ahora + 0.7)
        self.assertEqual(ev, "confirmado")
        self.assertEqual(valor, 60_300)
        self.assertEqual(bus.confirmada, 60_300)
        self.assertIsNone(bus.destino)
        self.assertIsNone(bus.candidato)

    def test_volver_a_cero_lejos_falla(self):
        bus = EstadoBusqueda(confirmada=75_082)
        ahora = time.monotonic()
        bus.solicitar(85_082, ahora)
        ev, valor = bus.observar(0, 300_000, "playing", ahora + 0.5)
        self.assertIsNone(ev)
        self.assertEqual(bus.confirmada, 75_082)
        self.assertEqual(bus.destino, 85_082)
        self.assertIsNone(bus.candidato)
        self.assertEqual(bus._ultima_valida, 0)
        ev, valor = bus.observar(0, 300_000, "playing", ahora + 8.5)
        self.assertEqual(ev, "vencido")
        self.assertEqual(valor, 0)
        self.assertEqual(bus.confirmada, 0)

    def test_destino_cero_confirma_normal(self):
        bus = EstadoBusqueda(confirmada=10_000)
        ahora = time.monotonic()
        bus.solicitar(0, ahora)
        ev, _ = bus.observar(0, 300_000, "playing", ahora + 0.2)
        self.assertEqual(ev, "candidato")
        ev, valor = bus.observar(300, 300_000, "playing", ahora + 0.6)
        self.assertEqual(ev, "confirmado")
        self.assertEqual(valor, 300)
        self.assertEqual(bus.confirmada, 300)

    def test_final_cercano_confirma_sin_250(self):
        dur = 300_000
        dest = 299_000  # a 1000 del final
        bus = EstadoBusqueda(confirmada=10_000)
        ahora = time.monotonic()
        bus.solicitar(dest, ahora)
        ev, valor = bus.observar(299_500, dur, "playing", ahora + 0.5)
        self.assertEqual(ev, "confirmado")
        self.assertEqual(valor, 299_500)
        self.assertIsNone(bus.destino)

    def test_pausa_no_confirma(self):
        bus = EstadoBusqueda(confirmada=5_000)
        ahora = time.monotonic()
        bus.solicitar(20_000, ahora)
        ev, _ = bus.observar(20_000, 100_000, "paused", ahora + 0.5)
        self.assertIsNone(ev)
        self.assertEqual(bus.destino, 20_000)
        self.assertIsNone(bus.candidato)

    def test_lectura_negativa_no_altera(self):
        bus = EstadoBusqueda(confirmada=5_000)
        ahora = time.monotonic()
        bus.solicitar(20_000, ahora)
        ev, _ = bus.observar(-1, 100_000, "playing", ahora + 0.5)
        self.assertIsNone(ev)
        self.assertEqual(bus.confirmada, 5_000)
        self.assertEqual(bus.destino, 20_000)

    def test_estado_final_incompatible_falla(self):
        for estado in ("ended", "stopped", "error", "nothingspecial"):
            with self.subTest(estado=estado):
                bus = EstadoBusqueda(confirmada=10_000)
                ahora = time.monotonic()
                bus.solicitar(20_000, ahora)
                ev, valor = bus.observar(20_000, 100_000, estado, ahora + 0.5)
                self.assertEqual(ev, "fallo")
                self.assertEqual(bus.confirmada, 20_000)

    def test_vencimiento_antes_y_despues_de_8000(self):
        bus = EstadoBusqueda(confirmada=0)
        ahora = time.monotonic()
        bus.solicitar(50_000, ahora)
        ev, _ = bus.observar(10_000, 100_000, "playing", ahora + 7.999)
        # a 7999 ms aún pendiente, lectura lejana ya falla antes del tope, pero probamos con lectura cercana sin progreso
        # usar lectura cercana para no fallar por lejanía
        bus2 = EstadoBusqueda(confirmada=0)
        bus2.solicitar(50_000, ahora)
        bus2.candidato = 50_000
        ev, _ = bus2.observar(50_000, 100_000, "playing", ahora + 7.999)
        self.assertIsNone(ev)
        ev, valor = bus2.observar(50_000, 100_000, "playing", ahora + 8.001)
        self.assertEqual(ev, "vencido")
        self.assertEqual(valor, 50_000)

    def test_pulsaciones_rapidas_acumulan_sin_cambiar_confirmada(self):
        bus = EstadoBusqueda(confirmada=10_000)
        ahora = time.monotonic()
        bus.solicitar(20_000, ahora)
        self.assertEqual(bus.confirmada, 10_000)
        # nueva pulsación acumula sobre destino, reinicia candidato
        bus.solicitar(30_000, ahora + 0.1)
        self.assertEqual(bus.destino, 30_000)
        self.assertIsNone(bus.candidato)
        self.assertEqual(bus.confirmada, 10_000)

    def test_cancelar_limpia_destino_y_candidato(self):
        bus = EstadoBusqueda(confirmada=5_000)
        ahora = time.monotonic()
        bus.solicitar(20_000, ahora)
        bus.candidato = 20_000
        bus.cancelar()
        self.assertIsNone(bus.destino)
        self.assertIsNone(bus.candidato)
        self.assertEqual(bus.confirmada, 5_000)

    def test_generacion_no_revive(self):
        bus = EstadoBusqueda(confirmada=0)
        ahora = time.monotonic()
        bus.solicitar(10_000, ahora)
        gen = bus.generacion
        bus.cancelar()
        # observar tardío con destino viejo no debe revivir
        ev, _ = bus.observar(10_000, 100_000, "playing", ahora + 0.5)
        self.assertIsNone(ev)
        self.assertIsNone(bus.destino)
        self.assertGreater(bus.generacion, gen)

    def test_posicion_a_mostrar_mientras_pendiente(self):
        bus = EstadoBusqueda(confirmada=5_000)
        ahora = time.monotonic()
        bus.solicitar(20_000, ahora)
        self.assertEqual(bus.posicion_a_mostrar(20_000), 5_000)
        self.assertEqual(bus.posicion_a_mostrar(9999), 5_000)
        bus.candidato = 20_000
        self.assertEqual(bus.posicion_a_mostrar(20_100), 5_000)
        bus.confirmada = 20_300
        bus.destino = None
        bus.candidato = None
        self.assertEqual(bus.posicion_a_mostrar(20_300), 20_300)

    def test_fallo_adopta_lectura_aunque_menor(self):
        bus = EstadoBusqueda(confirmada=30_000)
        ahora = time.monotonic()
        bus.solicitar(60_000, ahora)
        ev, _ = bus.observar(0, 300_000, "playing", ahora + 0.5)
        self.assertIsNone(ev)
        self.assertEqual(bus.confirmada, 30_000)
        self.assertEqual(bus._ultima_valida, 0)
        ev, _ = bus.observar(0, 300_000, "playing", ahora + 8.5)
        self.assertEqual(ev, "vencido")
        self.assertEqual(bus.confirmada, 0)

    def test_fallo_sin_lectura_valida_conserva_confirmada(self):
        bus = EstadoBusqueda(confirmada=30_000)
        ahora = time.monotonic()
        bus.solicitar(60_000, ahora)
        ev, _ = bus.observar(-1, 300_000, "playing", ahora + 8.5)
        self.assertEqual(ev, "vencido")
        self.assertIsNone(_)
        self.assertEqual(bus.confirmada, 30_000)


class TestEstadoBusquedaMuestrasLejanas(unittest.TestCase):

    def test_muestra_a_05_queda_pendiente_conserva_confirmada(self):
        bus = EstadoBusqueda(confirmada=10_000)
        bus.solicitar(60_000, ahora=0.0)
        ev, val = bus.observar(10_000, 120_000, "playing", ahora=0.5)
        self.assertIsNone(ev)
        self.assertEqual(bus.confirmada, 10_000)
        self.assertTrue(bus.pendiente)
        self.assertEqual(bus.destino, 60_000)

    def test_cero_lejos_pendiente_y_vencimiento_adopta(self):
        bus = EstadoBusqueda(confirmada=10_000)
        ahora = 0.0
        bus.solicitar(60_000, ahora)
        ev, _ = bus.observar(0, 120_000, "playing", ahora + 0.5)
        self.assertIsNone(ev)
        self.assertEqual(bus.confirmada, 10_000)
        ev, val = bus.observar(0, 120_000, "playing", ahora + 8.5)
        self.assertEqual(ev, "vencido")
        self.assertEqual(val, 0)
        self.assertEqual(bus.confirmada, 0)
        self.assertFalse(bus.pendiente)
        ev2, _ = bus.observar(0, 120_000, "playing", ahora + 9)
        self.assertIsNone(ev2)

    def test_lejana_luego_dos_cercanas_confirma(self):
        bus = EstadoBusqueda(confirmada=5_000)
        ahora = 0.0
        bus.solicitar(60_000, ahora)
        ev, _ = bus.observar(10_000, 120_000, "playing", ahora + 0.2)
        self.assertIsNone(ev)
        self.assertIsNone(bus.candidato)
        ev, _ = bus.observar(60_000, 120_000, "playing", ahora + 0.4)
        self.assertEqual(ev, "candidato")
        ev, val = bus.observar(60_300, 120_000, "playing", ahora + 0.7)
        self.assertEqual(ev, "confirmado")
        self.assertEqual(val, 60_300)

    def test_cercana_luego_lejana_descarta_candidato(self):
        bus = EstadoBusqueda(confirmada=5_000)
        ahora = 0.0
        bus.solicitar(60_000, ahora)
        ev, _ = bus.observar(60_000, 120_000, "playing", ahora + 0.2)
        self.assertEqual(ev, "candidato")
        ev, _ = bus.observar(10_000, 120_000, "playing", ahora + 0.4)
        self.assertIsNone(ev)
        self.assertIsNone(bus.candidato)
        self.assertEqual(bus._ultima_valida, 10_000)
        self.assertTrue(bus.pendiente)
        ev, _ = bus.observar(60_100, 120_000, "playing", ahora + 0.6)
        self.assertEqual(ev, "candidato")
        ev, val = bus.observar(60_400, 120_000, "playing", ahora + 0.9)
        self.assertEqual(ev, "confirmado")
        self.assertEqual(val, 60_400)

    def test_misma_muestra_repetida_no_confirma(self):
        bus = EstadoBusqueda(confirmada=0)
        ahora = 0.0
        bus.solicitar(60_000, ahora)
        ev, _ = bus.observar(60_000, 120_000, "playing", ahora + 0.2)
        self.assertEqual(ev, "candidato")
        ev, _ = bus.observar(60_000, 120_000, "playing", ahora + 0.4)
        self.assertIsNone(ev)
        self.assertTrue(bus.pendiente)

    def test_pausa_y_negativa_no_alteran(self):
        bus = EstadoBusqueda(confirmada=10_000)
        ahora = 0.0
        bus.solicitar(20_000, ahora)
        ev, _ = bus.observar(20_000, 100_000, "paused", ahora + 0.5)
        self.assertIsNone(ev)
        self.assertEqual(bus.destino, 20_000)
        ev, _ = bus.observar(-1, 100_000, "playing", ahora + 0.6)
        self.assertIsNone(ev)
        self.assertEqual(bus.destino, 20_000)
        self.assertEqual(bus.confirmada, 10_000)

    def test_estado_final_falla_inmediato(self):
        for est in ("ended", "stopped", "error", "nothingspecial"):
            bus = EstadoBusqueda(confirmada=10_000)
            bus.solicitar(20_000, 0.0)
            ev, val = bus.observar(20_000, 100_000, est, 0.5)
            self.assertEqual(ev, "fallo")
            self.assertEqual(bus.confirmada, 20_000)
            self.assertFalse(bus.pendiente)

    def test_destino_cero_y_final_video(self):
        bus = EstadoBusqueda(confirmada=10_000)
        bus.solicitar(0, 0.0)
        ev, _ = bus.observar(0, 120_000, "playing", 0.2)
        self.assertEqual(ev, "candidato")
        ev, val = bus.observar(300, 120_000, "playing", 0.6)
        self.assertEqual(ev, "confirmado")
        # cerca del final sin 250
        bus2 = EstadoBusqueda(confirmada=0)
        bus2.solicitar(119_000, 0.0)
        ev, val = bus2.observar(119_500, 120_000, "playing", 0.5)
        self.assertEqual(ev, "confirmado")

    def test_pulsaciones_acumulan_sin_alterar_confirmada(self):
        bus = EstadoBusqueda(confirmada=10_000)
        bus.solicitar(20_000, 0.0)
        self.assertEqual(bus.confirmada, 10_000)
        bus.solicitar(30_000, 0.1)
        self.assertEqual(bus.destino, 30_000)
        self.assertEqual(bus.confirmada, 10_000)
        self.assertIsNone(bus.candidato)

    def test_generacion_no_revive_y_doble_anuncio(self):
        import reproductor
        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._listo = True
        panel._video_id = "a"
        panel._url_flujo = ""
        panel._tiene_esclavo = False
        panel._usando_cache_local = False
        panel._estado_busqueda = EstadoBusqueda(confirmada=0)
        panel._player = mock.Mock()
        panel._player.get_length.return_value = 100_000
        panel._player.get_time.return_value = 60_000
        panel._player.get_state.return_value = mock.Mock(name="playing")
        panel._player.get_state.return_value.name = "playing"
        panel.sld_pos = mock.Mock()
        panel.lbl_tiempo = mock.Mock()
        panel._fijar_tiempo = mock.Mock()
        panel._topologia_actual = lambda: "unica"
        panel._estado_vlc_actual = lambda: "playing"
        bus = panel._estado_busqueda
        bus.solicitar(60_000, time.monotonic())
        gen = bus.generacion
        bus.candidato = 60_000
        panel._player.get_time.return_value = 60_300
        with mock.patch.object(reproductor, "anunciar") as anunciar:
            with mock.patch.object(reproductor.wx.Window, "FindFocus", return_value=None):
                panel._evaluar_busqueda()
                self.assertEqual(anunciar.call_count, 1)
                anunciar.reset_mock()
                panel._evaluar_busqueda()
                anunciar.assert_not_called()
                self.assertGreater(bus.generacion, gen)
                self.assertFalse(bus.pendiente)
        # prueba real del callback tardío vía CallLater
        panel2 = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel2._listo = True
        panel2._video_id = "a"
        panel2._url_flujo = ""
        panel2._tiene_esclavo = False
        panel2._usando_cache_local = False
        panel2._estado_busqueda = EstadoBusqueda(confirmada=0)
        panel2._player = mock.Mock()
        panel2._player.get_length.return_value = 100_000
        panel2._player.get_time.return_value = 10_000
        panel2._player.get_state.return_value = mock.Mock(name="playing")
        panel2._player.get_state.return_value.name = "playing"
        panel2.sld_pos = mock.Mock()
        panel2.lbl_tiempo = mock.Mock()
        panel2._fijar_tiempo = mock.Mock()
        panel2._topologia_actual = lambda: "unica"
        panel2._estado_vlc_actual = lambda: "playing"
        callbacks = []

        def fake_call_later(ms, func):
            callbacks.append(func)
            return mock.Mock()

        app_mock = mock.Mock()
        with mock.patch.object(reproductor.wx, "GetApp", return_value=app_mock), \
                mock.patch.object(reproductor.wx, "CallLater", side_effect=fake_call_later), \
                mock.patch.object(reproductor, "anunciar") as anunciar:
            panel2._marcar_destino(60_000, anunciar_usuario=True)
            self.assertEqual(len(callbacks), 1)
            cb_viejo = callbacks[0]
            gen1 = panel2._estado_busqueda.generacion
            self.assertEqual(panel2._estado_busqueda.destino, 60_000)
            anunciar.reset_mock()
            panel2._marcar_destino(70_000, anunciar_usuario=True)
            self.assertEqual(len(callbacks), 2)
            gen2 = panel2._estado_busqueda.generacion
            self.assertGreater(gen2, gen1)
            self.assertEqual(panel2._estado_busqueda.destino, 70_000)
            anunciar.reset_mock()
            with mock.patch.object(panel2, "_evaluar_busqueda") as evaluar:
                cb_viejo()
                evaluar.assert_not_called()
            anunciar.assert_not_called()
            self.assertEqual(panel2._estado_busqueda.destino, 70_000)
            self.assertEqual(panel2._estado_busqueda.generacion, gen2)
            # confirmar el segundo destino por camino normal
            panel2._estado_busqueda.candidato = 70_000
            panel2._player.get_time.return_value = 70_300
            with mock.patch.object(reproductor.wx.Window, "FindFocus", return_value=None):
                panel2._evaluar_busqueda()
            self.assertEqual(anunciar.call_count, 1)
            self.assertIn("Posición", anunciar.call_args[0][0])
            self.assertFalse(panel2._estado_busqueda.pendiente)
            anunciar.reset_mock()
            with mock.patch.object(reproductor.wx.Window, "FindFocus", return_value=None):
                panel2._evaluar_busqueda()
            anunciar.assert_not_called()
            cb_viejo()
            anunciar.assert_not_called()
            callbacks[1]()
            anunciar.assert_not_called()
            self.assertFalse(panel2._estado_busqueda.pendiente)

    def test_trazas_topologia_sin_url(self):
        from traza_transporte import traza_busqueda_orden, traza_busqueda_desenlace
        linea = traza_busqueda_orden("dividida", "playing", 0, 60000, 0, 100)
        self.assertIn("topologia=dividida", linea)
        self.assertNotIn("http", linea.lower())
        linea2 = traza_busqueda_desenlace("local", "playing", 0, 1000, 0, 10, "confirmado")
        self.assertIn("topologia=local", linea2)
        self.assertNotIn("googlevideo", linea2.lower())


class TestEstadoBusquedaConstantes(unittest.TestCase):

    def test_constantes_puras(self):
        self.assertEqual(TOPE_BUSQUEDA_MS, 8000)
        self.assertEqual(PROGRESO_MINIMO_MS, 250)


class TestBusquedaPermitida(unittest.TestCase):

    def test_vod_remoto_dividido_no_permitida(self):
        from busqueda_video import busqueda_permitida
        self.assertFalse(busqueda_permitida(False, False, True))

    def test_vod_local_dividido_si_permitida(self):
        from busqueda_video import busqueda_permitida
        self.assertTrue(busqueda_permitida(False, True, True))

    def test_vod_remoto_unica_si_permitida(self):
        from busqueda_video import busqueda_permitida
        self.assertTrue(busqueda_permitida(False, False, False))

    def test_vod_local_unica_si_permitida(self):
        from busqueda_video import busqueda_permitida
        self.assertTrue(busqueda_permitida(False, True, False))

    def test_directo_remoto_dividido_si_permitida(self):
        from busqueda_video import busqueda_permitida
        self.assertTrue(busqueda_permitida(True, False, True))

    def test_directo_local_si_permitida(self):
        from busqueda_video import busqueda_permitida
        self.assertTrue(busqueda_permitida(True, True, True))
        self.assertTrue(busqueda_permitida(True, True, False))

    def test_directo_remoto_unica_si_permitida(self):
        from busqueda_video import busqueda_permitida
        self.assertTrue(busqueda_permitida(True, False, False))

    def test_directo_por_relevo_no_permitida(self):
        # El relevo de ffmpeg deja el directo como un único flujo sin
        # ventana de retroceso para VLC (is_seekable=0, comprobado con un
        # directo real): buscar no hace nada, así que mejor avisar antes.
        from busqueda_video import busqueda_permitida
        self.assertFalse(busqueda_permitida(True, False, False, usa_relevo=True))
        self.assertFalse(busqueda_permitida(True, True, True, usa_relevo=True))


class TestEstadoBusquedaDirectoBorde(unittest.TestCase):

    def test_vod_finito_confirma_sin_progreso(self):
        bus = EstadoBusqueda(confirmada=10_000)
        ahora = time.monotonic()
        bus.solicitar(299_000, ahora)
        ev, valor = bus.observar(299_500, 300_000, "playing", ahora + 0.5, es_directo=False)
        self.assertEqual(ev, "confirmado")
        self.assertEqual(valor, 299_500)

    def test_directo_borde_no_confirma_con_una_muestra_inmovil(self):
        bus = EstadoBusqueda(confirmada=10_000)
        ahora = time.monotonic()
        bus.solicitar(845_000, ahora)
        ev, _ = bus.observar(845_000, 845_000, "playing", ahora + 0.5, es_directo=True)
        self.assertEqual(ev, "candidato")
        self.assertEqual(bus.confirmada, 10_000)
        ev2, _ = bus.observar(845_000, 845_000, "playing", ahora + 0.6, es_directo=True)
        self.assertIsNone(ev2)
        self.assertTrue(bus.pendiente)

    def test_directo_borde_confirma_tras_progreso_suficiente(self):
        bus = EstadoBusqueda(confirmada=5_000)
        ahora = time.monotonic()
        bus.solicitar(845_000, ahora)
        ev, _ = bus.observar(845_000, 845_000, "playing", ahora + 0.2, es_directo=True)
        self.assertEqual(ev, "candidato")
        ev, valor = bus.observar(845_300, 845_000, "playing", ahora + 0.7, es_directo=True)
        self.assertEqual(ev, "confirmado")
        self.assertEqual(valor, 845_300)

    def test_directo_borde_vence_sin_progreso(self):
        bus = EstadoBusqueda(confirmada=0)
        ahora = 0.0
        bus.solicitar(845_000, ahora)
        ev, _ = bus.observar(845_000, 845_000, "playing", ahora + 0.3, es_directo=True)
        self.assertEqual(ev, "candidato")
        ev, valor = bus.observar(845_000, 845_000, "playing", ahora + 8.5, es_directo=True)
        self.assertEqual(ev, "vencido")
        self.assertEqual(bus.confirmada, 845_000)


class TestEstadoInicioReproduccion(unittest.TestCase):

    def test_playing_inmovil_no_anuncia(self):
        from busqueda_video import EstadoInicioReproduccion
        est = EstadoInicioReproduccion()
        est.iniciar()
        self.assertFalse(est.observar("playing", 1000))
        self.assertFalse(est.observar("playing", 1000))
        self.assertFalse(est.anunciado)
        self.assertTrue(est.requiere)

    def test_dos_muestras_con_avance_anuncian_una_vez(self):
        from busqueda_video import EstadoInicioReproduccion
        est = EstadoInicioReproduccion()
        est.iniciar()
        self.assertFalse(est.observar("playing", 2000))
        self.assertTrue(est.observar("playing", 2300))
        self.assertTrue(est.anunciado)
        self.assertFalse(est.requiere)
        self.assertFalse(est.observar("playing", 2600))

    def test_no_playing_no_cuenta(self):
        from busqueda_video import EstadoInicioReproduccion
        est = EstadoInicioReproduccion()
        est.iniciar()
        self.assertFalse(est.observar("paused", 1000))
        self.assertFalse(est.observar("buffering", 1000))
        self.assertFalse(est.observar("playing", 1000))
        self.assertFalse(est.observar("playing", 1100))
        self.assertTrue(est.observar("playing", 1300))

    def test_cancelar_no_anuncia(self):
        from busqueda_video import EstadoInicioReproduccion
        est = EstadoInicioReproduccion()
        est.iniciar()
        est.cancelar()
        self.assertFalse(est.observar("playing", 1000))
        self.assertFalse(est.observar("playing", 1300))


if __name__ == "__main__":
    unittest.main()
