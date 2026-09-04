@echo off
REM ============================================================================
REM  YTChat TTS - Instalacion del entorno de desarrollo con uv
REM
REM  Crea el entorno virtual (.venv) con la version correcta de Python,
REM  instala las dependencias de requirements.txt y genera los sonidos.
REM  Si uv no esta instalado, se ofrece instalarlo automaticamente.
REM ============================================================================
cd /d "%~dp0"

call :ASEGURAR_UV
if errorlevel 1 ( pause & exit /b 1 )

echo == Creando el entorno (.venv) con uv ==
call uv venv --python 3.11
if errorlevel 1 ( echo ERROR creando el entorno. & pause & exit /b 1 )

echo == Instalando dependencias ==
call uv pip install -r requirements.txt
if errorlevel 1 ( echo ERROR instalando dependencias. & pause & exit /b 1 )

echo == Generando los sonidos (temas default y suave) ==
call uv run python sound_gen.py

echo.
echo Entorno listo. Para arrancar la aplicacion, ejecuta  ejecutar.bat
echo (o bien:  uv run python main.py)
echo.
set /p RUN="Abrir la aplicacion ahora? (s/N): "
if /i "%RUN%"=="s" call uv run python main.py
exit /b 0

REM ----------------------------------------------------------------------------
:ASEGURAR_UV
where uv >nul 2>nul
if not errorlevel 1 exit /b 0
echo uv no esta instalado.
set /p INS="Instalarlo ahora automaticamente? (S/n): "
if /i "%INS%"=="n" (
    echo Instalalo a mano en PowerShell:  irm https://astral.sh/uv/install.ps1 ^| iex
    exit /b 1
)
echo Instalando uv...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
REM El instalador deja uv en %USERPROFILE%\.local\bin; lo anadimos a esta sesion.
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul
if errorlevel 1 (
    echo uv se instalo pero no esta en el PATH de esta ventana.
    echo Cierra esta ventana, abre una nueva y vuelve a ejecutar instalar.bat
    exit /b 1
)
exit /b 0
