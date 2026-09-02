# Paleta de colores — Opobook

Referencia de los colores usados en la app y para qué sirve cada uno. Pensada para poder pasarla a otra persona que quiera usar el mismo criterio en su propia app.

## Paleta base (marca)

| Color | Hex | Uso |
|---|---|---|
| Crema | `#F7F4EE` | Fondo general de la app (modo claro) |
| Verde salvia | `#CAD7C5` | Color primario — botones principales, elementos activos, progreso |
| Rosa empolvado | `#E7D9D4` | Acento — días de fin de semana, estados "en progreso", detalles |
| Beige | `#E9E1D3` | Secundario/neutro — fondos suaves, estado "pendiente" |
| Texto | `#333333` | Texto principal sobre fondos claros |

## Tokens semánticos (modo claro / modo oscuro)

Estos son los "roles" de color que usa toda la UI — cada componente pide un rol, no un hex directo, así el tema cambia solo.

| Token | Claro | Oscuro | Para qué |
|---|---|---|---|
| `background` | `#F7F4EE` | `#201E1A` | Fondo de la página |
| `foreground` | `#333333` | `#F2EFE8` | Texto principal |
| `card` | `#FFFFFF` | `#2A2723` | Fondo de tarjetas/fichas |
| `card-foreground` | `#333333` | `#F2EFE8` | Texto dentro de tarjetas |
| `popover` | `#FFFFFF` | `#2A2723` | Fondo de menús flotantes, tooltips |
| `primary` | `#CAD7C5` | `#A9BBA1` | Botón principal, elementos activos |
| `primary-foreground` | `#333333` | `#1E1D1A` | Texto sobre el color primario |
| `secondary` | `#E9E1D3` | `#3A362F` | Fondos secundarios, estado neutro |
| `muted` | `#E9E1D3` | `#3A362F` | Fondos apagados/deshabilitados |
| `muted-foreground` | `#6B6B6B` | `#B5AFA3` | Texto secundario (subtítulos, hints) |
| `accent` | `#E7D9D4` | `#4A3E3A` | Acento — fin de semana, "en progreso" |
| `destructive` | `oklch(0.577 0.245 27.325)` | `oklch(0.704 0.191 22.216)` | Botones de borrar, errores |
| `border` / `input` | `#E3DCCF` | `#3E3A33` | Bordes de tarjetas y campos |
| `ring` | `#CAD7C5` | `#A9BBA1` | Anillo de foco (accesibilidad) |
| `sidebar` | `#F7F4EE` | `#201E1A` | Fondo del menú lateral (escritorio) |

## Colores de gráficas (`chart-1` a `chart-5`)

| Token | Claro | Oscuro |
|---|---|---|
| `chart-1` | `#CAD7C5` | `#A9BBA1` |
| `chart-2` | `#E7D9D4` | `#C9AFA6` |
| `chart-3` | `#E9E1D3` | `#3A362F` |
| `chart-4` | `#A9BBA1` | `#CAD7C5` |
| `chart-5` | `#C9AFA6` | `#E7D9D4` |

Se usan para diferenciar series (tipos de estudio, bloques, temas) manteniendo siempre la misma paleta de marca en vez de colores genéricos de gráfica.

## Colores con significado fijo (mismo tono en toda la app)

| Color | Hex claro | Hex oscuro | Significado |
|---|---|---|---|
| Salvia intenso | `#A9BBA1` | `#93A98B` | "Objetivo superado" — racha, calendario, donut de progreso, borde de cuenta atrás del examen |

Caso especial: en modo oscuro, `#A9BBA1` coincide con el `primary` normal, así que necesita su propio tono más claro (`#93A98B`) para seguir destacando por encima del progreso base.

## Mapeos por tipo de dato

- **Tipo de estudio** (lectura / estudio / test / otros) → `chart-1` / `chart-2` / `chart-4` / `chart-5` (se salta `chart-3` porque casi no se distingue del fondo de tarjeta).
- **Estado de un tema**: pendiente = `secondary`, en progreso = `chart-5`, acabado = `chart-4`.
- **Celda de calendario/racha** según minutos estudiados: sin estudio = `secondary/40`, estudiado sin objetivo = `primary/50`, objetivo cumplido = `primary`, estudiado pero no llegó = `accent`, objetivo superado = salvia intenso (color con significado fijo, arriba).

## Criterio general

- Paleta cálida (nunca grises fríos), tanto en claro como en oscuro.
- Pocos colores con roles muy definidos, no muchos colores decorativos.
- Cada color mantiene el mismo significado en toda la app: el mismo tono siempre quiere decir lo mismo, ya sea en una gráfica, una racha o un calendario.
