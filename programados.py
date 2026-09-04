"""Lógica de mensajes programados, sin acceso a la interfaz ni a la red."""

from __future__ import annotations

import json
import math
import re

import archivos
from redaccion import MAXIMO_CHAT as MAX_CARACTERES


MINUTOS_MINIMOS = 5  # Piso de prudencia contra el antispam.
SEGUNDOS_ENTRE_ENVIOS = 60  # Si dos vencen a la vez, el segundo espera.

VALORES_POR_DEFECTO = {
    "texto": "",
    "minutos_min": 10,
    "minutos_max": 10,
    "activo": False,
    "proximo": 0.0,
}

_URL_RE = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)


def validar_mensaje(texto: str, minutos_min: int, minutos_max: int) -> tuple[str, str]:
    """Valida un mensaje y devuelve un error y un aviso, en ese orden."""
    if not texto.strip():
        return "El mensaje no puede estar vacío.", ""
    if len(texto) > MAX_CARACTERES:
        return (f"El mensaje tiene {len(texto)} caracteres y el máximo son "
                f"{MAX_CARACTERES}."), ""
    if minutos_min < MINUTOS_MINIMOS:
        return "El intervalo mínimo son 5 minutos.", ""
    if minutos_max < minutos_min:
        return "El intervalo máximo no puede ser menor que el mínimo.", ""
    aviso = ""
    # Se avisan las formas habituales de URL; YouTube puede bloquearlas.
    if _URL_RE.search(texto):
        aviso = ("YouTube suele bloquear los enlaces en el chat en vivo. "
                 "Conviene poner el nombre de usuario en vez de la dirección completa.")
    return "", aviso


def calcular_proximo(minutos_min: int, minutos_max: int,
                     ahora: float, aleatorio) -> float:
    """Calcula el instante del próximo envío usando un azar inyectado."""
    if minutos_min == minutos_max:
        return ahora + minutos_min * 60
    return ahora + aleatorio(minutos_min * 60, minutos_max * 60)


def iniciar_reloj(mensajes: list[dict], ahora: float, aleatorio) -> None:
    """Da cuerda al reloj de los mensajes activos de esta sesión."""
    for mensaje in mensajes:
        if mensaje.get("activo", False):
            mensaje["proximo"] = calcular_proximo(
                mensaje.get("minutos_min", 10),
                mensaje.get("minutos_max", mensaje.get("minutos_min", 10)),
                ahora, aleatorio)


def elegir_envio(mensajes: list[dict], ahora: float,
                 ultimo_envio: float | None) -> dict | None:
    """Devuelve el mensaje activo vencido más antiguo que puede enviarse."""
    if ultimo_envio is not None and ahora - ultimo_envio < SEGUNDOS_ENTRE_ENVIOS:
        return None
    vencidos = [
        mensaje for mensaje in mensajes
        if mensaje.get("activo", False) and mensaje.get("proximo", float("inf")) <= ahora
    ]
    return min(vencidos, key=lambda mensaje: mensaje["proximo"]) if vencidos else None


def describir_mensaje(mensaje: dict) -> str:
    """Devuelve la línea accesible que representa un mensaje."""
    estado = "Activo" if mensaje.get("activo", False) else "Pausado"
    minimo = mensaje.get("minutos_min", 10)
    maximo = mensaje.get("minutos_max", minimo)
    if minimo == maximo:
        intervalo = f"cada {minimo} {_unidad_minutos(minimo)}"
    else:
        intervalo = f"entre {minimo} y {maximo} minutos"
    texto = str(mensaje.get("texto", ""))
    if len(texto) > 60:
        texto = texto[:57] + "..."
    return f"{estado}, {intervalo}: {texto}"


def _unidad_minutos(valor: int) -> str:
    return "minuto" if valor == 1 else "minutos"


def describir_proximo(mensajes: list[dict], ahora: float) -> str:
    """Describe cuándo vence el siguiente mensaje activo."""
    activos = [
        mensaje for mensaje in mensajes
        if mensaje.get("activo", False) and "proximo" in mensaje
    ]
    if not activos:
        return ""
    # proximo <= 0 es el valor recién cargado del disco (aún sin cuerda): no
    # es «en menos de un minuto», es que todavía no se ha programado.
    con_hora = [mensaje["proximo"] for mensaje in activos if mensaje["proximo"] > 0]
    if not con_hora:
        return "Próximo mensaje programado: pendiente de programar"
    restante = min(con_hora) - ahora
    if restante < 60:
        return "Próximo mensaje programado en menos de un minuto"
    minutos = math.ceil(restante / 60)
    unidad = "minuto" if minutos == 1 else "minutos"
    return f"Próximo mensaje programado en {minutos} {unidad}"


def _a_bool(valor) -> bool:
    if isinstance(valor, str):
        return valor.strip().lower() in ("true", "1", "yes", "si", "sí", "on")
    return bool(valor)


def _normalizar_mensaje(mensaje: dict) -> dict:
    resultado = dict(VALORES_POR_DEFECTO)
    resultado.update(mensaje)
    # Un JSON editado a mano puede traer "10" o "true": se fuerzan los tipos
    # de los campos conocidos para que el temporizador de la GUI no reviente
    # con un TypeError al comparar u operar con ellos.
    for clave, defecto in VALORES_POR_DEFECTO.items():
        valor = resultado[clave]
        try:
            if isinstance(defecto, bool):
                resultado[clave] = _a_bool(valor)
            elif isinstance(defecto, int):
                resultado[clave] = int(float(valor))   # admite "15" y "15.0"
            elif isinstance(defecto, float):
                resultado[clave] = float(valor)
            else:
                resultado[clave] = "" if valor is None else str(valor)
        except (TypeError, ValueError):
            resultado[clave] = defecto
    return resultado


def cargar(ruta) -> list[dict]:
    """Carga mensajes y devuelve una lista segura aunque el archivo esté roto."""
    try:
        with open(ruta, "r", encoding="utf-8") as archivo:
            datos = json.load(archivo)
        if not isinstance(datos, list):
            return []
        return [_normalizar_mensaje(mensaje) for mensaje in datos
                if isinstance(mensaje, dict)]
    except Exception:
        return []


def guardar(ruta, mensajes: list[dict]) -> None:
    """Guarda mensajes mediante un temporal para conservar el archivo anterior."""
    archivos.escribir_json_atomico(ruta, mensajes, indent=2)
