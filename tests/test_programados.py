import unittest
from pathlib import Path
import tempfile

import programados
import redaccion


class TestConstantes(unittest.TestCase):
    def test_limite_de_chat_es_un_alias_de_redaccion(self):
        self.assertIs(programados.MAX_CARACTERES, redaccion.MAXIMO_CHAT)


class TestValidarMensaje(unittest.TestCase):
    def test_acepta_mensaje_valido(self):
        self.assertEqual(programados.validar_mensaje("Sígueme", 10, 15), ("", ""))

    def test_rechaza_texto_vacio(self):
        self.assertEqual(programados.validar_mensaje("  ", 10, 10)[0],
                         "El mensaje no puede estar vacío.")

    def test_rechaza_texto_largo(self):
        error, _ = programados.validar_mensaje("x" * 201, 10, 10)
        self.assertEqual(error, "El mensaje tiene 201 caracteres y el máximo son 200.")

    def test_rechaza_minimo_bajo(self):
        error, _ = programados.validar_mensaje("Hola", 4, 10)
        self.assertEqual(error, "El intervalo mínimo son 5 minutos.")

    def test_rechaza_maximo_menor(self):
        error, _ = programados.validar_mensaje("Hola", 10, 9)
        self.assertEqual(error, "El intervalo máximo no puede ser menor que el mínimo.")

    def test_avisa_url_sin_rechazar(self):
        aviso_esperado = ("YouTube suele bloquear los enlaces en el chat en vivo. "
                          "Conviene poner el nombre de usuario en vez de la dirección completa.")
        for prefijo in ("http://", "https://", "www."):
            with self.subTest(prefijo=prefijo):
                error, aviso = programados.validar_mensaje(
                    f"Visita {prefijo}ejemplo.com", 10, 10)
                self.assertEqual(error, "")
                self.assertEqual(aviso, aviso_esperado)


class TestCalcularProximo(unittest.TestCase):
    def test_intervalo_fijo_no_llama_al_azar(self):
        llamadas = []
        aleatorio = lambda a, b: llamadas.append((a, b)) or 0
        self.assertEqual(programados.calcular_proximo(10, 10, 1000, aleatorio), 1600)
        self.assertEqual(llamadas, [])

    def test_intervalo_aleatorio_inyectado(self):
        self.assertEqual(programados.calcular_proximo(10, 15, 1000,
                                                       lambda a, b: 720), 1720)


class TestIniciarReloj(unittest.TestCase):
    def test_da_cuerda_a_activos_y_no_toca_pausados(self):
        activos = [{"activo": True, "minutos_min": 5, "minutos_max": 10,
                    "proximo": 0.0}]
        pausados = {"activo": False, "minutos_min": 5, "minutos_max": 5,
                    "proximo": 17.0}
        mensajes = activos + [pausados]
        programados.iniciar_reloj(mensajes, 1000.0, lambda minimo, maximo: 420)
        self.assertEqual(activos[0]["proximo"], 1420.0)
        self.assertEqual(pausados["proximo"], 17.0)


class TestElegirEnvio(unittest.TestCase):
    def setUp(self):
        self.mensajes = [
            {"texto": "nuevo", "activo": True, "proximo": 90},
            {"texto": "viejo", "activo": True, "proximo": 80},
        ]

    def test_ignora_inactivos(self):
        self.mensajes[1]["activo"] = False
        self.assertIs(self._elegir(100), self.mensajes[0])

    def test_elige_el_vencido_mas_antiguo(self):
        self.assertIs(self._elegir(100), self.mensajes[1])

    def test_reserva_un_minuto_entre_envios(self):
        self.assertIsNone(self._elegir(100, ultimo_envio=50))

    def test_no_devuelve_si_no_hay_vencidos(self):
        self.assertIsNone(self._elegir(70))

    def test_considera_vencido_el_mensaje_que_vence_exactamente_ahora(self):
        self.mensajes[1]["activo"] = False
        self.assertIs(self._elegir(90), self.mensajes[0])

    def _elegir(self, ahora, ultimo_envio=None):
        return programados.elegir_envio(self.mensajes, ahora, ultimo_envio)


class TestDescribirProximo(unittest.TestCase):
    def test_sin_mensajes_activos(self):
        self.assertEqual(programados.describir_proximo([], 0), "")

    def test_menos_de_un_minuto(self):
        mensajes = [{"activo": True, "proximo": 30}]
        self.assertEqual(programados.describir_proximo(mensajes, 0),
                         "Próximo mensaje programado en menos de un minuto")

    def test_singular(self):
        mensajes = [{"activo": True, "proximo": 60}]
        self.assertEqual(programados.describir_proximo(mensajes, 0),
                         "Próximo mensaje programado en 1 minuto")

    def test_elige_el_mas_cercano_y_redondea(self):
        mensajes = [{"activo": True, "proximo": 301},
                    {"activo": True, "proximo": 500}]
        self.assertEqual(programados.describir_proximo(mensajes, 0),
                         "Próximo mensaje programado en 6 minutos")

    def test_recien_cargado_sin_cuerda_no_dice_menos_de_un_minuto(self):
        mensajes = [{"activo": True, "proximo": 0.0}]
        self.assertEqual(programados.describir_proximo(mensajes, 1000.0),
                         "Próximo mensaje programado: pendiente de programar")

    def test_ignora_los_sin_cuerda_si_otro_ya_tiene_hora(self):
        mensajes = [{"activo": True, "proximo": 0.0},
                    {"activo": True, "proximo": 120.0}]
        self.assertEqual(programados.describir_proximo(mensajes, 0),
                         "Próximo mensaje programado en 2 minutos")


class TestDescribirMensaje(unittest.TestCase):
    def test_intervalo_fijo_y_estado(self):
        self.assertEqual(programados.describir_mensaje({
            "activo": True, "minutos_min": 10, "minutos_max": 10,
            "texto": "Seguime en Instagram, arroba loquesea",
        }), "Activo, cada 10 minutos: Seguime en Instagram, arroba loquesea")

    def test_intervalo_variable_y_singular(self):
        self.assertEqual(programados.describir_mensaje({
            "activo": False, "minutos_min": 8, "minutos_max": 10,
            "texto": "Hoy jugamos",
        }), "Pausado, entre 8 y 10 minutos: Hoy jugamos")
        self.assertEqual(programados.describir_mensaje({
            "activo": False, "minutos_min": 1, "minutos_max": 1,
            "texto": "Ahora",
        }), "Pausado, cada 1 minuto: Ahora")

    def test_recorta_el_texto_largo(self):
        self.assertEqual(programados.describir_mensaje({
            "minutos_min": 10, "minutos_max": 10, "texto": "x" * 61,
        }), "Pausado, cada 10 minutos: " + "x" * 57 + "...")


class TestAlmacenamiento(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.ruta = Path(self.temporal.name) / "mensajes_programados.json"
        self.addCleanup(self.temporal.cleanup)

    def test_cargar_archivo_inexistente(self):
        self.assertEqual(programados.cargar(self.ruta), [])

    def test_cargar_archivo_vacio(self):
        self.ruta.write_text("", encoding="utf-8")
        self.assertEqual(programados.cargar(self.ruta), [])

    def test_cargar_json_invalido(self):
        self.ruta.write_text("{ roto", encoding="utf-8")
        self.assertEqual(programados.cargar(self.ruta), [])

    def test_cargar_json_que_no_es_lista(self):
        self.ruta.write_text("{}", encoding="utf-8")
        self.assertEqual(programados.cargar(self.ruta), [])

    def test_cargar_filtra_y_completa_elementos(self):
        self.ruta.write_text('[{"texto": "Hola"}, "basura"]', encoding="utf-8")
        self.assertEqual(programados.cargar(self.ruta), [{
            "texto": "Hola", "minutos_min": 10, "minutos_max": 10,
            "activo": False, "proximo": 0.0,
        }])

    def test_cargar_fuerza_los_tipos_de_un_json_editado_a_mano(self):
        # "10" o "true" en el JSON hacían TypeError en el temporizador de la GUI.
        self.ruta.write_text(
            '[{"texto": 5, "minutos_min": "10", "minutos_max": "15.0",'
            ' "activo": "true", "proximo": "0"}]', encoding="utf-8")
        self.assertEqual(programados.cargar(self.ruta), [{
            "texto": "5", "minutos_min": 10, "minutos_max": 15,
            "activo": True, "proximo": 0.0,
        }])

    def test_cargar_repone_el_valor_por_defecto_si_no_se_puede_convertir(self):
        self.ruta.write_text(
            '[{"texto": null, "minutos_min": "muchos", "activo": null, "proximo": []}]',
            encoding="utf-8")
        self.assertEqual(programados.cargar(self.ruta), [{
            "texto": "", "minutos_min": 10, "minutos_max": 10,
            "activo": False, "proximo": 0.0,
        }])

    def test_guardar_y_cargar_conserva_los_mensajes(self):
        mensajes = [{"texto": "Redes", "minutos_min": 10, "minutos_max": 12,
                     "activo": True, "proximo": 600.0}]
        programados.guardar(self.ruta, mensajes)
        self.assertEqual(programados.cargar(self.ruta), mensajes)

    def test_guardar_reemplaza_de_forma_atomica(self):
        self.ruta.write_text("mensaje anterior", encoding="utf-8")
        programados.guardar(self.ruta, [])
        self.assertEqual(programados.cargar(self.ruta), [])
        self.assertEqual(list(self.ruta.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
