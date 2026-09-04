"""Frases del estado y las acciones de transmisión de OBS."""

from estado_sesion import _duracion


def frase_transmision(activa, segundos, perdidos, totales) -> str:
    """Describe el estado de la transmisión sin ruido innecesario."""
    if not activa:
        return "No estás transmitiendo"
    frase = f"Transmitiendo desde hace {_duracion(int(segundos))}"
    if perdidos:
        # El total da la medida: 4 fotogramas de 100 es un problema; de
        # 100 000, no.
        de_cuantos = f" de {int(totales)}" if totales else ""
        frase += f", {int(perdidos)}{de_cuantos} fotogramas perdidos"
    return frase


def frase_grabacion(activa, en_pausa, codigo_tiempo) -> str:
    """Describe el estado de la grabación con el tiempo útil de OBS."""
    if not activa:
        return "No estás grabando"
    tiempo = str(codigo_tiempo).split(".", 1)[0]
    return (f"Grabación en pausa, {tiempo}" if en_pausa
            else f"Grabando, {tiempo}")


def frase_escena_al_aire(escena) -> str:
    """Describe la escena que OBS está mostrando al público."""
    return f"Al aire: {escena}" if escena else "No se pudo saber que escena está al aire"


def frase_resultado(accion) -> str:
    """Traduce una acción de OBS a su confirmación audible."""
    return {
        "transmision_iniciada": "Transmisión iniciada",
        "transmision_detenida": "Transmisión detenida",
        "grabacion_iniciada": "Grabación iniciada",
        "grabacion_detenida": "Grabación detenida",
        "grabacion_en_pausa": "Grabación en pausa",
        "grabacion_reanudada": "Grabación reanudada",
        "escena_cambiada": "Escena puesta al aire",
    }[accion]
