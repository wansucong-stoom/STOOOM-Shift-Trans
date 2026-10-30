<picture>
  <source media="(prefers-color-scheme: dark)" srcset="branding/sst/lockup-dark-3x.png">
  <img src="branding/sst/lockup-light-3x.png" width="158" height="48" alt="STOOM SST">
</picture>

# STOOM Shift Translator

쓰던 자리에서 바로 번역하세요. Windows 입력창에서 **Shift 두 번 또는 Ctrl 두 번**으로 선택한 문장을 번역해 교체합니다. 언어팩을 설치하면 인터넷 없이 사용할 수 있습니다.

**0.6.14 · 빌드 20261030.12**

[MSI 설치 파일 다운로드](https://github.com/wansucong-stoom/STOOOM-Shift-Trans/releases/download/v0.6.14/STOOM-Translator-v0614-TSF-setup.msi) · [릴리즈](https://github.com/wansucong-stoom/STOOOM-Shift-Trans/releases/latest)

## 시작하기

1. Windows 10/11 x64에서 MSI를 설치합니다. Python은 필요하지 않습니다.
2. 시작 메뉴의 **STOOM Shift Translator**를 실행합니다. 실행 중에는 바탕화면 바로가기나 트레이 아이콘으로 설정을 다시 열 수 있습니다.
3. **언어팩 관리**에서 필요한 번역 방향과 모델을 선택해 다운로드합니다.
4. **단축키 설정**에서 Shift 두 번과 Ctrl 두 번에 목표 언어를 각각 지정합니다. 사용하지 않는 단축키는 끌 수 있습니다.
5. 번역할 문장을 선택하고 단축키를 누릅니다. 선택한 글이 없으면 **커서부터 현재 줄 시작까지** 번역합니다.

더블탭 간격은 **350ms**입니다. 줄 전체를 번역하려면 커서를 줄 끝에 두세요. 여러 줄이나 문단 전체는 원하는 범위를 드래그해 선택합니다. 커서가 줄 시작에 있으면 선택할 글이 없습니다.

## 언어팩

| 번역 방향 | 선택 가능한 모델 |
| --- | --- |
| 한국어 → 영어 | OPUS-MT Big 기본값 / Argos 기본 |
| 영어 → 한국어 | OPUS-MT Big 기본값 / Argos 기본 |
| 영어 → 일본어 | Argos 기본 |
| 일본어 → 영어 | Argos 기본 |

방향마다 사용할 모델을 하나씩 선택합니다. 양방향 번역에는 두 방향의 언어팩이 필요합니다. 한국어↔일본어는 필요한 두 팩을 설치하면 영어를 거쳐 번역합니다.

최초 다운로드에는 인터넷이 필요합니다. OPUS-MT Big는 방향당 약 741MiB, Argos는 약 112~115MiB를 다운로드하며, 이미 설치한 모델은 다시 받을 필요가 없습니다.

**번역 엔진** 설정에서 호환되는 사용자 외부 엔진도 추가할 수 있습니다. 외부 엔진의 인터넷 사용 여부는 해당 엔진에 따라 다릅니다.

## 업데이트

설정의 **업데이트** 또는 트레이 메뉴에서 새 버전을 확인할 수 있습니다. 자동 확인은 기본으로 켜져 있으며, 자동 설치는 원할 때 설정에서 켤 수 있습니다. 업데이트 후에도 받은 언어팩과 설정을 유지합니다.

앞으로 설치 파일은 **MSI로 배포**합니다. 기존 EXE 버전을 사용 중이라면 트레이에서 종료한 뒤 MSI를 한 번 직접 설치하세요. 기존 모델과 설정을 함께 사용합니다. [자세한 설치 안내](MSI_INSTALL.md)

## 사용 시 참고

- 자동 줄바꿈의 선택 범위와 서식 유지는 편집기에 따라 다를 수 있습니다. 원하는 범위가 다르면 직접 선택하세요.
- 이름·직급·전문 용어의 번역은 확인 후 사용하세요.
- 번역 후 클립보드에는 번역문이 남습니다.
- 현재 설치 파일에는 코드 서명이 없어 Windows 보안 경고가 나타날 수 있습니다.
- 모든 입력창·표에서의 동작을 보장하지는 않습니다.

[변경 기록](CHANGELOG.md) · [검증 기록](KEYBOARD_TEST_RESULTS.md) · [설치·빌드 안내](MSI_INSTALL.md)
