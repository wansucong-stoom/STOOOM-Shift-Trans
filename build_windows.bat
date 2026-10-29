@echo off
setlocal
cd /d "%~dp0"
py -3.11 -m venv .venv
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe tests\run_tests.py
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m PyInstaller --noconfirm --onedir --windowed --icon stoom.ico --add-data "stoom.ico;." --name STOOMShiftTranslator --exclude-module spacy --exclude-module stanza --exclude-module torch --exclude-module argostranslate main.py
if errorlevel 1 exit /b 1
where ISCC.exe >nul 2>nul
if errorlevel 1 (
  if not exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" (
    echo Inno Setup 6 is required to build the installer.
    exit /b 1
  )
  "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss
) else (
  ISCC.exe installer.iss
)
if errorlevel 1 exit /b 1
echo Build complete: dist\STOOM-Translator-v05-setup.exe
pause
