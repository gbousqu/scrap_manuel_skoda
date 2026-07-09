@echo off
setlocal
cd /d "%~dp0"

set "MANUAL=%~1"
if "%MANUAL%"=="" if exist "pdf_build_target.txt" set /p MANUAL=<pdf_build_target.txt
if "%MANUAL%"=="" set "MANUAL=elroq"

if exist "pdf_env.bat" call "pdf_env.bat"

set "PYTHON=C:\Python313\python.exe"
if exist "pdf_python_path.txt" set /p PYTHON=<pdf_python_path.txt

echo ==== %DATE% %TIME% manual=%MANUAL% ====>> "manuals\%MANUAL%\pdf_build.log"
echo Utilisation de %PYTHON%>> "manuals\%MANUAL%\pdf_build.log"
echo USERPROFILE=%USERPROFILE%>> "manuals\%MANUAL%\pdf_build.log"
echo PYTHONPATH=%PYTHONPATH%>> "manuals\%MANUAL%\pdf_build.log"

"%PYTHON%" "%~dp0build_manual_pdf.py" --manual %MANUAL% >> "manuals\%MANUAL%\pdf_build.log" 2>&1
exit /b %ERRORLEVEL%
