# 문단 선택 진단 v2

한글의 자동 문단 선택과 Outlook에서 번역한 문단이 앞 문단에 붙는 현상을 확인하는 도구입니다. v2는 복사한 글에 끝 줄바꿈이 없어도 선택 양 끝의 변화를 확인합니다. 정식 설치 파일은 MSI로 배포하며, 이 도구만 설치 없이 실행하는 별도 EXE입니다. 번역기 자체를 교체하거나 설치하지 않습니다.

## 사용자 시험

1. 이전 진단 도구를 닫고 `STOOM-SST-Input-Diagnostic-v2.exe`를 실행합니다.
2. Outlook에서 **보내지 않을 새 메일의 빈 본문**을 열고 아래 두 문장을 **Enter로 구분해 직접 입력**합니다. 이 시험에서는 Shift+Enter를 사용하지 않습니다.

   ```text
   이렇게 사용할 수 있어요.
   시프트만 두번 누르면 된답니다.
   ```

3. 두 번째 문장 끝에 커서를 놓습니다. 마지막에 Enter를 더 누르거나 글을 드래그하지 않고 **F8**을 누릅니다.
4. 완료될 때까지 잠시 입력을 멈춥니다. **Esc**를 누르거나 다른 창으로 이동하면 중단합니다.
5. 도구에 진단 완료가 표시되면 개발자에게 알려 주세요.

한글 동작을 비교할 때는 새 빈 문서에 세 문장을 입력하고 가운데 문장에 커서를 두고 시험할 수 있습니다. 결과 파일은 실행할 때마다 덮어쓰므로, 다른 프로그램에서 다시 실행하기 전에 앞선 결과 확인을 마쳐야 합니다.

선택·방향키·복사만 시험합니다. 잘라내기·붙여넣기·글자 입력을 보내지 않습니다. 시험이 끝나면 같은 창에 남아 있는 선택을 해제하고 이전 클립보드 복원을 시도합니다. 중단하거나 클립보드를 다른 앱에서 변경한 경우 복원 여부를 결과에 표시합니다. 기존 작업 문서는 사용하지 마세요.

결과는 다음 파일 하나에 덮어씁니다. 문장·번역문·문서명·창 제목·입력 글자는 저장하지 않습니다. 글자 수, 앞뒤 줄바꿈의 종류와 개수, 원문과의 일치 여부, 앞부분/뒷부분만 추가·제거됐는지 여부, 숫자 캐럿 위치만 저장합니다. `leading_boundary_chars`와 `terminal_boundary_chars`는 복사된 구분자 문자 수이므로 CRLF는 2로 기록합니다.

```text
%LOCALAPPDATA%\STOOMShiftTranslator05\paragraph-probe.json
```

F8을 다른 프로그램이 먼저 등록했다면 도구에 안내가 표시됩니다. 도구가 종료되면 F8 등록을 해제합니다.

끝 줄바꿈이 없는 경우에는 Shift+Right와 Shift+Left로 선택 끝의 변화를 비교합니다. 복사 내용이 달라졌다면 반대 키로 원문 범위가 복원됐는지 확인하며, 복원되지 않으면 멈춥니다. 복사 내용이 같다고 해서 키가 아무 일도 하지 않았다고 단정하지 않습니다. 끝 줄바꿈이 있는 경우에는 v1의 확인을 유지하고, 첫 재선택 결과가 원문과 같을 때만 왼쪽으로 한 단계 더 이동하는 후보를 한 번 확인합니다. 어느 경로도 번역문을 입력하거나 붙여넣지 않습니다.

## 빌드와 검증

릴리즈 소스 루트에서 PowerShell로 실행합니다. 기존 개발용 Python 3.11과 requirements 설치 환경을 사용합니다.

```powershell
$probeRoot = (Get-Location).Path
python -m PyInstaller --noconfirm --clean --onefile --windowed --paths . --icon "$probeRoot\stoom.ico" --add-data "$probeRoot\stoom.ico;." --add-data "$probeRoot\branding\sst\icon-48.png;branding/sst" --name STOOM-SST-Input-Diagnostic-v2 --distpath dist/diagnostics --workpath build/paragraph-probe-v2 --specpath work diagnostics/paragraph_probe.py
python diagnostics/paragraph_probe.py --self-test
```

v2 소스의 자체 시험은 고정된 메모리 예문으로 한글에서 관찰된 추가 이동, 끝 줄바꿈이 없는 범위의 양방향 탐색, 원문 관계 메타데이터, 중단과 클립보드 복원 경로를 확인합니다. 이 시험은 Windows 키 입력이나 실제 클립보드 내용을 사용하지 않습니다. v2 동결 EXE의 자체 시험·보조 프로세스 연결은 빌드 후 별도 확인하며, 실제 Outlook·한글 편집기 결과는 사용자 시험 대상입니다.
