# Paleta de colores — YTChat TTS

Referencia de los colores que usa la aplicación y para qué sirve cada uno. Hay
tres superficies distintas, cada una con su paleta: la **ventana** (wxPython,
la que usa quien retransmite), el **panel de chat para la emisión**
(`web/chat.html`, lo que ven los espectadores dentro de OBS) y la
**documentación HTML** (`docs/`). La fuente de verdad es el código; este
documento explica el criterio para que quien toque un color sepa qué está
tocando.

## Criterio general

- **La accesibilidad manda.** La app está pensada para personas ciegas o con
  baja visión. Todo par texto/fondo real da **4,5:1 o más** (WCAG AA) y se
  comprueba con la fórmula de contraste, no a ojo. Los tonos de marca que no
  llegan se oscurecen lo justo para el texto y se dejan tal cual solo en
  formas sólidas (botones, barras), que no son texto.
- **Contraste alto de Windows tiene prioridad.** Si el sistema tiene activado
  un tema de contraste alto, la ventana no aplica ninguno de estos colores y
  deja mandar al tema (`gui.ALTO_CONTRASTE`, detectado al arrancar con
  `SPI_GETHIGHCONTRAST`). Todo color se aplica a través de `gui._pintar` o
  `gui._tc`, que son los que respetan ese interruptor; no llamar a
  `SetBackgroundColour`/`SetForegroundColour` con colores de paleta por fuera.
- **Pocos colores con papel fijo.** Cada tono significa siempre lo mismo. Nada
  decorativo.
- **Paleta cálida.** Crema y beige en la ventana, carbón cálido en el panel de
  emisión; nunca grises fríos.

## Ventana (wxPython) — `gui._T`

Modo claro únicamente: wx pinta con el tema nativo de Windows y no hay tema
oscuro propio (con contraste alto se apaga la paleta entera, ver arriba).

| Nombre en código | Hex | Papel |
|---|---|---|
| `bg` | `#F7F4EE` | Crema. Fondo general de la ventana y de los diálogos. |
| `surface` | `#FFFFFF` | Blanco. Paneles, grupos y pestañas. |
| `field` | `#E9E1D3` | Beige. Campos de texto y listas. |
| `text` | `#333333` | Texto principal. |
| `dim` | `#6B6B6B` | Texto secundario: notas, estados, subtítulos. |
| `accent` | `#3F5B3A` | Salvia oscurecida. Solo texto: títulos de sección y estados «bien». |
| `red` | `#B3261E` | Rojo. Solo texto: errores. |
| `btn` / `btn_t` | `#E9E1D3` / `#333333` | Botones secundarios (mismo beige que los campos). |
| `primary` / `primary_t` | `#CAD7C5` / `#333333` | Salvia de marca sin oscurecer. Solo el botón principal (Conectar). |

Contraste medido (WCAG) de los pares que existen de verdad en la ventana:

| Par | Relación |
|---|---|
| `text` sobre `bg` | 11,5 |
| `text` sobre `surface` | 12,6 |
| `text` sobre `field` | 9,7 |
| `text` sobre `primary` | 8,5 |
| `dim` sobre `bg` | 4,9 |
| `dim` sobre `surface` | 5,3 |
| `accent` sobre `bg` | 6,9 |
| `red` sobre `bg` | 6,0 |

Regla derivada de la tabla: **`dim` no se pone sobre `field`** (daría 4,1).
Dentro de un campo o una lista, el texto es siempre `text`.

Por qué `accent` no es el salvia de marca: `#CAD7C5` sobre crema da 1,3, es un
color de relleno, no de texto. Para títulos y estados se usa la misma familia
oscurecida hasta `#3F5B3A`. Lo mismo con el rojo.

## Panel de chat para la emisión — `web/chat.html` y `overlay_datos.py`

Lo ven los espectadores dentro de OBS sobre el vídeo, así que es oscuro y con
fondo casi opaco para que el texto aguante cualquier imagen debajo. No es
parte de la interfaz accesible (no recibe foco), pero el texto cumple igual
4,5:1 sobre su tarjeta.

| Nombre en CSS / Python | Hex | Papel |
|---|---|---|
| `--tinta` / `COLOR_CUERPO` | `#EDEAE7` | Texto del mensaje. |
| `--caja-alta` / `--caja-baja` | `#201E1C` al 93 % / `#121110` al 93 % | Degradado de la tarjeta. |
| `--yt` | `#E8745C` | Marca YouTube. Solo barras y bordes (5,6 sobre la tarjeta). |
| `--yt-txt` / `COLOR_YOUTUBE` | `#ED8068` | Variante de texto de YouTube (6,2). |
| `--tk` | `#2D9D8F` | Marca TikTok. Solo barras y bordes (5,0). |
| `--tk-txt` / `COLOR_TIKTOK` | `#3FB8A8` | Variante de texto de TikTok (6,8). |
| `--oro` / `COLOR_DORADO` | `#E0AE4E` | Super Chat y miembros nuevos (8,2). |

Colores de autor (`overlay_datos.PALETA` y `PALETA` en el HTML): doce tonos
claros que se asignan a cada nombre de usuario por un hash del nombre, de modo
que la misma persona tiene siempre el mismo color. El hash recorre puntos de
código (no unidades UTF-16), y Python y JavaScript deben dar el mismo
resultado; hay un test de paridad en `tests/test_overlay_datos.py`. Si se
cambia la lista, cambiarla en los dos sitios.

```
#ED8068  #5FBFA8  #E0AE4E  #8FB8E8  #C79BE0  #9CC97E
#F0908A  #6FD0C4  #D8C06A  #B0A8F0  #E3A277  #7FC8E8
```

## Documentación HTML — `generar_docs.py`

Los HTML de `docs/` (Léeme, Novedades, guía de la API) llevan su propio par
claro/oscuro, elegido por `prefers-color-scheme` del navegador.

| Token | Claro | Oscuro | Papel |
|---|---|---|---|
| `--fondo` | `#FFFFFF` | `#1C1917` | Fondo de la página |
| `--texto` | `#1C1917` | `#E7E5E4` | Texto |
| `--tenue` | `#57534E` | `#A8A29E` | Texto secundario |
| `--acento` | `#B8452F` | `#E8745C` | Enlaces y títulos (el mismo coral que YouTube en el panel) |
| `--borde` | `#E7E5E4` | `#44403C` | Bordes y separadores |
| `--codigo-fondo` | `#F5F5F4` | `#292524` | Fondo de bloques de código |

## Cómo cambiar un color sin romper nada

1. Cambiarlo en el sitio que manda: `gui._T` para la ventana, `:root` de
   `web/chat.html` más `overlay_datos.py` para el panel, `generar_docs.py`
   para la documentación.
2. Recalcular el contraste del par afectado (fórmula WCAG; cualquier
   calculadora en línea sirve) y no bajar de 4,5:1 en texto.
3. Si el color es de texto y no llega, oscurecerlo (ventana) o aclararlo
   (panel) en vez de buscar otro tono: así la familia se mantiene.
4. Actualizar este documento.
