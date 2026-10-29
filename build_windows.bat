@echo off
setlocal
cd /d "%~dp0"
call native_tsf\build.cmd
if errorlevel 1 exit /b 1
cd /d "%~dp0"
call native_tsf\tests\run_host.cmd x64
if errorlevel 1 exit /b 1
cd /d "%~dp0"
call native_tsf\tests\run_host.cmd x86
if errorlevel 1 exit /b 1
cd /d "%~dp0"
py -3.11 -m venv .venv
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe tests\run_tests.py
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m PyInstaller --noconfirm --onedir --windowed --version-file version_info.txt --icon stoom.ico --add-data "stoom.ico;." --name STOOMShiftTranslator --exclude-module spacy --exclude-module stanza --exclude-module torch --exclude-module argostranslate main.py
if errorlevel 1 exit /b 1
where ISCC.exe >nul 2>nul
if errorlevel 1 (
  if not exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" (
    echo Inno Setup 6 is required to build the installer.
    exit /b 1
  )
  set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
) else (
  set "ISCC=ISCC.exe"
)
rem Each changed native build needs its own immutable installation directory.
if not defined STOOM_NATIVE_VERSION set "STOOM_NATIVE_VERSION=0.6.3-20261029.4"
"%ISCC%" "/DNativeBuildRoot=%~dp0native_tsf\build" "/DComponentVersion=%STOOM_NATIVE_VERSION%" native_tsf\installer.iss
if errorlevel 1 exit /b 1
"%ISCC%" "/DTsfSetup=%~dp0native_tsf\dist\STOOM-TextService-%STOOM_NATIVE_VERSION%-setup.exe" installer.iss
if errorlevel 1 exit /b 1
echo Build complete: dist\STOOM-Translator-v063-TSF-setup.exe
pause
