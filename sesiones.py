"""Estado puro del ciclo de vida de las sesiones de captura."""

from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class Sesion:
    gen: int
    parada: threading.Event


class RegistroSesiones:
    """Lleva cuál es la sesión de captura vigente."""

    def __init__(self):
        self._vigente = None
        self._gen = 0

    def abrir(self) -> Sesion:
        """Abre una sesión nueva y para la anterior.

        El 21/08/2026 hubo dos hilos Chat vivos durante siete minutos y medio.
        El anterior seguía pidiendo el chat porque nadie puso su evento de parada.
        """
        if self._vigente is not None:
            self._vigente.parada.set()
        self._gen += 1
        sesion = Sesion(self._gen, threading.Event())
        self._vigente = sesion
        return sesion

    def cerrar(self) -> bool:
        """Para la sesión vigente y dice si había alguna sin parar."""
        if self._vigente is None or self._vigente.parada.is_set():
            return False
        self._vigente.parada.set()
        return True

    def vigente(self, gen: int) -> bool:
        """Indica si ``gen`` sigue siendo el de la sesión activa y sin parar.

        Una sesión cerrada con ``cerrar()`` deja de ser vigente: si no, el
        hilo Chat que seguía en yt-dlp tras desconectar pasaba el guard y
        aplicaba título, historial y «conectado» de un vídeo ya cancelado.
        """
        return (self._vigente is not None and self._vigente.gen == gen
                and not self._vigente.parada.is_set())
