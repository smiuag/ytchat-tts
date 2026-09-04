"""Pruebas del resolvedor único de ffmpeg."""

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import config
import ffmpeg_bin


def _imageio(ruta):
    return types.SimpleNamespace(get_ffmpeg_exe=lambda: ruta)


def _imageio_roto():
    def fallar():
        raise RuntimeError("no hay ffmpeg")
    return types.SimpleNamespace(get_ffmpeg_exe=fallar)


class PruebasRutaFfmpeg(unittest.TestCase):

    def test_empaquetada_prefiere_la_copia_junto_al_exe(self):
        with tempfile.TemporaryDirectory() as carpeta:
            copia = Path(carpeta) / ffmpeg_bin.NOMBRE_BINARIO
            copia.write_bytes(b"ffmpeg")
            with mock.patch.object(sys, "frozen", True, create=True), \
                    mock.patch.object(config, "app_dir", return_value=Path(carpeta)), \
                    mock.patch.dict(sys.modules, {"imageio_ffmpeg": _imageio("otro")}):
                self.assertEqual(ffmpeg_bin.ruta_ffmpeg(), str(copia))

    def test_empaquetada_sin_copia_cae_a_las_otras_fuentes(self):
        with tempfile.TemporaryDirectory() as carpeta:
            with mock.patch.object(sys, "frozen", True, create=True), \
                    mock.patch.object(config, "app_dir", return_value=Path(carpeta)), \
                    mock.patch.dict(sys.modules, {"imageio_ffmpeg": _imageio("de-imageio")}):
                self.assertEqual(ffmpeg_bin.ruta_ffmpeg(), "de-imageio")

    def test_en_desarrollo_no_mira_la_carpeta_de_la_app(self):
        with mock.patch.object(sys, "frozen", False, create=True), \
                mock.patch.object(config, "app_dir") as app_dir, \
                mock.patch.dict(sys.modules, {"imageio_ffmpeg": _imageio("de-imageio")}):
            self.assertEqual(ffmpeg_bin.ruta_ffmpeg(), "de-imageio")
        app_dir.assert_not_called()

    def test_sin_imageio_usa_el_path(self):
        with mock.patch.object(sys, "frozen", False, create=True), \
                mock.patch.dict(sys.modules, {"imageio_ffmpeg": None}), \
                mock.patch.object(ffmpeg_bin.shutil, "which", return_value="C:/bin/ffmpeg.exe"):
            self.assertEqual(ffmpeg_bin.ruta_ffmpeg(), "C:/bin/ffmpeg.exe")

    def test_imageio_que_falla_no_rompe_y_usa_el_path(self):
        with mock.patch.object(sys, "frozen", False, create=True), \
                mock.patch.dict(sys.modules, {"imageio_ffmpeg": _imageio_roto()}), \
                mock.patch.object(ffmpeg_bin.shutil, "which", return_value="ffmpeg") as which:
            self.assertEqual(ffmpeg_bin.ruta_ffmpeg(), "ffmpeg")
        which.assert_called_once_with("ffmpeg")

    def test_sin_ninguna_fuente_devuelve_none(self):
        with mock.patch.object(sys, "frozen", False, create=True), \
                mock.patch.dict(sys.modules, {"imageio_ffmpeg": None}), \
                mock.patch.object(ffmpeg_bin.shutil, "which", return_value=None):
            self.assertIsNone(ffmpeg_bin.ruta_ffmpeg())


class PruebasConstruccion(unittest.TestCase):
    """El paquete lleva un solo ffmpeg: el de la raíz. El de imageio_ffmpeg
    (que su hook de PyInstaller metía en _internal) se excluye."""

    def _construir(self) -> str:
        return (Path(__file__).parents[1] / "construir.bat").read_text(encoding="utf-8")

    def test_excluye_imageio_ffmpeg_del_paquete(self):
        self.assertIn("--exclude-module imageio_ffmpeg", self._construir())

    def test_sigue_copiando_ffmpeg_a_la_raiz(self):
        self.assertIn('"%OUT%\\ffmpeg.exe"', self._construir())


if __name__ == "__main__":
    unittest.main()
