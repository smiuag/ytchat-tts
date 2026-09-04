"""Almacén de credenciales de la YouTube Data API (gestionable desde la app).

A diferencia de config.ini, esto NO se edita a mano normalmente: la sección
de Configuración de la aplicación escribe aquí la API key, el cliente OAuth y
el token de sesión. Es un JSON sencillo guardado junto al ejecutable.

El archivo `credenciales.json` está en .gitignore: contiene secretos del
usuario y nunca debe subirse al repositorio.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import archivos
import config
import diagnostico

logger = diagnostico.obtener_logger(__name__)

NOMBRE_ARCHIVO = "credenciales.json"

# guardar_campo es leer-modificar-escribir y lo llaman hilos de trabajo (el
# refresco del token OAuth, la GUI): sin candado, dos guardados cruzados
# pisarían el campo del otro. RLock porque guardar_campo llama a guardar.
_lock = threading.RLock()

# Estructura por defecto. `token` guarda el JSON de las credenciales OAuth
# (lo serializa google-auth con Credentials.to_json()); None = sin sesión.
_DEFECTO = {
    "api_key": "",
    "oauth_client_id": "",
    "oauth_client_secret": "",
    "token": None,
}


def ruta() -> Path:
    return config.app_dir() / NOMBRE_ARCHIVO


def cargar() -> dict:
    """Devuelve siempre un dict completo, aunque el archivo falte o esté roto."""
    datos = dict(_DEFECTO)
    with _lock:
        bruto = archivos.leer_json(ruta(), None)
    if isinstance(bruto, dict):
        for k in _DEFECTO:
            if k in bruto:
                datos[k] = bruto[k]
    return datos


def guardar(datos: dict) -> bool:
    """Escribe el dict completo. Devuelve True si se guardó."""
    limpio = {k: datos.get(k, _DEFECTO[k]) for k in _DEFECTO}
    try:
        with _lock:
            archivos.escribir_json_atomico(ruta(), limpio, indent=2)
        return True
    except Exception as exc:
        logger.error("No se pudo guardar %s: %s", NOMBRE_ARCHIVO, exc)
        return False


def guardar_campo(clave: str, valor) -> bool:
    """Actualiza una sola clave preservando el resto."""
    if clave not in _DEFECTO:
        logger.warning("credenciales: clave desconocida %r", clave)
        return False
    with _lock:
        datos = cargar()
        datos[clave] = valor
        return guardar(datos)


def hay_lectura(datos: dict | None = None) -> bool:
    """¿Hay API key para leer comentarios?"""
    d = datos if datos is not None else cargar()
    return bool((d.get("api_key") or "").strip())


def hay_oauth_configurado(datos: dict | None = None) -> bool:
    """¿Están puestos el client id y el secret del OAuth?"""
    d = datos if datos is not None else cargar()
    return bool((d.get("oauth_client_id") or "").strip()
                and (d.get("oauth_client_secret") or "").strip())


def hay_sesion(datos: dict | None = None) -> bool:
    """¿Hay un token OAuth guardado (sesión iniciada)?"""
    d = datos if datos is not None else cargar()
    return bool(d.get("token"))


def cerrar_sesion() -> bool:
    """Borra solo el token, conservando API key y cliente OAuth."""
    return guardar_campo("token", None)
