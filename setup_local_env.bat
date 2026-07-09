@echo off
setlocal
cd /d "%~dp0"
python setup_local_env.py %*
if errorlevel 1 exit /b 1
echo.
echo Configuration OK. Le viewer peut lancer le scraping et l'export PDF.
pause
