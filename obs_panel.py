"""Orquestación del panel de chat dentro de una escena de OBS."""

from __future__ import annotations

import obs_disposicion
import obs_cliente


NOMBRE_FUENTE = "Chat YTChat"
TIPO_FUENTE = "browser_source"


class GestorPanelObs:
    def __init__(self, cliente=None, ajustes=None):
        if cliente is None:
            if ajustes is None:
                ajustes = obs_cliente.leer_ajustes()
            cliente = obs_cliente.ClienteObs(ajustes)
        self._cliente = cliente

    def conectar(self, parada=None) -> None:
        self._cliente.conectar(parada)

    def cerrar(self) -> None:
        self._cliente.cerrar()

    @property
    def conectado(self) -> bool:
        return self._cliente.conectado

    def _pedir(self, tipo, datos=None, parada=None):
        respuesta = self._cliente.pedir(tipo, datos, parada)
        return respuesta.get("responseData", {})

    def escenas(self, parada=None) -> tuple:
        datos = self._pedir("GetSceneList", parada=parada)
        return tuple(escena["sceneName"] for escena in datos.get("scenes", ()))

    def escena_al_aire(self, parada=None) -> str:
        datos = self._pedir("GetCurrentProgramScene", parada=parada)
        return datos.get("currentProgramSceneName", "")

    def poner_escena_al_aire(self, escena, parada=None) -> str:
        self._pedir("SetCurrentProgramScene", {"sceneName": escena}, parada)
        return self.escena_al_aire(parada)

    def fuentes_audio(self, parada=None) -> tuple:
        entradas = self._pedir("GetInputList", parada=parada).get("inputs", ())
        fuentes = []
        for entrada in entradas:
            nombre = entrada.get("inputName", "")
            if not nombre:
                continue
            try:
                self.silenciada(nombre, parada)
            except Exception:
                continue
            fuentes.append(nombre)
        return tuple(fuentes)

    def silenciada(self, fuente, parada=None) -> bool:
        datos = self._pedir("GetInputMute", {"inputName": fuente}, parada)
        return bool(datos.get("inputMuted", False))

    def alternar_silencio(self, fuente, parada=None) -> bool:
        datos = self._pedir("ToggleInputMute", {"inputName": fuente}, parada)
        return bool(datos.get("inputMuted", False))

    def estado_transmision(self, parada=None) -> dict:
        datos = self._pedir("GetStreamStatus", parada=parada)
        estado = {clave: datos.get(clave, 0) for clave in (
            "outputActive", "outputDuration", "outputSkippedFrames", "outputTotalFrames")}
        # obs-websocket da outputDuration en milisegundos; el resto de la app
        # (obs_estado.frase_transmision, F2) lo trata en segundos. Sin esta
        # conversión un minuto de directo se anunciaba como «16 h 40 min».
        try:
            estado["outputDuration"] = int(float(estado["outputDuration"]) / 1000)
        except (TypeError, ValueError):
            estado["outputDuration"] = 0
        return estado

    def estado_grabacion(self, parada=None) -> dict:
        datos = self._pedir("GetRecordStatus", parada=parada)
        return {clave: datos.get(clave, False if clave != "outputTimecode" else "")
                for clave in ("outputActive", "outputPaused", "outputTimecode")}

    def alternar_transmision(self, parada=None) -> bool:
        return bool(self._pedir("ToggleStream", parada=parada).get("outputActive", False))

    def alternar_grabacion(self, parada=None) -> bool:
        return bool(self._pedir("ToggleRecord", parada=parada).get("outputActive", False))

    def alternar_pausa_grabacion(self, parada=None) -> bool:
        return bool(self._pedir("ToggleRecordPause", parada=parada).get("outputPaused", False))

    def _elementos(self, escena, parada=None):
        datos = self._pedir("GetSceneItemList", {"sceneName": escena}, parada)
        return list(datos.get("sceneItems", ()))

    def _elemento(self, escena, fuente, parada=None):
        return next((elemento for elemento in self._elementos(escena, parada)
                     if elemento.get("sourceName") == fuente), None)

    def _elemento_obligatorio(self, escena, fuente, parada=None):
        elemento = self._elemento(escena, fuente, parada)
        if elemento is None:
            # La fuente pudo borrarse o renombrarse en OBS desde la última
            # lectura; antes esto acababa en un TypeError sin explicación.
            raise obs_cliente.ObsError(obs_cliente.mensaje_de_fallo_obs("not found"))
        return elemento

    def _elemento_en_grupo(self, escena, fuente, parada=None):
        # GetSceneItemList no baja a los grupos: si el usuario agrupó el panel,
        # sin esta búsqueda se creaba un segundo elemento en la escena.
        for elemento in self._elementos(escena, parada):
            if not elemento.get("isGroup"):
                continue
            datos = self._pedir("GetGroupSceneItemList",
                                {"sceneName": elemento.get("sourceName", "")}, parada)
            hijo = next((hijo for hijo in datos.get("sceneItems", ())
                         if hijo.get("sourceName") == fuente), None)
            if hijo is not None:
                return hijo
        return None

    def asegurar_fuente(self, escena, url, ancho, alto, parada=None) -> int:
        elemento = self._elemento(escena, NOMBRE_FUENTE, parada)
        if elemento is None:
            elemento = self._elemento_en_grupo(escena, NOMBRE_FUENTE, parada)
        if elemento is not None:
            identificador = elemento["sceneItemId"]
        else:
            entradas = self._pedir("GetInputList", parada=parada).get("inputs", ())
            entrada = next((entrada for entrada in entradas
                            if entrada.get("inputName") == NOMBRE_FUENTE), None)
            if entrada is not None and entrada.get("inputKind", TIPO_FUENTE) != TIPO_FUENTE:
                # Reutilizar una fuente ajena con el mismo nombre la rompería
                # al escribirle la URL del panel.
                raise obs_cliente.ObsError(
                    f"Ya existe en OBS una fuente llamada «{NOMBRE_FUENTE}» que no es "
                    "un navegador. Cámbiale el nombre en OBS.")
            if entrada is not None:
                datos = self._pedir(
                    "CreateSceneItem", {"sceneName": escena,
                                        "sourceName": NOMBRE_FUENTE}, parada)
            else:
                datos = self._pedir(
                    "CreateInput", {"sceneName": escena,
                                    "inputName": NOMBRE_FUENTE,
                                    "inputKind": TIPO_FUENTE}, parada)
            identificador = datos.get("sceneItemId")
            elemento = self._elemento(escena, NOMBRE_FUENTE, parada)
            if elemento is not None:
                identificador = elemento["sceneItemId"]

        self._pedir("SetInputSettings", {
            "inputName": NOMBRE_FUENTE,
            "inputSettings": {"url": url, "width": ancho, "height": alto},
        }, parada)
        self._pedir("PressInputPropertiesButton", {
            "inputName": NOMBRE_FUENTE,
            "propertyName": "refreshnocache",
        }, parada)
        self.al_frente(escena, parada)
        elemento = self._elemento(escena, NOMBRE_FUENTE, parada)
        return elemento["sceneItemId"] if elemento is not None else identificador

    def colocar(self, escena, anclaje, parada=None, *, fuente=NOMBRE_FUENTE) -> None:
        lienzo = self._pedir("GetVideoSettings", parada=parada)
        x, y, alineacion = obs_disposicion.coordenadas(
            anclaje, lienzo["baseWidth"], lienzo["baseHeight"])
        self.posicionar(escena, x, y, alineacion, parada, fuente=fuente)

    def transformacion(self, escena, parada=None, *, fuente=NOMBRE_FUENTE) -> dict:
        elemento = self._elemento(escena, fuente, parada)
        if elemento is None:
            return {}
        transformacion = elemento["sceneItemTransform"]
        return {clave: transformacion[clave]
                for clave in ("positionX", "positionY", "alignment")}

    def posicionar(self, escena, x, y, alineacion, parada=None, *, fuente=NOMBRE_FUENTE) -> None:
        elemento = self._elemento_obligatorio(escena, fuente, parada)
        # OBS rechaza boundsWidth y boundsHeight en cero al recibir una transformación.
        transformacion = {"positionX": x, "positionY": y,
                          "alignment": alineacion}
        self._pedir("SetSceneItemTransform", {
            "sceneName": escena, "sceneItemId": elemento["sceneItemId"],
            "sceneItemTransform": transformacion,
        }, parada)

    def mover(self, escena, dx, dy, parada=None, *, fuente=NOMBRE_FUENTE) -> None:
        elemento = self._elemento_obligatorio(escena, fuente, parada)
        transformacion_actual = elemento["sceneItemTransform"]
        transformacion = {
            "positionX": transformacion_actual["positionX"] + dx,
            "positionY": transformacion_actual["positionY"] + dy,
        }
        self._pedir("SetSceneItemTransform", {
            "sceneName": escena, "sceneItemId": elemento["sceneItemId"],
            "sceneItemTransform": transformacion,
        }, parada)

    def redimensionar(self, escena, ancho, alto, parada=None) -> None:
        # El tamaño vive en la entrada, no en el elemento de la escena; si la
        # entrada no existe, OBS ya contesta 600 y se traduce solo.
        ajustes = self._pedir("GetInputSettings", {
            "inputName": NOMBRE_FUENTE,
        }, parada).get("inputSettings", {})
        ajustes = dict(ajustes)
        ajustes.update(width=ancho, height=alto)
        self._pedir("SetInputSettings", {
            "inputName": NOMBRE_FUENTE, "inputSettings": ajustes,
        }, parada)

    def escalar(self, escena, ancho, alto, parada=None, *, fuente=NOMBRE_FUENTE) -> bool:
        elemento = self._elemento_obligatorio(escena, fuente, parada)
        transformacion_actual = elemento["sceneItemTransform"]
        escala = obs_disposicion.escala_para(
            ancho, alto, transformacion_actual.get("sourceWidth", 0),
            transformacion_actual.get("sourceHeight", 0))
        if escala is None:
            return False
        self._pedir("SetSceneItemTransform", {
            "sceneName": escena, "sceneItemId": elemento["sceneItemId"],
            "sceneItemTransform": {"scaleX": escala[0], "scaleY": escala[1]},
        }, parada)
        return True

    def mostrar(self, escena, visible, parada=None, *, fuente=NOMBRE_FUENTE) -> None:
        elemento = self._elemento_obligatorio(escena, fuente, parada)
        self._pedir("SetSceneItemEnabled", {
            "sceneName": escena, "sceneItemId": elemento["sceneItemId"],
            "sceneItemEnabled": visible,
        }, parada)

    def fijar(self, escena, fijada, parada=None, *, fuente=NOMBRE_FUENTE) -> None:
        elemento = self._elemento_obligatorio(escena, fuente, parada)
        self._pedir("SetSceneItemLocked", {
            "sceneName": escena, "sceneItemId": elemento["sceneItemId"],
            "sceneItemLocked": fijada,
        }, parada)

    def al_frente(self, escena, parada=None, *, fuente=NOMBRE_FUENTE) -> None:
        elementos = self._elementos(escena, parada)
        elemento = next((elemento for elemento in elementos
                         if elemento.get("sourceName") == fuente), None)
        if elemento is None:
            return
        indice_mayor = max((elemento.get("sceneItemIndex", 0) for elemento in elementos),
                           default=0)
        if elemento.get("sceneItemIndex", 0) == indice_mayor:
            return
        self._pedir("SetSceneItemIndex", {
            "sceneName": escena, "sceneItemId": elemento["sceneItemId"],
            "sceneItemIndex": indice_mayor,
        }, parada)

    def fuentes(self, escena, parada=None) -> tuple:
        if escena not in self.escenas(parada):
            return ()
        elementos = self._elementos(escena, parada)
        return tuple(elemento.get("sourceName", "") for elemento in sorted(
            elementos, key=lambda elemento: elemento.get("sceneItemIndex", 0), reverse=True))

    def instantanea(self, escena, parada=None, *, fuente=NOMBRE_FUENTE) -> obs_disposicion.SnapshotPanel:
        elementos = self._elementos(escena, parada)
        panel = next((elemento for elemento in elementos
                      if elemento.get("sourceName") == fuente), None)
        al_aire = self.escena_al_aire(parada) == escena
        lienzo = self._pedir("GetVideoSettings", parada=parada)
        conectado = self.conectado
        if panel is None:
            return obs_disposicion.SnapshotPanel(
                conectado=conectado, escena=escena, al_aire=al_aire,
                lienzo_ancho=lienzo.get("baseWidth", 0),
                lienzo_alto=lienzo.get("baseHeight", 0))

        transformacion = panel["sceneItemTransform"]
        rect_panel = obs_disposicion.rectangulo(
            transformacion.get("positionX", 0), transformacion.get("positionY", 0),
            transformacion.get("width", 0), transformacion.get("height", 0),
            transformacion.get("alignment", 0))
        # width/height ya llevan la escala aplicada. El panel se redimensiona
        # escribiendo el tamaño de la entrada (redimensionar), así que el valor
        # editable es sourceWidth/sourceHeight: con width, un panel escalado se
        # encogía a la mitad con cada «Aplicar tamaño». Las demás fuentes se
        # escalan (escalar) y ahí sí manda el tamaño en pantalla.
        if fuente == NOMBRE_FUENTE:
            ancho = transformacion.get("sourceWidth") or rect_panel[2]
            alto = transformacion.get("sourceHeight") or rect_panel[3]
        else:
            ancho, alto = rect_panel[2], rect_panel[3]
        solapes = []
        delante = []
        for elemento in elementos:
            if elemento["sceneItemId"] == panel["sceneItemId"]:
                continue
            transformacion_otro = elemento["sceneItemTransform"]
            rect_otro = obs_disposicion.rectangulo(
                transformacion_otro.get("positionX", 0),
                transformacion_otro.get("positionY", 0),
                transformacion_otro.get("width", 0),
                transformacion_otro.get("height", 0),
                transformacion_otro.get("alignment", 0))
            porcentaje = obs_disposicion.solape(rect_otro, rect_panel)
            if porcentaje:
                solapes.append((elemento.get("sourceName", ""), porcentaje))
                if elemento.get("sceneItemIndex", 0) > panel.get("sceneItemIndex", 0):
                    delante.append((elemento.get("sceneItemIndex", 0),
                                    elemento.get("sourceName", "")))
        solapes.sort(key=lambda pareja: pareja[1], reverse=True)
        tapada_por = max(delante, default=(0, ""))[1]
        visible = panel.get("sceneItemEnabled", True)
        bloqueada = panel.get("sceneItemLocked", False)
        return obs_disposicion.SnapshotPanel(
            conectado=conectado, escena=escena, al_aire=al_aire,
            izquierda=rect_panel[0], arriba=rect_panel[1], ancho=int(ancho),
            alto=int(alto), lienzo_ancho=lienzo.get("baseWidth", 0),
            lienzo_alto=lienzo.get("baseHeight", 0), visible=visible,
            bloqueada=bloqueada, tapada_por=tapada_por, solapes=tuple(solapes),
            fuera=obs_disposicion.fuera_del_lienzo(
                rect_panel, lienzo.get("baseWidth", 0), lienzo.get("baseHeight", 0)))

    def captura_de_escena(self, escena, ruta, parada=None) -> None:
        self._pedir("SaveSourceScreenshot", {
            "sourceName": escena, "imageFormat": "png", "imageFilePath": ruta,
        }, parada)
