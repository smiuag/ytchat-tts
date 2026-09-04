"""Lectura y escritura segura de los JSON que la app guarda junto al exe.

Escribir directamente sobre el archivo (write_text / open "w") lo trunca
antes de volcar el contenido: un cierre o un fallo a mitad de escritura deja
el archivo vacío o cortado (historial perdido, credenciales en blanco o, peor,
el config.json de obs-websocket sin su contraseña). Aquí se escribe a un
temporal al lado y se renombra con os.replace, que en Windows es atómico
dentro del mismo volumen: el archivo viejo se conserva hasta que el nuevo
está completo en disco.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import diagnostico

logger = diagnostico.obtener_logger(__name__)


def escribir_json_atomico(ruta, datos, **json_kwargs) -> None:
    """Escribe `datos` como JSON en `ruta` vía temporal + os.replace.

    Lanza la excepción (OSError, TypeError…) si no se pudo: cada llamador
    decide si es crítico. En ese caso el archivo anterior queda intacto y el
    temporal se borra.
    """
    ruta = Path(ruta)
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    json_kwargs.setdefault("ensure_ascii", False)
    try:
        # Serializar antes de abrir el temporal: un dato no serializable no
        # deja ni siquiera un .tmp a medias.
        texto = json.dumps(datos, **json_kwargs)
        with open(temporal, "w", encoding="utf-8") as archivo:
            archivo.write(texto)
            archivo.write("\n")
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(temporal, ruta)
    except BaseException:
        try:
            os.unlink(temporal)
        except OSError:
            pass
        raise


def leer_json(ruta, predeterminado):
    """Lee un JSON o devuelve `predeterminado` si el archivo falta o está roto.

    Que falte es normal (primer arranque) y no se avisa; que esté corrupto
    sí se registra, porque el usuario perdería datos sin saber por qué.
    """
    ruta = Path(ruta)
    if not ruta.exists():
        return predeterminado
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("No se pudo leer %s (se usa el valor por defecto): %s",
                       ruta.name, exc)
        return predeterminado
