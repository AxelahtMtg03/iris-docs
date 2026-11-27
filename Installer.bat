@echo off
rem Installation d'Iris en un double-clic (Windows). Sans accents : cmd les lit mal.
setlocal
title Installation d'Iris
cd /d "%~dp0"
if not exist installer.py goto unzip
if not exist requirements.txt goto unzip

echo.
echo   Installation d'Iris
echo.
echo   Compte 10 a 20 minutes, une connexion internet et environ 3 Go libres.
echo   Seront installes s'ils manquent : Python, LibreOffice et Tesseract.
echo   En continuant, tu acceptes leurs licences.
echo.
echo   Appuie sur une touche pour commencer (ou ferme la fenetre pour annuler).
pause >nul

call :find_python
if defined PY goto install
echo.
echo   Installation de Python...
winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
call :find_python
if not defined PY goto nopython

:install
%PY% installer.py
if errorlevel 1 goto failed
echo.
echo   Termine. Iris s'ouvre ; tu le retrouveras sur le bureau et dans le menu Demarrer.
goto end

:unzip
echo.
echo   Fais d'abord un clic droit sur le fichier ZIP, puis "Extraire tout".
echo   Ouvre ensuite le dossier extrait et relance Installer.bat.
goto end

:nopython
echo.
echo   Python n'a pas pu etre installe automatiquement.
echo   Installe Python 3.13 depuis https://www.python.org/downloads/ puis relance ce fichier.
goto end

:failed
echo.
echo   L'installation a echoue. Ferme Iris s'il est ouvert, verifie internet,
echo   puis relance Installer.bat : il reprend ou il s'est arrete.

:end
echo.
pause
exit /b

rem Cherche un Python compatible (3.10 a 3.13).
:find_python
set "PY="
for %%V in (3.13 3.12 3.11 3.10) do if not defined PY py -%%V -c "" >nul 2>&1 && set "PY=py -%%V"
for %%V in (313 312 311 310) do if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
exit /b
