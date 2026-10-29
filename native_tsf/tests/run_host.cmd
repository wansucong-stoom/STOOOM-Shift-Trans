@echo off
setlocal
cd /d "%~dp0.."
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSROOT=%%i"
if not defined VSROOT exit /b 2
set "HOST_ARCH=%~1"
if not defined HOST_ARCH set "HOST_ARCH=x64"
call "%VSROOT%\VC\Auxiliary\Build\vcvarsall.bat" %HOST_ARCH% >nul || exit /b 1
if not exist build\test-%HOST_ARCH% mkdir build\test-%HOST_ARCH%
cl /nologo /std:c++17 /EHsc /MT /W4 /utf-8 /DUNICODE /D_UNICODE /I. tests\host.cpp range.cpp /Fo:build\test-%HOST_ARCH%\ /Fe:build\test-%HOST_ARCH%\STOOMTsfRangeTest.exe /link ole32.lib oleaut32.lib uuid.lib user32.lib || exit /b 1
build\test-%HOST_ARCH%\STOOMTsfRangeTest.exe
if errorlevel 1 exit /b 1
cl /nologo /std:c++17 /EHsc /MT /W4 /utf-8 /DUNICODE /D_UNICODE /I. tests\range_test.cpp range.cpp /Fo:build\test-%HOST_ARCH%\ /Fe:build\test-%HOST_ARCH%\range_test.exe /link ole32.lib oleaut32.lib uuid.lib user32.lib || exit /b 1
build\test-%HOST_ARCH%\range_test.exe || exit /b 1
cl /nologo /std:c++17 /EHsc /MT /W4 /utf-8 /DUNICODE /D_UNICODE /I. tests\service_lifecycle.cpp /Fo:build\test-%HOST_ARCH%\ /Fe:build\test-%HOST_ARCH%\service_lifecycle.exe /link ole32.lib oleaut32.lib uuid.lib user32.lib || exit /b 1
build\test-%HOST_ARCH%\service_lifecycle.exe "%CD%\build\%HOST_ARCH%\STOOMTextService.dll"
exit /b %errorlevel%
