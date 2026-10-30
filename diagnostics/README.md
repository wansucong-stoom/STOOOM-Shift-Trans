# 문단 선택 진단

한글에서 직접 드래그한 글은 번역되지만 자동 문단 선택은 실패하는 경우를 확인하는 도구입니다. 정식 설치 파일은 MSI로 배포하며, 이 도구만 설치 없이 실행하는 별도 EXE입니다. 번역기 자체를 교체하거나 설치하지 않습니다.

## 사용자 시험

1. `STOOM-SST-Input-Diagnostic.exe`를 실행합니다.
2. 한글에서 저장할 필요 없는 새 빈 문서를 열고 아래 세 문장을 **Enter로 구분해 직접 입력**합니다.

   ```text
   앞 문단입니다.
   문단 선택을 시험합니다.
   뒤 문단입니다.
   ```

3. 두 번째 문장 안에 커서를 놓습니다. 글을 드래그하지 않고 **F8**을 누릅니다.
4. 완료될 때까지 잠시 입력을 멈춥니다. **Esc**를 누르거나 다른 창으로 이동하면 중단합니다.
5. 도구에 진단 완료가 표시되면 개발자에게 알려 주세요.

선택·방향키·복사만 시험합니다. 잘라내기·붙여넣기·글자 입력을 보내지 않습니다. 시험이 끝나면 같은 창에 남아 있는 선택을 해제하고 이전 클립보드 복원을 시도합니다. 중단하거나 클립보드를 다른 앱에서 변경한 경우 복원 여부를 결과에 표시합니다. 기존 작업 문서는 사용하지 마세요.

결과는 다음 파일 하나에 덮어씁니다. 문장·번역문·문서명·창 제목·입력 글자는 저장하지 않습니다. 글자 수·줄바꿈 종류·범위 일치 여부·숫자 캐럿 위치만 저장합니다.

```text
%LOCALAPPDATA%\STOOMShiftTranslator05\paragraph-probe.json
```

F8을 다른 프로그램이 먼저 등록했다면 도구에 안내가 표시됩니다. 도구가 종료되면 F8 등록을 해제합니다.

## 빌드와 검증

릴리즈 소스 루트에서 PowerShell로 실행합니다. 기존 개발용 Python 3.11과 requirements 설치 환경을 사용합니다.

```powershell
$probeRoot = (Get-Location).Path
python -m PyInstaller --noconfirm --clean --onefile --windowed --paths . --icon "$probeRoot\stoom.ico" --add-data "$probeRoot\stoom.ico;." --add-data "$probeRoot\branding\sst\icon-48.png;branding/sst" --name STOOM-SST-Input-Diagnostic --distpath dist/diagnostics --workpath build/paragraph-probe --specpath work diagnostics/paragraph_probe.py
python diagnostics/paragraph_probe.py --self-test
```

고정된 메모리 예문을 사용하는 자체 시험과 동결 EXE의 자체 시험·클립보드 보조 프로세스 연결을 확인했습니다. 이 시험은 Windows 키 입력이나 실제 클립보드 내용을 사용하지 않습니다. 사용자의 한글 편집기에서의 실제 결과는 별도 사용자 시험 대상입니다.
