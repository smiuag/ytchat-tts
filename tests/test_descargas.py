from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import descargas
from descargas import (
    GestorDescargas,
    INTERVALO_PROGRESO_S,
    analizar_url,
    argumentos_descarga,
    construir_outtmpl,
    debe_emitir_progreso,
    descargar,
    formato_a_ydl,
    frase_aviso_descarga,
    gestor,
    recortar_url_registro,
    reiniciar_gestor,
    tiene_ffmpeg,
    _vigilar_cancelacion,
)


class TestDebeEmitirProgreso(unittest.TestCase):
    def test_primer_aviso(self): self.assertTrue(debe_emitir_progreso(None, 10, 0))
    def test_aviso_final(self): self.assertTrue(debe_emitir_progreso(10, 10.01, 100))
    def test_aviso_al_intervalo(self): self.assertTrue(debe_emitir_progreso(10, 10.5, 40))
    def test_aviso_dentro_del_intervalo(self): self.assertFalse(debe_emitir_progreso(10, 10.01, 40))


class TestRecortarUrlRegistro(unittest.TestCase):
    def test_deja_identificador_y_quita_parametros(self):
        url = "https://www.youtube.com/watch?v=abc123&list=secreta&token=oculto"
        self.assertEqual(recortar_url_registro(url), "abc123")


class TestFraseAvisoDescarga(unittest.TestCase):
    def test_completada_incluye_nombre(self):
        self.assertEqual(frase_aviso_descarga("completado", "", "archivo.mp4"),
                         "Descarga completada: archivo.mp4")

    def test_error_incluye_motivo(self):
        self.assertEqual(frase_aviso_descarga("error", "sin espacio", ""),
                         "Error en la descarga: sin espacio")

    def test_cancelada_no_agrega_mensaje(self):
        self.assertEqual(frase_aviso_descarga("cancelado", "motivo", "archivo"),
                         "Descarga cancelada")

    def test_progreso_no_se_anuncia(self):
        self.assertEqual(frase_aviso_descarga("descargando", "", "archivo"), "")


class TestFormatoAYdl(unittest.TestCase):
    def test_mp4(self):
        self.assertIn("bestvideo[ext=mp4]+bestaudio[ext=m4a]", formato_a_ydl("mp4", 192))
    def test_webm(self): self.assertIn("bestvideo[ext=webm]", formato_a_ydl("webm", 256))
    def test_mp3(self): self.assertEqual(formato_a_ydl("mp3", 192), "bestaudio")
    def test_m4a(self): self.assertEqual(formato_a_ydl("m4a", 320), "bestaudio")
    def test_desconocido(self): self.assertEqual(formato_a_ydl("xyz", 192), "best")
    def test_mayusculas(self): self.assertIn("mp4", formato_a_ydl("MP4", 192))


class TestConstruirOuttmpl(unittest.TestCase):
    def test_sin_enumerar(self):
        salida = construir_outtmpl({"carpeta": "/tmp/Descargas"}, False)
        self.assertNotIn("playlist_index", salida)
        self.assertIn("%(title)s", salida)
    def test_incluye_carpeta(self):
        self.assertEqual(Path(construir_outtmpl({"carpeta": "/tmp/Descargas"}, False)).parent,
                         Path("/tmp/Descargas"))
    def test_con_enumerar(self):
        self.assertIn("playlist_index", construir_outtmpl({"carpeta": "/tmp"}, True))

    def test_enumerar_no_deja_na_en_videos_sueltos(self):
        # «%(playlist_index)02d» a secas daba «NA - Título» fuera de una playlist.
        salida = Path(construir_outtmpl({"carpeta": "/tmp"}, True)).name
        self.assertTrue(salida.startswith("%(playlist_index&{:02d} - |)s"), salida)
        try:
            from yt_dlp import YoutubeDL
        except Exception:
            return
        ydl = YoutubeDL({"quiet": True})
        suelto = ydl.evaluate_outtmpl(salida, {"title": "T", "id": "x", "ext": "mp4"})
        en_lista = ydl.evaluate_outtmpl(
            salida, {"title": "T", "id": "x", "ext": "mp4", "playlist_index": 3})
        self.assertEqual(suelto, "T [x].mp4")
        self.assertEqual(en_lista, "03 - T [x].mp4")
    def test_carpeta_por_defecto(self): self.assertIn("Descargas", construir_outtmpl({}, False))
    def test_carpeta_windows(self): self.assertIn("Descargas", construir_outtmpl({"carpeta": r"C:\Users\foo\Descargas"}, False))


class TestAnalizarUrl(unittest.TestCase):
    def resultado(self, datos, codigo=0, error=""):
        return mock.Mock(stdout=json.dumps(datos), stderr=error, returncode=codigo)

    def test_video(self):
        with mock.patch.object(descargas.ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp"), \
                mock.patch.object(descargas.subprocess, "run", return_value=self.resultado({
                    "_type": "video", "id": "abc", "title": "Mi vídeo"})):
            res = analizar_url("https://example.com/v")
        self.assertEqual((res["tipo"], res["id"], res["cuenta"]), ("video", "abc", 1))

    def test_playlist(self):
        datos = {"_type": "playlist", "id": "PL", "title": "Lista", "entries": [{"id": "1"}]}
        with mock.patch.object(descargas.ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp"), \
                mock.patch.object(descargas.subprocess, "run", return_value=self.resultado(datos)):
            res = analizar_url("https://example.com/lista")
        self.assertEqual((res["tipo"], res["cuenta"]), ("playlist", 1))

    def test_sin_programa(self):
        with mock.patch.object(descargas.ytdlp_bin, "ruta_ytdlp", return_value=None):
            res = analizar_url("https://example.com/v")
        self.assertEqual(res["tipo"], "error")

    def test_fallo_del_programa(self):
        with mock.patch.object(descargas.ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp"), \
                mock.patch.object(descargas.subprocess, "run", return_value=self.resultado({}, 1, "URL inválida")):
            res = analizar_url("https://example.com/v")
        self.assertIn("inválida", res["mensaje"])

    def test_pide_un_unico_json_plano_con_tope(self):
        # --dump-json emitía un JSON por entrada en las playlists («Extra data»).
        with mock.patch.object(descargas.ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp"), \
                mock.patch.object(descargas.subprocess, "run",
                                  return_value=self.resultado({"id": "abc"})) as run:
            analizar_url("https://example.com/lista")
        args = run.call_args.args[0]
        self.assertIn("-J", args)
        self.assertIn("--flat-playlist", args)
        self.assertNotIn("--dump-json", args)
        self.assertEqual(run.call_args.kwargs["timeout"], descargas.TIEMPO_ESPERA_ANALISIS)

    def test_tope_agotado_es_error_y_no_revienta(self):
        with mock.patch.object(descargas.ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp"), \
                mock.patch.object(descargas.subprocess, "run",
                                  side_effect=descargas.subprocess.TimeoutExpired("yt-dlp", 60)):
            res = analizar_url("https://example.com/v")
        self.assertEqual(res["tipo"], "error")


class TestArgumentosDescarga(unittest.TestCase):
    def opciones(self, formato): return {"formato": formato, "bitrate": 256, "carpeta": "/tmp"}
    def test_mp3_lleva_conversion(self):
        args = argumentos_descarga("https://example.com/v", self.opciones("mp3"), False)
        self.assertIn("-x", args); self.assertIn("mp3", args); self.assertIn("256K", args)
    def test_mp4_no_lleva_conversion(self):
        args = argumentos_descarga("https://example.com/v", self.opciones("mp4"), False)
        self.assertNotIn("-x", args); self.assertNotIn("--audio-format", args)
        self.assertNotIn("--audio-quality", args)
    def test_no_lleva_quiet(self):
        self.assertNotIn("--quiet", argumentos_descarga("https://example.com/v", self.opciones("mp4"), False))
    def test_url_al_final(self):
        self.assertEqual(argumentos_descarga("-url", self.opciones("mp4"), False)[-2:],
                         ["--", "-url"])
    def test_lleva_plantilla_y_salida(self):
        args = argumentos_descarga("url", self.opciones("mp4"), True)
        self.assertIn("--progress-template", args); self.assertIn("-o", args)
    def test_usa_ruta_de_ffmpeg_recibida(self):
        args = argumentos_descarga("url", self.opciones("mp3"), False,
                                   r"C:\ffmpeg")
        indice = args.index("--ffmpeg-location")
        self.assertEqual(args[indice:indice + 2], ["--ffmpeg-location", r"C:\ffmpeg"])

    def test_sin_ffmpeg_resuelto_no_agrega_ffmpeg(self):
        with mock.patch.object(descargas.ffmpeg_bin, "ruta_ffmpeg", return_value=None):
            args = argumentos_descarga("url", self.opciones("mp3"), False)
        self.assertNotIn("--ffmpeg-location", args)

    def test_usa_el_resolvedor_unico_de_ffmpeg(self):
        with mock.patch.object(descargas.ffmpeg_bin, "ruta_ffmpeg",
                               return_value=r"C:\app\ffmpeg.exe"):
            args = argumentos_descarga("url", self.opciones("mp3"), False)
        indice = args.index("--ffmpeg-location")
        self.assertEqual(args[indice + 1], r"C:\app\ffmpeg.exe")

    def test_pide_la_ruta_final_sin_perder_el_progreso(self):
        # --print implica --quiet, que apaga el progreso: --progress lo recupera.
        args = argumentos_descarga("url", self.opciones("mp4"), False)
        indice = args.index("--print")
        self.assertEqual(args[indice + 1],
                         f"after_move:{descargas.PREFIJO_RUTA_FINAL} %(filepath)s")
        self.assertIn("--progress", args)
        self.assertIn("--progress-template", args)


class TestDescargar(unittest.TestCase):
    def proceso(self, lineas):
        proceso = mock.MagicMock()
        proceso.returncode = 0
        proceso.poll.return_value = 0
        proceso.stdout.readline.side_effect = [*lineas, ""]
        return proceso

    def preparar(self, proceso):
        return mock.patch.object(descargas.ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp"), \
            mock.patch.object(descargas, "tiene_ffmpeg", return_value=True), \
            mock.patch.object(descargas.subprocess, "Popen", return_value=proceso)

    def test_pasa_progreso_al_callback(self):
        proceso = self.proceso(["PROG 5 10 NA 2 3 nombre con espacios.mp4\n"])
        progresos = []; estados = []
        with self.preparar(proceso)[0], self.preparar(proceso)[1], self.preparar(proceso)[2]:
            descargar("url", {"formato": "mp4"}, lambda *a: progresos.append(a),
                      lambda *a: estados.append(a), threading.Event())
        self.assertEqual(progresos, [(50.0, 2.0, 3, "nombre con espacios.mp4")])
        self.assertEqual(estados[-1], ("completado", ""))

    def test_la_ruta_final_reemplaza_el_nombre_del_fragmento(self):
        proceso = self.proceso([
            "PROG 5 10 NA 2 3 C:/d/video [x].f140.m4a\n",
            f"{descargas.PREFIJO_RUTA_FINAL} C:/d/video [x].mp4\n",
        ])
        progresos = []; estados = []
        with self.preparar(proceso)[0], self.preparar(proceso)[1], self.preparar(proceso)[2]:
            descargar("url", {"formato": "mp4"}, lambda *a: progresos.append(a),
                      lambda *a: estados.append(a), threading.Event())
        self.assertEqual(progresos[-1], (100.0, None, None, "video [x].mp4"))
        self.assertEqual(estados[-1], ("completado", ""))

    def test_cancelar_borra_los_restos_de_la_carpeta(self):
        with tempfile.TemporaryDirectory() as carpeta:
            base = Path(carpeta) / "Vídeo [abc]"
            restos = [base.with_name(base.name + ".f140.m4a.part"),
                      base.with_name(base.name + ".f137.mp4"),
                      base.with_name(base.name + ".mp4.ytdl")]
            intactos = [base.with_name(base.name + ".mp4"),
                        Path(carpeta) / "Otro [zzz].mp4.part"]
            for ruta in restos + intactos:
                ruta.write_bytes(b"x")
            proceso = self.proceso([
                f"PROG 5 10 NA 2 3 {base}.f140.m4a\n",
                f"PROG 6 10 NA 2 3 {base}.f140.m4a\n",
            ])
            evento = threading.Event(); estados = []
            with self.preparar(proceso)[0], self.preparar(proceso)[1], self.preparar(proceso)[2]:
                descargar("url", {"formato": "mp4", "carpeta": carpeta},
                          lambda *a: evento.set(), lambda *a: estados.append(a), evento)
            self.assertEqual(estados[-1], ("cancelado", "Descarga cancelada"))
            self.assertFalse(any(ruta.exists() for ruta in restos))
            self.assertTrue(all(ruta.exists() for ruta in intactos))

    def test_ignora_lineas_no_progreso(self):
        proceso = self.proceso(["[youtube] Extracting URL\n"])
        callback = mock.Mock()
        with self.preparar(proceso)[0], self.preparar(proceso)[1], self.preparar(proceso)[2]:
            descargar("url", {"formato": "mp4"}, callback, lambda *a: None, threading.Event())
        callback.assert_not_called()

    def test_frena_progresos_seguidos(self):
        lineas = ["PROG 5 10 NA 2 3 nombre.mp4\n"] * 20
        proceso = self.proceso(lineas)
        progreso = mock.Mock()
        with self.preparar(proceso)[0], self.preparar(proceso)[1], \
                self.preparar(proceso)[2], \
                mock.patch.object(descargas.time, "monotonic", return_value=10):
            descargar("url", {"formato": "mp4"}, progreso, lambda *a: None,
                      threading.Event())
        self.assertLess(progreso.call_count, len(lineas))

    def test_cancelar_mata_el_proceso(self):
        proceso = self.proceso([]); evento = threading.Event(); evento.set(); estados = []
        with self.preparar(proceso)[0], self.preparar(proceso)[1], self.preparar(proceso)[2]:
            descargar("url", {"formato": "mp4"}, lambda *a: None,
                      lambda *a: estados.append(a), evento)
        self.assertEqual(estados[-1], ("cancelado", "Descarga cancelada"))
        proceso.kill.assert_called_once()

    def test_cancelar_durante_progreso_mata_el_proceso(self):
        proceso = self.proceso([
            "PROG 5 10 NA 2 3 nombre.mp4\n",
            "PROG 6 10 NA 2 3 nombre.mp4\n",
        ])
        evento = threading.Event(); estados = []

        def progreso(*args):
            evento.set()

        with self.preparar(proceso)[0], self.preparar(proceso)[1], self.preparar(proceso)[2]:
            descargar("url", {"formato": "mp4"}, progreso,
                      lambda *a: estados.append(a), evento)
        self.assertEqual(estados[-1], ("cancelado", "Descarga cancelada"))
        proceso.kill.assert_called_once()

    def test_cancelar_sin_nuevas_lineas_mata_e_informa(self):
        class ProcesoBloqueado:
            def __init__(self):
                self.inicio_lectura = threading.Event()
                self.terminado = threading.Event()
                self.codigo = None
                self.kill_count = 0
                self.stdout = self

            def poll(self):
                return self.codigo

            def kill(self):
                self.kill_count += 1
                self.codigo = -9
                self.terminado.set()

            def wait(self):
                self.terminado.wait(0.5)
                return self.codigo

            def readline(self):
                self.inicio_lectura.set()
                self.terminado.wait(0.5)
                return ""

        proceso = ProcesoBloqueado()
        evento = threading.Event(); estados = []
        with self.preparar(proceso)[0], self.preparar(proceso)[1], \
                self.preparar(proceso)[2]:
            hilo = threading.Thread(
                target=descargar,
                args=("url", {"formato": "mp4"}, lambda *a: None,
                      lambda *a: estados.append(a), evento),
            )
            hilo.start()
            self.assertTrue(proceso.inicio_lectura.wait(1))
            evento.set()
            hilo.join(1)
        self.assertFalse(hilo.is_alive())
        self.assertEqual(estados[-1], ("cancelado", "Descarga cancelada"))
        self.assertEqual(proceso.kill_count, 1)

    def test_vigilante_mata_al_cancelar(self):
        proceso = mock.Mock()
        proceso.poll.return_value = None
        evento = threading.Event()
        evento.set()
        self.assertTrue(_vigilar_cancelacion(proceso, evento, 0.01))
        proceso.kill.assert_called_once()

    def test_vigilante_no_mata_si_termina(self):
        proceso = mock.Mock()
        proceso.poll.return_value = 0
        self.assertFalse(_vigilar_cancelacion(proceso, threading.Event(), 0.01))
        proceso.kill.assert_not_called()

    def test_cancelar_despues_de_terminar_marca_estado(self):
        proceso = self.proceso([]); evento = threading.Event(); estados = []
        proceso.wait.side_effect = evento.set
        with self.preparar(proceso)[0], self.preparar(proceso)[1], self.preparar(proceso)[2]:
            descargar("url", {"formato": "mp4"}, lambda *a: None,
                      lambda *a: estados.append(a), evento)
        self.assertEqual(estados[-1], ("cancelado", "Descarga cancelada"))
        proceso.kill.assert_not_called()

    def test_codigo_no_cero_es_error(self):
        proceso = self.proceso([]); proceso.returncode = 2; estados = []
        with self.preparar(proceso)[0], self.preparar(proceso)[1], self.preparar(proceso)[2]:
            descargar("url", {"formato": "mp4"}, lambda *a: None,
                      lambda *a: estados.append(a), threading.Event())
        self.assertEqual(estados[-1][0], "error")

    def test_sin_programa_es_error(self):
        estados = []
        with mock.patch.object(descargas.ytdlp_bin, "ruta_ytdlp", return_value=None):
            descargar("url", {}, lambda *a: None, lambda *a: estados.append(a), threading.Event())
        self.assertEqual(estados[-1][0], "error")


class TestMatarArbol(unittest.TestCase):
    """kill() solo mata a yt-dlp; el ffmpeg hijo seguía uniendo audio y vídeo."""

    def test_en_windows_baja_el_arbol_con_taskkill_y_luego_kill(self):
        proceso = mock.Mock(pid=1234)
        with mock.patch.object(descargas.os, "name", "nt"), \
                mock.patch.object(descargas.subprocess, "run") as run:
            descargas._matar_arbol(proceso)
        self.assertEqual(run.call_args.args[0],
                         ["taskkill", "/T", "/F", "/PID", "1234"])
        proceso.kill.assert_called_once()

    def test_si_taskkill_falla_igual_hace_kill(self):
        proceso = mock.Mock(pid=1234)
        with mock.patch.object(descargas.os, "name", "nt"), \
                mock.patch.object(descargas.subprocess, "run", side_effect=OSError("no")):
            descargas._matar_arbol(proceso)
        proceso.kill.assert_called_once()

    def test_sin_pid_real_no_lanza_taskkill(self):
        proceso = mock.Mock()   # pid es un Mock, como en las demás pruebas
        with mock.patch.object(descargas.subprocess, "run") as run:
            descargas._matar_arbol(proceso)
        run.assert_not_called()
        proceso.kill.assert_called_once()


class TestLimpiarRestos(unittest.TestCase):

    def test_nombre_base_quita_fragmento_part_y_extension(self):
        for nombre in ("C:/d/Título [id].f140.m4a.part", "Título [id].f137.mp4",
                       "Título [id].mp4.ytdl", "Título [id].mp4", "Título [id].mp4.part"):
            self.assertEqual(descargas.nombre_base_descarga(nombre), "Título [id]", nombre)

    def test_sin_nombre_no_borra_nada(self):
        with tempfile.TemporaryDirectory() as carpeta:
            (Path(carpeta) / "a.part").write_bytes(b"x")
            self.assertEqual(descargas.limpiar_restos_descarga(carpeta, ""), [])
            self.assertTrue((Path(carpeta) / "a.part").exists())

    def test_borra_solo_temporales_de_esa_descarga(self):
        with tempfile.TemporaryDirectory() as carpeta:
            nombres = ["V [id].f140.m4a.part", "V [id].f137.mp4", "V [id].mp4.ytdl",
                       "V [id].mp4.part", "V [id].mp4", "V [id].jpg", "W [id].mp4.part"]
            for nombre in nombres:
                (Path(carpeta) / nombre).write_bytes(b"x")
            borrados = descargas.limpiar_restos_descarga(carpeta, "V [id].f140.m4a")
            self.assertEqual(sorted(borrados), ["V [id].f137.mp4", "V [id].f140.m4a.part",
                                                "V [id].mp4.part", "V [id].mp4.ytdl"])
            self.assertEqual(sorted(r.name for r in Path(carpeta).iterdir()),
                             ["V [id].jpg", "V [id].mp4", "W [id].mp4.part"])

    def test_carpeta_inexistente_no_revienta(self):
        self.assertEqual(descargas.limpiar_restos_descarga("/no/existe", "a.mp4"), [])


class TestGestorDescargas(unittest.TestCase):
    def opciones(self): return {"formato": "mp4", "bitrate": 192, "carpeta": "/tmp"}

    def test_cancelar_durante_el_analisis_no_lanza_la_descarga(self):
        gestor = GestorDescargas(self.opciones())
        seguir = threading.Event()
        estados = []
        terminado = threading.Event()

        def analizar(_url):
            seguir.wait(1)
            return {"tipo": "video"}

        def estado(_id, valor, _mensaje):
            estados.append(valor)
            terminado.set()

        with mock.patch.object(descargas, "analizar_url", side_effect=analizar), \
                mock.patch.object(descargas, "descargar") as descargar_mock:
            item_id = gestor.encolar("url", lambda *a: None, estado)
            gestor.cancelar(item_id)
            seguir.set()
            self.assertTrue(terminado.wait(1))
        descargar_mock.assert_not_called()
        self.assertEqual(estados, ["cancelado"])

    def test_el_item_lleva_la_carpeta_elegida_al_encolar(self):
        gestor = GestorDescargas(self.opciones())
        with mock.patch.object(descargas.ytdlp_bin, "ruta_ytdlp", return_value=None):
            id_ = gestor.encolar("url", lambda *a: None, lambda *a: None)
        self.assertEqual(gestor.obtener(id_).carpeta, "/tmp")
    def test_encolar_almacena_item(self):
        gestor = GestorDescargas(self.opciones())
        with mock.patch.object(descargas.ytdlp_bin, "ruta_ytdlp", return_value=None):
            id_ = gestor.encolar("url", lambda *a: None, lambda *a: None)
        self.assertEqual(gestor.obtener(id_).url, "url")
    def test_cancelar_marca_evento(self):
        gestor = GestorDescargas(self.opciones())
        with mock.patch.object(descargas.ytdlp_bin, "ruta_ytdlp", return_value=None):
            id_ = gestor.encolar("url", lambda *a: None, lambda *a: None)
        gestor.cancelar(id_); self.assertTrue(gestor._eventos[id_].is_set())
    def test_cancelar_inexistente(self): GestorDescargas(self.opciones()).cancelar("no-existe")
    def test_obtener_inexistente(self): self.assertIsNone(GestorDescargas(self.opciones()).obtener("no-existe"))
    def test_set_opciones(self):
        gestor = GestorDescargas(self.opciones()); gestor.set_opciones({"formato": "mp3"})
        self.assertEqual(gestor._opciones["formato"], "mp3")

    def test_encolar_devuelve_id_antes_de_analizar(self):
        gestor = GestorDescargas(self.opciones())
        analisis_iniciado = threading.Event()
        terminar_analisis = threading.Event()
        progresos = []

        def analizar(_url):
            analisis_iniciado.set()
            terminar_analisis.wait(1)
            return {"tipo": "video", "titulo": "Título conocido"}

        with mock.patch.object(descargas, "analizar_url", side_effect=analizar), \
                mock.patch.object(descargas, "descargar"):
            item_id = gestor.encolar("url", lambda *args: progresos.append(args),
                                     lambda *args: None)
            self.assertEqual(gestor.obtener(item_id).nombre, "url")
            self.assertTrue(analisis_iniciado.wait(1))
            terminar_analisis.set()
            for _ in range(100):
                if progresos:
                    break
                threading.Event().wait(0.01)

        self.assertEqual(progresos[0][4], "Título conocido")


class TestGestorUnico(unittest.TestCase):
    def tearDown(self):
        reiniciar_gestor()

    def test_devuelve_el_mismo_objeto(self):
        self.assertIs(gestor(), gestor())

    def test_reiniciar_crea_otro_gestor(self):
        anterior = gestor()
        reiniciar_gestor()
        self.assertIsNot(anterior, gestor())

    def test_suscriptor_recibe_estado_final(self):
        estados = []
        gestor_prueba = GestorDescargas({"formato": "mp4"})
        gestor_prueba.suscribir_fin(lambda estado, *_: estados.append(estado))
        terminado = threading.Event()

        def descarga_simulada(_url, _opciones, _progreso, estado, _cancelar):
            estado("completado", "")
            terminado.set()

        with mock.patch.object(descargas, "analizar_url", return_value={}), \
                mock.patch.object(descargas, "descargar", descarga_simulada):
            gestor_prueba.encolar("https://youtu.be/abc", lambda *_: None,
                                 lambda *_: None)
            self.assertTrue(terminado.wait(1))
        self.assertEqual(estados, ["completado"])

    def test_suscriptor_recibe_el_item_para_el_historial(self):
        recibidos = []
        gestor_prueba = GestorDescargas({"formato": "mp4", "carpeta": "/tmp"})
        gestor_prueba.suscribir_fin(lambda *args: recibidos.append(args))
        terminado = threading.Event()

        def descarga_simulada(_url, _opciones, _progreso, estado, _cancelar):
            estado("completado", "")
            terminado.set()

        with mock.patch.object(descargas, "analizar_url", return_value={}), \
                mock.patch.object(descargas, "descargar", descarga_simulada):
            item_id = gestor_prueba.encolar("https://youtu.be/abc", lambda *_: None,
                                            lambda *_: None)
            self.assertTrue(terminado.wait(1))
        estado, _mensaje, _nombre, item = recibidos[-1]
        self.assertEqual((estado, item.id, item.carpeta), ("completado", item_id, "/tmp"))

    def test_suscriptor_con_error_no_impide_a_los_demas(self):
        estados = []
        gestor_prueba = GestorDescargas({"formato": "mp4"})

        def suscriptor_roto(*_):
            raise RuntimeError("suscriptor roto")

        gestor_prueba.suscribir_fin(suscriptor_roto)
        gestor_prueba.suscribir_fin(lambda estado, *_: estados.append(estado))
        terminado = threading.Event()

        def descarga_simulada(_url, _opciones, _progreso, estado, _cancelar):
            estado("completado", "")
            terminado.set()

        with mock.patch.object(descargas, "analizar_url", return_value={}), \
                mock.patch.object(descargas, "descargar", descarga_simulada):
            gestor_prueba.encolar("https://youtu.be/abc", lambda *_: None,
                                 lambda *_: None)
            self.assertTrue(terminado.wait(1))
        self.assertEqual(estados, ["completado"])


class TestFfmpeg(unittest.TestCase):
    def test_devuelve_bool(self): self.assertIsInstance(tiene_ffmpeg(), bool)
    def test_faltante_informa_error(self):
        estados = []
        with mock.patch.object(descargas.ytdlp_bin, "ruta_ytdlp", return_value="yt-dlp"), \
                mock.patch.object(descargas, "tiene_ffmpeg", return_value=False):
            descargar("url", {}, lambda *a: None, lambda *a: estados.append(a), threading.Event())
        self.assertIn("ffmpeg", estados[-1][1])


if __name__ == "__main__": unittest.main()
