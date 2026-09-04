"""Vigilancia en segundo plano del estado de OBS."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
import time

import diagnostico
from obs_panel import GestorPanelObs

PLAZO_FRESCURA = 12.0
INTERVALO_SONDEO = 5.0


@dataclass(frozen=True)
class EstadoObs:
    transmision: dict | None = None
    grabacion: dict | None = None
    escena: str = ""


class VigilanteObs:
    """Conserva una conexión a OBS y una copia segura para el hilo de GUI."""

    def __init__(self, crear_gestor=GestorPanelObs, reloj=time.monotonic):
        self._crear_gestor = crear_gestor
        self._reloj = reloj
        self._parada = threading.Event()
        self._cerrojo = threading.Lock()
        self._estado = EstadoObs()
        self._ultimo_sondeo = None
        self._hilo = None
        self._gestor = None

    def iniciar(self):
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._parada.clear()
        self._hilo = diagnostico.crear_hilo(self._vigilar, "VigilanteObs")
        self._hilo.start()

    def detener(self):
        self._parada.set()
        hilo = self._hilo
        if hilo is not None:
            hilo.join(1.0)

    def estado(self, ahora=None) -> EstadoObs | None:
        if ahora is None:
            ahora = self._reloj()
        with self._cerrojo:
            if not dato_fresco(self._ultimo_sondeo, ahora):
                return None
            return self._estado

    def _vigilar(self):
        logger = diagnostico.obtener_logger(__name__)
        fallo = False
        gestor = self._crear_gestor()
        self._gestor = gestor
        try:
            while not self._parada.is_set():
                try:
                    if not gestor.conectado:
                        gestor.conectar(self._parada)
                    estado = EstadoObs(gestor.estado_transmision(self._parada),
                                       gestor.estado_grabacion(self._parada),
                                       gestor.escena_al_aire(self._parada))
                    with self._cerrojo:
                        self._estado = estado
                        self._ultimo_sondeo = self._reloj()
                    if fallo:
                        logger.info("OBS volvió a responder")
                        fallo = False
                except Exception:
                    if self._parada.is_set():
                        # Al cerrar la app la petición en vuelo se cancela; ese
                        # aviso se anuncia en voz alta y OBS no tiene la culpa.
                        break
                    if not fallo:
                        logger.warning("OBS no responde; se reintentará")
                        fallo = True
                    try:
                        gestor.cerrar()
                    except Exception:
                        pass
                self._parada.wait(INTERVALO_SONDEO)
        finally:
            try:
                gestor.cerrar()
            except Exception:
                pass
            self._gestor = None


def dato_fresco(ultimo_sondeo: float | None, ahora: float) -> bool:
    """Indica si un sondeo de OBS todavía puede anunciarse."""
    return ultimo_sondeo is not None and ahora - ultimo_sondeo <= PLAZO_FRESCURA
