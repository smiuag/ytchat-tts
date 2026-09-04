import base64
import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

import obs_cliente


class AjustesObsTest(unittest.TestCase):
    def test_lee_configuracion(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False,
                                         encoding="utf-8") as archivo:
            json.dump({"server_enabled": True, "server_port": 4456,
                       "server_password": "secreto"}, archivo)
            ruta = archivo.name
        try:
            self.assertEqual(obs_cliente.leer_ajustes(ruta),
                             obs_cliente.AjustesObs(True, 4456, "secreto"))
        finally:
            os.unlink(ruta)

    def test_usa_valores_por_defecto_ausentes(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False,
                                         encoding="utf-8") as archivo:
            archivo.write("{}")
            ruta = archivo.name
        try:
            self.assertEqual(obs_cliente.leer_ajustes(ruta), obs_cliente.AjustesObs())
        finally:
            os.unlink(ruta)

    def test_archivo_inexistente_no_revienta(self):
        self.assertEqual(obs_cliente.leer_ajustes("ruta-que-no-existe.json"),
                         obs_cliente.AjustesObs())

    def test_archivo_invalido_no_revienta(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False,
                                         encoding="utf-8") as archivo:
            archivo.write("no es json")
            ruta = archivo.name
        try:
            self.assertEqual(obs_cliente.leer_ajustes(ruta), obs_cliente.AjustesObs())
        finally:
            os.unlink(ruta)


class AutenticacionTest(unittest.TestCase):
    def test_respuesta_auth_hace_las_dos_pasadas(self):
        password, salt, challenge = "clave", "sal", "desafio"
        intermedio = base64.b64encode(
            hashlib.sha256((password + salt).encode()).digest()
        ).decode()
        esperado = base64.b64encode(
            hashlib.sha256((intermedio + challenge).encode()).digest()
        ).decode()
        self.assertEqual(obs_cliente.respuesta_auth(password, salt, challenge), esperado)

    def test_respuesta_auth_acepta_textos_vacios(self):
        resultado = obs_cliente.respuesta_auth("", "", "")
        self.assertIsInstance(resultado, str)
        self.assertEqual(len(resultado), 44)


class MensajesDeFalloTest(unittest.TestCase):
    def test_error_de_obs_conserva_su_texto(self):
        texto = ("No se pudo conectar con OBS. Comprueba que OBS esté abierto y "
                 "que su servidor websocket esté activado.")
        self.assertEqual(obs_cliente.mensaje_de_fallo_obs(obs_cliente.ObsError(texto)), texto)

    def test_traducir_dos_veces_conserva_el_mismo_texto(self):
        una_vez = obs_cliente.mensaje_de_fallo_obs("Connection refused")
        dos_veces = obs_cliente.mensaje_de_fallo_obs(obs_cliente.ObsError(una_vez))
        self.assertEqual(dos_veces, una_vez)

    def test_error_crudo_de_conexion_rechazada(self):
        self.assertEqual(obs_cliente.mensaje_de_fallo_obs("Connection refused"),
                         "No se pudo conectar con OBS. Comprueba que OBS esté abierto y "
                         "que su servidor websocket esté activado.")

    def test_error_crudo_desconocido_conserva_el_generico(self):
        self.assertEqual(obs_cliente.mensaje_de_fallo_obs("fallo extraño"),
                         "OBS no pudo completar la operación. Inténtalo de nuevo.")

    def test_fallo_de_conexion(self):
        self.assertIn("No se pudo conectar", obs_cliente.mensaje_de_fallo_obs("Connection refused"))

    def test_fallo_de_autenticacion(self):
        self.assertEqual(obs_cliente.mensaje_de_fallo_obs("error 4009 unauthorized"),
                         "OBS rechazó la contraseña guardada. Vuelve a conectar para leerla de nuevo.")

    def test_fuente_duplicada(self):
        self.assertEqual(obs_cliente.mensaje_de_fallo_obs("601"),
                         "Ya existe una fuente con ese nombre en OBS.")

    def test_escena_o_fuente_inexistente(self):
        self.assertEqual(obs_cliente.mensaje_de_fallo_obs("No scene"),
                         "OBS no encuentra la escena o la fuente indicada.")

    def test_fallo_desconocido(self):
        self.assertEqual(obs_cliente.mensaje_de_fallo_obs("fallo extraño"),
                         "OBS no pudo completar la operación. Inténtalo de nuevo.")

    def test_motivo_vacio(self):
        self.assertEqual(obs_cliente.mensaje_de_fallo_obs(None),
                         "OBS no pudo completar la operación. Inténtalo de nuevo.")


class TransporteDoble:
    def __init__(self, mensajes):
        self.mensajes = list(mensajes)
        self.enviados = []
        self.cerrado = False

    def send(self, mensaje):
        datos = json.loads(mensaje)
        self.enviados.append(datos)
        if datos.get("op") == 6:
            self.mensajes.append(json.dumps({
                "op": 7,
                "d": {
                    "requestId": datos["d"]["requestId"],
                    "requestStatus": {"result": True},
                    "responseData": {"ok": True},
                },
            }))

    def recv(self, timeout=None):
        if not self.mensajes:
            raise TimeoutError()
        return self.mensajes.pop(0)

    def close(self):
        self.cerrado = True


class TransporteSinRespuesta(TransporteDoble):
    def send(self, mensaje):
        self.enviados.append(json.loads(mensaje))


class ClienteObsTest(unittest.TestCase):
    def cliente(self, transporte, password=""):
        return obs_cliente.ClienteObs(
            obs_cliente.AjustesObs(True, 4455, password),
            lambda uri: transporte,
        )

    def test_conectar_sin_autenticacion(self):
        transporte = TransporteDoble([
            json.dumps({"op": 0, "d": {"rpcVersion": 1}}),
            json.dumps({"op": 2, "d": {}}),
        ])
        cliente = self.cliente(transporte)
        cliente.conectar()
        self.assertTrue(cliente.conectado)
        self.assertEqual(transporte.enviados[0],
                         {"op": 1, "d": {"rpcVersion": 1, "eventSubscriptions": 0}})

    def test_conectar_de_nuevo_cierra_el_transporte_anterior(self):
        def transporte_nuevo():
            return TransporteDoble([
                json.dumps({"op": 0, "d": {"rpcVersion": 1}}),
                json.dumps({"op": 2, "d": {}}),
            ])
        transportes = [transporte_nuevo(), transporte_nuevo()]
        cliente = obs_cliente.ClienteObs(
            obs_cliente.AjustesObs(True, 4455, ""),
            lambda uri: transportes.pop(0))
        cliente.conectar()
        primero = cliente._transporte
        cliente.conectar()
        self.assertTrue(primero.cerrado)
        self.assertIsNot(cliente._transporte, primero)
        self.assertTrue(cliente.conectado)

    def test_obs_cierra_la_conexion_y_el_cliente_deja_de_estar_conectado(self):
        from websockets.exceptions import ConnectionClosed
        transporte = TransporteDoble([])
        transporte.recv = mock.Mock(side_effect=ConnectionClosed(None, None))
        cliente = self.cliente(transporte)
        cliente._transporte = transporte
        with self.assertRaisesRegex(obs_cliente.ObsError, "Se perdió la conexión"):
            cliente.pedir("GetVersion")
        self.assertFalse(cliente.conectado)
        self.assertTrue(transporte.cerrado)

    def test_peticiones_concurrentes_no_se_pisan(self):
        # Sin cerrojo, dos hilos hacían send/recv a la vez sobre el mismo socket.
        class TransporteLento(TransporteDoble):
            def __init__(self):
                super().__init__([])
                self.ocupado = False
                self.solapes = 0

            def send(self, mensaje):
                if self.ocupado:
                    self.solapes += 1
                self.ocupado = True
                time.sleep(0.01)
                super().send(mensaje)

            def recv(self, timeout=None):
                mensaje = super().recv(timeout)
                self.ocupado = False
                return mensaje

        transporte = TransporteLento()
        cliente = self.cliente(transporte)
        cliente._transporte = transporte
        hilos = [threading.Thread(target=cliente.pedir, args=("GetVersion",))
                 for _ in range(4)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(2)
        self.assertEqual(transporte.solapes, 0)
        self.assertEqual(len(transporte.enviados), 4)

    def test_conectar_con_autenticacion(self):
        transporte = TransporteDoble([
            json.dumps({"op": 0, "d": {"rpcVersion": 1,
                                         "authentication": {"salt": "sal",
                                                             "challenge": "reto"}}}),
            json.dumps({"op": 2, "d": {}}),
        ])
        cliente = self.cliente(transporte, "clave")
        cliente.conectar()
        enviado = transporte.enviados[0]["d"]
        self.assertEqual(enviado["rpcVersion"], 1)
        self.assertEqual(enviado["authentication"],
                         obs_cliente.respuesta_auth("clave", "sal", "reto"))

    def test_salta_eventos_y_devuelve_respuesta(self):
        transporte = TransporteDoble([
            json.dumps({"op": 5, "d": {"eventType": "CurrentProgramSceneChanged"}}),
            json.dumps({"op": 7, "d": {"requestId": "otro",
                                         "requestStatus": {"result": True}}}),
        ])
        cliente = self.cliente(transporte)
        cliente._transporte = transporte
        resultado = cliente.pedir("GetVersion", {"campo": 1})
        self.assertEqual(resultado["responseData"], {"ok": True})
        pedido = transporte.enviados[0]
        self.assertEqual(pedido["d"]["requestType"], "GetVersion")
        self.assertEqual(pedido["d"]["requestData"], {"campo": 1})

    def test_cerrar_libera_el_transporte(self):
        transporte = TransporteDoble([])
        cliente = self.cliente(transporte)
        cliente._transporte = transporte
        cliente.cerrar()
        self.assertFalse(cliente.conectado)
        self.assertTrue(transporte.cerrado)

    def test_pedir_traduce_error_de_obs(self):
        transporte = TransporteDoble([])
        cliente = self.cliente(transporte)
        cliente._transporte = transporte
        transporte.recv = lambda timeout=None: json.dumps({
            "op": 7,
            "d": {"requestId": transporte.enviados[0]["d"]["requestId"],
                  "requestStatus": {"result": False, "code": 601,
                                     "comment": "A source already exists"}},
        })
        with self.assertRaisesRegex(obs_cliente.ObsError,
                                    "Ya existe una fuente"):
            cliente.pedir("CreateInput")

    def test_pedir_sin_conexion_falla(self):
        with self.assertRaisesRegex(obs_cliente.ObsError, "no pudo completar"):
            self.cliente(TransporteDoble([])).pedir("GetVersion")


class CancelacionYTiempoTest(unittest.TestCase):
    def cliente_sin_respuesta(self):
        transporte = TransporteSinRespuesta([])
        cliente = obs_cliente.ClienteObs(
            obs_cliente.AjustesObs(True, 4455, ""), lambda uri: transporte
        )
        cliente._transporte = transporte
        return cliente

    def test_pedir_se_cancela_mientras_recv_espera(self):
        cliente = self.cliente_sin_respuesta()
        parada = threading.Event()
        resultado = []

        def ejecutar():
            try:
                cliente.pedir("GetVersion", parada=parada)
            except obs_cliente.ObsError as error:
                resultado.append(str(error))

        hilo = threading.Thread(target=ejecutar)
        hilo.start()
        parada.set()
        hilo.join(1.5)
        self.assertFalse(hilo.is_alive())
        self.assertEqual(resultado, ["Operación cancelada."])

    def test_pedir_respeta_el_tiempo_total(self):
        cliente = self.cliente_sin_respuesta()
        original = cliente._TIEMPO_LIMITE
        cliente._TIEMPO_LIMITE = 0.02
        try:
            with self.assertRaisesRegex(obs_cliente.ObsError, "No se pudo conectar"):
                cliente.pedir("GetVersion")
        finally:
            cliente._TIEMPO_LIMITE = original
