"""Decisiones puras para la posición y el transporte del reproductor."""

from dataclasses import dataclass

TOLERANCIA_DESTINO_MS = 1500
TOLERANCIA_ATRAS_MS = 2000
CADUCIDAD_DESTINO_MS = 5000
TOPE_BUSQUEDA_MS = 8000
PROGRESO_MINIMO_MS = 250
PLAZO_TRANSPORTE_MS = 8000

_ESTADOS_FINALES = {"ended", "stopped", "error", "nothingspecial"}


@dataclass(frozen=True, slots=True)
class OrdenTransporte:
    """Orden inmutable de transporte."""

    intencion_reproducir: bool
    instante: float


def evaluar_transporte(orden, estado, ahora) -> str:
    """Devuelve pendiente, confirmada o fallida para una orden de transporte."""
    if orden is None:
        return "fallida"
    estado_norm = (estado or "").lower()
    if estado_norm in _ESTADOS_FINALES:
        return "fallida"
    if estado_norm == "playing" and bool(orden.intencion_reproducir):
        return "confirmada"
    if estado_norm == "paused" and not bool(orden.intencion_reproducir):
        return "confirmada"
    try:
        edad_ms = (float(ahora) - float(orden.instante)) * 1000
    except Exception:
        edad_ms = 0
    if edad_ms >= PLAZO_TRANSPORTE_MS:
        return "fallida"
    return "pendiente"


def busqueda_permitida(es_directo, es_local, tiene_esclavo, usa_relevo=False) -> bool:
    """Indica si la topología actual admite búsquedas.

    Un VOD remoto dividido no admite búsquedas. Un archivo local sí.
    Una fuente única conserva el comportamiento actual. El directo
    no se deshabilita: solo pierde la confirmación especial de final.
    Un directo por el relevo de ffmpeg (vídeo+audio ya remuxados en un
    único flujo, ver relevo_ffmpeg.py) tampoco admite búsquedas: para VLC
    es un flujo en vivo sin ventana de retroceso (comprobado: is_seekable=0,
    length=0), así que set_time() no hace nada y sin este aviso la app
    dice «Moviendo a...» y recién a los 8 s «No se pudo mover el vídeo».
    """
    if usa_relevo:
        return False
    if es_directo:
        return True
    if es_local:
        return True
    if tiene_esclavo:
        return False
    return True


def destino_acumulado(destino_pendiente, posicion_actual, delta_ms,
                      duracion_ms) -> int:
    base = posicion_actual if destino_pendiente is None else destino_pendiente
    destino = min(max(0, base + delta_ms), duracion_ms)
    if delta_ms > 0 and destino < base:
        return base
    return destino


def destino_alcanzado(destino_pendiente, posicion_actual,
                      tolerancia_ms) -> bool:
    return (destino_pendiente is None
            or abs(posicion_actual - destino_pendiente) <= tolerancia_ms)


def posicion_a_mostrar(destino_pendiente, posicion_actual) -> int:
    return posicion_actual if destino_pendiente is None else destino_pendiente


def posicion_confiable(ultima_confiable, lectura, tolerancia_ms) -> int:
    if ultima_confiable is not None and lectura < ultima_confiable - tolerancia_ms:
        return ultima_confiable
    return lectura


def destino_vigente(destino_pendiente, edad_ms, tope_ms):
    if destino_pendiente is None or edad_ms > tope_ms:
        return None
    return destino_pendiente


def transporte_confirmado(estado, intencion_reproducir) -> bool:
    if intencion_reproducir:
        return estado == "playing"
    return estado == "paused"


def accion_play_pausa(estado, hay_medio, intencion_reproducir,
                       orden_pendiente=False) -> str:
    if not hay_medio:
        return "cargar"
    if estado in {"ended", "stopped", "error", "nothingspecial"}:
        return "cargar"
    if orden_pendiente and not transporte_confirmado(estado, intencion_reproducir):
        return "en_curso"
    if estado == "playing":
        return "pausar"
    if estado == "paused":
        return "reanudar"
    return "pausar" if intencion_reproducir else "reanudar"


class EstadoBusqueda:
    """Tres conceptos separados para un salto fiable."""

    def __init__(self, confirmada=0):
        self.confirmada = int(confirmada) if confirmada is not None else 0
        self.destino = None
        self.candidato = None
        self.marca_destino = None
        self._gen = 0
        self._ultima_valida = None

    @property
    def pendiente(self) -> bool:
        return self.destino is not None

    @property
    def destino_pendiente(self):
        return self.destino

    @property
    def posicion_confirmada(self) -> int:
        return self.confirmada

    @property
    def candidato_valor(self):
        return self.candidato

    @property
    def generacion(self) -> int:
        return self._gen

    def solicitar(self, destino, ahora) -> int:
        self.destino = int(destino)
        self.candidato = None
        self.marca_destino = float(ahora)
        self._ultima_valida = None
        self._gen += 1
        return self._gen

    def cancelar(self) -> int:
        self._gen += 1
        self.destino = None
        self.candidato = None
        self.marca_destino = None
        self._ultima_valida = None
        return self._gen

    def edad_ms(self, ahora) -> float:
        if self.marca_destino is None:
            return 0
        return (float(ahora) - float(self.marca_destino)) * 1000

    def posicion_a_mostrar(self, lectura_actual) -> int:
        if self.pendiente:
            return self.confirmada
        if lectura_actual is None:
            return self.confirmada
        return int(lectura_actual)

    def observar(self, muestra, duracion, estado, ahora, es_directo=False):
        if self.destino is None:
            if isinstance(muestra, int) and muestra >= 0:
                self.confirmada = int(muestra)
                self._ultima_valida = int(muestra)
            return (None, None)

        estado_norm = (estado or "").lower()

        if self.marca_destino is not None:
            edad = (float(ahora) - float(self.marca_destino)) * 1000
            if edad > TOPE_BUSQUEDA_MS:
                adopcion = None
                if isinstance(muestra, int) and muestra >= 0:
                    adopcion = int(muestra)
                elif self._ultima_valida is not None:
                    adopcion = int(self._ultima_valida)
                self.destino = None
                self.candidato = None
                self.marca_destino = None
                self._ultima_valida = None
                self._gen += 1
                if adopcion is not None:
                    self.confirmada = int(adopcion)
                return ("vencido", adopcion)

        if estado_norm in _ESTADOS_FINALES:
            adopcion = None
            if isinstance(muestra, int) and muestra >= 0:
                adopcion = int(muestra)
            elif self._ultima_valida is not None:
                adopcion = int(self._ultima_valida)
            self.destino = None
            self.candidato = None
            self.marca_destino = None
            self._ultima_valida = None
            self._gen += 1
            if adopcion is not None:
                self.confirmada = int(adopcion)
            return ("fallo", adopcion)

        if not isinstance(muestra, int) or muestra < 0:
            return (None, None)

        if estado_norm != "playing":
            return (None, None)

        if not es_directo and duracion and duracion > 0:
            cerca_dest = abs(int(duracion) - int(self.destino)) <= TOLERANCIA_DESTINO_MS
            cerca_muestra = abs(int(duracion) - int(muestra)) <= TOLERANCIA_DESTINO_MS
            dentro = abs(int(muestra) - int(self.destino)) <= TOLERANCIA_DESTINO_MS
            if cerca_dest and cerca_muestra and dentro:
                self.confirmada = int(muestra)
                self.destino = None
                self.candidato = None
                self.marca_destino = None
                self._ultima_valida = None
                self._gen += 1
                return ("confirmado", int(muestra))

        if abs(int(muestra) - int(self.destino)) > TOLERANCIA_DESTINO_MS:
            self._ultima_valida = int(muestra)
            self.candidato = None
            return (None, None)

        if self.candidato is None:
            self.candidato = int(muestra)
            self._ultima_valida = int(muestra)
            return ("candidato", int(muestra))

        if int(muestra) - int(self.candidato) >= PROGRESO_MINIMO_MS:
            self.confirmada = int(muestra)
            self.destino = None
            self.candidato = None
            self.marca_destino = None
            self._ultima_valida = None
            self._gen += 1
            return ("confirmado", int(muestra))

        self._ultima_valida = int(muestra)
        return (None, None)


class EstadoInicioReproduccion:
    """Inicio real de una carga explícita.

    Deja el estado visible en preparación y solo etiqueta y anuncia
    Reproduciendo después de observar estado reproducible y al menos
    dos muestras válidas con avance de 250 ms o más. El evento Playing
    solo no basta y el cambio interno a caché local no lo repite.
    """

    def __init__(self):
        self._requiere = False
        self._anunciado = False
        self._primera = None
        self._gen = 0

    @property
    def requiere(self) -> bool:
        return bool(self._requiere and not self._anunciado)

    @property
    def anunciado(self) -> bool:
        return bool(self._anunciado)

    @property
    def generacion(self) -> int:
        return self._gen

    @property
    def primera(self):
        return self._primera

    def iniciar(self) -> int:
        self._requiere = True
        self._anunciado = False
        self._primera = None
        self._gen += 1
        return self._gen

    def cancelar(self) -> int:
        self._requiere = False
        self._anunciado = False
        self._primera = None
        self._gen += 1
        return self._gen

    def observar(self, estado, muestra) -> bool:
        if not self._requiere or self._anunciado:
            return False
        estado_norm = (estado or "").lower()
        if estado_norm != "playing":
            self._primera = None
            return False
        if not isinstance(muestra, int) or muestra < 0:
            return False
        muestra = int(muestra)
        if self._primera is None:
            self._primera = muestra
            return False
        if muestra < self._primera:
            self._primera = muestra
            return False
        if muestra - self._primera >= PROGRESO_MINIMO_MS:
            self._anunciado = True
            self._requiere = False
            self._primera = None
            self._gen += 1
            return True
        return False
