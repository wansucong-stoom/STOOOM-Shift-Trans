<picture>
  <source media="(prefers-color-scheme: dark)" srcset="branding/sst/lockup-dark-3x.png">
  <img src="branding/sst/lockup-light-3x.png" width="158" height="48" alt="STOOM SST">
</picture>

# STOOM Shift Translator

Windows 입력창에서 선택한 글을 오프라인으로 번역해 교체합니다. **Shift 두 번 / Ctrl 두 번**에 각각 목표 언어를 지정할 수 있습니다.

**0.6.11 · 빌드 20261030.7**  
[최신 릴리즈](https://github.com/wansucong-stoom/STOOOM-Shift-Trans/releases/latest) · [변경 기록](CHANGELOG.md) · [검증 결과](KEYBOARD_TEST_RESULTS.md)

## 설치와 업데이트

- Windows 10/11 x64용입니다. 사용 PC에 Python이나 빌드 도구를 따로 설치하지 않습니다.
- [v0.6.11 MSI 설치 파일](https://github.com/wansucong-stoom/STOOOM-Shift-Trans/releases/download/v0.6.11/STOOM-Translator-v0611-TSF-setup.msi)을 실행합니다. **앞으로 새 릴리즈는 MSI로 배포하며, 과거 릴리즈의 EXE 파일은 보존합니다.**
- MSI 버전 간 업데이트는 같은 설치 제품군을 사용하며 받은 언어팩과 설정을 유지합니다.
- 모델은 설치 파일에 포함하지 않습니다. 최초 다운로드에는 인터넷이 필요하고, 설치 후 기본 번역은 오프라인으로 실행됩니다.
- 기본 키보드 경로는 TSF 문서 기능을 필수로 요구하지 않습니다. 기존에 등록한 TSF 구성요소는 유지하지만 MSI가 새로 등록하지는 않습니다.

**기존 EXE에서 처음 전환할 때:** 기존 번역기를 트레이에서 종료한 뒤 MSI를 직접 설치하고 시작 메뉴의 **STOOM Shift Translator MSI**를 실행하세요. MSI는 기존 EXE 설치와 별도 경로를 사용하며 받은 모델·설정은 공유합니다. 기존 EXE 설치를 자동 제거하거나 MSI로 전환하지 않습니다. 구형 EXE의 자동 업데이트만으로 MSI로 바뀌지는 않습니다. 자세한 절차와 검증 범위는 [MSI 안내](MSI_INSTALL.md)에 정리했습니다.

현재 배포 파일은 코드 서명되지 않았습니다. **MSI 확장자만으로 SmartScreen·백신·게시자 경고가 없어지지는 않습니다.** 보안 설정을 변경하지 않습니다.

릴리즈의 `SHA256SUMS.txt`로 파일을 확인할 수 있습니다. `STOOM-product-identity-v1.zip`은 공통 브랜드 개발 자료이며 앱 설치에 필요하지 않습니다.

## 사용법

1. 트레이 아이콘을 눌러 설정을 엽니다.
2. **단축키 설정**에서 Shift 두 번과 Ctrl 두 번의 목표 언어를 각각 고릅니다. 하나를 끄거나 서로 다른 언어를 지정할 수 있습니다. 더블탭 간격은 350ms입니다.
3. **언어팩 관리**에서 필요한 방향과 모델을 선택해 설치합니다.
4. 입력창에서 번역할 글을 선택하고 단축키를 누릅니다. 선택이 없으면 키보드 문단 선택을 시도합니다.

기본 경로는 자동 마우스 클릭을 하지 않습니다. 문단 끝의 선택 방향을 복사 결과로 확인하며, 앞으로 재선택하던 키 동작을 제거했습니다. 같은 창 안의 자식 입력창·스레드·캐럿 변화만으로 중단하지 않으며, 교체 직전 실제 원문을 다시 복사해 확인하고 Ctrl+V를 한 번 보냅니다.

**자동 문단 선택은 Windows가 모든 프로그램에 보장하는 기능이 아닙니다.** 각 편집기의 Ctrl+방향키 동작에 영향을 받으므로 범위가 맞지 않는 프로그램에서는 글을 직접 선택하세요.

## 언어팩과 모델

| 번역 방향 | 선택 가능한 모델 |
| --- | --- |
| 한국어 → 영어 | OPUS-MT Big 기본값 / Argos 기본 |
| 영어 → 한국어 | OPUS-MT Big 기본값 / Argos 기본 |
| 영어 → 일본어 | Argos 기본 |
| 일본어 → 영어 | Argos 기본 |

**방향별 별도 모델입니다.** 한국어→영어를 설치해도 영어→한국어가 함께 설치되지 않습니다. 양방향으로 쓰려면 두 방향을 각각 설치하세요. 한국어↔일본어는 필요한 두 팩이 있으면 영어를 경유합니다.

- OPUS-MT Big: 방향당 원본 약 741MiB를 받고 최초 설치 시 CTranslate2 INT8로 변환합니다.
- Argos 기본: 방향당 약 112~115MiB를 받습니다. Argos Translate·spaCy·Stanza 런타임을 앱에 포함하는 구성은 아닙니다.
- OPUS 원본 Marian은 미등록 토큰 출력을 기본적으로 막습니다. CTranslate2 호출도 같은 정책으로 맞춰 `⁇` 반복 출력을 수정했습니다. FP32에서도 기존 문제를 재현해 INT8만의 문제는 아님을 확인했습니다. 전문 용어·직급·이름의 오역은 여전히 발생할 수 있습니다.
- INT8은 추론용 양자화 방식이며, 하나의 모델을 양방향으로 쓴다는 뜻은 아닙니다.
- 같은 방향에서는 모델 하나를 선택합니다. 이미 설치된 모델은 다시 받지 않습니다.
- 이름·주어·문맥의 오역이 있을 수 있으며 모델 크기나 양자화 여부만으로 품질을 보장하지 않습니다.

OPUS 원본은 University of Helsinki의 [한국어→영어](https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-ko-en), [영어→한국어](https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-en-ko)입니다. 출처·라이선스·변환 정보는 설치한 팩에도 보존합니다.

## 호환 범위와 알려진 한계

- 사용자가 Pwh와 여러 한글 문단의 실제 교체 성공을 확인했습니다. 모든 프로그램·입력창의 성공을 뜻하지는 않습니다.
- 한글 표 마지막 문장·대괄호 제목 등에서 선택 실패와 표 속성 창 열림이 보고됐습니다. 0.6.11은 자동 마우스 선택을 제거했으며 해당 위치의 새 버전 최종 성공은 추가 확인 대상입니다.
- 0.6.11에서도 한글 자동 선택이 끝 줄바꿈을 제외하지 못하는 실패를 확인했습니다. 직접 드래그는 성공한 기록이 있으며, 자동 선택은 해결 완료로 간주하지 않습니다. 사용자 시험 방법은 [문단 선택 진단 안내](diagnostics/README.md)에 정리했습니다.
- 마지막 줄바꿈 뒤 빈 문단에서는 직전 문단을 선택할 수 있습니다. 이 위치에서는 글을 직접 선택하세요.
- 문단·글자별 혼합 서식과 실행 취소는 편집기별 추가 검증 대상입니다.
- 같은 창 안의 다른 위치에 동일 문구가 있으면 클립보드만으로 원래 범위를 구분할 수 없습니다.
- 실제 새 입력·다른 전경 창 이동·원문 불일치가 확인되면 오래된 결과를 붙여넣지 않습니다.

번역 후에는 **클립보드에 번역문이 남습니다.** 편집기가 늦게 읽을 때 이전 이미지가 삽입되는 문제를 피하기 위한 동작입니다.

## 설정·모델·진단 기록

```text
%LOCALAPPDATA%\STOOMShiftTranslator05\
  settings.json
  models\
  input-diagnostics.jsonl
```

업데이트 시 이 폴더의 모델과 설정을 삭제하지 않습니다. 진단은 약 256KiB로 제한하며 단계·문자 수·숫자 창 정보·알려진 오류를 별도 작업에서 저장합니다. **원문·번역문·입력 글자·창 제목·문서명은 기록하지 않습니다.**

## 자동 업데이트

**업데이트** 화면이나 트레이에서 이 저장소의 새 정식 GitHub Release를 확인합니다.

- 기본값: 자동 확인 켜짐 / 자동 설치 꺼짐.
- MSI로 설치한 앱에서 직접 업데이트를 누르거나 자동 설치를 켜면 같은 MSI 형식의 공식 설치 파일을 다운로드합니다.
- GitHub의 SHA-256·크기를 확인한 뒤 설치하며 번역·언어팩 설치·입력 교체가 끝날 때까지 기다립니다.
- 초안·prerelease·현재보다 낮은 버전은 자동 설치 대상이 아닙니다. 모델과 설정은 유지합니다.
- 기존 EXE 버전은 MSI로 한 번 직접 전환해야 합니다. 이후 새 릴리즈에 EXE 설치 파일을 추가하지 않습니다.

## 사용자 번역 엔진

**번역 엔진 → 사용자 외부 엔진**에서 호환되는 EXE를 선택합니다. 표준 입력으로 UTF-8 JSON을 보내고 표준 출력에서 결과 JSON을 받습니다.

입력:
```json
{"text":"안녕하세요","source":"ko","target":"en"}
```

출력:
```json
{"translation":"Hello"}
```

진단 메시지는 표준 오류로 출력하세요. 이 규약을 지원하지 않는 임의의 EXE를 그대로 연결할 수는 없습니다. 원문은 선택한 EXE에 전달되고 인터넷 사용 여부는 그 엔진에 달려 있습니다. 실제 외부 엔진 전반의 통합은 미검증입니다.

## 공통 STOOM 브랜딩

[product-identity-v1](branding/README.md)을 프로젝트에 복사해 사용합니다.

- SST/Pwh는 같은 원형·사선·청록 글로우·Inter·크기·배치·겹침 규칙을 사용하고 제품 표기만 다릅니다.
- 헤더는 아이콘48px, 간격10px, STOOM 글자20px의 158×48 락업입니다.
- 16~256px ICO, 전체 글로우를 보존한 투명 PNG/SVG, 밝은 배경용 어두운 받침을 제공합니다.
- 16px 약자 판독성과 기존 Windows TSF 프로필의 예전 아이콘 경로/캐시에는 한계가 있습니다.
- 글꼴 출처·OFL·해시·재생성 도구를 포함합니다. 앱은 공용 폴더나 설치된 Inter에 의존하지 않습니다.

## 개발과 빌드

기본 MSI 빌드에는 Windows와 Python 3.11이 필요합니다. Python 3.11의 `msilib`로 MSI를 만들므로 Inno Setup이나 Visual Studio C++ Build Tools는 기본 빌드의 필수 도구가 아닙니다.

```bat
build_windows.bat
```

Python 회귀 시험, PyInstaller 패키징, MSI 생성과 내장 CAB 파일 검증 후 다음 파일을 만듭니다.

```text
dist/STOOM-Translator-v0611-TSF-setup.msi
dist/SHA256SUMS.txt
```

선택적인 네이티브 TSF 개발 시험은 Visual Studio C++ Build Tools/Windows SDK가 있는 환경에서 `build_windows.bat --with-native-tests`로 함께 실행할 수 있습니다. 기존 Inno/TSF 설치 소스는 유지하지만 기본 빌드와 GitHub 릴리즈 작업은 새 EXE 설치 파일을 생성·게시하지 않습니다. 현재 배포 파일은 별도로 코드 서명하지 않았습니다.

GitHub Actions도 MSI를 생성하고 CAB 내 모든 파일을 검사한 뒤 MSI와 체크섬만 게시합니다. 이미 존재하는 릴리즈와 그 자산은 덮어쓰지 않습니다.

브랜드 자산은 PySide6·NumPy가 있는 개발 환경에서 별도 출력 폴더로 재생성합니다.

```text
python branding/build_product_identity.py NEW_OUTPUT_DIRECTORY
```

전역 폰트 설치는 하지 않습니다. 바이트 일치는 같은 Windows/Qt 환경에서 확인했으며, 다른 제품에서는 게시된 공통 자산을 그대로 복사하는 것이 기준입니다.

## 검증

0.6.11은 문단 선택·OPUS 디코딩·작업표시줄 아이콘 회귀 시험과 최종 EXE 검사를 수행했습니다. MSI는 설치 데이터베이스·업그레이드 테이블·내장 파일의 바이트를 검사합니다. 실제 MSI 설치·제거 및 기존 MSI에서의 업데이트는 별도 사용자 확인 대상입니다. 네이티브 TSF 코드와 브랜드 원형 자산은 0.6.10에서 검증한 것을 유지합니다. Python을 PATH에서 제외한 동결 EXE의 모델 로딩·고정 예문 번역도 확인했습니다.

실제 한글 표의 남은 위치·모든 앱의 교체/서식/실행 취소, Python 미설치 클린 PC의 전체 설치/UI, v0.4 대비 전체 용량·메모리·지연 실측 비교는 미검증입니다. 상세 범위는 [KEYBOARD_TEST_RESULTS.md](KEYBOARD_TEST_RESULTS.md)를 참고하세요.

## 소스 구성

| 경로 | 역할 |
| --- | --- |
| `main.py` | 설정 UI·트레이·작업 전달 |
| `keyboard_access.py` / `focus_guard.py` | 선택·복사·교체·전경 창 확인 |
| `clipboard_process.py` / `clipboard_worker.py` / `clipboard_native.py` | 격리된 클립보드 작업 |
| `model_packs.py` | 언어팩 목록·검증·설치 |
| `release_updates.py` / `update_control.py` | 릴리즈 확인·검증·업데이트 |
| `build_msi.py` / `verify_msi.py` | 기본 MSI 생성·내장 파일 검증 |
| `branding/` | 공통 자산·규격·글꼴 출처 |
| `native_tsf/` | 선택적 Windows TSF 구성요소 |
| `tests/` | 회귀 시험 |

MSI 빌드는 Windows Python 3.11에서 `python build_msi.py --version 0.6.11`로 실행합니다. 자세한 사용 조건은 [MSI 안내](MSI_INSTALL.md)를 참고하세요.
