@echo off
REM ==================================================================
REM  ciseau - lanceur Windows
REM  Double-clic : verifie les prerequis, installe ce qui manque la
REM  premiere fois, met yt-dlp a jour, puis ouvre l'interface.
REM  La fenetre noire EST le serveur : la laisser ouverte pendant
REM  l'utilisation, la fermer pour arreter ciseau.
REM ==================================================================
title ciseau
REM Toujours travailler depuis le dossier du projet (les extraits vont dans .\extraits)
cd /d "%~dp0"

REM --- Python : le lanceur "py" (installe avec Python) sinon "python" ---
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto :sans_python
%PY% --version >nul 2>nul || goto :sans_python

REM --- ffmpeg : indispensable pour couper ---
where ffmpeg >nul 2>nul || goto :sans_ffmpeg

REM --- Premiere utilisation : installation de ciseau et de ses dependances ---
%PY% -c "import yt_dlp" >nul 2>nul
if errorlevel 1 (
    echo Premiere utilisation : installation des dependances, une minute...
    %PY% -m pip install -e .
    if errorlevel 1 goto :echec_pip
) else (
    REM YouTube change souvent : un yt-dlp a jour regle la plupart des pannes.
    echo Mise a jour de yt-dlp...
    %PY% -m pip install -q -U "yt-dlp[default]" >nul 2>nul
)

REM --- Deno : yt-dlp s'en sert pour YouTube (conseille, pas bloquant) ---
where deno >nul 2>nul || (
    echo.
    echo Conseil : pour YouTube, installe Deno puis relance ciseau :
    echo     winget install DenoLand.Deno
    echo.
)

REM --- Lancement de l'interface (ouvre le navigateur) ---
%PY% -m ciseau ui
echo.
echo ciseau s'est arrete.
pause
exit /b

:sans_python
echo Python est introuvable.
echo Installe-le avec la commande suivante dans PowerShell, puis relance ciseau.bat :
echo     winget install Python.Python.3.12
pause
exit /b 1

:sans_ffmpeg
echo ffmpeg est introuvable.
echo Installe-le avec la commande suivante dans PowerShell, FERME cette fenetre,
echo puis relance ciseau.bat :
echo     winget install Gyan.FFmpeg
pause
exit /b 1

:echec_pip
echo L'installation des dependances a echoue (voir le message ci-dessus).
echo Verifie ta connexion internet puis relance ciseau.bat.
pause
exit /b 1
