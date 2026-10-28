@echo off
setlocal
cd /d "%~dp0"
py -3.11 -m venv .venv
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed --icon stoom.ico --add-data "stoom.ico;." --name STOOMShiftTranslator-v05 --exclude-module spacy --exclude-module stanza --exclude-module torch --exclude-module argostranslate main.py
if errorlevel 1 exit /b 1
echo Build complete: dist\STOOMShiftTranslator-v05.exe
pause
