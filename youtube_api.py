"""Capa de la YouTube Data API v3 (oficial, con OAuth2).

Aislada del resto de la app: si `google-api-python-client` y compañía no están
instalados, `google_disponible()` devuelve False y la GUI desactiva las
funciones que dependen de la API. El núcleo (leer el chat en vivo con pytchat)
funciona igual sin nada de esto.

Dos niveles de uso:
  - LECTURA de comentarios de vídeos: solo necesita una API key (sin login).
  - ESCRITURA (moderar, comentar, enviar mensajes al live): necesita OAuth2
    con el scope `youtube.force-ssl`, autorizado por el dueño/moderador.

Los parsers (`parsear_pagina_comentarios`, `normalizar_comentario`,
`mensaje_error_api`) son funciones puras, sin red, cubiertas por tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import diagnostico

logger = diagnostico.obtener_logger(__name__)

# Scope mínimo que cubre moderar, comentar y enviar mensajes al live.
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


# ── Disponibilidad de las librerías de Google ────────────────────────────────

def google_disponible() -> bool:
    """True si están instaladas las dependencias de la API oficial."""
    try:
        import googleapiclient.discovery  # noqa: F401
        import google_auth_oauthlib.flow  # noqa: F401
        import google.oauth2.credentials   # noqa: F401
        return True
    except Exception:
        return False


# ── Modelo de datos ──────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Comentario:
    autor: str
    texto: str
    likes: int
    publicado: str          # ISO8601 tal cual lo da la API
    respuestas: int         # nº de respuestas (solo en comentarios de nivel 1)
    comment_id: str         # id para responder (parentId)
    autor_canal_id: str     # channelId del autor (para moderar/identificar)
    es_respuesta: bool = False


# ── Parsers puros (testeables sin red) ───────────────────────────────────────

def normalizar_comentario(snippet: dict, comment_id: str = "",
                          es_respuesta: bool = False, respuestas: int = 0) -> Comentario:
    """Convierte el `snippet` de un comment recurso a un Comentario."""
    autor = (snippet.get("authorDisplayName") or "Usuario").strip() or "Usuario"
    texto = snippet.get("textOriginal") or snippet.get("textDisplay") or ""
    try:
        likes = int(snippet.get("likeCount", 0) or 0)
    except (TypeError, ValueError):
        likes = 0
    publicado = snippet.get("publishedAt") or ""
    canal = ""
    ac = snippet.get("authorChannelId")
    if isinstance(ac, dict):
        canal = ac.get("value", "") or ""
    elif isinstance(ac, str):
        canal = ac
    return Comentario(
        autor=autor, texto=texto, likes=likes, publicado=publicado,
        respuestas=int(respuestas or 0), comment_id=comment_id,
        autor_canal_id=canal, es_respuesta=es_respuesta,
    )


def parsear_pagina_comentarios(resp: dict, incluir_respuestas: bool = True
                               ) -> tuple[list[Comentario], str]:
    """De la respuesta de commentThreads.list saca (comentarios, nextPageToken).

    Las respuestas de cada hilo se intercalan justo tras su comentario padre.
    """
    salida: list[Comentario] = []
    for item in resp.get("items", []) or []:
        snip = item.get("snippet", {}) or {}
        top = snip.get("topLevelComment", {}) or {}
        top_id = top.get("id", "") or ""
        top_snip = top.get("snippet", {}) or {}
        n_resp = int(snip.get("totalReplyCount", 0) or 0)
        salida.append(normalizar_comentario(top_snip, comment_id=top_id,
                                             es_respuesta=False, respuestas=n_resp))
        if incluir_respuestas:
            for r in (item.get("replies", {}) or {}).get("comments", []) or []:
                r_snip = r.get("snippet", {}) or {}
                r_id = r.get("id", "") or ""
                salida.append(normalizar_comentario(r_snip, comment_id=r_id,
                                                    es_respuesta=True))
    return salida, resp.get("nextPageToken", "") or ""


def mensaje_error_api(exc) -> str:
    """Traduce errores de la API a algo legible para el usuario."""
    texto = str(exc)
    low = texto.lower()
    if "quotaexceeded" in low or "quota" in low and "exceeded" in low:
        return ("Se agotó la cuota diaria de la API de YouTube. "
                "Vuelve a intentarlo mañana o usa otra clave.")
    if "commentsdisabled" in low or "disabled comments" in low:
        return "Los comentarios están desactivados en este vídeo."
    if "videonotfound" in low or "video not found" in low:
        return "No se encontró el vídeo. Revisa la URL o el ID."
    if "keyinvalid" in low or "api key not valid" in low or "badrequest" in low and "key" in low:
        return "La API key no es válida. Revísala en Configuración."
    if "insufficientpermissions" in low or "forbidden" in low:
        return ("No tienes permiso para esta acción. Debes ser el dueño o "
                "moderador del directo, y haber iniciado sesión.")
    if "livechatnotfound" in low or "live chat not found" in low:
        return "Este vídeo no tiene un chat en vivo activo."
    if "rate" in low and "limit" in low:
        return "Demasiadas peticiones seguidas. Espera unos segundos."
    return f"Error de la API de YouTube: {texto}"


def comentarios_desactivados(exc) -> bool:
    """Indica si la API rechazó la operación porque el vídeo cerró comentarios."""
    texto = str(exc).lower()
    return "commentsdisabled" in texto or "disabled comments" in texto


# ── OAuth2 (flujo de aplicación de escritorio) ───────────────────────────────

def iniciar_sesion(client_id: str, client_secret: str) -> str:
    """Abre el navegador para autorizar y devuelve el token serializado (JSON).

    Bloquea hasta que el usuario completa el login, así que conviene llamarlo
    desde un hilo aparte. Lanza excepción si falla.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow
    config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(config, scopes=SCOPES)
    # port=0 -> el SO elige un puerto libre para el redirect del loopback.
    # prompt=consent: Google solo entrega refresh_token en el primer
    # consentimiento; tras «Cerrar sesión» y volver a entrar llegaba un token
    # sin él, to_json() lo omitía y toda escritura fallaba con «Authorized
    # user info was not in the expected format».
    creds = flow.run_local_server(port=0, open_browser=True,
                                  prompt="consent",
                                  authorization_prompt_message="",
                                  success_message="Sesión iniciada. Ya puedes "
                                  "volver a la aplicación.")
    return creds.to_json()


def _cargar_credenciales(token_json: str):
    """Reconstruye y refresca las credenciales OAuth. Devuelve (creds, token_json_actualizado)."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    import json as _json
    info = _json.loads(token_json)
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    nuevo = token_json
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        nuevo = creds.to_json()
    return creds, nuevo


# ── Cliente de alto nivel ────────────────────────────────────────────────────

class ClienteYouTube:
    """Envoltura fina sobre la Data API. Construye los servicios de forma perezosa."""

    def __init__(self, creds: dict):
        self._api_key = (creds.get("api_key") or "").strip()
        self._client_id = (creds.get("oauth_client_id") or "").strip()
        self._client_secret = (creds.get("oauth_client_secret") or "").strip()
        self._token_json = creds.get("token") or ""
        self._svc_lectura = None
        self._svc_escritura = None
        self._token_actualizado = None  # se rellena si se refresca el token

    # -- estado --
    def puede_leer(self) -> bool:
        return bool(self._api_key)

    def puede_escribir(self) -> bool:
        return bool(self._token_json)

    def token_actualizado(self) -> str | None:
        """Si al construir el servicio de escritura se refrescó el token,
        devuelve el nuevo JSON para que la app lo persista. Si no, None."""
        return self._token_actualizado

    # -- servicios --
    def _lectura(self):
        if self._svc_lectura is None:
            from googleapiclient.discovery import build
            self._svc_lectura = build("youtube", "v3", developerKey=self._api_key,
                                      cache_discovery=False)
        return self._svc_lectura

    def _escritura(self):
        if self._svc_escritura is None:
            from googleapiclient.discovery import build
            creds, nuevo = _cargar_credenciales(self._token_json)
            if nuevo != self._token_json:
                self._token_actualizado = nuevo
                self._token_json = nuevo
            self._svc_escritura = build("youtube", "v3", credentials=creds,
                                        cache_discovery=False)
        return self._svc_escritura

    # -- lectura de comentarios (API key) --
    def leer_comentarios(self, video_id: str, page_token: str = "",
                         max_results: int = 50, orden: str = "relevance"
                         ) -> tuple[list[Comentario], str]:
        params = {
            "part": "snippet,replies",
            "videoId": video_id,
            "maxResults": max(1, min(100, int(max_results))),
            "order": orden if orden in ("relevance", "time") else "relevance",
            "textFormat": "plainText",
        }
        if page_token:
            params["pageToken"] = page_token
        resp = self._lectura().commentThreads().list(**params).execute()
        return parsear_pagina_comentarios(resp)

    # -- resolución del chat en vivo (API key) --
    def datos_chat_directo(self, video_id: str) -> dict:
        """Devuelve los datos de disponibilidad del chat de un directo."""
        resp = self._lectura().videos().list(
            part="liveStreamingDetails", id=video_id).execute()
        items = resp.get("items", []) or []
        if not items:
            return {"hay_video": False, "hay_directo": False, "live_chat_id": ""}
        det = items[0].get("liveStreamingDetails")
        return {"hay_video": True, "hay_directo": det is not None,
                "live_chat_id": (det or {}).get("activeLiveChatId", "") or ""}

    def resolver_live_chat_id(self, video_id: str) -> str:
        return self.datos_chat_directo(video_id)["live_chat_id"]

    def detalles_directo(self, video_id: str) -> dict:
        try:
            resp = self._lectura().videos().list(
                part="liveStreamingDetails", id=video_id).execute()
            items = resp.get("items", []) or []
            if not items:
                return {"espectadores": None, "comienzo": ""}
            det = items[0].get("liveStreamingDetails", {}) or {}
            espectadores = det.get("concurrentViewers")
            espectadores = int(espectadores) if espectadores is not None else None
            return {"espectadores": espectadores,
                    "comienzo": det.get("actualStartTime", "") or ""}
        except Exception:
            return {"espectadores": None, "comienzo": ""}

    # -- escrituras (OAuth) --
    def enviar_mensaje_live(self, live_chat_id: str, texto: str) -> None:
        self._escritura().liveChatMessages().insert(
            part="snippet",
            body={"snippet": {
                "liveChatId": live_chat_id,
                "type": "textMessageEvent",
                "textMessageDetails": {"messageText": texto},
            }},
        ).execute()

    def banear_usuario(self, live_chat_id: str, canal_id: str,
                       segundos: int | None = None) -> None:
        """segundos=None -> baneo permanente; >0 -> timeout temporal."""
        snippet = {
            "liveChatId": live_chat_id,
            "bannedUserDetails": {"channelId": canal_id},
        }
        if segundos and segundos > 0:
            snippet["type"] = "temporary"
            snippet["banDurationSeconds"] = int(segundos)
        else:
            snippet["type"] = "permanent"
        self._escritura().liveChatBans().insert(
            part="snippet", body={"snippet": snippet}).execute()

    def publicar_comentario(self, video_id: str, texto: str) -> None:
        self._escritura().commentThreads().insert(
            part="snippet",
            body={"snippet": {
                "videoId": video_id,
                "topLevelComment": {"snippet": {"textOriginal": texto}},
            }},
        ).execute()

    def responder_comentario(self, parent_id: str, texto: str) -> None:
        self._escritura().comments().insert(
            part="snippet",
            body={"snippet": {"parentId": parent_id, "textOriginal": texto}},
        ).execute()
