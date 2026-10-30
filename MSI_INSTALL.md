# MSI 설치 안내

MSI는 현재 Windows 계정에 설치합니다. 별도의 Python 설치는 필요하지 않습니다. 앞으로 새 릴리즈의 설치 파일은 MSI로 통일하며 과거에 게시한 EXE 파일은 보존합니다.

1. 실행 중인 번역기가 있으면 트레이 메뉴에서 종료합니다.
2. `STOOM-Translator-v0613-TSF-setup.msi`를 실행합니다.
3. 설치 후 시작 메뉴의 **STOOM Shift Translator**를 실행합니다.

기존 EXE 설치와 MSI 설치는 서로 다른 설치 관리 체계를 사용합니다. MSI는 기존 EXE 버전을 자동 제거하거나 같은 파일의 소유권을 넘겨받지 않고 `%LOCALAPPDATA%\Programs\STOOM Shift Translator MSI`에 설치합니다. 기존 EXE 버전이 남아 있다면 사용하려는 버전을 구분해 실행하세요. 동시에 실행되면 앱의 중복 실행 방지 기능에 따라 이미 실행된 버전이 사용됩니다.

기존 EXE 사용자는 MSI를 한 번 직접 설치해야 합니다. 구형 EXE의 자동 업데이트 기능이 MSI 설치로 자동 전환해 주지는 않습니다. MSI 설치 후에는 MSI 형식을 인식하는 업데이트 경로를 사용합니다.

언어팩과 설정은 기존 `%LOCALAPPDATA%\STOOMShiftTranslator05`에서 공유합니다. MSI의 설치·제거 대상에는 이 사용자 데이터 폴더가 포함되지 않습니다. 이미 등록한 TSF 구성요소는 유지하며, 이 MSI가 새로 TSF를 등록하지는 않습니다.

같은 계정의 향후 MSI 업데이트는 공통 UpgradeCode로 이전 MSI를 교체하도록 구성했습니다. EXE에서 MSI로의 자동 전환, 실제 설치·제거·복구·업그레이드 동작은 아직 검증하지 않았습니다. 검증한 범위는 MSI 테이블, 한국어 안내문 저장, 내장 CAB 추출과 모든 배포 파일 해시 일치입니다.

## 보안 경고

현재 MSI에는 게시자 코드 서명이 없습니다. **MSI 확장자로 바꾸는 것만으로 Windows 보안 경고를 없앨 수는 없습니다.** 패키지는 Windows 보안 설정을 변경하지 않으며 경고가 사라진다고 보장하지 않습니다.

## 빌드와 검증

기본 `build_windows.bat`은 Python 회귀 시험부터 MSI 생성·검증까지 실행합니다. Inno Setup이나 C++ Build Tools는 이 기본 경로에 필요하지 않습니다. 선택적인 TSF 개발 시험에만 C++ Build Tools/Windows SDK를 사용합니다.

이미 PyInstaller 배포 폴더를 만들었다면 Windows의 Python 3.11 환경에서 아래 명령만 실행할 수 있습니다. `msilib`는 Python 3.11에 포함되어 있으며 Python 3.13에서는 사용할 수 없습니다.

```powershell
python build_msi.py
python verify_msi.py dist/STOOM-Translator-v0613-TSF-setup.msi work/msi-verify
```

검증 명령은 새로운 폴더로 CAB 파일을 추출하고 빌드 매니페스트와 바이트를 비교합니다. MSI 설치 작업은 실행하지 않습니다. 이미 존재하는 MSI나 검증 폴더를 덮어쓰지 않습니다.
