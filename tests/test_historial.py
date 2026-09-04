"""Tests del historial de directos (lógica pura y persistencia)."""

import tempfile
import unittest
from pathlib import Path

import historial as h


class TestUpsert(unittest.TestCase):

    def test_agrega_al_principio(self):
        l = h.upsert([], "tiktok", "pepe", "url1", "T1", "C1", fecha="2026-01-01")
        l = h.upsert(l, "tiktok", "ana", "url2", "T2", "C2", fecha="2026-01-02")
        self.assertEqual(l[0]["clave"], "ana")   # la más reciente arriba
        self.assertEqual(len(l), 2)

    def test_dedupe_por_plataforma_y_clave(self):
        l = h.upsert([], "tiktok", "pepe", "u", "viejo", "C", fecha="2026-01-01")
        l = h.upsert(l, "tiktok", "pepe", "u", "nuevo", "C", fecha="2026-01-02")
        self.assertEqual(len(l), 1)
        self.assertEqual(l[0]["titulo"], "nuevo")   # se actualiza y sube

    def test_misma_clave_distinta_plataforma_no_dedupe(self):
        l = h.upsert([], "tiktok", "x", "u", "T", "C")
        l = h.upsert(l, "youtube", "x", "u", "T", "C")
        self.assertEqual(len(l), 2)

    def test_recorta_al_maximo(self):
        l = []
        for i in range(10):
            l = h.upsert(l, "tiktok", f"u{i}", "url", "T", "C", max_entradas=5)
        self.assertEqual(len(l), 5)
        self.assertEqual(l[0]["clave"], "u9")   # los más recientes

    def test_clave_vacia_no_agrega(self):
        self.assertEqual(h.upsert([], "tiktok", "", "u", "T", "C"), [])


class TestConsulta(unittest.TestCase):

    def _lista(self):
        l = h.upsert([], "youtube", "vid1", "u", "TY", "CY")
        l = h.upsert(l, "tiktok", "pepe", "u", "TT", "CT")
        return l

    def test_de_plataforma(self):
        l = self._lista()
        self.assertEqual([e["clave"] for e in h.de_plataforma(l, "youtube")], ["vid1"])
        self.assertEqual([e["clave"] for e in h.de_plataforma(l, "tiktok")], ["pepe"])

    def test_etiqueta_completa(self):
        e = {"canal": "Larzock", "titulo": "Módulos", "fecha": "2026-07-08T20:00:00"}
        self.assertEqual(h.etiqueta(e), "Larzock — Módulos (2026-07-08)")

    def test_etiqueta_sin_datos_usa_clave(self):
        e = {"clave": "pepe", "canal": "", "titulo": "", "fecha": ""}
        self.assertEqual(h.etiqueta(e), "pepe")

    def test_etiqueta_marca_directo(self):
        e = {"canal": "Larzock", "titulo": "Módulos", "fecha": "2026-07-08T20:00:00",
             "directo": True}
        self.assertEqual(h.etiqueta(e), "Larzock — Módulos · directo (2026-07-08)")

    def test_upsert_guarda_directo(self):
        l = h.upsert([], "tiktok", "pepe", "u", "T", "C", directo=True)
        self.assertTrue(l[0]["directo"])


class TestPersistencia(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ruta = Path(self._tmp.name) / "historial_lives.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_ida_y_vuelta(self):
        l = h.upsert([], "tiktok", "pepe", "url", "Charla", "Pepe")
        h.guardar(self.ruta, l)
        self.assertEqual(h.cargar(self.ruta), l)

    def test_cargar_inexistente_es_vacio(self):
        self.assertEqual(h.cargar(self.ruta), [])

    def test_cargar_corrupto_es_vacio(self):
        self.ruta.write_text("no es json {", encoding="utf-8")
        self.assertEqual(h.cargar(self.ruta), [])

    def test_cargar_descarta_entradas_que_no_son_dict(self):
        # Una lista editada a mano con basura dentro no debe tirar el diálogo.
        self.ruta.write_text('[{"plataforma": "tiktok", "clave": "pepe"}, "basura", 3, null]',
                             encoding="utf-8")
        self.assertEqual(h.cargar(self.ruta), [{"plataforma": "tiktok", "clave": "pepe"}])

    def test_guardar_no_deja_temporales(self):
        h.guardar(self.ruta, h.upsert([], "tiktok", "pepe", "url", "T", "C"))
        self.assertTrue(self.ruta.exists())
        self.assertEqual(list(self.ruta.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
