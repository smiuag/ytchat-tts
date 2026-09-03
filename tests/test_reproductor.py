"""Pruebas de los avisos de los controles del reproductor."""

import unittest
from unittest import mock
import types
import sys

import reproductor


class RelojMonotonic:
    def __init__(self, primero, despues):
        self._llamadas = 0
        self._primero = primero
        self._despues = despues

    def __call__(self):
        self._llamadas += 1
        return self._primero if self._llamadas == 1 else self._despues


FORMATOS_SEPARADOS = [
    {"format_id": "233", "height": None, "vcodec": "none",
     "acodec": None, "abr": None, "tbr": None, "url": "audio-233"},
    {"format_id": "234", "height": None, "vcodec": "none",
     "acodec": None, "abr": None, "tbr": None, "url": "audio-234"},
    {"format_id": "269", "height": 144, "vcodec": "avc1.42C00B",
     "acodec": "none", "abr": 0, "tbr": 269.034, "url": "video-144"},
    {"format_id": "229", "height": 240, "vcodec": "avc1.4D4015",
     "acodec": "none", "abr": 0, "tbr": 507.418, "url": "video-240"},
    {"format_id": "230", "height": 360, "vcodec": "avc1.4D401E",
     "acodec": "none", "abr": 0, "tbr": 1000.0, "url": "video-360"},
    {"format_id": "231", "height": 480, "vcodec": "avc1.4D401F",
     "acodec": "none", "abr": 0, "tbr": 1500.0, "url": "video-480"},
    {"format_id": "232", "height": 720, "vcodec": "avc1.4D401F",
     "acodec": "none", "abr": 0, "tbr": 2500.0, "url": "video-720"},
    {"format_id": "270", "height": 1080, "vcodec": "avc1.640028",
     "acodec": "none", "abr": 0, "tbr": 4500.0, "url": "video-1080"},
]


class TestSeleccionFormatos(unittest.TestCase):

    def test_elige_audio_con_acodec_nulo(self):
        self.assertIn(
            reproductor._mejor_audio({"formats": FORMATOS_SEPARADOS}),
            ("audio-233", "audio-234"),
        )

    def test_elige_video_1080_sin_progresivo(self):
        self.assertEqual(
            reproductor._video_para_altura(
                {"formats": FORMATOS_SEPARADOS}, 10000),
            ("video-1080", False),
        )

    def test_elige_video_480_sin_progresivo(self):
        self.assertEqual(
            reproductor._video_para_altura(
                {"formats": FORMATOS_SEPARADOS}, 480),
            ("video-480", False),
        )

    def test_a_igual_altura_gana_mayor_tbr(self):
        formatos = [
            {"vcodec": "avc1", "acodec": "none", "height": 720,
             "tbr": 2000, "url": "video-720-lento"},
            {"vcodec": "avc1", "acodec": "none", "height": 720,
             "tbr": 3000, "url": "video-720-rapido"},
        ]
        self.assertEqual(
            reproductor._video_para_altura({"formats": formatos}, 1000),
            ("video-720-rapido", False),
        )

    def test_sin_progresivo_elige_la_menor_altura_no_superior(self):
        formatos = [
            {"vcodec": "avc1", "acodec": "none", "height": 720,
             "url": "video-720"},
            {"vcodec": "avc1", "acodec": "none", "height": 1080,
             "url": "video-1080"},
        ]
        self.assertEqual(
            reproductor._video_para_altura({"formats": formatos}, 480),
            ("video-720", False),
        )

    def test_sin_progresivo_elige_la_menor_altura_disponible(self):
        formatos = [
            {"vcodec": "avc1", "acodec": "none", "height": 720,
             "url": "video-720"},
            {"vcodec": "avc1", "acodec": "none", "height": 1080,
             "url": "video-1080"},
        ]
        self.assertEqual(
            reproductor._video_para_altura({"formats": formatos}, 144),
            ("video-720", False),
        )

    def test_descarta_guion_grafico_como_audio(self):
        formato = {"vcodec": "none", "acodec": "none", "url": "grafico"}
        self.assertEqual(reproductor._mejor_audio({"formats": [formato]}), "")

    def test_conserva_la_seleccion_progresiva(self):
        formatos = [
            {"vcodec": "avc1", "acodec": "mp4a", "height": 360,
             "url": "progresivo-360"},
            {"vcodec": "avc1", "acodec": "mp4a", "height": 720,
             "url": "progresivo-720"},
        ]
        self.assertEqual(
            reproductor._video_para_altura({"formats": formatos}, 720),
            ("progresivo-720", True),
        )

    def test_prefiere_idioma_alto_antes_que_bitrate(self):
        formatos = [
            {"vcodec": "none", "acodec": None, "abr": 320,
             "language_preference": 1, "url": "doblaje"},
            {"vcodec": "none", "acodec": None, "abr": 128,
             "language_preference": 10, "url": "original"},
        ]
        self.assertEqual(
            reproductor._mejor_audio({"formats": formatos}), "original")


class TestPreferirHls(unittest.TestCase):

    def test_hay_hls_se_queda_solo_con_esas(self):
        formatos = [
            {"protocol": "https", "url": "dash-crudo"},
            {"protocol": "m3u8_native", "url": "hls"},
        ]
        self.assertEqual(reproductor._preferir_hls(formatos),
                         [{"protocol": "m3u8_native", "url": "hls"}])

    def test_sin_hls_deja_la_lista_igual(self):
        formatos = [{"protocol": "https", "url": "dash-crudo"}]
        self.assertEqual(reproductor._preferir_hls(formatos), formatos)

    def test_lista_vacia(self):
        self.assertEqual(reproductor._preferir_hls([]), [])

    def test_protocolo_ausente_no_rompe(self):
        formatos = [{"url": "sin-protocolo"}]
        self.assertEqual(reproductor._preferir_hls(formatos), formatos)


class TestFuentesParaDirecto(unittest.TestCase):

    def test_directo_mezcla_hls_y_dash_crudo_gana_hls(self):
        # Lo que se vio con un directo real: la misma extracción trae
        # variantes m3u8 (HLS, la que entienden VLC/ffmpeg) y variantes
        # «https»/DASH-en-crudo (protocolo de secuencias propio de YouTube,
        # que ffmpeg no sabe abrir directo: "Invalid data found").
        info = {"formats": [
            {"vcodec": "avc1", "acodec": "none", "height": 1080,
             "protocol": "https", "url": "video-dash-crudo"},
            {"vcodec": "none", "acodec": "mp4a", "protocol": "https",
             "url": "audio-dash-crudo"},
            {"vcodec": "avc1", "acodec": "none", "height": 1080,
             "protocol": "m3u8_native", "url": "video-hls"},
            {"vcodec": "none", "acodec": "mp4a", "protocol": "m3u8_native",
             "url": "audio-hls"},
        ]}
        self.assertEqual(
            reproductor.fuentes_para_directo(info),
            ("video-hls", "audio-hls"))

    def test_url_superior_gana_sobre_las_demás_fuentes(self):
        info = {
            "url": "superior",
            "formats": FORMATOS_SEPARADOS,
            "requested_formats": [
                {"vcodec": "avc1", "acodec": "none", "url": "video"},
                {"vcodec": "none", "acodec": "mp4a", "url": "audio"},
            ],
        }
        self.assertEqual(reproductor.fuentes_para_directo(info), ("superior", ""))

    def test_usa_formato_progresivo(self):
        info = {"formats": [
            {"vcodec": "avc1", "acodec": "mp4a", "height": 720,
             "url": "progresivo"},
        ]}
        self.assertEqual(reproductor.fuentes_para_directo(info), ("progresivo", ""))

    def test_usa_video_y_audio_de_formats(self):
        self.assertEqual(
            reproductor.fuentes_para_directo({"formats": FORMATOS_SEPARADOS}),
            ("video-1080", "audio-233"),
        )

    def test_usa_el_par_solicitado_si_formats_no_sirve(self):
        info = {"formats": [], "requested_formats": [
            {"vcodec": "avc1", "acodec": "none", "url": "video-solicitado"},
            {"vcodec": "none", "acodec": "mp4a", "url": "audio-solicitado"},
        ]}
        self.assertEqual(
            reproductor.fuentes_para_directo(info),
            ("video-solicitado", "audio-solicitado"),
        )

    def test_sin_fuentes_devuelve_vacio(self):
        self.assertEqual(reproductor.fuentes_para_directo({}), ("", ""))


class TestReproducirDirecto(unittest.TestCase):

    def _panel(self, info):
        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._info = info
        panel._inst = mock.Mock()
        player = mock.Mock()
        panel._player = player
        panel._vol = 75
        panel._muted = False
        panel._timer = mock.Mock()
        panel.lbl_estado = mock.Mock()
        panel._video_id = "vid"
        panel._gen = 0
        panel._relevo_gen = 0
        panel._relevo_ffmpeg = None
        panel._asegurar_player = mock.Mock(return_value=True)
        panel._error_carga = mock.Mock()
        panel._mostrar_pausa = mock.Mock()
        return panel

    def _hilo_sincrono(self):
        """Reemplaza diagnostico.crear_hilo por algo que corre en el
        momento, y wx.CallAfter por una llamada directa: así el relevo (que
        en producción va a un hilo aparte para no bloquear la GUI) se puede
        probar sin hilos reales."""
        hilo = mock.Mock()

        def crear(target, _nombre):
            hilo.target = target
            return hilo

        hilo.start.side_effect = lambda: hilo.target()
        return (
            mock.patch.object(reproductor.diagnostico, "crear_hilo", side_effect=crear),
            mock.patch.object(reproductor.wx, "CallAfter", side_effect=lambda fn, *a: fn(*a)),
        )

    def test_directo_con_pares_separados_usa_el_relevo_de_ffmpeg(self):
        panel = self._panel({"is_live": True, "formats": [], "requested_formats": [
            {"vcodec": "avc1", "acodec": "none", "url": "video-solicitado"},
            {"vcodec": "none", "acodec": "mp4a", "url": "audio-solicitado"},
        ]})
        medio = mock.Mock()
        panel._inst.media_new.return_value = medio
        relevo = mock.Mock()
        relevo.iniciar.return_value = "tcp://127.0.0.1:5555"

        parche_hilo, parche_callafter = self._hilo_sincrono()
        with parche_hilo, parche_callafter, \
                mock.patch.object(reproductor.relevo_ffmpeg, "RelevoFfmpeg",
                                  return_value=relevo) as clase_relevo, \
                mock.patch.object(reproductor.time, "sleep"):
            panel._reproducir_calidad(None, reproducir=False)

        clase_relevo.assert_called_once_with("video-solicitado", "audio-solicitado")
        panel._inst.media_new.assert_called_once_with("tcp://127.0.0.1:5555")
        opciones = [c.args[0] for c in medio.add_option.call_args_list]
        self.assertFalse(any(o.startswith(":input-slave=") for o in opciones))
        self.assertIs(panel._relevo_ffmpeg, relevo)
        self.assertFalse(panel._tiene_esclavo)
        panel._error_carga.assert_not_called()

    def test_directo_si_el_relevo_no_arranca_cae_a_input_slave(self):
        panel = self._panel({"is_live": True, "formats": [], "requested_formats": [
            {"vcodec": "avc1", "acodec": "none", "url": "video-solicitado"},
            {"vcodec": "none", "acodec": "mp4a", "url": "audio-solicitado"},
        ]})
        medio = mock.Mock()
        panel._inst.media_new.return_value = medio
        relevo = mock.Mock()
        relevo.iniciar.return_value = None  # sin ffmpeg disponible, por ejemplo

        parche_hilo, parche_callafter = self._hilo_sincrono()
        with parche_hilo, parche_callafter, \
                mock.patch.object(reproductor.relevo_ffmpeg, "RelevoFfmpeg",
                                  return_value=relevo):
            panel._reproducir_calidad(None, reproducir=False)

        panel._inst.media_new.assert_called_once_with("video-solicitado")
        medio.add_option.assert_any_call(":input-slave=audio-solicitado")
        self.assertIsNone(panel._relevo_ffmpeg)
        panel._error_carga.assert_not_called()

    def test_directo_descarta_el_relevo_si_ya_no_es_el_ultimo_pedido(self):
        # El usuario cambió de vídeo (o desconectó) mientras el relevo
        # arrancaba: el resultado, si llega tarde, no debe usarse ni dejar
        # el proceso de ffmpeg huérfano.
        panel = self._panel({"is_live": True, "formats": [], "requested_formats": [
            {"vcodec": "avc1", "acodec": "none", "url": "video-solicitado"},
            {"vcodec": "none", "acodec": "mp4a", "url": "audio-solicitado"},
        ]})
        relevo = mock.Mock()
        relevo.iniciar.return_value = "tcp://127.0.0.1:5555"

        callbacks = []
        with mock.patch.object(reproductor.diagnostico, "crear_hilo",
                               side_effect=lambda target, _n: mock.Mock(
                                   start=lambda: target())), \
                mock.patch.object(reproductor.wx, "CallAfter",
                                  side_effect=lambda fn, *a: callbacks.append(
                                      lambda: fn(*a))), \
                mock.patch.object(reproductor.relevo_ffmpeg, "RelevoFfmpeg",
                                  return_value=relevo), \
                mock.patch.object(reproductor.time, "sleep"):
            panel._reproducir_calidad(None, reproducir=False)
            panel._video_id = "otro-vid"  # cambió de vídeo antes de que llegue
            callbacks[0]()

        relevo.detener.assert_called_once()
        self.assertIsNone(panel._relevo_ffmpeg)
        panel._inst.media_new.assert_not_called()

    def test_directo_sin_fuentes_deja_diagnostico(self):
        panel = self._panel({"is_live": True, "formats": [],
                             "requested_formats": []})
        with mock.patch.object(reproductor.logger, "warning") as warning:
            panel._reproducir_calidad(None, reproducir=False)

        warning.assert_called_once_with(
            "reproducir directo sin fuentes: url_superior=%s formats=%d "
            "requested_formats=%d is_live=%s", "no", 0, 0, True)
        panel._error_carga.assert_called_once_with()


class _YoutubeDL:
    def __init__(self, opciones):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, *args, **kwargs):
        return {"formats": [{"vcodec": "avc1", "height": 720}]}


class TestInfoVideo(unittest.TestCase):

    def test_info_video_con_programa_no_importa_el_modulo(self):
        info = {"formats": [{"vcodec": "avc1", "height": 1080}]}
        with mock.patch.object(reproductor.ytdlp_bin, "info_video", return_value=info), \
                mock.patch.dict(sys.modules, {"yt_dlp": None}):
            self.assertIs(info, reproductor._info_video("A" * 11))

    def test_info_video_sin_programa_usa_el_modulo(self):
        modulo = types.SimpleNamespace(YoutubeDL=_YoutubeDL)
        with mock.patch.object(reproductor.ytdlp_bin, "info_video", return_value=None), \
                mock.patch.dict(sys.modules, {"yt_dlp": modulo}):
            self.assertEqual(
                {"formats": [{"vcodec": "avc1", "height": 720}]},
                reproductor._info_video("A" * 11),
            )


class TestAvisoReproductor(unittest.TestCase):

    def test_sin_reproductor(self):
        self.assertEqual(
            reproductor.aviso_reproductor(False, False),
            "El reproductor no está disponible")

    def test_reproductor_sin_medio(self):
        self.assertEqual(
            reproductor.aviso_reproductor(True, False),
            "No hay ningún vídeo cargado")

    def test_reproductor_con_medio(self):
        self.assertEqual(reproductor.aviso_reproductor(True, True), "")


class TestOpcionesMedio(unittest.TestCase):

    def test_grabado_tiene_mas_colchon_de_red_que_directo(self):
        grabado = dict(opcion[1:].split("=", 1)
                       for opcion in reproductor.opciones_medio(False))
        directo = dict(opcion[1:].split("=", 1)
                       for opcion in reproductor.opciones_medio(True))
        self.assertGreater(int(grabado["network-caching"]),
                           int(directo["network-caching"]))

    def test_ambos_medios_declaran_las_dos_opciones_de_buffer(self):
        for es_directo in (False, True):
            opciones = reproductor.opciones_medio(es_directo)
            self.assertEqual(len(opciones), 2)
            self.assertTrue(any(opcion.startswith(":network-caching=")
                                for opcion in opciones))
            self.assertTrue(any(opcion.startswith(":live-caching=")
                                for opcion in opciones))


class TestAvisoDeCorte(unittest.TestCase):

    def test_avisa_al_caer_el_buffer_por_primera_vez(self):
        self.assertTrue(reproductor.aviso_de_corte(99, None))

    def test_avisa_al_recuperarse_el_buffer(self):
        self.assertTrue(reproductor.aviso_de_corte(100, 99))

    def test_no_avisa_cada_evento_durante_un_corte(self):
        self.assertEqual(reproductor.aviso_de_corte(80, 99), "")


class TestPrecalentamiento(unittest.TestCase):

    def _panel(self):
        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._precalentamiento_cancelado = False
        return panel

    def test_anuncia_antes_del_trabajo_y_al_terminar(self):
        panel = self._panel()
        orden = []
        hilo = mock.Mock()

        def crear(target, _nombre):
            hilo.target = target
            return hilo

        def iniciar():
            hilo.target()

        hilo.start.side_effect = iniciar
        panel._asegurar_instancia = lambda: orden.append("trabajo") or True
        with mock.patch.object(reproductor, "anunciar",
                               side_effect=lambda texto: orden.append(texto)), \
                mock.patch.object(reproductor.diagnostico, "crear_hilo",
                                  side_effect=crear), \
                mock.patch.object(reproductor.wx, "CallAfter",
                                  side_effect=lambda fn: fn()):
            panel._precalentar()

        self.assertEqual(orden, [
            "Preparando el reproductor", "trabajo", "Reproductor listo"])

    def test_si_falla_no_anuncia_que_esta_listo(self):
        panel = self._panel()
        hilo = mock.Mock()
        def crear(target, _nombre):
            hilo.target = target
            return hilo
        hilo.start.side_effect = lambda: hilo.target()
        panel._asegurar_instancia = mock.Mock(side_effect=RuntimeError("fallo"))
        with mock.patch.object(reproductor, "anunciar") as anunciar, \
                mock.patch.object(reproductor.diagnostico, "crear_hilo",
                                  side_effect=crear):
            panel._precalentar()

        anunciar.assert_called_once_with("Preparando el reproductor")

    def test_si_se_cierra_no_anuncia_que_esta_listo(self):
        panel = self._panel()
        callbacks = []
        hilo = mock.Mock()
        def crear(target, _nombre):
            hilo.target = target
            return hilo
        hilo.start.side_effect = lambda: hilo.target()
        panel._asegurar_instancia = mock.Mock(return_value=True)
        with mock.patch.object(reproductor, "anunciar") as anunciar, \
                mock.patch.object(reproductor.diagnostico, "crear_hilo",
                                  side_effect=crear), \
                mock.patch.object(reproductor.wx, "CallAfter",
                                  side_effect=lambda fn: callbacks.append(fn)):
            panel._precalentar()
            panel._precalentamiento_cancelado = True
            callbacks[0]()

        anunciar.assert_called_once_with("Preparando el reproductor")

    def test_el_constructor_no_precalienta(self):
        with mock.patch.object(reproductor.wx.Panel, "__init__", return_value=None), \
                mock.patch.object(reproductor.ReproductorPanel, "SetBackgroundColour"), \
                mock.patch.object(reproductor.ReproductorPanel, "SetForegroundColour"), \
                mock.patch.object(reproductor, "disponible", return_value=True), \
                mock.patch.object(reproductor.ReproductorPanel, "_build_ui"), \
                mock.patch.object(reproductor.ReproductorPanel, "_precalentar") as precalentar:
            reproductor.ReproductorPanel(None, {})

        precalentar.assert_not_called()

    def test_preparar_dll_registra_su_tramo(self):
        anterior = reproductor._VLC_PREPARADO
        try:
            reproductor._VLC_PREPARADO = False
            reloj = RelojMonotonic(1.0, 1.25)
            with mock.patch.object(reproductor, "_carpeta_vlc_empaquetada",
                                   return_value=None), \
                    mock.patch.object(reproductor.time, "monotonic",
                                      side_effect=reloj), \
                    mock.patch.object(reproductor.diagnostico.logger, "info") as registrar:
                reproductor._preparar_vlc()
            registrar.assert_any_call(
                "VLC_PRECALENTAMIENTO tramo=%s ms=%.0f", "preparar_dll", 250)
            self.assertEqual(sum(llamada.args[1] == "preparar_dll"
                                 for llamada in registrar.call_args_list), 1)
        finally:
            reproductor._VLC_PREPARADO = anterior

    def test_importar_modulo_registra_su_tramo(self):
        anterior = reproductor._vlc
        try:
            reproductor._vlc = None
            reloj = RelojMonotonic(2.0, 2.5)
            with mock.patch.object(reproductor, "_preparar_vlc"), \
                    mock.patch.object(reproductor.time, "monotonic",
                                      side_effect=reloj), \
                    mock.patch.object(reproductor.diagnostico.logger, "info") as registrar, \
                    mock.patch.dict(sys.modules, {"vlc": types.SimpleNamespace()}):
                self.assertTrue(reproductor._cargar_vlc())
            registrar.assert_any_call(
                "VLC_PRECALENTAMIENTO tramo=%s ms=%.0f", "importar_modulo", 500)
            self.assertEqual(sum(llamada.args[1] == "importar_modulo"
                                 for llamada in registrar.call_args_list), 1)
        finally:
            reproductor._vlc = anterior


class TestEventosVlc(unittest.TestCase):

    def _panel_para_detener(self, gestor=None):
        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._gen = 0
        panel._cargando = True
        panel._destino_pendiente = object()
        panel._intencion_reproducir = True
        panel._timer_progreso = mock.Mock()
        panel._player = mock.Mock()
        panel._gestor_eventos_vlc = gestor
        return panel

    def _panel_con_eventos(self):
        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._player = mock.Mock()
        panel._gestor_eventos_vlc = None
        return panel

    def test_engancha_eventos_solo_con_registro_detallado(self):
        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._player = None
        panel._inst = mock.Mock()
        panel._asegurar_instancia = mock.Mock(return_value=True)
        panel._video = mock.Mock()
        panel._fijar_salida = mock.Mock()
        panel._enganchar_eventos_vlc = mock.Mock()
        with mock.patch.object(reproductor, "_registro_detallado_activo",
                               return_value=False):
            self.assertTrue(panel._asegurar_player())
        panel._enganchar_eventos_vlc.assert_called_once()
        panel._enganchar_eventos_vlc.reset_mock()
        panel._player = None
        with mock.patch.object(reproductor, "_registro_detallado_activo",
                               return_value=True):
            self.assertTrue(panel._asegurar_player())
        panel._enganchar_eventos_vlc.assert_called_once()

    def test_enganchar_eventos_conserva_el_gestor(self):
        panel = self._panel_con_eventos()
        gestor = mock.Mock()
        panel._player.event_manager.return_value = gestor
        tipos = types.SimpleNamespace(**{
            nombre: object() for nombre in (
                "MediaPlayerPlaying", "MediaPlayerPaused", "MediaPlayerStopped",
                "MediaPlayerEndReached", "MediaPlayerEncounteredError",
                "MediaPlayerBuffering")})

        with mock.patch.object(reproductor, "_vlc", EventType=tipos):
            panel._enganchar_eventos_vlc()

        self.assertIs(panel._gestor_eventos_vlc, gestor)

    def test_enganchar_eventos_usa_el_mismo_gestor_para_los_seis_tipos(self):
        panel = self._panel_con_eventos()
        gestor = mock.Mock()
        panel._player.event_manager.return_value = gestor
        tipos = types.SimpleNamespace(**{
            nombre: object() for nombre in (
                "MediaPlayerPlaying", "MediaPlayerPaused", "MediaPlayerStopped",
                "MediaPlayerEndReached", "MediaPlayerEncounteredError",
                "MediaPlayerBuffering")})

        with mock.patch.object(reproductor, "_vlc", EventType=tipos), \
             mock.patch.object(reproductor, "_registro_detallado_activo", return_value=True):
            panel._enganchar_eventos_vlc()

        self.assertEqual(gestor.event_attach.call_count, 6)

    def test_detener_en_segundo_plano_conserva_el_gestor_hasta_liberar(self):
        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._gen = 0
        panel._cargando = True
        panel._destino_pendiente = object()
        panel._intencion_reproducir = True
        panel._timer_progreso = mock.Mock()
        player = mock.Mock()
        panel._player = player
        gestor = object()
        panel._gestor_eventos_vlc = gestor
        hilo = mock.Mock()
        hilo.start = mock.Mock()

        with mock.patch.object(reproductor.diagnostico, "crear_hilo",
                               return_value=hilo) as crear_hilo:
            panel._detener(silencioso=True, en_segundo_plano=True)

        cierre = crear_hilo.call_args.args[0]
        self.assertIsNone(panel._gestor_eventos_vlc)
        self.assertIn(gestor, cierre.__defaults__)
        player.release.side_effect = lambda: self.assertIn(gestor, cierre.__defaults__)
        cierre()
        player.release.assert_called_once_with()

    def test_detener_en_segundo_plano_suelta_la_ventana_de_video(self):
        panel = self._panel_para_detener()
        player = panel._player
        hilo = mock.Mock()
        with mock.patch.object(reproductor.diagnostico, "crear_hilo",
                               return_value=hilo):
            panel._detener(silencioso=True, en_segundo_plano=True)
        player.set_hwnd.assert_called_once_with(0)
        hilo.start.assert_called_once_with()

    def test_detener_suelta_la_ventana_antes_de_crear_el_hilo(self):
        panel = self._panel_para_detener()
        player = panel._player
        hilo = mock.Mock()

        def crear_hilo(_cerrar, _nombre):
            self.assertTrue(player.set_hwnd.called)
            return hilo

        with mock.patch.object(reproductor.diagnostico, "crear_hilo",
                               side_effect=crear_hilo):
            panel._detener(silencioso=True, en_segundo_plano=True)

        player.set_hwnd.assert_called_once_with(0)

    def test_detener_normal_no_suelta_la_ventana_de_video(self):
        panel = self._panel_para_detener()
        player = panel._player
        panel._detener(silencioso=True, en_segundo_plano=False)
        player.set_hwnd.assert_not_called()
        self.assertIs(panel._player, player)

    def test_detener_continua_si_no_puede_soltar_la_ventana(self):
        panel = self._panel_para_detener()
        panel._player.set_hwnd.side_effect = RuntimeError("sin salida")
        hilo = mock.Mock()
        with mock.patch.object(reproductor.diagnostico, "crear_hilo",
                               return_value=hilo) as crear_hilo:
            panel._detener(silencioso=True, en_segundo_plano=True)
        crear_hilo.assert_called_once()
        hilo.start.assert_called_once_with()

    def test_detener_en_segundo_plano_sin_gestor_de_eventos(self):
        panel = self._panel_para_detener(gestor=None)
        hilo = mock.Mock()
        with mock.patch.object(reproductor.diagnostico, "crear_hilo",
                               return_value=hilo):
            panel._detener(silencioso=True, en_segundo_plano=True)
        self.assertIsNone(panel._player)
        hilo.start.assert_called_once_with()

    def test_constructor_inicializa_el_gestor_de_eventos(self):
        """Evita AttributeError al cerrar por detrás sin registro detallado."""
        self.assertIn("_gestor_eventos_vlc",
                      reproductor.ReproductorPanel.__init__.__code__.co_names)

    def test_crear_instancia_registra_su_tramo(self):
        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._inst = None
        panel._listo = True
        panel._inst_lock = mock.Mock()
        panel._inst_lock.__enter__ = mock.Mock(return_value=panel._inst_lock)
        panel._inst_lock.__exit__ = mock.Mock(return_value=False)
        instancia = object()
        anterior = reproductor._vlc
        try:
            reproductor._vlc = types.SimpleNamespace(Instance=lambda *_: instancia)
            reloj = RelojMonotonic(3.0, 3.75)
            with mock.patch.object(reproductor, "_cargar_vlc", return_value=True), \
                    mock.patch.object(reproductor.time, "monotonic",
                                      side_effect=reloj), \
                    mock.patch.object(reproductor.diagnostico.logger, "info") as registrar:
                self.assertTrue(panel._asegurar_instancia())
            registrar.assert_any_call(
                "VLC_PRECALENTAMIENTO tramo=%s ms=%.0f", "crear_instancia", 750)
            self.assertEqual(sum(llamada.args[1] == "crear_instancia"
                                 for llamada in registrar.call_args_list), 1)
        finally:
            reproductor._vlc = anterior


class TestAvisoAlReproducir(unittest.TestCase):

    def test_reproducir_sin_medio_anuncia(self):
        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._listo = True
        panel._video_id = ""
        panel._url_flujo = ""
        panel._asegurar_player = lambda: True
        panel._player = mock.Mock()
        panel._intencion_reproducir = False
        panel._player.get_state.return_value = object()

        estados = mock.Mock(Playing=object(), Paused=object())
        with mock.patch.object(reproductor, "anunciar") as anunciar, \
                mock.patch.object(reproductor, "_vlc", State=estados):
            panel._toggle_play()

        anunciar.assert_called_once_with("No hay ningún vídeo cargado")

    def _panel_sin_medio(self):
        panel = reproductor.ReproductorPanel.__new__(reproductor.ReproductorPanel)
        panel._listo = True
        panel._video_id = ""
        panel._url_flujo = ""
        panel._player = None
        return panel

    def test_silenciar_sin_medio_anuncia(self):
        with mock.patch.object(reproductor, "anunciar") as anunciar:
            self._panel_sin_medio()._toggle_mute()
        anunciar.assert_called_once_with("No hay ningún vídeo cargado")

    def test_silenciar_sin_reproductor_anuncia_indisponible(self):
        panel = self._panel_sin_medio()
        panel._listo = False
        with mock.patch.object(reproductor, "anunciar") as anunciar:
            panel._toggle_mute()
        anunciar.assert_called_once_with("El reproductor no está disponible")

    def test_buscar_sin_medio_anuncia(self):
        with mock.patch.object(reproductor, "anunciar") as anunciar:
            self._panel_sin_medio()._buscar_rel(10_000)
        anunciar.assert_called_once_with("No hay ningún vídeo cargado")

    def test_pantalla_completa_sin_reproductor_anuncia(self):
        panel = self._panel_sin_medio()
        panel._listo = False
        panel._asegurar_player = lambda: False
        with mock.patch.object(reproductor, "anunciar") as anunciar:
            panel.alternar_pantalla_completa()
        anunciar.assert_called_once_with("El reproductor no está disponible")

    def test_reproducir_sin_reproductor_anuncia(self):
        panel = self._panel_sin_medio()
        panel._listo = False
        panel._asegurar_player = lambda: False
        with mock.patch.object(reproductor, "anunciar") as anunciar:
            panel._toggle_play()
        anunciar.assert_called_once_with("El reproductor no está disponible")

    def test_reproducir_con_medio_no_anuncia_falta_de_medio(self):
        panel = self._panel_sin_medio()
        panel._video_id = "video-cargado"
        panel._asegurar_player = lambda: False
        with mock.patch.object(reproductor, "anunciar") as anunciar:
            panel._toggle_play()
        anunciar.assert_not_called()

        panel._video_id = ""
        with mock.patch.object(reproductor, "anunciar") as anunciar:
            panel._toggle_play()
        anunciar.assert_called_once_with("No hay ningún vídeo cargado")

    def test_reproducir_con_flujo_no_anuncia_falta_de_medio(self):
        panel = self._panel_sin_medio()
        panel._url_flujo = "https://flujo.example/stream"
        panel._asegurar_player = lambda: False
        with mock.patch.object(reproductor, "anunciar") as anunciar:
            panel._toggle_play()
        anunciar.assert_not_called()

if __name__ == "__main__":
    unittest.main()
