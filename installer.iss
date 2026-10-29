#define AppName "STOOM Shift Translator"
#define AppExe "STOOMShiftTranslator.exe"
#ifndef BuildRoot
#define BuildRoot "dist"
#endif
[Setup]
AppId={{66A24CEC-81E4-4FC0-9B1F-0E7E4214FB52}
AppName={#AppName}
AppVersion=0.5
DefaultDirName={localappdata}\Programs\STOOM Shift Translator
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=STOOM-Translator-v05-setup
SetupIconFile=stoom.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
[Files]
Source: "{#BuildRoot}\STOOMShiftTranslator\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "바탕 화면에 바로가기 만들기"; Flags: unchecked
