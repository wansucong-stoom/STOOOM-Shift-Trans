@echo off
setlocal
cd /d "%~dp0"
rem Optional developer-only native TSF verification; not an EXE installer build.
if /I "%~1"=="--with-native-tests" (
  call native_tsf\build.cmd
  if errorlevel 1 exit /b 1
  cd /d "%~dp0"
  call native_tsf\tests\run_host.cmd x64
  if errorlevel 1 exit /b 1
  cd /d "%~dp0"
  call native_tsf\tests\run_host.cmd x86
  if errorlevel 1 exit /b 1
  cd /d "%~dp0"
)
py -3.11 -m venv .venv
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe tests\run_tests.py
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --onedir --windowed --version-file version_info.txt --icon stoom.ico --add-data "stoom.ico;." --add-data "branding/sst/lockup-light-3x.png;branding/sst" --add-data "branding/sst/stoom.ico;branding/sst" --add-data "branding/OFL-Inter.txt;branding" --name STOOMShiftTranslator --exclude-module spacy --exclude-module stanza --exclude-module torch --exclude-module argostranslate main.py
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe build_msi.py
if errorlevel 1 exit /b 1
for /f %%V in ('.venv\Scripts\python.exe -c "import release_updates; print(release_updates.VERSION.replace(chr(46), str()))"') do set "SST_VERSION=%%V"
if not defined SST_VERSION exit /b 1
set "SST_MSI=dist\STOOM-Translator-v%SST_VERSION%-TSF-setup.msi"
.venv\Scripts\python.exe verify_msi.py "%SST_MSI%" "work\msi-verify-%RANDOM%-%RANDOM%"
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -c "import hashlib; from pathlib import Path; p=Path(r'%SST_MSI%'); (p.parent/'SHA256SUMS.txt').write_text(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+chr(10),encoding='utf-8')"
if errorlevel 1 exit /b 1
echo Build complete: %SST_MSI%
pause
