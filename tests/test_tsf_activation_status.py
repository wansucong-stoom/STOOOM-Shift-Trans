"""Activation status formatting only: temporary paths and stubbed registry/process.

Never reads the installed TSF registry, launches a helper, or activates profiles.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tsf_bridge as bridge


class Key:
    def __enter__(self):return self
    def __exit__(self,*args):pass


def status(**changes):
    value={'ok':True,'operation':'activate','registered':True,'runtime_verified':False,
           'self_service_loaded':True,'keyboard_unchanged':True,'self_probe_hresult':'0x00000000','error':'',
           'category_checks':{'type_registered':True,'service_member':True,'keyboard_member':False,'hresult':'0x00000000'},
           'profiles':[{'language':lang,'hresult':'0x00000000'} for lang in (0x0412,0x0409,0x0411)]}
    value.update(changes)
    return value


with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);dll=root/'STOOMTextService.dll';host=root/'STOOMTextServiceHost.exe'
    host.write_bytes(b'Test placeholder - never executed')
    registry=types.SimpleNamespace(HKEY_LOCAL_MACHINE=1,KEY_READ=0x20019,KEY_WOW64_64KEY=0x100,REG_SZ=1,REG_EXPAND_SZ=2)
    calls=[]
    def open_key(hive,path,reserved,access):
        assert hive==registry.HKEY_LOCAL_MACHINE and bridge.SERVICE_ID in path
        assert access&registry.KEY_WOW64_64KEY
        return Key()
    registry.OpenKey=open_key
    registry.QueryValueEx=lambda key,name:(str(dll),registry.REG_SZ)
    def invoke(payload=None,code=0,raw=None,error=None):
        def run(argv,**kwargs):
            calls.append((argv,kwargs))
            assert argv==[str(host),'--activate']
            assert kwargs=={'capture_output':True,'timeout':10,'creationflags':subprocess.CREATE_NO_WINDOW}
            if error:raise error
            return subprocess.CompletedProcess(argv,code,stdout=raw if raw is not None else json.dumps(status() if payload is None else payload).encode(),stderr=b'')
        with patch.dict(sys.modules,winreg=registry),patch.object(bridge.subprocess,'run',run):
            return bridge.activate_installed()

    success=invoke()
    assert '활성화 요청 완료' in success and '실제 연결은 단축키' in success
    assert '준비 완료' not in success

    # Regression: v0.6 reported invalid-data for every language. Preserve the
    # exact evidence instead of reducing it to a generic unavailable message.
    broken=status(ok=False,registered=False,profiles=[{'language':lang,'hresult':'0x8007000D'} for lang in (0x0412,0x0409,0x0411)])
    result=invoke(broken,code=1)
    assert '활성화 실패' in result and '프로필 등록 확인 실패' in result and result.count('0x8007000D')==3
    assert all(word in result for word in ('한국어','영어','일본어','종료 코드 1'))

    fatal=invoke({'ok':False,'step':'CoCreateInstance','hresult':'0x80070005'},code=1)
    assert 'CoCreateInstance' in fatal and '0x80070005' in fatal
    partial=status(ok=False);partial['profiles'][1]['hresult']='0x00000001'
    assert '영어 0x00000001' in invoke(partial,code=1)
    negative=status(ok=False);negative['profiles'][0]['hresult']=-2147024891
    assert '0x80070005' in invoke(negative,code=1)
    assert '종료 코드 17' in invoke({},code=17)
    assert '결과 확인 실패' in invoke(status(profiles=[]))
    assert '결과 확인 실패' in invoke(status(operation='status'))
    assert '결과 확인 실패' in invoke(status(profiles=[{'language':1042,'hresult':'0x00000000'}]*3))
    assert '응답을 해석하지 못했습니다' in invoke(raw=b'not json')
    assert '응답을 해석하지 못했습니다' in invoke(raw=b'\xff')
    assert '응답을 해석하지 못했습니다' in invoke(raw=b'x'*65537)
    assert '응답을 해석하지 못했습니다' in invoke(payload=[])
    assert '결과 코드 없음' in invoke(status(profiles=[{'language':1042,'hresult':True}]))
    assert '결과 확인 실패' in invoke(status(profiles=[{'language':[],'hresult':'0x00000000'}]*3))
    assert '결과 확인 실패' in invoke(status(profiles=[None,None,None]))
    failed_self=invoke(status(ok=False,self_service_loaded=False,self_probe_hresult='0x800705B4',error='self_service_not_loaded'),code=1)
    assert 'self_service_not_loaded' in failed_self and '서비스 자체 확인 0x800705B4' in failed_self
    assert '로드되지 않았습니다' in failed_self
    assert 'keyboard_profile_changed' in invoke(status(ok=False,keyboard_unchanged=False,error='keyboard_profile_changed'),code=1)
    assert '키보드 프로필 유지 여부' in invoke(status(keyboard_unchanged=False))
    assert '자체 로딩을 확인하지 못했습니다' in invoke(status(self_service_loaded=False))
    legacy=status()
    for field in ('self_service_loaded','keyboard_unchanged','self_probe_hresult'):legacy.pop(field)
    assert '이전 TSF 구성요소' in invoke(legacy) and '활성화 요청 완료' not in invoke(legacy)
    category_failure=status(ok=False,registered=False,error='registration_incomplete',category_checks={'type_registered':True,'service_member':False,'keyboard_member':False,'hresult':'0x80070005'})
    assert '등록 관계가 일치하지 않습니다' in invoke(category_failure,code=1)
    assert '입력 서비스 분류 확인 0x80070005' in invoke(category_failure,code=1)
    inconsistent=status(category_checks={'type_registered':True,'service_member':False,'keyboard_member':False,'hresult':'0x00000000'})
    assert '활성화 요청 완료' not in invoke(inconsistent)

    timeout=invoke(error=subprocess.TimeoutExpired(['fixture'],10))
    assert '시간 초과 (10초)' in timeout and '등록되어 있지만' in timeout
    assert '구성요소 없음' not in timeout
    launch=invoke(error=PermissionError(13,'fixture denied'))
    assert '도우미 시작 실패' in launch and '13' in launch

    before=len(calls)
    with patch.object(registry,'OpenKey',side_effect=FileNotFoundError(2,'fixture absent')):
        assert '등록되지 않았습니다' in invoke()
    with patch.object(registry,'OpenKey',side_effect=PermissionError(13,'fixture denied')):
        assert '등록 정보 읽기 실패' in invoke()
    with patch.object(registry,'QueryValueEx',side_effect=FileNotFoundError(2,'fixture incomplete')):
        assert '등록 정보 또는 실행 파일 확인 실패' in invoke()
    for invalid in ('',None,'relative.dll'):
        with patch.object(registry,'QueryValueEx',return_value=(invalid,registry.REG_SZ)):
            assert '등록 정보 형식 오류' in invoke()
    host.unlink()
    assert '등록은 있지만 실행 도우미 파일이 없습니다' in invoke()
    assert len(calls)==before,'invalid registration must not launch a helper'

print('TSF activation diagnostics: precise registration/launch/timeout/JSON/HRESULT states; explicit activation success only; no real profile activation: PASS')
