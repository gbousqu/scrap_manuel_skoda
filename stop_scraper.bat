@echo off
cd /d "%~dp0"
if exist "pdf_env.bat" call "pdf_env.bat"
set "PYTHON=C:\Python313\python.exe"
if exist "pdf_python_path.txt" set /p PYTHON=<pdf_python_path.txt
"%PYTHON%" "%~dp0stop_scraper.py"
pause
