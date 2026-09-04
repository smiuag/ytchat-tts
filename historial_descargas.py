"""Historial persistente de las descargas terminadas."""

from __future__ import annotations

import logging
from pathlib import Path

import archivos
import diagnostico

logger = diagnostico.obtener_logger(__name__)

TOPE_ENTRADAS = 200


def cargar(ruta: Path) -> list[dict]:
    """Lee el historial o devuelve una lista vacía si no se puede usar."""
    datos = archivos.leer_json(ruta, [])
    if not isinstance(datos, list):
        return []
    return [e for e in datos if isinstance(e, dict)]


def guardar(ruta: Path, entradas: list[dict]) -> None:
    """Guarda el historial sin impedir las descargas si falla el disco."""
    try:
        archivos.escribir_json_atomico(ruta, entradas, indent=1)
    except Exception as exc:
        logger.debug("guardar historial de descargas: %s", exc)


def agregar(entradas: list[dict], entrada: dict,
            tope: int = TOPE_ENTRADAS) -> list[dict]:
    """Devuelve una lista nueva con la entrada reciente al principio."""
    return ([dict(entrada)] + list(entradas))[:tope]


def formatear(entrada: dict) -> tuple[str, str, str]:
    """Devuelve las celdas Nombre, Fecha y Estado de una entrada."""
    return (str(entrada.get("nombre") or ""),
            str(entrada.get("fecha") or ""),
            str(entrada.get("estado") or ""))
