"""Hilo TTS (SAPI5) y sanitización de texto.

Speak se lanza en modo asíncrono con WaitUntilDone en tramos de 100 ms,
lo que permite interrumpir un mensaje en curso (Alt+D) insertando un
purge entre tramos.
"""

from __future__ import annotations

import threading
import queue
import logging
import re
import time

import diagnostico

logger = diagnostico.obtener_logger(__name__)

_STOP = object()

SVSF_ASYNC        = 1
SVSF_PURGE_BEFORE = 2
SVSF_IS_NOT_XML   = 16   # evita que '<' al inicio se interprete como XML SAPI
_SPEAK_FLAGS      = SVSF_ASYNC | SVSF_IS_NOT_XML


# ── Sanitización de texto ────────────────────────────────────────────────────

_EMOJI = re.compile(
    "[\U0001F300-\U0001F9FF\U0001FA00-\U0001FAFF"
    "\U00002702-\U000027B0\U0001F1E0-\U0001F1FF"
    "\u2600-\u2B55\u200d\ufe0f\u3030]+",
    flags=re.UNICODE,
)
_URL   = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+", re.IGNORECASE)
_CTRL  = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_SPACE = re.compile(r"\s+")
# Emojis personalizados de YouTube que pytchat entrega como texto «:nombre:»
# (p. ej. :blue_heart:). Sin esto el TTS leería «dos puntos blue heart…».
_SHORTCODE = re.compile(r":[a-zA-Z0-9_+\-]{2,}:")


def quitar_emojis(texto: str) -> str:
    """Quita emojis Unicode y los shortcodes :nombre: de YouTube."""
    if not texto:
        return ""
    return _SHORTCODE.sub("", _EMOJI.sub("", texto))


def sanitizar(texto: str, emojis: bool, urls: bool, maxlen: int) -> str:
    if not texto:
        return ""
    if urls:   texto = _URL.sub("", texto)
    if emojis: texto = quitar_emojis(texto)
    texto = _CTRL.sub("", texto)
    texto = _SPACE.sub(" ", texto).strip()
    if maxlen > 0 and len(texto) > maxlen:
        t  = texto[:maxlen]
        sp = t.rfind(" ")
        texto = (t[:sp] if sp > maxlen // 2 else t) + "..."
    return texto


def construir_tts(autor: str, mensaje: str, config: dict) -> str:
    autor_limpio = sanitizar(autor, config["limpiar_emojis"], False, 50) or "Usuario"
    fmt = config.get("formato_prefijo", "nombre_mensaje")
    if fmt == "solo_mensaje": return mensaje
    if fmt == "solo_nombre":  return autor_limpio
    if fmt == "mensaje_nombre": return f"{mensaje}, de {autor_limpio}"
    return f"{autor_limpio}: {mensaje}"


# ── Conversión WPM → Rate SAPI5 ─────────────────────────────────────────────

def _wpm_a_rate(wpm: int) -> int:
    return max(-10, min(10, round((int(wpm) - 180) / 20)))


# ── Hilo TTS ─────────────────────────────────────────────────────────────────

class TTSWorker(threading.Thread):

    def __init__(self, cola: queue.Queue, config: dict):
        super().__init__(daemon=True, name="TTSWorker")
        self.cola   = cola
        self.config = config
        self._ready  = threading.Event()
        self._error  = None
        self._active = threading.Event()
        self._active.set()
        self._paused = False
        self._cmds   = queue.Queue()
        self._rate   = _wpm_a_rate(config.get("velocidad", 175))
        self._volume = max(0, min(100, int(config.get("volumen", 1.0) * 100)))
        self._purge_pending = threading.Event()
        # Multi-voz: colección de voces cacheada y qué voz está activa ahora. La
        # voz «base» es la del menú/preferencias; un mensaje puede pedir otra
        # (p. ej. eventos con una voz distinta) y se cambia solo para ese.
        self._voces_col = None
        self._voz_base_idx = 0
        self._voz_actual_idx = 0

    def run(self):
        try:
            # Dentro del try: si falta pywin32, la causa llega a _error (y al
            # log) en vez de un «No se pudo iniciar el motor de voz» genérico.
            self._init_com()
            self._voz = self._create_voice()
        except Exception as exc:
            self._error = exc
            self._ready.set()
            logger.error("TTSWorker: %s", exc)
            return
        self._ready.set()
        logger.info("TTSWorker listo.")
        _err = 0

        while True:
            self._active.wait()
            self._procesar_comandos()
            try:
                item = self.cola.get(timeout=0.3)
            except queue.Empty:
                self._pump(); continue
            if item is _STOP:
                break
            texto = (item.get("texto_tts") or "").strip()
            if not texto:
                continue
            self._active.wait()
            try:
                self._hablar(texto, item.get("voz")); _err = 0
            except Exception as exc:
                _err += 1
                if _err <= 5:
                    logger.warning("TTS error: %s", exc)
                elif _err == 6:
                    logger.error("TTS: demasiados errores seguidos.")
        logger.info("TTSWorker terminado.")

    def _aplicar_voz_idx(self, idx) -> None:
        """Cambia la voz activa de SAPI si hace falta (usa la colección cacheada,
        sin recrearla). Silencioso ante índices fuera de rango o fallos."""
        try:
            if (self._voces_col is not None and idx is not None
                    and idx != self._voz_actual_idx
                    and 0 <= idx < self._voces_col.Count):
                self._voz.Voice = self._voces_col.Item(idx)
                self._voz_actual_idx = idx
        except Exception as exc:
            logger.debug("cambiar voz a %s: %s", idx, exc)

    def _hablar(self, texto: str, voz=None) -> None:
        # Multi-voz: si el mensaje pide una voz concreta, se usa; si no, la base.
        self._aplicar_voz_idx(voz if voz is not None else self._voz_base_idx)
        # Una purga pedida con la voz callada (p. ej. detener_actual() al
        # reconectar) quedaba armada y cortaba el SIGUIENTE mensaje a los
        # 100 ms: el primer mensaje de cada reconexión se oía a medias.
        # No había nada que cortar, así que se descarta antes de hablar.
        self._purge_pending.clear()
        self._voz.Speak(texto, _SPEAK_FLAGS)
        while True:
            try:
                terminado = bool(self._voz.WaitUntilDone(100))
            except Exception:
                time.sleep(0.1)
                try:    terminado = (self._voz.Status.RunningState == 1)
                except Exception: terminado = True
            if terminado:
                break
            self._procesar_comandos()
            if not self._active.is_set():
                self._esperar_pausa()
            if self._purge_pending.is_set():
                self._purge_pending.clear()
                try:
                    self._voz.Speak("", SVSF_ASYNC | SVSF_PURGE_BEFORE)
                    self._voz.WaitUntilDone(200)
                except Exception: pass
                break

    def _esperar_pausa(self) -> None:
        """Pausa a mitad de frase. Antes el hilo se quedaba en wait() pero
        SAPI seguía sonando hasta acabar la frase y los comandos (voz,
        velocidad, volumen, purga) no se atendían hasta reanudar. Ahora se
        pausa la voz de verdad y se sigue vaciando la cola de comandos."""
        try:    self._voz.Pause()
        except Exception as exc:
            logger.debug("Pause: %s", exc)
        try:
            while not self._active.wait(0.1):
                self._procesar_comandos()
                if self._purge_pending.is_set():
                    break   # Alt+D en pausa: se reanuda para poder purgar
        finally:
            try:    self._voz.Resume()
            except Exception as exc:
                logger.debug("Resume: %s", exc)

    def _procesar_comandos(self):
        while not self._cmds.empty():
            try:    cmd, val = self._cmds.get_nowait()
            except queue.Empty: break
            try:
                if cmd == "voice":
                    # Cambia la voz BASE (la del menú); los mensajes normales la
                    # usan y los eventos pueden pedir otra (multi-voz).
                    if self._voces_col is not None and 0 <= val < self._voces_col.Count:
                        self._voz_base_idx = val
                        self._aplicar_voz_idx(val)
                        logger.info("Voz base: %s",
                                    self._voces_col.Item(val).GetDescription())
                elif cmd == "rate":
                    self._voz.Rate = max(-10, min(10, int(val)))
                elif cmd == "volume":
                    self._voz.Volume = max(0, min(100, int(val)))
                elif cmd == "purge":
                    self._purge_pending.set()
            except Exception as exc:
                logger.warning("Comando %s: %s", cmd, exc)

    def _init_com(self):
        try:
            import pythoncom; pythoncom.CoInitialize()
        except ImportError:
            raise RuntimeError("pywin32 no instalado: pip install pywin32")
        except Exception as exc:
            logger.debug("CoInitialize: %s", exc)

    def _create_voice(self):
        try:    import win32com.client
        except ImportError:
            raise RuntimeError("win32com no disponible: pip install pywin32")
        try:    tts = win32com.client.Dispatch("SAPI.SpVoice")
        except Exception as exc:
            raise RuntimeError(f"No se pudo crear SAPI.SpVoice: {exc}") from exc

        voces = tts.GetVoices()
        if voces.Count == 0:
            raise RuntimeError("No hay voces SAPI5.")
        idx = self._resolve_voice(self.config["voz"], voces)
        if idx is None:
            # Una voz desinstalada no debe impedir arrancar la app (antes:
            # ValueError → «No se pudo iniciar el motor de voz» y salida).
            nombres = "\n".join(f"  [{i}] {voces.Item(i).GetDescription()}" for i in range(voces.Count))
            logger.warning("Voz '%s' no encontrada; se usa la primera disponible.\n%s",
                           self.config["voz"], nombres)
            idx = 0

        tts.Voice  = voces.Item(idx)
        tts.Volume = self._volume
        tts.Rate   = self._rate
        self._voces_col = voces      # cacheada para cambiar de voz sin recrearla
        self._voz_base_idx = idx
        self._voz_actual_idx = idx
        logger.info("Voz: %s | Rate: %+d | Vol: %d%%",
                    voces.Item(idx).GetDescription(), tts.Rate, tts.Volume)
        return tts

    def _resolve_voice(self, cfg, voces):
        try:
            idx = int(cfg)
            if 0 <= idx < voces.Count: return idx
            return 0
        except ValueError: pass
        term = str(cfg).lower()
        for i in range(voces.Count):
            if term in voces.Item(i).GetDescription().lower(): return i
        return None

    def _pump(self):
        try:
            import pythoncom; pythoncom.PumpWaitingMessages()
        except Exception: pass

    # ── API pública ──────────────────────────────────────────────────────────

    def esperar_inicio(self, timeout=10.0):
        if not self._ready.wait(timeout=timeout): return False
        if self._error:
            logger.error(str(self._error)); return False
        return True

    def pausar(self):
        if not self._paused:
            self._paused = True; self._active.clear()

    def reanudar(self):
        if self._paused:
            self._paused = False; self._active.set()

    def toggle_pausa(self):
        self.reanudar() if self._paused else self.pausar()

    def esta_pausado(self):
        return self._paused

    def vaciar_cola(self):
        n = 0
        while not self.cola.empty():
            try:    self.cola.get_nowait(); n += 1
            except queue.Empty: break
        if n: logger.info("Cola vaciada: %d mensaje(s).", n)

    def detener(self):
        if self._paused: self._active.set()
        try:    self.cola.put(_STOP)
        except Exception: pass
        self.join(timeout=5.0)

    def detener_actual(self):
        """Interrumpe el mensaje en curso y vacía la cola (Alt+D)."""
        self.vaciar_cola()
        self._cmds.put(("purge", None))

    def cambiar_voz(self, idx: int):
        self._cmds.put(("voice", idx))

    def cambiar_rate(self, delta: int):
        # El contador se actualiza AQUÍ (en el hilo del llamador) y al hilo TTS
        # va el valor absoluto: así get_rate() devuelve el valor nuevo al
        # instante y pulsar rápido no desfasa lo anunciado/persistido.
        self._rate = max(-10, min(10, self._rate + int(delta)))
        self._cmds.put(("rate", self._rate))

    def cambiar_volumen(self, delta: int) -> None:
        self._volume = max(0, min(100, self._volume + int(delta)))
        self._cmds.put(("volume", self._volume))

    def get_rate(self) -> int:
        return self._rate

    def get_volume(self) -> int:
        return self._volume
