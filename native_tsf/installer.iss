; Native TSF registration uses the machine catalog. Keep this small privileged
; component separate from the per-user translator and its downloaded models.
; Bump ComponentVersion for every shipped native build: loaded DLLs belong to
; other applications and must not be overwritten in place during an upgrade.
#ifndef ComponentVersion
#define ComponentVersion "0.6.11-20261030.7"
#endif
#ifndef NativeBuildRoot
#define NativeBuildRoot "build"
#endif

[Setup]
AppId={{A685965F-1A24-4497-A024-0C195DFDB8E9}
AppName=STOOM TSF 입력 지원
AppVersion={#ComponentVersion}
DefaultDirName={autopf}\STOOM\TextService
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UsePreviousAppDir=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
SetupMutex=Global\STOOMTextService.Setup
CloseApplications=no
RestartApplications=no
OutputDir=dist
OutputBaseFilename=STOOM-TextService-{#ComponentVersion}-setup
SetupIconFile=..\stoom.ico
WizardImageFile=..\branding\sst\installer.bmp
WizardSmallImageFile=..\branding\sst\installer-small.bmp
UninstallDisplayIcon={app}\{#ComponentVersion}\stoom.ico
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "{#NativeBuildRoot}\x64\STOOMTextService.dll"; DestDir: "{app}\{#ComponentVersion}\x64"; Flags: ignoreversion 64bit regserver restartreplace uninsrestartdelete
Source: "{#NativeBuildRoot}\x86\STOOMTextService.dll"; DestDir: "{app}\{#ComponentVersion}\x86"; Flags: ignoreversion 32bit regserver restartreplace uninsrestartdelete
Source: "{#NativeBuildRoot}\x64\STOOMTextServiceHost.exe"; DestDir: "{app}\{#ComponentVersion}\x64"; Flags: ignoreversion
Source: "{#NativeBuildRoot}\x86\STOOMTextServiceHost.exe"; DestDir: "{app}\{#ComponentVersion}\x86"; Flags: ignoreversion
Source: "..\stoom.ico"; DestDir: "{app}\{#ComponentVersion}"; Flags: ignoreversion

[Messages]
FinishedLabel=STOOM TSF 입력 지원을 설치했습니다.%n%n이미 실행 중인 편집기는 종료 후 다시 열어야 새 입력 지원이 적용될 수 있습니다. 다운로드한 번역 모델과 설정은 그대로 유지됩니다.

[Code]
function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfoInfo,
  MemoTypeInfoInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := 'Windows TSF 입력 서비스 (32비트 및 64비트)' + NewLine +
    MemoDirInfoInfo + NewLine + NewLine +
    'Windows 입력 서비스 등록을 위해 관리자 권한을 사용합니다.' + NewLine +
    '편집기를 강제로 종료하지 않습니다. 설치 후 열린 편집기를 다시 열어 주세요.' + NewLine +
    '번역 모델과 사용자 설정은 변경하지 않습니다.';
end;
