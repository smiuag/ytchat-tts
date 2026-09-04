"""Conexión y desconexión de sesiones de captura."""

import logging

import diagnostico
import sound_player as _snd
import tiktok_captura
import overlay_servidor
from overlay_datos import evento_de_mensaje

from sesiones import RegistroSesiones


logger = diagnostico.obtener_logger(__name__)


class Conexiones:
    def __init__(self, cola, config, stats, parada_app, crear_hilo=None,
                 registro=None):
        self._cola = cola
        self._config = config
        self._stats = stats
        self._parada_app = parada_app
        self._crear_hilo = crear_hilo or diagnostico.crear_hilo
        self._registro = registro or RegistroSesiones()

    @property
    def registro(self):
        return self._registro

    def conectar(self, url_raw):
        import main
        import gui as _gm
        # ¿Es una URL de TikTok? Va por su propia rama de captura (fase 1:
        # chat + reproductor, sin comentarios ni moderación).
        usuario_tt = tiktok_captura.usuario_de_url(url_raw)
        if usuario_tt:
            self._conectar_tiktok(usuario_tt)
            return
        vid = main.extraer_video_id(url_raw)
        # Validar el formato ANTES de tocar la red: si no es un ID de 11
        # caracteres, es basura. Se rechaza al instante (sin esperas ni freeze).
        if not main._ID_RE.match(vid):
            if _gm._gui_frame:
                import wx
                wx.CallAfter(_gm._gui_frame.url_invalida)
            return
        sesion = self._registro.abrir()
        ps, gen = sesion.parada, sesion.gen

        def _on_msg(autor, mensaje, hora, tipo=main.TIPO_TEXTO, monto="", canal_id=""):
            if not self._registro.vigente(gen):
                return  # mensaje de una sesión anterior: descartar
            overlay_servidor.difundir(
                evento_de_mensaje(autor, mensaje, "youtube", monto or None))
            if _gm._gui_frame and _gm._gui_frame._alive:
                import wx
                wx.CallAfter(_gm._gui_frame.agregar_mensaje_chat,
                             autor, mensaje, hora, tipo, monto, canal_id,
                             plataforma="youtube")

        def _on_estado(tipo_estado, texto):
            if not self._registro.vigente(gen):
                return  # estado de una sesión anterior: descartar
            if not _gm._gui_frame or not _gm._gui_frame._alive:
                return
            import wx
            if tipo_estado == "conectado":
                # set_conectado ya anuncia un mensaje claro según el tipo; no
                # repetimos el texto genérico aquí.
                wx.CallAfter(_gm._gui_frame.set_conectado, True)
                return
            if tipo_estado in ("error_permanente", "error", "desconectado"):
                wx.CallAfter(_gm._gui_frame.set_conectado, False)
                wx.CallAfter(_gm._gui_frame.set_titulo_stream, "")
            # El resto de estados (conectando, reintentando, errores) se anuncian.
            from gui import anunciar
            wx.CallAfter(anunciar, texto)

        def _refrescar_directo():
            try:
                import credenciales
                import youtube_api
                if not (youtube_api.google_disponible() and
                        credenciales.hay_lectura()):
                    return
                if not self._registro.vigente(gen):
                    return
                cliente = youtube_api.ClienteYouTube(credenciales.cargar())
                # La primera consulta va nada más conectar (antes se esperaba
                # un minuto entero sin espectadores ni hora de inicio); las
                # siguientes, cada minuto.
                while not ps.is_set():
                    if not self._registro.vigente(gen):
                        return
                    detalles = None
                    try:
                        detalles = cliente.detalles_directo(vid)
                    except Exception as exc:
                        logger.debug("actualizar detalles del directo: %s", exc)
                    if not self._registro.vigente(gen):
                        return
                    frame_actual = _gm._gui_frame
                    if detalles is not None and frame_actual and frame_actual._alive:
                        import wx
                        wx.CallAfter(frame_actual.set_espectadores,
                                     detalles["espectadores"])
                        wx.CallAfter(frame_actual.set_inicio_directo,
                                     detalles["comienzo"])
                    ps.wait(60)
            except Exception as exc:
                logger.debug("actualizar detalles del directo: %s", exc)

        def _run():
            # Una sola descarga del watch para sacar título, tipo y metadatos.
            # sesion_activa: si se desconecta a mitad, no encadena más pasos
            # y el hilo Chat termina rápido (el cierre de la app lo espera).
            titulo, tipo, metadatos = main.obtener_info_video(
                vid, sesion_activa=lambda: self._registro.vigente(gen))
            # Si mientras buscábamos info se desconectó o se conectó a otro vídeo,
            # esta sesión ya no vale: no tocar la GUI (si no, pisaríamos la nueva).
            if not self._registro.vigente(gen):
                return
            frame = _gm._gui_frame
            import wx
            if frame:
                main._anunciar_fallo_video(metadatos, wx.CallAfter)
                if titulo:
                    wx.CallAfter(frame.set_titulo_stream, titulo)
                wx.CallAfter(frame.set_tipo_video, tipo, vid)
                wx.CallAfter(frame.set_metadatos, metadatos)
                # Registrar en el historial (canal desde los metadatos de yt-dlp).
                # directo=True si es un live: su id cambia cada vez y, terminado,
                # no reconecta (se marca en la lista del historial).
                wx.CallAfter(frame.registrar_historial, "youtube", vid,
                             f"https://www.youtube.com/watch?v={vid}",
                             titulo, (metadatos or {}).get("canal", ""),
                             tipo == main.deteccion.LIVE)

            if main.deteccion.tiene_chat_en_vivo(tipo):
                # Directo (o tipo no determinado): capturamos el chat con pytchat.
                # Resolver el id del chat en vivo en paralelo (red opcional).
                self._crear_hilo(main._resolver_live_chat_id, "LiveChatId",
                                 args=(vid,)).start()
                if tipo == main.deteccion.LIVE:
                    self._crear_hilo(_refrescar_directo, "DetallesDirecto",
                                     daemon=True).start()
                main.captura_con_reconexion(
                    vid, self._cola, self._config, ps, self._stats,
                    on_message=_on_msg, on_estado=_on_estado,
                    sesion_activa=lambda: self._registro.vigente(gen))
                # Solo refrescar la UI a «desconectado» si seguimos siendo la
                # sesión activa: un hilo viejo que termina tarde no debe apagar
                # el directo nuevo.
                if (self._registro.vigente(gen) and frame
                        and not self._parada_app.is_set()):
                    wx.CallAfter(frame.set_conectado, False)
                    wx.CallAfter(frame.set_titulo_stream, "")
            else:
                # Vídeo subido o directo programado: no hay chat en vivo. No se
                # arranca pytchat; quedan disponibles comentarios y reproductor.
                # El sonido también va tras el guard: una sesión ya descartada
                # no debe sonar como si conectara.
                if self._registro.vigente(gen) and frame:
                    wx.CallAfter(frame.set_conectado, True)
                    _snd.reproducir("conectado")

        self._crear_hilo(_run, "Chat").start()

    def _conectar_tiktok(self, usuario):
        """Rama TikTok: mismo esquema de sesión (ps + gen) que YouTube, con la
        captura de tiktok_captura y el pipeline común procesar_entrante."""
        import main
        import gui as _gm
        sesion = self._registro.abrir()
        ps, gen = sesion.parada, sesion.gen

        def _on_msg(autor, mensaje, hora, tipo=main.TIPO_TEXTO, monto="", canal_id=""):
            if not self._registro.vigente(gen):
                return
            overlay_servidor.difundir(
                evento_de_mensaje(autor, mensaje, "tiktok", monto or None))
            if _gm._gui_frame and _gm._gui_frame._alive:
                import wx
                wx.CallAfter(_gm._gui_frame.agregar_mensaje_chat,
                             autor, mensaje, hora, tipo, monto, canal_id,
                             plataforma="tiktok")

        def _on_evento(autor, mensaje, tipo, monto, canal_id):
            if not self._registro.vigente(gen):
                return
            main.procesar_entrante(
                autor, mensaje, tipo, monto, canal_id,
                self._cola, self._config, self._stats, on_message=_on_msg,
                sesion_activa=lambda: self._registro.vigente(gen),
                etiqueta_monto="Regalo")

        def _on_estado(tipo_estado, texto):
            if not self._registro.vigente(gen):
                return
            frame = _gm._gui_frame
            if not frame or not frame._alive:
                return
            import wx
            # Los sonidos van aquí (no en tiktok_captura, que queda sin wx ni
            # audio): mismo mapa de eventos que la captura de YouTube.
            if tipo_estado in ("conectando", "reintentando"):
                _snd.reproducir("conectando")
                if tipo_estado == "reintentando":
                    self._stats.inc("reconexiones")
            elif tipo_estado == "conectado":
                _snd.reproducir("conectado")
                wx.CallAfter(frame.set_conectado, True)
                return  # set_conectado ya anuncia el mensaje adecuado
            elif tipo_estado in ("error_permanente", "error"):
                _snd.reproducir("error")
                wx.CallAfter(frame.set_conectado, False)
                wx.CallAfter(frame.set_titulo_stream, "")
            elif tipo_estado == "desconectado":
                wx.CallAfter(frame.set_conectado, False)
                wx.CallAfter(frame.set_titulo_stream, "")
            from gui import anunciar
            wx.CallAfter(anunciar, texto)

        def _on_info(meta):
            # Llega al conectar, con título, espectadores y la URL HLS del
            # directo (clave interna que consume el reproductor, no el panel).
            if not self._registro.vigente(gen):
                return
            frame = _gm._gui_frame
            if not frame or not frame._alive:
                return
            import wx
            url_flujo = meta.pop("_url_flujo", "")
            titulo = (meta.get("titulo") or "").strip() or f"TikTok de @{usuario}"
            wx.CallAfter(frame.set_titulo_stream, titulo)
            wx.CallAfter(frame.configurar_tiktok, usuario, url_flujo)
            wx.CallAfter(frame.set_metadatos, meta)
            # Registrar en el historial (TikTok reconecta por @usuario/live).
            wx.CallAfter(frame.registrar_historial, "tiktok", usuario,
                         f"https://www.tiktok.com/@{usuario}/live",
                         titulo, (meta.get("canal") or ""), True)

        def _on_espectadores(n):
            if not self._registro.vigente(gen):
                return
            if _gm._gui_frame and _gm._gui_frame._alive:
                import wx
                wx.CallAfter(_gm._gui_frame.set_espectadores, n)

        def _run():
            tiktok_captura.capturar_con_reconexion(
                usuario, self._config, ps,
                on_evento=_on_evento, on_estado=_on_estado, on_info=_on_info,
                on_espectadores=_on_espectadores)
            # Igual que en YouTube: solo apagar la UI si seguimos siendo la
            # sesión activa (un hilo viejo no debe pisar el directo nuevo).
            if (self._registro.vigente(gen) and _gm._gui_frame
                    and not self._parada_app.is_set()):
                import wx
                wx.CallAfter(_gm._gui_frame.set_conectado, False)
                wx.CallAfter(_gm._gui_frame.set_titulo_stream, "")

        self._crear_hilo(_run, "TikTok").start()

    def desconectar(self):
        self._registro.cerrar()
