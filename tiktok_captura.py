"""Captura del chat de TikTok LIVE (fase 1: solo lectura, sin login).

Usa la librería no oficial TikTokLive (el «pytchat de TikTok»): se conecta a
cualquier directo público con el @usuario del streamer y entrega comentarios,
regalos y suscripciones en tiempo real. La firma de la conexión pasa por el
servidor de Euler Stream (tier gratuito, de sobra para uso personal). No hay
API oficial de TikTok para esto; los riesgos y la decisión de no implementar
escritura/moderación están en INFORME_TIKTOK.md.

Diseño espejo de la captura de YouTube en main.py:
  - `usuario_de_url()` es lógica pura (testeable sin la librería).
  - `capturar_con_reconexion()` bloquea en un hilo propio y reporta por
    callbacks: `on_info(dict)` al conectar (título, espectadores, URL HLS que
    reproduce libVLC tal cual), `on_evento(...)` por cada mensaje y
    `on_estado(tipo, texto)` para la GUI. El filtrado, el TTS y la cola los
    decide quien llama (main), igual que con pytchat.
  - Todo degrada tras guardas: sin TikTokLive instalado, `disponible()` es
    False y la app avisa sin romperse.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import re
import sys

import diagnostico
from config import TIPO_TEXTO, TIPO_SUPERCHAT, TIPO_MIEMBRO, TIPO_ENTRADA

logger = diagnostico.obtener_logger(__name__)

# tiktok.com/@usuario[/live]. Los usuarios de TikTok llevan letras, números,
# guion bajo y punto. No se aceptan "@usuario" sueltos (chocarían con los
# handles de YouTube); hace falta la URL con dominio.
_URL_RE = re.compile(
    r"(?<![\w.-])(?:https?://)?(?:(?:www|m)\.)?tiktok\.com/@([\w.]+)(?:/live)?(?:[/?#]|$)",
    re.IGNORECASE)


def usuario_de_url(entrada: str) -> str:
    """@usuario si la entrada es una URL de TikTok; cadena vacía si no lo es."""
    m = _URL_RE.search((entrada or "").strip())
    return m.group(1) if m else ""


def _parchear_extended_user() -> None:
    """Arregla un choque entre TikTokLive 6.6.5 y betterproto 2.0.0b7.

    `ExtendedUser.from_user` hace `ExtendedUser(**user.to_pydict())`, y en esta
    betterproto `to_pydict()` devuelve claves camelCase (p. ej. «nickName») que
    el constructor no acepta → lanza TypeError (que el fallback de la librería
    NO captura, solo AttributeError). Resultado: leer `evento.user` revienta y se
    pierden comentarios/regalos según qué campos traiga cada usuario.

    Lo reemplazamos por una copia campo a campo en snake_case (lo que la propia
    librería ya hace como respaldo). Idempotente y con guardas: si la librería
    cambia, no rompe nada.
    """
    try:
        from TikTokLive.proto.custom_proto import ExtendedUser
    except Exception:
        return
    if getattr(ExtendedUser, "_from_user_parcheado", False):
        return

    def _from_user(cls, user, **kwargs):
        if isinstance(user, cls):
            return user
        datos = {}
        for campo in user.__class__.__dataclass_fields__:
            try:
                datos[campo] = getattr(user, campo)
            except AttributeError as exc:
                bajo = f"_{campo}"
                datos[campo] = (getattr(user, bajo, None)
                                if "is set to None" in str(exc) else None)
        return cls(**datos)

    try:
        ExtendedUser.from_user = classmethod(_from_user)
        ExtendedUser._from_user_parcheado = True
    except Exception as exc:
        logger.debug("no se pudo parchear ExtendedUser: %s", exc)


def disponible() -> bool:
    """¿Está instalada TikTokLive? Sin importarla, para no frenar el arranque."""
    if getattr(sys, "frozen", False):
        base = os.path.join(os.path.dirname(sys.executable), "_internal", "TikTokLive")
        return os.path.isdir(base)
    try:
        return importlib.util.find_spec("TikTokLive") is not None
    except Exception:
        return False


# ── Sesión de captura ─────────────────────────────────────────────────────────

def _mejor_flujo(stream: dict) -> str:
    """URL de vídeo reproducible del directo. Se PREFIERE el FLV: el HLS que da
    TikTok (`hls_pull_url`) suele no responder (timeout) en el reproductor,
    mientras que el FLV sobre HTTP va directo y trae audio. HD mejor que SD; si
    no hay FLV, se cae al HLS o al RTMP como último recurso."""
    flv = stream.get("flv_pull_url") or {}
    if isinstance(flv, dict):
        for clave in ("FULL_HD1", "ORIGION", "HD1", "SD2", "SD1"):
            if flv.get(clave):
                return flv[clave].strip()
        for v in flv.values():          # cualquier calidad presente
            if v:
                return str(v).strip()
    return (stream.get("hls_pull_url") or stream.get("rtmp_pull_url") or "").strip()


def _g(obj, nombre_attr) -> str:
    """getattr a prueba de betterproto: sus alias no siempre existen y pueden
    lanzar en vez de devolver el defecto; devolvemos "" ante cualquier fallo."""
    try:    return str(getattr(obj, nombre_attr, "") or "")
    except Exception: return ""


def autor_de_evento(evento) -> tuple[str, str]:
    """(nombre, id) del autor de un evento de TikTok, sin usar el wrapper
    `.user` cuando se puede (crashea con betterproto 2.0.0b7).

    En eventos reales el usuario llega como `User` plano: el nombre está en el
    campo REAL `nick_name`, no en el alias `nickname` (que es de ExtendedUser).
    Probamos ambos y varios respaldos. Para comentarios está `user_info` (proto
    crudo); regalos/suscripciones caen a `.user` (ya sin crash por el parche).
    Nunca lanza: mejor «Usuario» que perder el evento.
    """
    u = getattr(evento, "user_info", None)
    if u is None:
        try:    u = evento.user
        except Exception as exc:
            logger.debug("autor: no se pudo leer user: %s", exc)
            u = None
    if u is None:
        return "Usuario", ""
    nombre = (_g(u, "nick_name") or _g(u, "nickname") or _g(u, "unique_id")
              or _g(u, "username") or _g(u, "display_id") or "Usuario").strip()
    canal_id = (_g(u, "id") or _g(u, "unique_id") or _g(u, "username"))
    return (nombre or "Usuario"), canal_id


def _info_de_sala(client) -> dict:
    """Metadatos de la sala en el formato del panel de información + la URL del
    flujo de vídeo del directo (clave interna `_url_flujo`, la consume el
    reproductor)."""
    info = client.room_info or {}
    stream = info.get("stream_url") or {}
    owner = info.get("owner") or {}
    return {
        "titulo":      (info.get("title") or "").strip(),
        "canal":       (owner.get("nickname") or "").strip(),
        "vistas":      info.get("user_count"),   # espectadores actuales
        "en_vivo":     True,
        "_url_flujo":  _mejor_flujo(stream),
    }


async def _vigilar_parada(client, parada) -> None:
    """Convierte el Event de parada (mundo de hilos) en un disconnect (asyncio)."""
    try:
        while not parada.is_set():
            await asyncio.sleep(0.3)
        await client.disconnect()
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.debug("vigilar_parada: %s", exc)


def _sesion(usuario, parada, on_evento, on_estado, on_info, on_espectadores,
            anunciar_entradas=False):
    """Una conexión completa (bloquea hasta desconectar). Devuelve la excepción
    de conexión si la hubo, o None si terminó con normalidad."""
    _parchear_extended_user()   # antes de tocar ningún evento (ver la función)
    from TikTokLive import TikTokLiveClient
    from TikTokLive.events import (ConnectEvent, CommentEvent, GiftEvent,
                                   SubscribeEvent, DisconnectEvent, LiveEndEvent,
                                   RoomUserSeqEvent, JoinEvent)

    client = TikTokLiveClient(unique_id=usuario)
    error: list = [None]
    _autor = autor_de_evento

    @client.on(ConnectEvent)
    async def _on_connect(evento):
        try:
            if on_info:
                on_info(_info_de_sala(client))
        except Exception as exc:
            logger.debug("info de sala: %s", exc)
        if on_estado:
            on_estado("conectado", "Conectado al directo de TikTok.")

    @client.on(CommentEvent)
    async def _on_comment(evento):
        autor, canal_id = _autor(evento)
        on_evento(autor, (evento.comment or "").strip(), TIPO_TEXTO, "", canal_id)

    @client.on(GiftEvent)
    async def _on_gift(evento):
        # Los regalos «en racha» disparan un evento por repetición: solo se
        # anuncia el final de la racha, con el total, para no inundar el TTS.
        if getattr(evento, "streaking", False):
            return
        autor, canal_id = _autor(evento)
        gift = getattr(evento, "gift", None)
        nombre = (getattr(gift, "name", "") or "regalo").strip()
        diamantes = int(getattr(gift, "diamond_count", 0) or 0)
        repes = max(1, int(getattr(evento, "repeat_count", 1) or 1))
        total = diamantes * repes
        detalle = f"{nombre} x{repes}" if repes > 1 else nombre
        monto = f"{total} diamantes" if total else ""
        on_evento(autor, detalle, TIPO_SUPERCHAT, monto, canal_id)

    @client.on(SubscribeEvent)
    async def _on_subscribe(evento):
        autor, canal_id = _autor(evento)
        on_evento(autor, "", TIPO_MIEMBRO, "", canal_id)

    if anunciar_entradas:
        # Quién entra al directo. Solo si el usuario lo pidió: en directos
        # grandes son constantes y saturarían el TTS.
        @client.on(JoinEvent)
        async def _on_join(evento):
            autor, canal_id = _autor(evento)
            on_evento(autor, "", TIPO_ENTRADA, "", canal_id)

    @client.on(RoomUserSeqEvent)
    async def _on_user_seq(evento):
        # Conteo de espectadores EN VIVO (se actualiza cada pocos segundos).
        if not on_espectadores:
            return
        n = getattr(evento, "total_user", None)
        if n is None:
            n = getattr(evento, "m_total", None)
        try:
            if n is not None:
                on_espectadores(int(n))
        except (TypeError, ValueError):
            pass

    @client.on(LiveEndEvent)
    async def _on_live_end(evento):
        # El directo acabó: desconectamos para que connect() retorne y sea el
        # bucle (capturar_con_reconexion) quien anuncie el fin UNA sola vez y no
        # reintente. Si anunciáramos aquí, saldría el aviso por duplicado.
        try:    await client.disconnect()
        except Exception as exc:
            logger.debug("disconnect en LiveEnd: %s", exc)

    @client.on(DisconnectEvent)
    async def _on_disconnect(evento):
        pass  # el cierre ordenado lo gestiona quien llama

    async def _correr():
        vigia = asyncio.create_task(_vigilar_parada(client, parada))
        try:
            await client.connect(fetch_room_info=True)
        finally:
            vigia.cancel()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_correr())
    except Exception as exc:
        error[0] = exc
        logger.debug("sesión TikTok: %s", exc)
    finally:
        # Drenar lo pendiente (cierre del websocket, keepalives) antes de
        # cerrar el loop; si no, asyncio escupe «Task was destroyed but it
        # is pending» al terminar cada sesión.
        try:
            pendientes = asyncio.all_tasks(loop)
            for t in pendientes:
                t.cancel()
            if pendientes:
                loop.run_until_complete(
                    asyncio.gather(*pendientes, return_exceptions=True))
        except Exception:
            pass
        try:    loop.close()
        except Exception: pass
    return error[0]


# Excepciones de TikTokLive que no vale la pena reintentar. Se comparan por
# NOMBRE de clase (la librería es opcional, no se importa aquí) y no por
# subcadena del mensaje: un «404 Not Found» del servidor de firmas es un
# httpx.HTTPStatusError transitorio, no un usuario inexistente.
_CLASES_OFFLINE = ("UserOfflineError",)
_CLASES_NO_EXISTE = ("UserNotFoundError",)


def _nombre(exc) -> str:
    return type(exc).__name__


def _es_error_http(exc) -> bool:
    n = _nombre(exc).lower()
    return "http" in n or n.endswith("statuserror")


def _mensaje_error(exc) -> str:
    nombre = _nombre(exc)
    t = f"{nombre}: {exc}".lower()
    if nombre in _CLASES_OFFLINE:
        return "Ese usuario de TikTok no está en directo ahora mismo."
    if nombre in _CLASES_NO_EXISTE:
        return "No se encontró ese usuario de TikTok. Revisa la URL."
    if "sign" in t or "euler" in t or "rate" in t and "limit" in t:
        return ("El servidor de firmas de TikTok no responde o alcanzó su "
                "límite. Espera un momento y reintenta.")
    if "captcha" in t or "blocked" in t:
        return "TikTok pidió verificación (captcha). Reintenta más tarde."
    if _es_error_http(exc):
        return f"TikTok no respondió bien (error HTTP): {exc}"
    return f"No se pudo conectar al directo de TikTok: {exc}"


def _es_error_permanente(exc) -> bool:
    return _nombre(exc) in _CLASES_OFFLINE + _CLASES_NO_EXISTE


def capturar_con_reconexion(usuario, config, parada, on_evento,
                            on_estado=None, on_info=None,
                            on_espectadores=None) -> None:
    """Bucle de captura con reintentos, con el mismo contrato de estados que la
    captura de YouTube (conectando/conectado/reintentando/error…). Bloquea:
    llamar desde un hilo aparte. on_espectadores(n) (opcional) recibe el conteo
    de espectadores en vivo cuando TikTok lo actualiza."""
    if not disponible():
        if on_estado:
            on_estado("error_permanente",
                      "Falta la librería TikTokLive. Ejecuta instalar.bat.")
        parada.set()
        return

    intentos = 0
    conecto = [False]

    def _estado(tipo, texto):
        # Se intercepta «conectado» para contar solo los fallos SEGUIDOS: un
        # directo largo con microcortes sueltos no debe agotar max_intentos.
        if tipo == "conectado":
            conecto[0] = True
        if on_estado:
            on_estado(tipo, texto)

    while not parada.is_set():
        if on_estado:
            on_estado("conectando", f"Conectando al directo de TikTok de @{usuario}...")
        conecto[0] = False
        err = _sesion(usuario, parada, on_evento, _estado, on_info, on_espectadores,
                      anunciar_entradas=bool(config.get("tiktok_anunciar_entradas")))
        if conecto[0]:
            intentos = 0
        if parada.is_set():
            break
        if err is not None and _es_error_permanente(err):
            if on_estado:
                on_estado("error_permanente", _mensaje_error(err))
            parada.set()
            break
        if err is None:
            # Conexión que terminó sola (fin del directo): no reintentamos.
            if on_estado:
                on_estado("desconectado", "El directo de TikTok ha terminado.")
            parada.set()
            break
        if not config.get("reconectar", True):
            if on_estado:
                on_estado("error", _mensaje_error(err))
            parada.set()
            break
        intentos += 1
        mi = config.get("max_intentos", 0)
        if mi > 0 and intentos >= mi:
            if on_estado:
                on_estado("error", f"Se agotaron los {mi} intentos de reconexión.")
            parada.set()
            break
        espera = config.get("espera_entre_intentos", 10)
        sfx = f" de {mi}" if mi else ""
        if on_estado:
            on_estado("reintentando",
                      f"Reintentando en {espera} segundos (intento {intentos}{sfx})...")
        parada.wait(timeout=espera)
