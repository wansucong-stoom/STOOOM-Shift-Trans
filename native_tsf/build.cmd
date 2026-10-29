@echo off
setlocal
cd /d "%~dp0"
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSROOT=%%i"
if not defined VSROOT exit /b 2
call :build x64 || exit /b 1
call :build x86 || exit /b 1
exit /b 0
:build
setlocal
call "%VSROOT%\VC\Auxiliary\Build\vcvarsall.bat" %1 >nul || exit /b 1
if not exist build\%1 mkdir build\%1
rc /nologo /fo build\%1\service.res service.rc || exit /b 1
cl /nologo /std:c++17 /EHsc /MT /O2 /W4 /utf-8 /DUNICODE /D_UNICODE /LD service.cpp range.cpp registration.cpp build\%1\service.res /Fo:build\%1\ /Fe:build\%1\STOOMTextService.dll /link /DEF:service.def ole32.lib oleaut32.lib uuid.lib advapi32.lib user32.lib || exit /b 1
cl /nologo /std:c++17 /EHsc /MT /O2 /W4 /utf-8 /DUNICODE /D_UNICODE activation.cpp build\%1\service.res /Fo:build\%1\ /Fe:build\%1\STOOMTextServiceHost.exe /link ole32.lib oleaut32.lib uuid.lib advapi32.lib user32.lib || exit /b 1
exit /b 0
