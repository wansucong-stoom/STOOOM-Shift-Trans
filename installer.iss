#define AppName "STOOM Shift Translator"
#define AppExe "STOOMShiftTranslator.exe"
#ifndef AppVersion
#define AppVersion "0.6.5"
#endif
#ifndef BuildRoot
#define BuildRoot "dist"
#endif
[Setup]
AppId={{66A24CEC-81E4-4FC0-9B1F-0E7E4214FB52}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\STOOM Shift Translator
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes
DisableDirPage=auto
DisableProgramGroupPage=auto
SetupMutex=Local\STOOMShiftTranslator05.Setup
; Loaded TSF modules may belong to editors. Never ask Restart Manager to close
; unrelated apps just because a translation DLL is loaded in their process.
CloseApplications=no
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=STOOM-Translator-v065-TSF-setup
SetupIconFile=stoom.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
[Files]
Source: "{#BuildRoot}\STOOMShiftTranslator\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifdef TsfSetup
Source: "{#TsfSetup}"; DestName: "STOOMTextService-setup.exe"; Flags: dontcopy
#endif
[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "바탕 화면에 바로가기 만들기"; Flags: unchecked
#ifdef TsfSetup
Name: "tsf"; Description: "Windows TSF 입력 지원 설치·업데이트 (관리자 승인 필요)"
#endif

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "--after-update"; Description: "STOOM Shift Translator 실행"; Flags: nowait postinstall skipifsilent runasoriginaluser; Check: not IsAppUpdate
Filename: "{app}\{#AppExe}"; Parameters: "--after-update"; Flags: nowait runasoriginaluser; Check: IsAppUpdate

[Code]
const
  AppMutexName = 'Local\STOOMShiftTranslator05.SingleInstance';
  UpdateEventName = 'Local\STOOMShiftTranslator05.UpdateRequested';
  EventModifyState = $0002;

var
  UpdateEventHandle: THandle;
#ifdef TsfSetup
  TsfInstalled: Boolean;
#endif

function IsAppUpdate: Boolean;
begin
  Result := ExpandConstant('{param:STOOMUPDATE|0}') = '1';
end;

function OpenEvent(DesiredAccess: LongWord; InheritHandle: Boolean;
  Name: String): THandle;
  external 'OpenEventW@kernel32.dll stdcall';
function SetEvent(EventHandle: THandle): Boolean;
  external 'SetEvent@kernel32.dll stdcall';
function ResetEvent(EventHandle: THandle): Boolean;
  external 'ResetEvent@kernel32.dll stdcall';
function CloseHandle(Handle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

procedure ClearUpdateRequest;
begin
  if UpdateEventHandle <> 0 then
  begin
    ResetEvent(UpdateEventHandle);
    CloseHandle(UpdateEventHandle);
    UpdateEventHandle := 0;
  end;
end;

function StopTranslator: Boolean;
var
  Attempt: Integer;
begin
  Result := not CheckForMutexes(AppMutexName);
  if Result then Exit;
  UpdateEventHandle := OpenEvent(EventModifyState, False, UpdateEventName);
  if UpdateEventHandle = 0 then Exit; { Older release: tray Exit is required. }
  if not SetEvent(UpdateEventHandle) then
  begin
    ClearUpdateRequest;
    Exit;
  end;
  { Bounded cooperative shutdown. Never interrupt model extraction or paste. }
  for Attempt := 1 to 150 do
  begin
    if not CheckForMutexes(AppMutexName) then
    begin
      Result := True;
      Break;
    end;
    Sleep(100);
  end;
  ClearUpdateRequest;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
#ifdef TsfSetup
var
  ExitCode: Integer;
#endif
begin
  Result := '';
#ifdef TsfSetup
  { Resolve the optional elevated prerequisite before stopping the old app.
    Declining UAC or failing TSF setup must leave the translator available.
    Native TSF DLLs use versioned directories, so loaded editors stay intact. }
  if WizardIsTaskSelected('tsf') and not TsfInstalled then
  begin
    ExtractTemporaryFile('STOOMTextService-setup.exe');
    if not ShellExec('runas', ExpandConstant('{tmp}\STOOMTextService-setup.exe'),
      '/SP- /SILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_SHOW,
      ewWaitUntilTerminated, ExitCode) then
    begin
      Result := 'TSF 입력 지원 설치를 시작하지 못했습니다. 관리자 승인 후 다시 시도하거나 ' +
        '이전 화면에서 TSF 입력 지원 선택을 해제하세요. 모델과 설정은 변경되지 않았습니다.';
      Exit;
    end;
    if (ExitCode <> 0) and (ExitCode <> 3010) then
    begin
      Result := Format('TSF 입력 지원 설치가 완료되지 않았습니다 (코드 %d). ' +
        '다시 시도하거나 이전 화면에서 TSF 입력 지원 선택을 해제하세요.', [ExitCode]);
      Exit;
    end;
    TsfInstalled := True;
    if ExitCode = 3010 then NeedsRestart := True;
  end;
#endif
  if not StopTranslator then
  begin
    Result := 'STOOM 번역기가 실행 중입니다. 다운로드 또는 번역이 끝나면 ' +
      '작업 표시줄 트레이의 STOOM 아이콘에서 종료한 뒤 다시 시도하세요.' + #13#10 +
      '기존 버전을 삭제할 필요는 없습니다. 받은 언어팩과 설정은 그대로 유지됩니다.';
    Exit;
  end;
end;

procedure DeinitializeSetup;
begin
  ClearUpdateRequest;
end;

function InitializeUninstall: Boolean;
begin
  Result := StopTranslator;
  if not Result then
    MsgBox('작업 표시줄 트레이에서 STOOM 번역기를 종료한 뒤 다시 시도하세요.' + #13#10 +
      '다운로드한 모델과 설정은 삭제하지 않습니다.', mbInformation, MB_OK);
end;

procedure DeinitializeUninstall;
begin
  ClearUpdateRequest;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfoInfo,
  MemoTypeInfoInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfoInfo + NewLine + NewLine + MemoTasksInfo + NewLine + NewLine +
    '기존 설치가 있으면 같은 위치에 업데이트합니다.' + NewLine +
    '다운로드한 모델, 단축키 및 엔진 설정은 그대로 유지됩니다.';
end;
