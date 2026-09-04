# Novedades de YTChat TTS

Qué cambia en cada versión, en lenguaje llano. El detalle técnico está en el
historial de git.

## Próxima versión (en desarrollo, septiembre de 2026)

Revisión general del código con arreglos en el reproductor, la voz, OBS, las
descargas y la ventana de Preferencias.

- **Los directos ya no se congelan cada minuto y medio.** El vídeo y el audio
  de un directo llegan por separado y el reproductor perdía la sincronía entre
  ambos cada 60-90 segundos, quedándose parado 25-50 segundos. Ahora se juntan
  antes con ffmpeg en un único flujo. Si ffmpeg tarda en arrancar, el
  reproductor espera a que esté listo en vez de fallar en silencio; si el
  directo se corta, lo dice y vuelve a conectar solo (hasta dos veces).
- **Retroceder en un directo ya no salta dos horas atrás.** El reproductor se
  fiaba de una duración falsa que daba VLC y un retroceso de un minuto acababa
  al principio de la ventana del directo.
- **El primer mensaje tras reconectar ya no se corta.** Una orden de callar
  pendiente se aplicaba al mensaje siguiente a los 100 milisegundos.
- **La voz configurada que ya no existe no impide arrancar.** Se usa la
  primera disponible y se anota en el registro.
- **Pausar la lectura (F5) pausa de verdad la frase en curso**, y mientras está
  en pausa se atienden cambios de voz, velocidad y volumen.
- **Iniciar sesión otra vez tras cerrarla vuelve a funcionar.** Antes Google
  devolvía un permiso incompleto y moderar, comentar o escribir en el chat
  fallaba con un error de formato.
- **Los Super Chats en yenes, wones o rupias suman bien.** «¥1,000» sumaba 1.
- **Al reconectar a un directo distinto, los mensajes automáticos y el
  compositor ya no pueden acabar en el chat anterior**, ni los comentarios del
  vídeo anterior en el nuevo.
- **Reconectar de verdad cuenta.** Con la wifi inestable, cinco microcortes
  repartidos en horas agotaban los intentos aunque cada reconexión hubiera
  funcionado. Solo cuentan los fallos seguidos.
- **Desconectar mientras dice «Conectando…» ahora es posible**, y cerrar la app
  no espera a que termine una consulta a YouTube.
- **OBS: el tiempo de transmisión era mil veces mayor.** Un minuto se anunciaba
  como «16 horas 40 minutos».
- **La ventana de Transmisión no se queda bloqueada** si la fuente elegida ha
  desaparecido en OBS o si OBS cierra la conexión: avisa y deja seguir.
  «Aplicar tamaño» sobre un panel escalado ya no lo encoge a la mitad.
- **El panel de chat en la emisión no repite mensajes** cuando se apaga y se
  enciende rápido.
- **Preferencias: la pestaña Atajos se ve entera.** Antes dos tercios de los
  botones quedaban fuera de la ventana. Ahora las pestañas se desplazan y la
  ventana se puede agrandar.
- **Alt+Enter en la lista del chat abre el compositor** en vez de copiar el
  mensaje. «Ir a Comentarios» ya no se anuncia dos veces.
- **Modo de contraste alto de Windows respetado.** La aplicación dejaba de
  aplicar sus colores fijos encima del tema del sistema.
- **Descargas:** la carpeta «Descargas» siempre está junto a la aplicación
  (antes dependía de desde dónde se abría); el nombre que se anuncia y se
  guarda es el del archivo final, no el de un trozo temporal; «Enumerar» ya no
  antepone «NA - » a los vídeos sueltos; cancelar mata también a ffmpeg y borra
  los restos; las descargas que terminan con la ventana cerrada entran en el
  historial; al reabrir la ventana el progreso sigue vivo.
- **Los archivos que la app guarda (historial, credenciales, mensajes
  programados y la configuración de OBS) se escriben de forma segura**: un
  cierre a mitad ya no los deja vacíos.
- **Los sonidos largos de temas personalizados ya no se cortan a los 5 s.**

## 2.1.0 — agosto de 2026

Esta versión añade un panel de chat para mostrar en la emisión, la posibilidad
de escribir en el chat desde la propia aplicación, y simplifica la
personalización de los atajos. También arregla el reproductor, que hasta ahora
hacía caso cuando quería.

- **El reproductor obedece al instante.** Después de adelantar o retroceder, el
  pausar y el reproducir se perdían durante diez o veinte segundos: se anunciaba
  «pausar» tres veces seguidas y el vídeo seguía andando. En los vídeos de YouTube el
  audio viaja por separado del vídeo, y al reproductor le llegaban los dos por
  la red: el audio frenaba todo lo demás. Ahora el audio se guarda antes en el disco, en
  una carpeta `cache-audio` junto al ejecutable, y las órdenes se cumplen todas.
  De paso, el vídeo empieza a verse en menos de un segundo en vez de en seis.
- **Ya no se abre una ventana negra al arrancar.** Aparecía un instante y le
  robaba el foco al lector de pantalla. Era una consulta al sistema sobre la
  tarjeta de vídeo, que además retrasaba el arranque unos segundos y ahora se
  hace por detrás.
- **El servidor de OBS se activa desde aquí.** *Preferencias, Transmisión*,
  botón *Activar el servidor de OBS*, sin tener que buscarlo en los menús de
  OBS.
- **Los avisos del menú ya no se cortan.** Al elegir una opción del menú, el
  lector empezaba a leer el aviso y se callaba a mitad, porque enseguida leía
  otra cosa. Pasaba en diecinueve sitios, incluido el menú del botón derecho
  sobre el chat, donde fallaba siempre.
- **La casilla del panel de chat funciona aunque OBS no esté.** Dejaba de
  responder si OBS no contestaba, aunque el panel no necesita OBS para nada.
- **Cuando OBS no se puede activar, dice por qué.** Antes salía un mensaje
  vacío de contenido.
- **En las descargas se lee primero el progreso.** Las columnas pasaron a ser
  progreso, estado y nombre, que es el orden en que interesan.
- **Se atacaron dos defectos de los cierres inesperados al salir.** El
  reproductor dejaba cabos sueltos al cerrarse, que encajan con los cierres
  bruscos que aparecían en el registro. No se puede dar por curado hasta usarlo
  un tiempo, pero el registro ahora deja rastro de ese cierre en vez de callarse.
- **Los fallos de la voz quedan anotados.** Si el sintetizador falla al
  anunciar algo, antes no quedaba ni rastro.

- **Un panel de chat para que lo vean los espectadores.** Los mensajes aparecen
  en una página con fondo transparente que puede añadirse a la emisión, de modo
  que quien mira el directo lee el chat sin salir del vídeo. El panel se
  enciende en la ventana de *Transmisión*, menú Transmisión → *Panel de
  transmisión*, o `Ctrl+Mayúsculas+T`.
- **Componer la escena sin ver la pantalla.** Menú Herramientas →
  *Transmisión*, o `Ctrl+Mayúsculas+T`. La ventana se comunica con OBS y permite
  elegir la escena, elegir **cualquiera de sus fuentes** (el panel de chat, la
  cámara, la captura del juego), llevarla a cualquiera de las nueve posiciones
  habituales (por ejemplo, inferior derecha), cambiarle el tamaño, mostrarla u
  ocultarla, fijarla para que no se mueva sin querer y ponerla por delante de lo
  demás.

  Así puede armarse una escena completa a ciegas: el juego en el centro, la
  cámara en un recuadro más pequeño arriba a la derecha y el chat en una
  esquina.

  Cada cambio se anuncia en voz alta con lo que hace falta saber: en qué
  posición quedó, qué tamaño tiene, qué parte de la pantalla ocupa, si se sale
  del borde y, sobre todo, **si alguna otra fuente lo está tapando y cuánto**.
  Esa es la pregunta que no puede responderse mirando.

  Hay además un modo de ajuste fino: se activa con un botón y a partir de ahí
  las flechas mueven el panel, en pasos normales, grandes con `Control` o de un
  píxel con `Mayúsculas`. `Intro` confirma y `Escape` deshace. Y un botón
  guarda una captura de la escena, para poder enseñársela a alguien que vea.

  También hay una explicación de qué es el lienzo, para quien no haya usado
  antes un programa de emisión.
- **Alias para los nombres imposibles de escuchar.** Muchos nombres de YouTube
  son cadenas de letras y números que la voz lee enteras en cada mensaje. Ahora
  puede ponérseles un nombre corto: en la lista del chat, menú contextual sobre
  un mensaje y *Poner alias*. Desde ese momento, ese usuario se lee y se ve con
  el alias. Para quitarlo, se abre lo mismo y se deja el campo vacío.

  El nombre real no se pierde: expulsar, banear, silenciar y responder siguen
  actuando sobre la cuenta de verdad. Y el menú pasa a nombrar al usuario como
  se lo ve en la lista, para que no digan cosas distintas.
- **Una forma más de que le lean el chat: primero el mensaje, después quién lo
  escribió.** En Preferencias, *Lectura*, junto a las tres que ya había. Se oye
  «hola a todos, de Lucía». Sirve cuando llegan muchos mensajes seguidos: se
  oye el contenido antes que el nombre y puede decidirse si interesa sin
  esperar.
- **El panel deja de mostrar mensajes viejos si la aplicación se cierra.** Antes
  se quedaba con lo último que había recibido, y esos mensajes seguían viéndose
  en la emisión como si el chat siguiera vivo.
- **`F2` dice cuánta gente está viendo el directo y cuánto lleva emitiendo.** El
  número de espectadores estaba mal: decía cero aunque hubiera gente. Ahora es
  correcto y se actualiza solo cada minuto.
- **Conectarse volvió a ser rápido.** Se había vuelto lento, entre veinte y
  treinta segundos en algunos equipos, por la forma en que se pedían los datos
  del vídeo.
- **Ya se puede escribir en el chat en vivo.** Debajo de la lista de mensajes
  hay un cuadro de escritura con su botón *Enviar*. `Intro` envía el mensaje y
  `Mayúsculas+Intro` inserta un salto de línea. Tras enviarlo, el cuadro se
  vacía y el foco permanece dentro, de modo que puede escribirse el siguiente
  sin tabular. Cuando falta la conexión o la sesión de Google, el cuadro y el
  botón siguen alcanzándose con el tabulador y el motivo forma parte del nombre
  del botón, para que el lector de pantalla lo anuncie.
- **Comentar y responder en los vídeos.** En la pestaña *Comentarios*, los
  botones *Comentar en el vídeo* y *Responder* abren ese mismo cuadro en una
  ventana.
- **El vídeo de los directos vuelve a cargarse.** YouTube dejó de ofrecer un
  único flujo con imagen y sonido juntos, y la aplicación seguía esperándolo.
  Los directos mostraban «No se pudo cargar el vídeo» aunque el chat funcionara.
- **`Intro` copia el mensaje seleccionado.** En la lista del chat y en la de
  comentarios no hacía nada.
- **Los atajos se cambian en un solo paso.** Antes se abría una ventana aparte y
  había que confirmar en un botón. Ahora se activa el botón de la acción, se
  pulsa la combinación y queda guardada de inmediato, sin salir de la lista.
  `Intro` a solas deja la acción sin atajo y `Escape` cancela. Si la combinación
  no es válida o ya está en uso, se indica el motivo por voz y en un aviso en
  pantalla, y el botón sigue esperando otra.
- **Restablecer los atajos.** Un botón al final de la lista devuelve todas las
  combinaciones personalizables a sus valores originales.
- **Tres atajos nuevos para abrir ventanas**: `Ctrl+Mayúsculas+P` abre
  Preferencias, `Ctrl+Mayúsculas+H` el historial de directos y
  `Ctrl+Mayúsculas+I` marca una incidencia en el registro.
- **El registro detallado viene desactivado.** Es una opción de diagnóstico y
  estaba activa de fábrica, lo que hacía crecer el archivo de registro sin
  necesidad.
- **La guía de configuración de la API está reescrita.** Cada paso indica la
  dirección exacta de la pantalla de Google Cloud correspondiente, y se explican
  los tres puntos en los que es fácil quedarse atascado con un lector de
  pantalla.
- **Publicar un comentario y responder a uno ya funcionan.** No hacían nada: se
  escribía el texto, se pulsaba *Publicar*, la ventana se cerraba y no se
  enviaba ni se avisaba de nada.
- **Los avisos ya no se cortan a la mitad.** Cuando la aplicación decía algo,
  ese texto se ponía en la cola del lector de pantalla detrás de lo que el
  lector estuviera diciendo por su cuenta, y se perdía en cuanto se pulsaba otra
  tecla. Ahora los avisos de la aplicación se oyen enteros. Los dos únicos que
  no interrumpen son los que se repiten solos: el aviso de que un vídeo sigue
  cargando y el de que se está consultando a OBS.
- **Cuando no se puede escribir en el chat, ahora dice por qué.** Antes daba
  siempre el mismo motivo. Ahora distingue si falta la clave de la API, si el
  vídeo no existe, si no es un directo o si el directo tiene el chat
  desactivado.
- **En un vídeo con los comentarios cerrados ya no deja escribir uno.** Antes se
  podía redactarlo entero y solo al publicarlo se descubría que no se podía.
- **El reproductor deja de desfasarse al avanzar rápido.** Pulsando varias veces
  seguidas para adelantar, algunas pulsaciones se perdían y el tiempo anunciado
  retrocedía solo. Y pulsar reproducir o pausa mientras el vídeo estaba
  cargando lo hacía empezar de cero.
- **El vídeo se corta menos.** El colchón de red era muy pequeño y cualquier
  fluctuación de la conexión interrumpía la reproducción.
- **Las descargas avisan cuando terminan**, esté abierto o cerrado el gestor, y
  la cola ya no se olvida al cerrar la ventana.
- **Recorrer un desplegable ya no cambia nada.** En el diálogo de Transmisión,
  pasar por las nueve posiciones con las flechas movía el panel dentro de OBS
  una vez por flecha, en directo. Ahora se elige la posición y se aplica con su
  botón. Lo mismo con el orden de los comentarios, que recargaba la lista en
  cada flecha y gastaba cuota de la API.
- **El diálogo de Transmisión explica dónde está el panel en castellano
  llano.** Antes mezclaba tres porcentajes que medían cosas distintas y usaba
  la palabra «fuera» para dos ideas: pasarse de un borde y perder superficie.
  Y hay un botón nuevo que explica en qué orden se usa la ventana.
- **Preferencias se recorre con una lista de categorías**, no con pestañas. Con
  lector de pantalla, las flechas anuncian cada categoría al pasar por ella. Son
  trece, repartidas por tema.
- **Nueve opciones que existían y no se podían tocar.** Cómo se comporta la cola
  de lectura cuando el chat se acelera, la reconexión automática, el puerto del
  panel de chat, el micrófono de OBS que silencia el atajo, y el registro
  detallado, que hasta ahora solo se encendía editando un archivo a mano.
- **Los contadores numéricos se pueden reescribir sin borrar antes.** Al entrar
  en uno, su contenido queda seleccionado.
- **El registro de diagnóstico dejó de llenarse de ruido.** Nueve de cada diez
  líneas eran de librerías internas, y con una sesión larga ese ruido borraba el
  principio del archivo, que es justo donde suele estar el problema.
- **Avisa cuando se están perdiendo mensajes.** Si entra más chat del que la voz
  puede leer, la aplicación descarta los más viejos. Lo hacía en silencio: quien
  depende de la voz no tenía forma de enterarse de que se estaba perdiendo algo.
  Ahora lo dice una vez por sesión, recuerda que esos mensajes siguen escritos
  en la lista del chat y sugiere activar la lectura solo del nombre, que es lo
  que hace que la voz alcance. `F2` puede decir además cuántos van, si se activa
  ese dato en Preferencias.
- **El vídeo de los directos se carga en más casos.** Quedaba un caso en el que
  seguía diciendo «No se pudo cargar el vídeo» con un directo que se veía bien
  en el navegador: cuando YouTube ofrece la imagen y el sonido por separado en
  vez de juntos. Ahora los junta. Y si aun así no puede, deja anotado en el
  registro qué encontró, que antes no dejaba nada.
- **Los textos que lee el lector de pantalla llevan sus tildes.** Quince estaban
  escritos sin ellas, así que se oían mal pronunciados: «maxímo» por «máximo»,
  «transmisiòn» por «transmisión». Entre ellos dos categorías de Preferencias y
  varios botones del diálogo de Transmisión.
- **El archivo de fallos ya no asusta.** Recoge sucesos internos de Windows, y
  muchos son inofensivos, pero quien lo abría leía «Windows fatal exception» y
  creía que su aplicación estaba rota. Ahora cada arranque escribe una línea que
  lo explica y dice cuál es la señal de que la sesión terminó bien. Además, ocho
  elementos de menú dejaban ahí un aviso cada vez que se abrían con lector de
  pantalla, y ya no lo hacen.

## 2.0.1 — agosto de 2026

Versión de arreglos. No trae funciones nuevas grandes: trae que las que ya
había molesten menos y avisen mejor.

- **El diagnóstico dejó de hablar solo.** Cada treinta segundos anunciaba por
  voz cuántos hilos había vivos. Era información para arreglar problemas, no
  para escucharla mientras miras un directo. Ahora se sigue guardando en el
  registro, pero callado.
- **Los controles del reproductor ya no se quedan mudos.** Pulsar reproducir,
  silenciar o buscar sin tener un vídeo cargado no hacía absolutamente nada, ni
  siquiera decirlo. Ahora contestan «No hay ningún vídeo cargado» o «El
  reproductor no está disponible», según el caso.
- **Los atajos del reproductor funcionan siempre.** Estaban apagados hasta
  conectarte a algo, así que las siete combinaciones de Control parecían rotas.
- **Avisa al pulsar reproducir.** Antes había un silencio largo mientras
  cargaba, que parecía que se había colgado. Ahora dice «Cargando vídeo».
- **Avisos claros cuando falla la red.** Antes, si YouTube no contestaba o el
  vídeo era privado, no se oía nada. Ahora lo dice con palabras: que la red no
  responde, que el vídeo no está disponible, o que hay que esperar unos minutos
  porque se hicieron demasiadas consultas.
- **Los atajos de Preferencias van agrupados.** Los veinte botones colgaban
  sueltos; ahora el lector anuncia a qué grupo pertenece cada uno, «Reproductor»
  o «Conexión y chat».
- **yt-dlp se puede actualizar desde la aplicación.** Menú Herramientas →
  Actualizar yt-dlp. Es la pieza que se rompe cuando YouTube cambia algo por
  dentro, y hasta ahora había que esperar a una versión nueva del programa
  entero. Comprueba qué versión hay publicada, la compara con la instalada y la
  descarga solo si hace falta, verificando que el archivo sea el auténtico.
- **Las descargas usan ese mismo yt-dlp.** Antes el gestor de descargas llevaba
  su propia copia por dentro, que se quedaba vieja aunque actualizaras. Ahora
  todo usa el mismo, y la versión que muestra la aplicación es la de verdad.
- **Se arregló una fuga que dejaba el chat leyéndose dos veces por dentro.** Si
  te reconectabas a otro directo sin desconectar antes, la conexión anterior
  seguía viva pidiéndole mensajes a YouTube para siempre, en silencio, hasta
  cerrar el programa.
- **La carpeta de descargas ya no se guarda sola.** Se escribía en la
  configuración una ruta de la máquina donde se compiló el programa.
- Se quitó una entrada de menú que ya no llevaba a ninguna parte, y los avisos
  también salen por línea braille.

## 2.0.0 — julio de 2026

- **Directos de TikTok, ya finos.** La primera versión los estrenó y esta los
  deja fiables: se leen todos los comentarios con su autor, se oye el vídeo del
  directo, y F2 muestra los espectadores en vivo. Opcional: leer quién entra al
  directo (desactivado por defecto, en Preferencias → Lectura).
- **Historial de directos** (menú Archivo): guarda lo que has visto, en dos
  pestañas (YouTube y TikTok), para volver a un directo con Enter sin recordar
  el enlace. Los directos se marcan como tales, porque al terminar pueden dejar
  de existir.
- **Búsqueda por letras en el chat y los comentarios**: escribe unas letras
  seguidas («mig») y salta al mensaje que empieza así, anunciándolo. Da la
  vuelta a la lista si hace falta y avisa si no hay coincidencias.
- **Segunda voz para los eventos** (opcional): los Super Chats, regalos y
  miembros nuevos pueden leerse con una voz distinta de la de los mensajes.
- **Atajos que se capturan pulsándolos**: en Preferencias → Atajos ya no se
  escribe la combinación a mano; pulsas el botón de la acción y luego las
  teclas, y la app comprueba sola que sea válida y no choque con otra.
- **Estado por voz (F2) configurable**: dice los datos del directo (título,
  canal, espectadores, mensajes leídos, aportes…) y en Preferencias → Estado
  se elige exactamente qué cuenta.
- **Chat más fluido con el lector de pantalla**: navegar la lista con las
  flechas mientras llegan mensajes ya no se traba.
- **Menús coherentes**: las acciones que necesitan conexión se deshabilitan
  cuando no la hay, y desconectar es instantáneo (antes podía congelar la
  ventana unos segundos).
- **Reconexión de YouTube más robusta**: un error de red que dejaba la
  conexión rota hasta reconectar a mano ya se recupera solo.
- **Reproductor pulido**: reanudar un directo tras pausarlo vuelve al momento
  actual, la pantalla completa lleva el título del vídeo, y en los directos se
  indica «En directo» en lugar de una barra de progreso confusa.

## 1.0.0 — julio de 2026

Primera versión. Lectura del chat de YouTube Live con voces SAPI5; comentarios
de vídeos con lectura, respuesta y publicación; reproductor de vídeo integrado
con pantalla completa manejable por teclado; moderación y envío al chat con la
API oficial; pestaña de información del vídeo; y directos de TikTok (solo
lectura). Interfaz navegable por teclado, con anuncios por voz y braille.
