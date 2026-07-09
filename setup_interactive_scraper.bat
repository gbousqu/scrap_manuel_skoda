@echo off
setlocal
cd /d "%~dp0"
python setup_local_env.py --skip-pdf %*
if errorlevel 1 exit /b 1
echo.
echo Tâche scraper enregistrée. Le bouton du viewer peut ouvrir le navigateur.
pause
