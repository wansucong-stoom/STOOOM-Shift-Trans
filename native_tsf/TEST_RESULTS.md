# TSF 구현과 검증 기록 — 2026-10-29

## v0.6.1 활성화 오류 수정

사용자가 실행한 앱 파일의 SHA-256을 v0.6 배포 빌드와 비교해 동일함을 확인했다. 설치된 x64/x86 구성요소와 COM 등록도 존재했다. 그러나 v0.6 도우미는 `GetProfile().catid`가 사용자 정의 범주와 정확히 같아야 한다고 검사하여, 실제 Windows에서 `GUID_NULL`이 반환되는 정상 등록까지 `0x8007000D`로 거부했다. 따라서 서비스 활성화 전에 실패하고 UIA 경로로 남아 있었다.

v0.6.1은 `ITfCategoryMgr`로 보조 범주·서비스의 등록 관계를 확인하고 키보드 범주 등록은 거부한다. 프로필 활성화를 자신의 스레드 관리자 초기화보다 먼저 수행하며, 실제 DLL의 메시지 창이 나타나는지 확인한다. 수정 도구로 설치된 구성요소를 현재 사용자 세션에서 활성화한 결과:

- `ok:true`, `registered:true`, 세 언어의 HRESULT 모두 `0x00000000`.
- `self_service_loaded:true`, `self_probe_hresult:0x00000000`.
- `keyboard_unchanged:true`: Microsoft 한글 입력기 프로필 유지.
- `runtime_verified:false`: 대상 편집기에서의 실제 교체 확인과 구분.

x64/x86의 프로세스 한정 시험에서도 실제 DLL 로딩과 테스트 소유 TSF 문맥을 확인했다. 초기 프로필 활성 상태를 복원했으며 사용자 문서를 읽거나 쓰지 않았다. 이어 현재 사용자에게 승인된 세션 활성화를 적용했다. 0.6.1 리소스로 다시 빌드한 두 아키텍처 모두 16개 실제 TSF 범위 시험, COM 오류 조건 시험, 서비스 수명 시험을 통과했다.

실제 생산 DLL의 전체 IPC 시험을 테스트 소유 창에서 실행하려 했으나 자동 조작 환경에서 창을 활성화할 수 없어 **SKIP** 처리했다. 한컴 한글·Threads 등 대상 앱 교체 성공으로 보고하지 않는다.

## 구현 범위

- 별도의 C++17 보조 TSF 서비스. 기존 미연결 Kolemak 입력기 코드를 재사용하지 않음.
- x64/x86 DLL과 활성화 도구. IME 기본값·키보드 배열·한/영 전환키를 수정하지 않음.
- OS의 실제 키보드 포커스 스레드로 라우팅. 전면 창 소유 스레드와 입력창 소유 스레드가 다른 경우도 식별.
- 원래 STA의 편집 세션에서 선택 범위/현재 문단 캡처 및 직접 교체. 번역 계산은 기존 앱 작업 스레드에 유지.
- 조합 중 읽기 보류, 범위/문맥/원문/포커스 재검증, 마지막 쓰기 직전 시간 제한 재검증, 한 요청당 최대 한 번 쓰기.
- 사용자와 SYSTEM만 허용하는 임시 공유 메모리·이벤트. 요청마다 UUID 사용. 원문을 파일·로그·네트워크로 전송하지 않음. 사용자가 선택한 외부 번역 엔진은 기존 설정에 따름.
- 오래된 문맥은 STA에서 해제. 컴포넌트와 창 클래스는 해제 시 수명을 맞춰 DLL 재로드를 검사.
- 동일 AppId 업데이트, 설치 중 실행 방지, 작업 완료 후 정상 종료 요청. 기존 사용자 모델/설정 경로 유지.
- 아이콘은 사용자 제공 canonical STOOM 자산을 프로젝트에 복사해 사용.

## 실행한 시험

| 시험 | 환경/증거 | 결과 |
| --- | --- | --- |
| 생산 DLL/활성화 도구 빌드 | MSVC /W4, x64 및 x86, 정적 C 런타임 | 통과 |
| 실제 TSF 범위 교체 | 테스트 소유 ITextStoreACP + 실제 msctf.dll 문맥/범위/편집 세션 | 각 아키텍처 16개 통과 |
| 범위 경계·오류 주입 | COM 공급자 대역, 짧은 읽기/잘못된 UTF-16/객체/길이/최종 쓰기 취소 | 통과 |
| 서비스 수명 | 실제 비활성 private TSF 스레드 관리자, DLL 직접 생성 | 각 아키텍처 8회 DLL 로드/해제, 순차 96회 및 동시 24회 이중 인스턴스 통과 |
| Python IPC | 별도 시험용 수신 프로세스, 실제 WM_COPYDATA/공유 메모리/이벤트 | 통과 |
| IPC 접근 권한 | 매 요청 객체 DACL을 검사, 사용자+SYSTEM만 포함 | 정상 사용자 권한에서 통과 |
| Python 기존/신규 경로 | 단축키, 모델 재사용, UI/클립보드, TSF 경로, 업데이트 이벤트 | 전체 스크립트 통과 |
| 생산 DLL 전체 IPC 읽기/교체 | 테스트 소유 창을 통한 별도 수동 시험 | SKIP: Windows가 시험 창의 전경 포커스를 허용하지 않음 |

실제 TSF 범위 시험에는 선택 글 교체, 주변 문단 보존, 커서 끝 이동, 원문/선택 변경 거부, 다른 문맥의 동일 문장 거부, 읽기 전용, password/private/numeric password/PIN/PIN setup, 보호 속성 변경, 실제 StartComposition/EndComposition, 긴 문단 거부, 교체 후 커서 실패를 구별하는 경우가 포함됩니다.

제한된 Low Integrity 샌드박스는 사용자 전용 공유 객체 접근을 거부했습니다. ACL을 완화하지 않고 정상 사용자 권한에서 동일 시험을 재실행했습니다. 실제 앱의 권한 경계나 AppContainer 지원을 증명하는 시험은 아닙니다.

## 아직 검증하지 않은 것

- v0.6 설치/등록은 현재 PC에서 확인했지만 v0.6.1 설치 위 업데이트·제거 전체 절차는 아직 미실행.
- 설치된 서비스의 활성화·자체 로딩은 확인했지만, 각 대상 앱에서 새 모듈이 로드되는지와 편집기 문맥 제공 여부는 미검증.
- Threads, ChatGPT, Codex 입력창, 한컴 한글, Word 등 타사 앱에서의 입력·되돌리기·서식 보존.
- 앱마다 다른 권한 수준, UWP/AppContainer, TSF/UIA 없는 자체 렌더링 입력창.
- v0.4 대비 전체 메모리·설치 용량·실사용 단축키 지연. 이전 모델 계산 측정과 혼동하지 않음.

## 이전 v0.6 배포물 기준값

- 최종 설치 EXE: 68,286,820바이트 (약 65.1 MiB), SHA-256 `DE1E592BE46AA06827975D2BC05967C997D04DA528FC938664FD2D49467636DB`.
- 앱 파일: 262개 / 202,585,828바이트. 별도 TSF DLL/활성화 도구 4개: 2,093,056바이트. TSF의 별도 아이콘과 설치/제거 프로그램, 언어팩은 이 집계에서 제외.
- 비교용 직전 v0.5 onedir 앱: 262개 / 201,868,442바이트. v0.4와의 비교가 아님.
- 최종 패키지의 `--check-pack` 실행으로 기존 설치된 OPUS-MT Big ko→en을 다시 내려받지 않고 로딩: `저는 누구일까요?` → `Who am I?`, 성공. 진단 함수 내부 모델 로딩+번역 1.2997초. 이 시간은 전체 실행 시작이나 단축키 교체 지연이 아님.
- 당시 메인 설치 EXE와 별도 TSF 설치 EXE 컴파일 성공. 이후 사용자가 v0.6을 설치한 상태를 확인했으며, 이번 수정 과정에서 모델 폴더를 변경하지 않음.

## v0.6.1 배포물과 업데이트 시험

- 설치 EXE: **68,329,376바이트**, SHA-256 `DA2C2474DF553DD12FFCDB85D00764BF2058D3FFC984CE53AE4F4321DCB1AF9A`.
- 앱 파일 262개 / 202,614,353바이트. 별도 x64/x86 TSF DLL·도우미 4개 / 2,125,312바이트. 언어팩, 별도 TSF 아이콘과 설치/제거 파일은 제외.
- Windows EXE 파일 버전 0.6.1. 최종 패키지에서 이미 설치된 OPUS ko→en을 다시 내려받지 않고 로딩해 `저는 누구일까요?` → `Who am I?` 확인. 진단 함수 내부 로딩+첫 번역 1.2989초이며 단축키→교체 지연이 아님.
- Python 시험 스크립트 **30개 전체 통과**. 실제 업데이트 확인 요청도 실행하여 아직 릴리스가 없는 저장소의 응답을 정상 처리함.
- 업데이트 검증 시험: 안정 버전 비교, 초안·시험판·다른 저장소·잘못된 이동 주소 거부, 크기·SHA-256·캐시 재검증, 손상/중단 파일 정리, 실행 직전 Windows 쓰기·삭제 잠금 확인. 네트워크와 실행은 시험용 대역으로 대체.
- 업데이트 UI 시험: 실제 Qt 이벤트 루프가 다운로드 중에도 반응, 자동 설치 동의 철회, 번역/모델/클립보드/TSF 작업 대기, 중복 실행 방지, 확인·설치 작업 직렬화, 설정 보존, OPUS 기본값 및 기존 명시적 Argos 선택 보존. 임시 사용자 폴더를 사용하고 실제 모델 파일을 변경하지 않음.
- 최종 설치 스크립트 컴파일 성공. TSF 관리자 승인을 먼저 처리하여 승인 취소 시 기존 앱을 먼저 종료하지 않도록 수정. 실제 설치/UAC/앱 재시작 전체 과정은 **미검증**.
- 업데이트 화면의 한국어 표시와 850×590 배치를 offscreen Qt 화면으로 확인. 실제 데스크톱 설정창의 시작 시간 측정은 별도 수행하지 않음.

## 재현

개발 PC: Windows, Visual Studio C++ Build Tools/Windows SDK, Python 3.11 개발 환경, Inno Setup 6.

```bat
native_tsf\build.cmd
native_tsf\tests\run_host.cmd x64
native_tsf\tests\run_host.cmd x86
.venv\Scripts\python.exe tests\run_tests.py
build_windows.bat
```

서비스 수명과 범위 시험은 전역 TSF 등록이나 사용자 문서를 조작하지 않습니다. Python IPC 시험도 수신기를 명시적으로 시험용 대역으로 구별합니다. 성공한 프로필 활성화 API 호출만으로 편집기 준비 완료를 표시하지 않습니다.

실제 DLL 전체 통신 시험은 자동 실행 목록에서 분리했습니다. 사용자가 자신의 대화형 세션에서 `python native_tsf/tests/service_ipc.py native_tsf/build/test-x64/STOOMTsfRangeTest.exe native_tsf/build/x64/STOOMTextService.dll`로 실행할 수 있습니다. 이 시험은 임시 창을 만들며, 포커스를 얻지 못하면 검증을 우회하지 않고 건너뜁니다. x86 시험은 두 경로의 `x64`를 `x86`으로 바꿉니다.

## 설계 근거

- [Microsoft: Text Service Registration](https://learn.microsoft.com/en-us/windows/win32/tsf/text-service-registration)
- [Microsoft: TF_INPUTPROCESSORPROFILE](https://learn.microsoft.com/en-us/windows/win32/api/msctf/ns-msctf-tf_inputprocessorprofile)
- [Microsoft: RegisterCategory](https://learn.microsoft.com/en-us/windows/win32/api/msctf/nf-msctf-itfcategorymgr-registercategory)
- [Microsoft: ActivateProfile](https://learn.microsoft.com/en-us/windows/win32/api/msctf/nf-msctf-itfinputprocessorprofilemgr-activateprofile)
- [Microsoft: 64-bit considerations](https://learn.microsoft.com/en-us/windows/win32/tsf/64-bit-platform-considerations)

문서는 등록·범주·편집 세션 API 사용의 근거이며 타사 앱 호환성을 보장하는 근거가 아닙니다.
