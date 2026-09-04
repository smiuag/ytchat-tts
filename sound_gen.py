"""Genera los WAV de retroalimentación con stdlib (wave + struct + math).

Los sonidos se escriben en un *tema*: una carpeta bajo `sounds/themes/` con
un WAV por evento, nombrado igual que el evento (p. ej. `mensaje_nuevo.wav`).
Así un usuario puede crear su propio tema simplemente dejando archivos con esos
mismos nombres en `sounds/themes/<su_tema>/` y seleccionándolo en `sounds.ini`.

Uso:  python sound_gen.py  [--forzar]  [--destino CARPETA]
"""

import math
import struct
import wave
from pathlib import Path


SR       = 44100
BITS     = 16
CANALES  = 2         # Estéreo real: permite un leve paneo por evento para que
                     # el oído los ubique sin pensar (útil sin lectura visual).
AMP      = 0.55      # Margen sobre 1.0 para evitar clipping al sumar ondas.
# Carpeta base de temas. Cada tema es una subcarpeta con un <evento>.wav.
THEMES_DIR = Path(__file__).parent / "sounds" / "themes"

C4, D4, E4, F4, G4, A4, B4 = 261.63, 293.66, 329.63, 349.23, 392.00, 440.00, 493.88
C5, D5, E5, F5, G5, A5, B5 = 523.25, 587.33, 659.25, 698.46, 783.99, 880.00, 987.77
C6, E6 = 1046.50, 1318.51
A3, F3, E3 = 220.00, 174.61, 164.81


# ── Primitivas ────────────────────────────────────────────────────────────────

def _seno(freq, dur, amp=AMP, fase=0.0):
    n = int(SR * dur)
    return [amp * math.sin(2 * math.pi * freq * i / SR + fase) for i in range(n)]


def _triangular(freq, dur, amp=AMP):
    # Más cálida que la senoidal y menos agresiva que la cuadrada: apta
    # para tonos de UI que van a sonar muchas veces seguidas.
    n = int(SR * dur)
    p = SR / freq
    out = []
    for i in range(n):
        x = (i % p) / p
        y = 4 * x - 1 if x < 0.5 else 3 - 4 * x
        out.append(amp * y)
    return out


def _glide(f0, f1, dur, amp=AMP, fn=math.sin):
    # Barrido de frecuencia (glissando) integrando la fase: para sonidos de
    # "deslizar/limpiar" sin saltos audibles entre notas.
    n = int(SR * dur)
    out = []
    fase = 0.0
    for i in range(n):
        t = i / max(1, n - 1)
        f = f0 * (f1 / f0) ** t            # interpolación exponencial (musical)
        fase += 2 * math.pi * f / SR
        out.append(amp * fn(fase))
    return out


def _silencio(dur):
    return [0.0] * int(SR * dur)


def _suma(*ondas):
    if not ondas:
        return []
    n = min(len(o) for o in ondas)
    return [sum(o[i] for o in ondas) for i in range(n)]


def _concat(*ondas):
    r = []
    for o in ondas:
        r.extend(o)
    return r


def _detune(freq, dur, amp=AMP, cents=7.0, fn=_triangular):
    # Dos osciladores levemente desafinados (unos pocos cents): añaden cuerpo
    # y un sutil efecto coro, sin que llegue a sonar desafinado de verdad.
    f2 = freq * (2 ** (cents / 1200.0))
    return _suma(fn(freq, dur, amp), fn(f2, dur, amp))


def _perc(muestras, ataque=0.004, tau=0.10):
    # Ataque rápido + caída EXPONENCIAL (e^-t/τ): imita cómo decae un sonido
    # real (campana, pulsación). Más natural y "premium" que el fade lineal
    # para blips y notas sueltas. τ menor = decae antes.
    n = len(muestras)
    if n == 0:
        return muestras
    na = min(max(1, int(SR * ataque)), n)
    out = []
    for i, m in enumerate(muestras):
        a = (i / na) if i < na else 1.0
        out.append(m * a * math.exp(-i / (SR * tau)))
    return out


def _normalizar(muestras, objetivo=0.85):
    if not muestras:
        return muestras
    pico = max(abs(x) for x in muestras)
    if pico < 1e-9:
        return muestras
    k = objetivo / pico
    return [x * k for x in muestras]


def _escribir_wav(path: Path, muestras, pan: float = 0.0):
    """Escribe el WAV. `pan` en [-1, 1] reparte la señal entre L y R con ley de
    'balance': el lado dominante queda a nivel completo y solo se atenúa el
    contrario. Así el centro (pan=0) conserva todo el volumen (a diferencia de
    la ley de potencia constante, que dejaría el centro a -3 dB)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    maxv = (1 << (BITS - 1)) - 1
    frames = bytearray()
    if CANALES == 1:
        for x in muestras:
            x = max(-1.0, min(1.0, x))
            frames += struct.pack("<h", int(x * maxv))
    else:
        pan = max(-1.0, min(1.0, pan))
        gl = 1.0 if pan <= 0 else (1.0 - pan)
        gr = 1.0 if pan >= 0 else (1.0 + pan)
        for x in muestras:
            x = max(-1.0, min(1.0, x))
            l = int(max(-1.0, min(1.0, x * gl)) * maxv)
            r = int(max(-1.0, min(1.0, x * gr)) * maxv)
            frames += struct.pack("<hh", l, r)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(CANALES)
        w.setsampwidth(BITS // 8)
        w.setframerate(SR)
        w.writeframes(bytes(frames))


# ── Diseño de cada sonido ─────────────────────────────────────────────────────
# Cada función devuelve las muestras listas para escribir. Las decisiones
# tonales buscan sobriedad: nada infantil, nada estridente.

def gen_app_inicio():
    # Acorde mayor C-E-G en arpegio rápido, con cuerpo (detune) y caída
    # natural: da la bienvenida sin sonar a videojuego.
    d = 0.16
    partes = [
        _perc(_detune(C4, d,        0.40), 0.004, 0.14),
        _perc(_detune(E4, d,        0.40), 0.004, 0.14),
        _perc(_detune(G4, d + 0.10, 0.45), 0.004, 0.22),
    ]
    retardo = int(SR * 0.075)
    n_total = max(retardo * (i + 1) + len(p) for i, p in enumerate(partes))
    mix = [0.0] * n_total
    for i, p in enumerate(partes):
        off = retardo * i
        for j, v in enumerate(p):
            mix[off + j] += v
    return _normalizar(mix, 0.75)


def gen_conectando():
    # Dos pulsos con hueco: leído como "esperando", no como "listo".
    pulso = _perc(_triangular(A4, 0.10, 0.40), 0.006, 0.05)
    return _concat(pulso, _silencio(0.06), pulso, _silencio(0.02))


def gen_conectado():
    # Quinta C5-G5 cálida y abierta, con cuerpo y decaimiento suave.
    a = _detune(C5, 0.26, 0.34)
    b = _detune(G5, 0.26, 0.22)
    return _normalizar(_perc(_suma(a, b), 0.005, 0.20), 0.8)


def gen_desconectado():
    # Caída E5→C5: gesto descendente = "se cierra".
    t1 = _perc(_triangular(E5, 0.13, 0.35), 0.005, 0.10)
    t2 = _perc(_triangular(C5, 0.16, 0.32), 0.005, 0.14)
    return _normalizar(_concat(t1, t2), 0.75)


def gen_mensaje():
    # Amplitud baja y duración corta porque suena potencialmente cientos
    # de veces por sesión: cualquier cosa más notable cansa rapidísimo.
    return _normalizar(_perc(_seno(G5, 0.07, 0.22), 0.010, 0.045), 0.42)


def gen_superchat():
    # Parcial inarmónico (f * 4.2) imita el espectro de una campana real;
    # sin él suena a órgano y pierde la asociación con "importante". Cada
    # parcial decae a su ritmo (los agudos antes), como una campana de verdad.
    f = A5
    partes = [
        _perc(_seno(f,       0.45, 0.32), 0.002, 0.34),
        _perc(_seno(f * 2,   0.40, 0.14), 0.002, 0.20),
        _perc(_seno(f * 3,   0.30, 0.08), 0.002, 0.12),
        _perc(_seno(f * 4.2, 0.20, 0.05), 0.002, 0.07),
    ]
    return _normalizar(_suma(*partes), 0.8)


def gen_miembro():
    # Tríada ascendente C-E-G brillante: alguien "sube" al canal. Leve paneo
    # a la derecha (ver PANEO) para distinguirla del arranque.
    d = 0.11
    n1 = _perc(_detune(C5, d,        0.35), 0.005, 0.10)
    n2 = _perc(_detune(E5, d,        0.38), 0.005, 0.10)
    n3 = _perc(_detune(G5, d + 0.08, 0.42), 0.005, 0.18)
    return _normalizar(_concat(n1, n2, n3), 0.80)


def gen_error():
    # Dos senos muy cercanos producen un batido (beat) que el oído asocia
    # a aviso; más limpio que un zumbido grave solo.
    a = _seno(175, 0.20, 0.35)
    b = _seno(185, 0.20, 0.35)
    return _normalizar(_perc(_suma(a, b), 0.003, 0.16), 0.75)


def gen_pausa():
    # Descendente G4→D4: "se detiene".
    n1 = _perc(_triangular(G4, 0.07, 0.32), 0.004, 0.07)
    n2 = _perc(_triangular(D4, 0.10, 0.32), 0.004, 0.10)
    return _normalizar(_concat(n1, n2), 0.7)


def gen_reanudar():
    # Ascendente D4→G4: espejo de la pausa, "se reanuda".
    n1 = _perc(_triangular(D4, 0.07, 0.32), 0.004, 0.07)
    n2 = _perc(_triangular(G4, 0.10, 0.32), 0.004, 0.10)
    return _normalizar(_concat(n1, n2), 0.7)


def gen_transporte_en_curso():
    return _normalizar(_perc(_triangular(A4, 0.07, 0.28), 0.003, 0.05), 0.52)


def gen_copiar():
    # Tic agudo y muy breve: confirmación discreta.
    return _normalizar(_perc(_triangular(C6, 0.05, 0.30), 0.002, 0.04), 0.55)


def gen_voz_cambiada():
    return _normalizar(_perc(_triangular(E5, 0.10, 0.30), 0.005, 0.07), 0.65)


# ── Sonidos nuevos (v0.6 online y acciones que antes reusaban otros) ──────────

def gen_enviado():
    # Mensaje enviado al chat en vivo. Dos notas ascendentes E5→A5, brillante
    # y resuelto: "salió". Leve paneo a la derecha (acción saliente).
    n1 = _perc(_triangular(E5, 0.06, 0.34), 0.003, 0.06)
    n2 = _perc(_detune(A5, 0.12, 0.36),     0.003, 0.12)
    return _normalizar(_concat(n1, n2), 0.7)


def gen_comentario():
    # Comentario publicado/respondido. Doble blip G5→C6, suave y claro,
    # emparentado con "enviado" pero distinguible (más agudo y corto).
    n1 = _perc(_triangular(G5, 0.05, 0.30), 0.003, 0.05)
    n2 = _perc(_triangular(C6, 0.09, 0.32), 0.003, 0.09)
    return _normalizar(_concat(n1, n2), 0.62)


def gen_moderacion():
    # Banear / expulsar (timeout). Dos notas graves y firmes A3→E3 con cuerpo:
    # autoritario y serio, sin ser alarmante como el error. Paneo a la izquierda.
    n1 = _perc(_detune(A3, 0.14, 0.40, cents=5), 0.004, 0.12)
    n2 = _perc(_detune(E3, 0.20, 0.40, cents=5), 0.004, 0.18)
    return _normalizar(_concat(n1, n2), 0.78)


def gen_cola_vaciada():
    # Cola de lectura vaciada. Barrido descendente A5→D5: gesto de "barrer/
    # limpiar". Corto y suave para no competir con nada importante.
    sweep = _glide(A5, D5, 0.16, 0.30)
    return _normalizar(_perc(sweep, 0.004, 0.13), 0.55)


# ── Tema "suave": senos cálidos con decaimiento tipo marimba/madera ───────────
# Más redondo, bajo y mate que el tema por defecto: nada de aristas brillantes
# ni regusto a videojuego. Mismo lenguaje de gestos (ascendente = abrir, etc.).

def _madera(freq, dur, amp, tau=0.12):
    # Seno fundamental + un toque de octava: timbre de madera/marimba, suave.
    base = _suma(_seno(freq, dur, amp), _seno(freq * 2, dur, amp * 0.18))
    return _perc(base, 0.005, tau)


def _seq(*notas):
    return _normalizar(_concat(*notas), 0.7)


def s_app_inicio():
    # Quinta y octava abiertas C4-G4-C5: cálido, recibe sin estridencia.
    return _seq(_madera(C4, 0.10, 0.42, 0.10),
                _madera(G4, 0.10, 0.42, 0.10),
                _madera(C5, 0.30, 0.46, 0.26))


def s_conectando():
    pulso = _madera(A3, 0.12, 0.40, 0.09)
    return _concat(pulso, _silencio(0.07), pulso, _silencio(0.02))


def s_conectado():
    # Tercera mayor C5-E5 sostenida y redonda.
    return _normalizar(_perc(_suma(_seno(C5, 0.30, 0.34), _seno(E5, 0.30, 0.26)),
                             0.006, 0.24), 0.78)


def s_desconectado():
    return _seq(_madera(E5, 0.12, 0.34, 0.10), _madera(C5, 0.22, 0.32, 0.16))


def s_mensaje():
    # Toque de madera muy breve y bajo: el evento más frecuente, casi un roce.
    return _normalizar(_madera(C5, 0.08, 0.20, 0.05), 0.40)


def s_superchat():
    # Campana cálida: pocos parciales y mucho seno, registro medio (F5).
    f = F5
    partes = [
        _perc(_seno(f,       0.55, 0.34), 0.003, 0.42),
        _perc(_seno(f * 2,   0.45, 0.12), 0.003, 0.26),
        _perc(_seno(f * 3.1, 0.30, 0.05), 0.003, 0.14),
    ]
    return _normalizar(_suma(*partes), 0.78)


def s_miembro():
    return _seq(_madera(C5, 0.11, 0.36, 0.10),
                _madera(E5, 0.11, 0.38, 0.10),
                _madera(G5, 0.26, 0.42, 0.20))


def s_error():
    # Dos notas graves y mates descendentes A3→F3: "algo no fue", sin aspereza.
    return _seq(_madera(A3, 0.16, 0.40, 0.13), _madera(F3, 0.24, 0.40, 0.18))


def s_pausa():
    return _seq(_madera(G4, 0.10, 0.34, 0.08), _madera(D4, 0.16, 0.34, 0.12))


def s_reanudar():
    return _seq(_madera(D4, 0.10, 0.34, 0.08), _madera(G4, 0.16, 0.34, 0.12))


def s_transporte_en_curso():
    return _normalizar(_madera(A4, 0.08, 0.26, 0.05), 0.48)


def s_copiar():
    return _normalizar(_madera(C6, 0.07, 0.30, 0.04), 0.5)


def s_voz_cambiada():
    return _normalizar(_madera(E5, 0.12, 0.30, 0.08), 0.6)


def s_enviado():
    return _seq(_madera(E5, 0.09, 0.34, 0.07), _madera(A5, 0.16, 0.36, 0.13))


def s_comentario():
    return _seq(_madera(G5, 0.08, 0.30, 0.06), _madera(C6, 0.13, 0.32, 0.10))


def s_moderacion():
    return _seq(_madera(A3, 0.16, 0.42, 0.13), _madera(E3, 0.24, 0.42, 0.20))


def s_cola_vaciada():
    return _normalizar(_perc(_glide(A5, D5, 0.18, 0.28), 0.005, 0.14), 0.5)


# Catálogo de temas: nombre → {archivo (= evento) .wav : generador}.
TEMAS = {
    "default": {
        "app_inicio.wav":    gen_app_inicio,
        "conectando.wav":    gen_conectando,
        "conectado.wav":     gen_conectado,
        "desconectado.wav":  gen_desconectado,
        "mensaje_nuevo.wav": gen_mensaje,
        "superchat.wav":     gen_superchat,
        "nuevo_miembro.wav": gen_miembro,
        "error.wav":         gen_error,
        "pausa.wav":         gen_pausa,
        "reanudar.wav":      gen_reanudar,
        "transporte_en_curso.wav": gen_transporte_en_curso,
        "copiar.wav":        gen_copiar,
        "voz_cambiada.wav":  gen_voz_cambiada,
        "enviado.wav":       gen_enviado,
        "comentario.wav":    gen_comentario,
        "moderacion.wav":    gen_moderacion,
        "cola_vaciada.wav":  gen_cola_vaciada,
    },
    "suave": {
        "app_inicio.wav":    s_app_inicio,
        "conectando.wav":    s_conectando,
        "conectado.wav":     s_conectado,
        "desconectado.wav":  s_desconectado,
        "mensaje_nuevo.wav": s_mensaje,
        "superchat.wav":     s_superchat,
        "nuevo_miembro.wav": s_miembro,
        "error.wav":         s_error,
        "pausa.wav":         s_pausa,
        "reanudar.wav":      s_reanudar,
        "transporte_en_curso.wav": s_transporte_en_curso,
        "copiar.wav":        s_copiar,
        "voz_cambiada.wav":  s_voz_cambiada,
        "enviado.wav":       s_enviado,
        "comentario.wav":    s_comentario,
        "moderacion.wav":    s_moderacion,
        "cola_vaciada.wav":  s_cola_vaciada,
    },
}

# Paneo estéreo por evento, en [-1, 1] (0 = centro). Muy sutil y solo donde
# ayuda a diferenciar; el resto va centrado. Compartido por todos los temas.
PANEO = {
    "nuevo_miembro.wav": 0.25,    # llega alguien → ligeramente a la derecha
    "enviado.wav":       0.20,    # acción saliente → derecha
    "comentario.wav":    0.20,
    "moderacion.wav":   -0.25,    # acción de moderación → izquierda
}


# ── Entrada ───────────────────────────────────────────────────────────────────

def generar_tema(tema: str, destino: Path | None = None,
                 sobreescribir: bool = False) -> int:
    sonidos = TEMAS[tema]
    destino = destino or (THEMES_DIR / tema)
    destino.mkdir(parents=True, exist_ok=True)
    n = 0
    for nombre, fn in sonidos.items():
        ruta = destino / nombre
        if ruta.exists() and not sobreescribir:
            print(f"  [saltar]  {nombre}  (ya existe)")
            continue
        _escribir_wav(ruta, fn(), pan=PANEO.get(nombre, 0.0))
        print(f"  [crear ]  {nombre:20s}  {ruta.stat().st_size:6d} bytes")
        n += 1
    return n


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Genera los WAV de retroalimentación.")
    ap.add_argument("-f", "--forzar", action="store_true", help="Sobreescribir existentes")
    ap.add_argument("-t", "--tema", default="all",
                    help=f"Tema a generar: {', '.join(TEMAS)} o 'all' (por defecto)")
    ap.add_argument("-d", "--destino", default=None,
                    help="Carpeta de salida (por defecto sounds/themes/<tema>)")
    args = ap.parse_args()

    temas = list(TEMAS) if args.tema == "all" else [args.tema]
    if any(t not in TEMAS for t in temas):
        ap.error(f"tema desconocido. Opciones: {', '.join(TEMAS)}, all")

    total = 0
    for t in temas:
        destino = Path(args.destino) if args.destino else (THEMES_DIR / t)
        print(f"\n  Tema '{t}' → {destino}")
        print("-" * 60)
        n = generar_tema(t, destino, sobreescribir=args.forzar)
        total += n
        print("-" * 60)
        print(f"  {n} creado(s). {len(TEMAS[t]) - n} saltado(s).")
    if not args.forzar and total < sum(len(TEMAS[t]) for t in temas):
        print("\n  Usa --forzar para regenerar los existentes.")
    print()


if __name__ == "__main__":
    main()
