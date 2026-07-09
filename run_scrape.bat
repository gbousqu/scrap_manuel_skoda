@echo off
setlocal
cd /d "%~dp0"

if exist "pdf_env.bat" call "pdf_env.bat"

set "PYTHON=C:\Python313\python.exe"
if exist "pdf_python_path.txt" set /p PYTHON=<pdf_python_path.txt

echo ==== %DATE% %TIME% ==== > scraper_last_run.log
echo Utilisation de %PYTHON%>> scraper_last_run.log

"%PYTHON%" -u "%~dp0scrape_manual_skoda.py" %* >> scraper_last_run.log 2>&1
set ERR=%ERRORLEVEL%
type scraper_last_run.log >> scraper_run.log 2>nul
exit /b %ERR%
