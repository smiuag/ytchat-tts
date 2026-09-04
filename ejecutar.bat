@echo off
REM ============================================================================
REM  YTChat TTS - Arranca la aplicacion desde el codigo fuente (con uv).
REM  Si falta el entorno o alguna dependencia, uv los prepara solo.
REM ============================================================================
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 ( echo ERROR: uv no esta instalado. Ejecuta primero instalar.bat & pause & exit /b 1 )

REM uv run crea/sincroniza el entorno si hace falta antes de arrancar.
if not exist ".venv" call uv venv --python 3.11
call uv pip install -r requirements.txt >nul 2>nul
if not exist "sounds\themes\default\app_inicio.wav" call uv run python sound_gen.py >nul

call uv run python main.py
if errorlevel 1 pause
