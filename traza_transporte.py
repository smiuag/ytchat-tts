"""Formato de trazas del transporte del reproductor."""


def _booleano(valor) -> str:
    return "si" if valor else "no"


def _booleano_vlc(valor) -> str:
    if valor is None:
        return "desconocido"
    return _booleano(valor)


def traza_transporte(estado, accion, hay_medio, intencion_reproducir,
                     puede_pausar, es_buscable) -> str:
    """Arma la traza de una decisión de reproducir o pausar."""
    return (
        f"TRANSPORTE estado={estado} accion={accion} medio={_booleano(hay_medio)} "
        f"intencion={_booleano(intencion_reproducir)} "
        f"puede_pausar={_booleano_vlc(puede_pausar)} "
        f"buscable={_booleano_vlc(es_buscable)}"
    )


def traza_salto(origen, pendiente, posicion, delta_ms, destino, duracion) -> str:
    """Arma la traza de un salto sobre la línea de tiempo."""
    pendiente = "ninguno" if pendiente is None else pendiente
    return (f"SALTO origen={origen} pendiente={pendiente} pos={posicion} "
            f"delta={delta_ms} destino={destino} dur={duracion}")


def traza_sin_barra(origen, duracion) -> str:
    """Arma la traza de un salto sin duración disponible."""
    return f"SALTO_SIN_BARRA origen={origen} dur={duracion}"


def topologia_medio(es_local=False, tiene_esclavo=False, es_flujo=False,
                    usa_relevo=False) -> str:
    """Etiqueta de topología sin datos sensibles."""
    if es_flujo:
        return "flujo"
    if usa_relevo:
        return "relevo"
    if es_local:
        return "local"
    if tiene_esclavo:
        return "dividida"
    return "unica"


def traza_busqueda_orden(topologia, estado, confirmada, destino, muestra, edad_ms) -> str:
    """Traza pura de una orden de búsqueda."""
    return (
        f"BUSQUEDA_ORDEN topologia={topologia} estado={estado} "
        f"confirmada={confirmada} destino={destino} muestra={muestra} edad={int(edad_ms)}"
    )


def traza_busqueda_muestra(topologia, es_directo, estado, confirmada, destino,
                           muestra, duracion, candidato, edad_ms) -> str:
    """Traza pura de una muestra mientras la búsqueda está pendiente."""
    cand = "ninguno" if candidato is None else str(int(candidato))
    return (
        f"BUSQUEDA_MUESTRA topologia={topologia} es_directo={_booleano(es_directo)} "
        f"estado={estado} confirmada={confirmada} destino={destino} muestra={muestra} "
        f"dur={duracion} candidato={cand} edad={int(edad_ms)}"
    )


def traza_busqueda_desenlace(topologia, estado, confirmada, destino, muestra, edad_ms,
                             resultado) -> str:
    """Traza pura de un desenlace de búsqueda."""
    return (
        f"BUSQUEDA_{resultado.upper()} topologia={topologia} estado={estado} "
        f"confirmada={confirmada} destino={destino} muestra={muestra} edad={int(edad_ms)}"
    )


def traza_inicio_muestra(topologia, es_directo, estado, primera, muestra) -> str:
    """Traza pura de una muestra mientras el inicio está pendiente."""
    prim = "ninguna" if primera is None else str(int(primera))
    if isinstance(muestra, int) and muestra >= 0:
        muest = str(int(muestra))
    else:
        muest = "ninguna"
    return (
        f"INICIO_MUESTRA topologia={topologia} es_directo={_booleano(es_directo)} "
        f"estado={estado} primera={prim} muestra={muest}"
    )
