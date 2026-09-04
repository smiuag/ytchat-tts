"""Activación segura del servidor websocket de OBS."""

import json
import subprocess

import archivos


NO_TOCAR = "no_tocar"
ACTIVAR = "activar"


def decidir_activacion(obs_en_ejecucion, ajustes):
    """Indica si la configuración de OBS puede modificarse."""
    if ajustes.activo:
        return NO_TOCAR, "El servidor websocket de OBS ya está activado"
    if obs_en_ejecucion:
        return (NO_TOCAR,
                "OBS está abierto. Ciérralo y vuelve a pulsar este botón, porque OBS reescribe su configuración al cerrarse")
    return ACTIVAR, "Se puede activar el servidor websocket de OBS"


def ajustes_con_servidor_activado(ajustes):
    """Devuelve los ajustes sin cambiar nada salvo el servidor websocket."""
    resultado = dict(ajustes)
    resultado["server_enabled"] = True
    return resultado


def obs_esta_en_ejecucion():
    """Comprueba OBS sin abrir una consola que robe el foco."""
    try:
        resultado = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq obs64.exe"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "obs64.exe" in resultado.stdout.lower()


def activar_servidor(ruta):
    """Guarda la activación y devuelve la frase que debe anunciarse."""
    try:
        with open(ruta, "r", encoding="utf-8") as archivo:
            ajustes = json.load(archivo)
        # Es el config.json del propio OBS: abrirlo en "w" lo truncaba antes
        # de volcar y un fallo a mitad dejaba a OBS sin su contraseña.
        archivos.escribir_json_atomico(
            ruta, ajustes_con_servidor_activado(ajustes), indent=2)
    except (OSError, ValueError, TypeError) as exc:
        return f"No se pudo activar el servidor websocket de OBS: {exc}"
    return "El servidor websocket de OBS se activó. Inicia OBS para usarlo"
