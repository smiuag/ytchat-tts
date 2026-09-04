"""Pruebas del reproductor de sonidos sin usar el backend real."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import sound_player


class PruebasBarridoAlias(unittest.TestCase):
    """El barrido cierra un alias cuando MCI dice que terminó, no a los 5 s:
    un tema de usuario largo se cortaba a mitad."""

    def test_alias_vencido_solo_si_dejo_de_sonar_o_supero_el_tope(self):
        self.assertFalse(sound_player._alias_vencido(6.0, "playing"))
        self.assertTrue(sound_player._alias_vencido(0.2, "stopped"))
        self.assertTrue(sound_player._alias_vencido(0.2, ""))   # MCI no contesta
        self.assertTrue(sound_player._alias_vencido(
            sound_player._TTL_ALIAS_SEG + 1, "playing"))

    def test_barrido_cierra_solo_los_alias_que_terminaron(self):
        modos = {"ytcsnd1": "playing", "ytcsnd2": "stopped"}
        enviados = []

        def mci(cmd, buf, n, cb):
            enviados.append(cmd)
            if cmd.startswith("status "):
                buf.value = modos[cmd.split()[1]]
            return 0
        winmm = mock.Mock()
        winmm.mciSendStringW.side_effect = mci
        activos = {"ytcsnd1": time.monotonic(), "ytcsnd2": time.monotonic()}
        with mock.patch.object(sound_player, "_winmm", winmm), \
                mock.patch.object(sound_player, "_alias_activos", activos):
            sound_player._barrer_alias()
            self.assertEqual(set(sound_player._alias_activos), {"ytcsnd1"})
        self.assertIn("close ytcsnd2", enviados)
        self.assertNotIn("close ytcsnd1", enviados)

    def test_barrido_cierra_por_tope_aunque_mci_diga_que_suena(self):
        def mci(cmd, buf, n, cb):
            if cmd.startswith("status "):
                buf.value = "playing"
            return 0
        winmm = mock.Mock()
        winmm.mciSendStringW.side_effect = mci
        activos = {"ytcsnd1": time.monotonic() - sound_player._TTL_ALIAS_SEG - 1}
        with mock.patch.object(sound_player, "_winmm", winmm), \
                mock.patch.object(sound_player, "_alias_activos", activos):
            sound_player._barrer_alias()
            self.assertEqual(sound_player._alias_activos, {})


class PruebasSoundPlayer(unittest.TestCase):
    def setUp(self):
        parches = (
            mock.patch.object(sound_player, "_eventos", {}),
            mock.patch.object(sound_player, "_volumen", 0.7),
            mock.patch.object(sound_player, "_activo", True),
            mock.patch.object(sound_player, "_silenciado_usuario", False),
            mock.patch.object(sound_player, "_backend_winmm", False),
            mock.patch.object(sound_player, "_init_backend"),
            mock.patch.object(sound_player, "_iniciar_sweeper"),
            mock.patch.object(sound_player, "_sweeper_thread", None),
        )
        for parche in parches:
            parche.start()
            self.addCleanup(parche.stop)

    def test_cargar_desactivado_silencia(self):
        sound_player.cargar({"activar": False})

        self.assertTrue(sound_player.esta_silenciado())

    def test_cargar_activo_con_eventos_no_silencia(self):
        sound_player.cargar({"activar": True, "eventos": {"mensaje": Path("mensaje.wav")}})

        self.assertFalse(sound_player.esta_silenciado())

    def test_cargar_recorta_el_volumen(self):
        sound_player.cargar({"volumen": 5})
        self.assertEqual(sound_player._volumen, 1.0)

        sound_player.cargar({"volumen": -3})
        self.assertEqual(sound_player._volumen, 0.0)

    def test_cargar_descarta_eventos_vacios(self):
        ruta = Path("mensaje.wav")
        sound_player.cargar({"eventos": {"mensaje": ruta, "vacio": "", "nulo": None}})

        self.assertEqual(sound_player._eventos, {"mensaje": ruta})

    def test_silenciar_todo_impide_llegar_al_backend(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directorio:
            ruta = Path(directorio) / "mensaje.wav"
            ruta.touch()
            sound_player.cargar({"eventos": {"mensaje": ruta}})
            sound_player.silenciar_todo(True)
            with mock.patch.object(sound_player, "_reproducir_winmm") as winmm, \
                    mock.patch.object(sound_player, "_reproducir_fallback") as fallback:
                sound_player.reproducir("mensaje")

        winmm.assert_not_called()
        fallback.assert_not_called()

    def test_reproducir_evento_desconocido_no_llama_al_backend(self):
        with mock.patch.object(sound_player, "_reproducir_winmm") as winmm, \
                mock.patch.object(sound_player, "_reproducir_fallback") as fallback:
            sound_player.reproducir("inexistente")

        winmm.assert_not_called()
        fallback.assert_not_called()

    def test_reproducir_archivo_ausente_no_llama_al_backend(self):
        sound_player.cargar({"eventos": {"mensaje": Path("no-existe.wav")}})
        with mock.patch.object(sound_player, "_reproducir_winmm") as winmm, \
                mock.patch.object(sound_player, "_reproducir_fallback") as fallback:
            sound_player.reproducir("mensaje")

        winmm.assert_not_called()
        fallback.assert_not_called()

    def test_reproducir_archivo_existente_llama_al_backend(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directorio:
            ruta = Path(directorio) / "mensaje.wav"
            ruta.touch()
            sound_player.cargar({"eventos": {"mensaje": ruta}})
            with mock.patch.object(sound_player, "_reproducir_fallback") as fallback:
                sound_player.reproducir("mensaje")

        fallback.assert_called_once_with(ruta)

    def test_cerrar_sin_haber_cargado_no_lanza(self):
        sound_player.cerrar()


if __name__ == "__main__":
    unittest.main()
