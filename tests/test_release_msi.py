"""Package-aware updater tests; no installer or network is executed."""
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import release_updates as u


class Response(io.BytesIO):
    def __init__(self,data,url):super().__init__(data);self.url=url;self.headers={};self.status=200
    def geturl(self):return self.url


def raises(kind,call):
    try:call()
    except kind:return
    raise AssertionError('Expected '+kind.__name__)


version='0.6.12';tag='v'+version
payload=b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'+b'fixture only; not an installer'*128
digest=hashlib.sha256(payload).hexdigest()
page=f'https://github.com/{u.REPOSITORY}/releases/tag/{tag}'
name='STOOM-Translator-v0612-TSF-setup.msi'
url=f'https://github.com/{u.REPOSITORY}/releases/download/{tag}/{name}'
msi={'name':name,'state':'uploaded','size':len(payload),'digest':'sha256:'+digest,'browser_download_url':url}
exe={**msi,'name':name[:-3]+'exe','browser_download_url':url[:-3]+'exe'}
data={'draft':False,'prerelease':False,'tag_name':tag,'html_url':page,'assets':[exe,msi]}


def check(metadata):
    with patch.object(u,'_open',return_value=Response(json.dumps(metadata).encode(),u.API_URL)):
        return u.check_latest(current_version='0.6.11')


with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);installed=root/'installed';installed.mkdir()
    marker=installed/'msi-install.json';marker.write_text('{"format":"msi"}')
    with patch.object(sys,'executable',str(installed/'STOOMShiftTranslator.exe')):
        with patch.object(sys,'frozen',False,create=True):assert u.installed_package_kind()=='exe'
        with patch.object(sys,'frozen',True,create=True):assert u.installed_package_kind()=='msi'
    with patch.object(sys,'executable',str(root/'STOOMShiftTranslator.exe')),patch.object(sys,'frozen',True,create=True),patch.object(sys,'_MEIPASS',str(installed),create=True):
        assert u.installed_package_kind()=='exe'

    with patch.object(u,'installed_package_kind',return_value='exe'):
        assert check(data).asset_name.endswith('.exe')
        raises(u.NoInstaller,lambda:check({**data,'assets':[msi]}))

    with patch.object(u,'installed_package_kind',return_value='msi'):
        release=check(data);assert release.asset_name==name
        raises(u.NoInstaller,lambda:check({**data,'assets':[exe]}))
        raises(u.NoInstaller,lambda:check({**data,'assets':[msi,dict(msi)]}))
        raises(u.NoInstaller,lambda:check({**data,'assets':[{**msi,'digest':None}]}))
        raises(u.NoInstaller,lambda:check({**data,'assets':[{**msi,'browser_download_url':'https://evil.invalid/package.msi'}]}))
        with patch.object(u,'_open',return_value=Response(payload,url)):
            path=u.download_verified(release,root/'cache')
        assert path.suffix=='.msi' and path.read_bytes()==payload
        sentinel=object();seen=[]
        def fake_launch(argv,**kwargs):
            import msvcrt
            seen.append(argv)
            assert argv[1:]==['/i',str(path),'/passive','/norestart']
            assert Path(argv[0]).name.lower()=='msiexec.exe' and Path(argv[0]).is_absolute()
            handles=kwargs['startupinfo'].lpAttributeList['handle_list']
            assert len(handles)==1 and os.get_handle_inheritable(handles[0])
            assert kwargs['close_fds'] is True
            raises(PermissionError,lambda:path.write_bytes(b'tampered'))
            return sentinel
        with patch.object(u.subprocess,'Popen',side_effect=fake_launch):
            assert u.launch_installer(path) is sentinel
        assert len(seen)==1
        with patch.object(u.subprocess,'Popen',side_effect=AssertionError('invalid package must not execute')):
            arbitrary=root/'arbitrary.msi';arbitrary.write_bytes(payload)
            raises(u.UpdateError,lambda:u.launch_installer(arbitrary))
            path.write_bytes(payload[:-1]+b'X')
            raises(u.UpdateError,lambda:u.launch_installer(path))
        wrong=b'MZ'+b'wrong package kind'
        wrong_release=replace(release,size=len(wrong),sha256=hashlib.sha256(wrong).hexdigest())
        with patch.object(u,'_open',return_value=Response(wrong,url)):
            raises(u.UpdateError,lambda:u.download_verified(wrong_release,root/'wrong'))
        assert not list((root/'wrong').glob('*.msi'))
        assert not list((root/'wrong').glob('*.part'))

print('PASS: frozen installation marker, MSI/EXE candidate separation, trusted msiexec arguments, inherited file lock, tampering and package signature checks; no installer/network executed')
