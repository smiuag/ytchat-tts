@echo off
REM ============================================================================
REM  YTChat TTS - Construye el ejecutable distribuible con PyInstaller (onedir)
REM
REM  Resultado: carpeta "YTChat TTS" en la raiz del proyecto, lista para
REM  comprimir (7-Zip / ZIP) y enviar. Quien la reciba solo descomprime y abre
REM  YTChatTTS.exe; no necesita Python ni nada instalado.
REM
REM  Modo onedir: el .exe queda junto a la carpeta _internal (dependencias) y a
REM  los archivos editables (config.ini, sounds.ini, sounds/). Es mas fiable y
REM  arranca mas rapido que --onefile, y mantiene pocos elementos sueltos.
REM ============================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 ( echo ERROR: uv no esta instalado. Ver README. & pause & exit /b 1 )

echo == Preparando entorno (uv) ==
REM Reutiliza el .venv si ya existe; si no, lo crea con Python 3.11 (las
REM dependencias, sobre todo wxPython, tienen wheels para 3.11).
if not exist ".venv" (
  call uv venv --python 3.11
  if errorlevel 1 ( echo ERROR creando el entorno. & pause & exit /b 1 )
)
call uv pip install -r requirements.txt
if errorlevel 1 ( echo ERROR instalando dependencias. & pause & exit /b 1 )
call uv pip install pyinstaller
if errorlevel 1 ( echo ERROR instalando PyInstaller. & pause & exit /b 1 )

echo == Generando los sonidos ==
call uv run python sound_gen.py >nul

echo == Localizando el discovery doc de YouTube (solo ese, no el cache entero) ==
for /f "delims=" %%i in ('uv run python -c "import googleapiclient,os;print(os.path.join(os.path.dirname(googleapiclient.__file__),'discovery_cache','documents','youtube.v3.json'))"') do set "YTDOC=%%i"
echo    %YTDOC%

echo == Localizando VLC (para empaquetar libVLC y que el amigo no instale nada) ==
set "VLCDIR="
if exist "C:\Program Files\VideoLAN\VLC\libvlc.dll" set "VLCDIR=C:\Program Files\VideoLAN\VLC"
if not defined VLCDIR if exist "C:\Program Files (x86)\VideoLAN\VLC\libvlc.dll" set "VLCDIR=C:\Program Files (x86)\VideoLAN\VLC"
if defined VLCDIR ( echo    %VLCDIR% ) else ( echo    AVISO: VLC no encontrado. El paquete saldra SIN reproductor. Instala VLC y reconstruye. )

REM Icono opcional: si dejas un app.ico en la raiz, se usa para el .exe.
REM Ruta absoluta: PyInstaller resuelve --icon relativo a --specpath (build).
set "ICONO="
if exist "app.ico" set "ICONO=--icon "%~dp0app.ico""

echo == Generando documentacion HTML (Leeme) ==
REM No fatal: si pandoc no esta, se usan los HTML ya versionados en docs/.
call uv run python generar_docs.py || echo    AVISO: no se pudo regenerar; se usara la copia versionada en docs/.

echo == Empaquetando con PyInstaller ==
REM --noupx: NO comprimir con UPX. UPX dispara muchos falsos positivos de
REM antivirus; sin el, el .exe levanta menos sospechas en el PC del amigo.
REM El modulo da metadatos rapidos y el ejecutable mantiene flujos y descargas.
REM yt-dlp carga extractores al vuelo, por eso se recopila completo.
REM --exclude-module imageio_ffmpeg: su hook metia un segundo ffmpeg.exe en
REM _internal; la app empaquetada usa el que se copia a la raiz mas abajo
REM (ffmpeg_bin.ruta_ffmpeg lo busca primero), asi que el otro sobraba.
call uv run pyinstaller main.py ^
  --name YTChatTTS ^
  --onedir --windowed --noconfirm --clean --noupx ^
  --distpath dist --workpath build --specpath build ^
  %ICONO% ^
  --collect-all accessible_output2 ^
  --collect-submodules googleapiclient ^
  --collect-submodules google_auth_oauthlib ^
  --collect-submodules pytchat ^
  --collect-all TikTokLive ^
  --collect-all yt_dlp ^
  --exclude-module imageio_ffmpeg ^
  --hidden-import vlc ^
  --add-data "!YTDOC!;googleapiclient/discovery_cache/documents"
if errorlevel 1 ( echo ERROR en PyInstaller. & pause & exit /b 1 )

echo == Ensamblando la carpeta distribuible ==
REM Version desde config.py (fuente unica): nombra la carpeta y el zip como
REM "YTChat TTS vX.Y.Z", asi el archivo que se manda y la carpeta al descomprimir
REM dejan clara la version.
for /f "delims=" %%v in ('uv run python -c "import config;print(config.APP_VERSION)"') do set "VER=%%v"
if not defined VER ( echo ERROR: no se pudo leer la version de config.py. & pause & exit /b 1 )
set "OUT=YTChat TTS v%VER%"
REM Ojo: "^>" escapado; un ">" literal en echo redirige y crea un archivo basura.
echo    Version %VER%  -^>  "%OUT%"
REM Limpia builds previos de CUALQUIER version para no acumular carpetas/zips.
for /d %%d in ("YTChat TTS v*") do rmdir /s /q "%%d"
if exist "YTChat TTS" rmdir /s /q "YTChat TTS"
if exist "%OUT%" rmdir /s /q "%OUT%"

REM robocopy devuelve codigos ^>=1 incluso en exito; no encadenamos errorlevel.
robocopy "dist\YTChatTTS" "%OUT%" /E /NFL /NDL /NJH /NJS /NP >nul
robocopy "sounds" "%OUT%\sounds" /E /NFL /NDL /NJH /NJS /NP >nul
robocopy "docs"   "%OUT%\docs"   /E /NFL /NDL /NJH /NJS /NP >nul
robocopy "web"    "%OUT%\web"    /E /NFL /NDL /NJH /NJS /NP >nul
if defined VLCDIR (
  echo == Empaquetando libVLC junto al exe: plugins de audio y video ==
  robocopy "%VLCDIR%" "%OUT%\vlc" libvlc.dll libvlccore.dll /NFL /NDL /NJH /NJS /NP >nul
  REM Plugins necesarios para el reproductor embebido: red HTTP/TLS y demux.
  REM DASH/HLS, codecs y salida de audio y video. La imagen va con set_hwnd.
  REM Se deja fuera lo que no usamos -GUI/skins, visualizaciones- para reducir
  REM tamano y acelerar el arranque. OJO: sin parentesis en estos REM, romperian
  REM el bloque IF.
  for %%d in (access codec demux audio_output audio_filter audio_mixer packetizer stream_filter stream_extractor misc keystore logger video_output video_chroma video_filter d3d9 d3d11) do (
    robocopy "%VLCDIR%\plugins\%%d" "%OUT%\vlc\plugins\%%d" /E /NFL /NDL /NJH /NJS /NP >nul
  )
  REM Generar la cache de plugins del set recortado evita el escaneo en el
  REM primer arranque, que hacia que la app tardara en abrir.
  if exist "%VLCDIR%\vlc-cache-gen.exe" "%VLCDIR%\vlc-cache-gen.exe" "%OUT%\vlc\plugins" >nul 2>nul
)

echo == Empaquetando ffmpeg (mux audio+video de yt-dlp en el gestor de descargas) ==
REM imageio-ffmpeg trae un ffmpeg.exe portable en site-packages. Lo copiamos
REM junto al .exe para que el gestor de descargas (yt-dlp + FFmpegExtractAudio)
REM pueda muxear sin que el usuario instale nada. Sin parentesis en estos REM,
REM romperian el bloque IF.
set "FFEXE="
for /f "delims=" %%f in ('uv run python -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"') do set "FFEXE=%%f"
if defined FFEXE (
  echo    %FFEXE%
  copy /y "%FFEXE%" "%OUT%\ffmpeg.exe" >nul
  if not exist "%OUT%\ffmpeg.exe" echo    AVISO: no se pudo copiar ffmpeg; el paquete saldra SIN ffmpeg.
) else (
  echo    AVISO: imageio-ffmpeg no encontrado. El paquete saldra SIN ffmpeg; las descargas de audio fallaran.
)
echo == Empaquetando yt-dlp independiente ==
echo    La primera vez descarga yt-dlp desde GitHub y puede tardar.
call uv run python -c "import shutil,ytdlp_bin; from pathlib import Path; r=ytdlp_bin.asegurar_ytdlp(); p=ytdlp_bin.ruta_ytdlp(); d=Path(r'%OUT%') / 'yt-dlp.exe'; shutil.copy2(p,d) if r.correcta and p else None; print('   ' + ('resultado: ' if r.correcta else 'AVISO: ') + r.motivo)"
REM El lanzador del entorno pesa unos 45 KB; el ejecutable oficial observado
REM el 21/08/2026 pesa unos 17 MB. Un MiB deja margen y descarta el lanzador.
set "YTDLP_MIN_BYTES=1048576"
if not exist "%OUT%\yt-dlp.exe" (
  echo    AVISO: no se obtuvo yt-dlp.exe de verdad; el paquete saldra sin el programa independiente.
) else (
  for %%f in ("%OUT%\yt-dlp.exe") do if %%~zf LSS %YTDLP_MIN_BYTES% (
    echo    AVISO: yt-dlp.exe pesa %%~zf bytes y no es el programa independiente; se elimina.
    del /q "%OUT%\yt-dlp.exe"
  ) else (
    echo    OK: yt-dlp.exe independiente copiado, %%~zf bytes.
  )
)
REM config.ini se genera SIEMPRE desde la fuente canonica
REM config_predeterminada.py. No se copia el config.ini local ni se depende
REM de git para este archivo. Si falla la generacion, la construccion se detiene.
call uv run python config_predeterminada.py "%OUT%\config.ini"
if errorlevel 1 ( echo ERROR: no se pudo generar config.ini desde config_predeterminada.py. & pause & exit /b 1 )
REM sounds.ini sigue con el tratamiento previo: intentar git, si no local.
git show HEAD:sounds.ini > "%OUT%\sounds.ini" 2>nul
if errorlevel 1 ( echo    AVISO: sin git; sounds.ini local ^(puede llevar ajustes personales^). & copy /y "sounds.ini" "%OUT%\" >nul )
copy /y "LICENSE"    "%OUT%\" >nul
REM Documentacion de cara al usuario en HTML (se abre con doble clic; el amigo
REM no tiene por que saber abrir un Markdown). Se genera con generar_docs.py y
REM viaja tambien dentro de docs/. La dejamos ademas en la raiz, a la vista. El
REM historial de versiones (CHANGELOG) va como docs/CHANGELOG.html, enlazado
REM desde el propio Leeme ("que hay de nuevo").
copy /y "docs\README.html" "%OUT%\Leeme.html" >nul
REM Solo en la raiz: sus enlaces (docs/...) se calculan desde ahi y dentro de docs/ quedaban rotos.
del /q "%OUT%\docs\README.html" >nul 2>&1

REM Por higiene: nada de log ni credenciales en el paquete que se envia.
del /q "%OUT%\ytchat.log" 2>nul
del /q "%OUT%\credenciales.json" 2>nul

echo == Comprobando el modulo yt-dlp ==
dir /b /s "%OUT%\_internal\yt_dlp\*" >nul 2>nul
if errorlevel 1 (
  echo    AVISO: yt_dlp no viaja en el paquete; al conectar saldra lento porque falta el modulo.
)

echo == Comprimiendo a "%OUT%.zip" ==
REM Borra zips de cualquier version anterior (incluido el viejo sin version).
del /q "YTChat TTS.zip" 2>nul
del /q "YTChat TTS v*.zip" 2>nul
powershell -NoProfile -Command "Compress-Archive -Path '%OUT%' -DestinationPath '%OUT%.zip' -Force"

echo.
echo ============================================================================
echo  Listo.
echo    Carpeta: "%OUT%"        (para probar: "%OUT%\YTChatTTS.exe")
echo    ZIP    : "%OUT%.zip"    (esto es lo que mandas al amigo)
echo  El amigo solo descomprime y abre YTChatTTS.exe; no necesita nada mas.
echo ============================================================================
pause
