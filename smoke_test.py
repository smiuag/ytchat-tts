#!/usr/bin/env python
"""Smoke test y verificación de accesibilidad de YTChat TTS.

Pensado para correrlo en Windows (donde está wxPython y el árbol de
accesibilidad). Tres fases, cada una se ejecuta solo si el entorno la permite:

  Fase 1  (cualquier SO):   importa los módulos de lógica pura.
  Fase 2  (necesita wx):    importa los módulos de GUI. Esto EJECUTA el código
                            a nivel de módulo y caza NameError, imports
                            circulares y atributos inexistentes que la simple
                            compilación (py_compile) no detecta.
  Fase 3  (Windows + pywinauto): lanza la aplicación, recorre el árbol de
                            accesibilidad (UI Automation, el mismo que lee
                            NVDA) y avisa de los controles interactivos sin
                            nombre accesible. Después cierra la app.

Uso:
    python smoke_test.py            # todas las fases disponibles
    python smoke_test.py --no-gui   # solo fases 1 y 2 (no abre la ventana)

Para la fase 3 hace falta:  pip install pywinauto
"""

from __future__ import annotations

import csv
import os
import re
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))

# Tipos de control que deben tener SIEMPRE un nombre accesible (lo que NVDA
# anuncia al llegar a ellos con Tab). Si alguno aparece sin nombre, es un fallo
# de accesibilidad.
_INTERACTIVOS = {"Button", "Edit", "ComboBox", "List", "CheckBox", "RadioButton"}



def _modulos_de_la_raiz() -> tuple[list[str], list[str]]:
    """(módulos puros, módulos de GUI) leídos de los .py de la raíz.

    Antes era una lista a mano y se quedaba corta: cada módulo nuevo
    (relevo_ffmpeg, obs_*, overlay_*, programados…) se quedaba fuera del
    smoke sin que nadie lo notara. Es de GUI si importa wx a nivel de módulo;
    los que lo importan dentro de una función (main) siguen siendo puros.
    """
    puros, gui = [], []
    for nombre in sorted(os.listdir(AQUI)):
        if not nombre.endswith(".py") or nombre == os.path.basename(__file__):
            continue
        with open(os.path.join(AQUI, nombre), encoding="utf-8", errors="replace") as f:
            fuente = f.read()
        modulo = nombre[:-3]
        if re.search(r"^(?:import wx|from wx)", fuente, re.M):
            gui.append(modulo)
        else:
            puros.append(modulo)
    return puros, gui


_MODULOS_PUROS, _MODULOS_GUI = _modulos_de_la_raiz()

_PREFIJO_TITULO = "YTChat TTS"
_PROCESOS_APLICACION = {"python.exe", "pythonw.exe", "ytchattts.exe"}


def ventana_es_de_la_aplicacion(titulo: str, nombre_proceso: str) -> bool:
    """Indica si título y proceso identifican la ventana de la aplicación."""
    return (titulo.startswith(_PREFIJO_TITULO)
            and nombre_proceso.lower() in _PROCESOS_APLICACION)


def interactivos_sin_nombre(controles) -> list[str]:
    """Tipos de control interactivo que no tienen nombre accesible."""
    return [tipo for tipo, nombre in controles
            if tipo in _INTERACTIVOS and not nombre]


def _nombre_proceso(pid: int) -> str:
    """Devuelve el nombre de imagen del proceso indicado en Windows."""
    resultado = subprocess.run(
        ["tasklist", "/fi", f"PID eq {pid}", "/fo", "csv", "/nh"],
        capture_output=True, text=True, encoding="mbcs", errors="replace",
        check=False)
    filas = list(csv.reader(resultado.stdout.splitlines()))
    return filas[0][0] if filas and filas[0] else ""


def _titulo(texto):
    print("\n" + "=" * 60)
    print("  " + texto)
    print("=" * 60)


def fase1_logica() -> bool:
    _titulo("FASE 1 — Importar lógica pura (cualquier SO)")
    ok = True
    for nombre in _MODULOS_PUROS:
        try:
            __import__(nombre)
            print(f"  [ok]    import {nombre}")
        except Exception as exc:
            ok = False
            print(f"  [FALLO] import {nombre}: {exc.__class__.__name__}: {exc}")
    return ok


def fase2_gui() -> bool:
    _titulo("FASE 2 — Importar módulos de GUI (necesita wxPython)")
    try:
        import wx  # noqa: F401
    except ImportError:
        print("  [saltada] wxPython no está instalado. En Windows:")
        print("            pip install -r requirements.txt")
        return True  # no es un fallo, solo no aplica en este entorno
    ok = True
    print(f"  wxPython {wx.version()}")
    for nombre in _MODULOS_GUI:
        try:
            __import__(nombre)
            print(f"  [ok]    import {nombre}")
        except Exception as exc:
            ok = False
            print(f"  [FALLO] import {nombre}: {exc.__class__.__name__}: {exc}")
    return ok


def _recorrer(win):
    """Devuelve lista de (tipo, nombre) de win y sus descendientes."""
    salida = []
    try:
        elementos = [win] + win.descendants()
    except Exception as exc:
        print(f"  No se pudo recorrer la ventana: {exc}")
        return salida
    for el in elementos:
        try:
            info = el.element_info
            salida.append((info.control_type or "?", (info.name or "").strip()))
        except Exception:
            pass
    return salida


def fase3_accesibilidad() -> bool:
    _titulo("FASE 3 — Árbol de accesibilidad (solo Windows + pywinauto)")
    if sys.platform != "win32":
        print("  [saltada] No es Windows; no hay árbol UI Automation que leer.")
        return True
    try:
        import time
        from pywinauto import Application, Desktop
    except ImportError:
        print("  [saltada] pywinauto no está instalado.  pip install pywinauto")
        return True

    main_py = os.path.join(AQUI, "main.py")
    cmd = f'"{sys.executable}" "{main_py}"'
    print(f"  Lanzando: {cmd}")
    # wait_for_idle=False: el ejecutable lanzado es python.exe (proceso de
    # consola que luego abre la ventana wx). pywinauto, por defecto, llama a
    # WaitForInputIdle sobre ese proceso y falla con el error 1471 ("no es un
    # proceso GUI").
    #
    # Además, NO buscamos la ventana por el PID que lanzamos: bajo `uv` el
    # python.exe del venv es un trampolín que reejecuta el intérprete base en un
    # proceso hijo, y es ese hijo quien crea la ventana. Por eso localizamos la
    # ventana por título en todo el escritorio y luego cerramos su PID real.
    app = Application(backend="uia").start(cmd, work_dir=AQUI,
                                           wait_for_idle=False)
    win_pid = None
    try:
        procesos_descartados = []

        def _buscar_ventana():
            # Iteramos los top-level del escritorio y casamos por título. Es más
            # fiable con backend UIA que window(title_re=...).exists(), y nos da
            # directamente el wrapper sobre el que recorrer descendientes.
            try:
                for w in Desktop(backend="uia").windows():
                    try:
                        titulo = w.window_text() or ""
                        if not titulo.startswith(_PREFIJO_TITULO):
                            continue
                        nombre_proceso = _nombre_proceso(w.element_info.process_id)
                        # El título no basta: una carpeta abierta puede llamarse igual.
                        if ventana_es_de_la_aplicacion(titulo, nombre_proceso):
                            return w
                        procesos_descartados.append(nombre_proceso or "desconocido")
                    except Exception:
                        continue
            except Exception:
                pass
            return None

        # Sondeo manual hasta 25 s: la ventana puede tardar en aparecer.
        win = None
        limite = time.monotonic() + 25
        while time.monotonic() < limite:
            win = _buscar_ventana()
            if win is not None:
                break
            time.sleep(0.5)
        if win is None:
            mensaje = "la ventana 'YTChat TTS' no apareció en 25 s"
            if procesos_descartados:
                mensaje += ("; se descartó una ventana con ese título del proceso "
                            f"{procesos_descartados[-1]}")
            raise TimeoutError(mensaje)
        win_pid = win.element_info.process_id
        print("  Ventana visible. Recorriendo controles...\n")

        controles = _recorrer(win)
        for tipo, nombre in controles:
            etiqueta = nombre if nombre else "(SIN NOMBRE)"
            print(f"    {tipo:12s}  {etiqueta}")
        sin_nombre = interactivos_sin_nombre(controles)

        print(f"\n  Total de controles: {len(controles)}")
        if sin_nombre:
            print(f"  [AVISO ACCESIBILIDAD] {len(sin_nombre)} control(es) "
                  f"interactivo(s) SIN nombre: {', '.join(sin_nombre)}")
            return False
        print("  [ok] Todos los controles interactivos tienen nombre accesible.")
        return True
    except Exception as exc:
        print(f"  [FALLO] {exc.__class__.__name__}: {exc}")
        return False
    finally:
        cerrado = False
        # El proceso real de la ventana (hijo bajo uv) y el lanzado pueden ser
        # distintos: intentamos cerrar ambos.
        if win_pid is not None:
            try:
                Application(backend="uia").connect(process=win_pid).kill()
                cerrado = True
            except Exception:
                pass
        try:
            app.kill()
            cerrado = True
        except Exception:
            pass
        if cerrado:
            print("\n  Aplicación cerrada.")


def main():
    no_gui = "--no-gui" in sys.argv
    os.chdir(AQUI)
    if AQUI not in sys.path:
        sys.path.insert(0, AQUI)

    r1 = fase1_logica()
    r2 = fase2_gui()
    r3 = True if no_gui else fase3_accesibilidad()

    _titulo("RESUMEN")
    print(f"  Fase 1 (lógica):        {'OK' if r1 else 'FALLO'}")
    print(f"  Fase 2 (GUI imports):   {'OK' if r2 else 'FALLO'}")
    if no_gui:
        print("  Fase 3 (accesibilidad): omitida (--no-gui)")
    else:
        print(f"  Fase 3 (accesibilidad): {'OK' if r3 else 'FALLO / avisos'}")
    print()
    sys.exit(0 if (r1 and r2 and r3) else 1)


if __name__ == "__main__":
    main()
