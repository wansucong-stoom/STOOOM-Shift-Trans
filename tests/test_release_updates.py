"""Offline updater security/upgrade tests; no network or executable is run."""
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import release_updates as updates

PAYLOAD=b'MZ'+b'owned installer fixture\x00'*4096
DIGEST=hashlib.sha256(PAYLOAD).hexdigest()


def metadata(tag='v0.6.2',**changes):
    version=tag[1:];compact=version.replace('.','')
    name=f'STOOM-Translator-v{compact}-TSF-setup.exe'
    data={'draft':False,'prerelease':False,'tag_name':tag,
          'html_url':f'https://github.com/{updates.REPOSITORY}/releases/tag/{tag}',
          'assets':[{'name':name,'state':'uploaded','size':len(PAYLOAD),'digest':'sha256:'+DIGEST,
                     'browser_download_url':f'https://github.com/{updates.REPOSITORY}/releases/download/{tag}/{name}'}]}
    data.update(changes);return data


class Response(io.BytesIO):
    def __init__(self,body,url=updates.API_URL,headers=None,status=200):
        super().__init__(body);self.url=url;self.headers={} if headers is None else headers;self.status=status
    def geturl(self):return self.url


def latest(data=None,raw=None,headers=None,final=updates.API_URL):
    response=Response(raw if raw is not None else json.dumps(metadata() if data is None else data).encode(),final,headers)
    with patch.object(updates,'_open',return_value=response) as opened:
        # Simulate the old installed version, independently of today's build.
        result=updates.check_latest(current_version='0.6.1')
        opened.assert_called_once_with(updates.API_URL)
        return result


def raises(kind,fn):
    try:fn()
    except kind as error:return error
    raise AssertionError('Expected '+kind.__name__)


# A failing default network stub catches any accidentally unmocked request.
with patch.object(urllib.request,'build_opener',side_effect=AssertionError('network forbidden in unit tests')):
    release=latest()
    assert release.version=='0.6.2' and release.tag=='v0.6.2' and release.sha256==DIGEST
    assert latest(metadata('v0.6.1')) is None
    assert latest(metadata('v0.5.9')) is None
    assert latest(metadata('v0.6.3',prerelease=True)) is None
    assert latest(metadata('v0.6.3',draft=True)) is None
    for tag in ('0.6.2','v0.06.2','v0.6.2-rc1','v0.6.2+build','v1.2','v1.2.3.4','v999999999999.2.3','v0.6.2\n'):
        raises(updates.UpdateError,lambda tag=tag:latest(metadata(tag)))
    raises(updates.UpdateError,lambda:latest(metadata(draft='false')))
    raises(updates.UpdateError,lambda:latest(metadata(html_url='https://github.com/other/repo/releases/tag/v0.6.2')))
    raises(updates.UpdateError,lambda:latest(raw=b'not json'))
    raises(updates.UpdateError,lambda:latest(raw=b'\xff'))
    raises(updates.UpdateError,lambda:latest(raw=b'[]'))
    raises(updates.UpdateError,lambda:latest(raw=b'x'*(updates.MAX_METADATA_SIZE+1)))
    raises(updates.UpdateError,lambda:latest(headers={'Content-Length':str(updates.MAX_METADATA_SIZE+1)}))
    raises(updates.UpdateError,lambda:latest(final='https://evil.example/releases'))
    with patch.object(updates,'_open',side_effect=urllib.error.HTTPError(updates.API_URL,404,'absent',{},None)):
        assert updates.check_latest() is None
    with patch.object(updates,'_open',side_effect=urllib.error.HTTPError(updates.API_URL,403,'limited',{},None)):
        assert '403' in str(raises(updates.UpdateError,updates.check_latest))
    with patch.object(updates,'_open',side_effect=urllib.error.URLError('offline')):
        raises(updates.UpdateError,updates.check_latest)

    missing=raises(updates.NoInstaller,lambda:latest(metadata(assets=[])))
    assert missing.version=='0.6.2' and missing.url==release.url
    duplicate=metadata();duplicate['assets'].append(dict(duplicate['assets'][0]))
    raises(updates.NoInstaller,lambda:latest(duplicate))
    for key,value in [('state','new'),('digest',None),('digest','md5:'+DIGEST),('digest','sha256:bad'),
                      ('size',0),('size',True),('size',updates.MAX_INSTALLER_SIZE+1),
                      ('browser_download_url','https://github.com/other/repo/releases/download/v0.6.2/file.exe'),
                      ('browser_download_url',release.download_url+'?other=1')]:
        data=metadata();data['assets'][0][key]=value
        raises(updates.NoInstaller,lambda data=data:latest(data))
    dotted=metadata();dotted['assets'][0]['name']='STOOM-Translator-v0.6.2-TSF-setup.exe'
    dotted['assets'][0]['browser_download_url']=f'https://github.com/{updates.REPOSITORY}/releases/download/v0.6.2/'+dotted['assets'][0]['name']
    assert latest(dotted).asset_name==dotted['assets'][0]['name']
    malformed=metadata(assets=[{'name':['not','a','string']}])
    raises(updates.NoInstaller,lambda:latest(malformed))

    handler=updates._SafeRedirect(release)
    request=urllib.request.Request(release.download_url)
    for url in ('http://github.com/file','https://github.com.evil.example/file','https://github.com@evil.example/file',
                'https://release-assets.githubusercontent.com:444/file','file:///C:/evil.exe',
                'https://github.com/other/repo/file','https://objects.githubusercontent.com/file#fragment',
                'https://objects.githubusercontent.com/\r\nheader'):
        raises(updates.UpdateError,lambda url=url:handler.redirect_request(request,None,302,'',{},url))
    for url in ('https://release-assets.githubusercontent.com/github-production-release-asset/123?sig=fixture',
                'https://objects.githubusercontent.com/github-production-release-asset/123?sig=fixture'):
        assert handler.redirect_request(request,None,302,'',{},url).full_url==url
    raises(updates.UpdateError,lambda:updates._SafeRedirect().redirect_request(urllib.request.Request(updates.API_URL),None,302,'',{},release.download_url))

    with tempfile.TemporaryDirectory() as directory:
        cache=Path(directory)/'updates';progress=[]
        def response(payload=PAYLOAD,headers=None,url=None):
            return Response(payload,url or release.download_url,headers)
        with patch.object(updates,'_open',return_value=response(headers={'Content-Length':str(len(PAYLOAD)),'Content-Disposition':'filename="../../evil.exe"'})) as opened:
            path=updates.download_verified(release,cache,lambda done,total:progress.append((done,total)))
            opened.assert_called_once_with(release.download_url,release)
        assert path.parent==cache.resolve() and path.name==f'stoom-update-0.6.2-{DIGEST[:16]}.exe'
        assert path.read_bytes()==PAYLOAD and progress[0]==(0,len(PAYLOAD)) and progress[-1]==(len(PAYLOAD),len(PAYLOAD))
        assert not list(cache.glob('*.part'))
        with patch.object(updates,'_open',side_effect=AssertionError('valid cache should not redownload')):
            assert updates.download_verified(release,cache)==path

        sentinel=object()
        def fake_launch(argv,**kwargs):
            assert argv==[str(path),'/STOOMUPDATE=1','/SP-','/SILENT','/NORESTART']
            assert kwargs=={'creationflags':getattr(subprocess,'CREATE_NO_WINDOW',0),'close_fds':True}
            if os.name=='nt':
                # The launch-time hash file remains locked against modification.
                raises(PermissionError,lambda:path.write_bytes(b'MZchanged'))
            return sentinel
        with patch.object(updates.subprocess,'Popen',fake_launch):
            assert updates.launch_installer(path) is sentinel
        with patch.object(updates.subprocess,'Popen',side_effect=AssertionError('unverified installer must not run')):
            arbitrary=cache/'arbitrary.exe';arbitrary.write_bytes(PAYLOAD)
            raises(updates.UpdateError,lambda:updates.launch_installer(arbitrary))
            path.write_bytes(b'MZ'+b'X'*(len(PAYLOAD)-2))
            raises(updates.UpdateError,lambda:updates.launch_installer(path))
        with patch.object(updates,'_open',return_value=response()):
            assert updates.download_verified(release,cache)==path
        assert path.read_bytes()==PAYLOAD

        # Corrupt/short/oversized/disguised HTTP responses never replace a
        # previously valid cache under another release and never remain .part.
        for payload,headers in [(PAYLOAD[:-1],None),(PAYLOAD+b'extra',None),
                                (b'MZ'+b'Y'*(len(PAYLOAD)-2),None),
                                (PAYLOAD,{'Content-Length':'1'}),(PAYLOAD,{'Content-Length':'garbage'})]:
            destination=cache/('bad-'+str(len(list(cache.iterdir()))))
            with patch.object(updates,'_open',return_value=response(payload,headers)):
                raises(updates.UpdateError,lambda:updates.download_verified(release,destination))
            assert not list(destination.glob('*.exe')) and not list(destination.glob('*.part'))
        wrong_kind=b'<!doctype html>error page'
        html=replace(release,size=len(wrong_kind),sha256=hashlib.sha256(wrong_kind).hexdigest())
        with patch.object(updates,'_open',return_value=response(wrong_kind)):
            raises(updates.UpdateError,lambda:updates.download_verified(html,cache/'html'))
        with patch.object(updates,'_open',return_value=response(url='https://evil.example/payload')):
            raises(updates.UpdateError,lambda:updates.download_verified(release,cache/'redirect'))
        with patch.object(updates,'_open',side_effect=urllib.error.URLError('interrupted')):
            raises(updates.UpdateError,lambda:updates.download_verified(release,cache/'offline'))
        assert not list(cache.rglob('*.part'))
        # A failed progress callback also cleans the exact temporary file.
        with patch.object(updates,'_open',return_value=response()):
            raises(RuntimeError,lambda:updates.download_verified(release,cache/'callback',lambda *args:(_ for _ in ()).throw(RuntimeError('cancelled'))))
        assert not list((cache/'callback').iterdir())
        with patch.object(updates.subprocess,'Popen',side_effect=OSError('launch denied')):
            raises(updates.UpdateError,lambda:updates.launch_installer(path))
        for invalid in (replace(release,asset_name='../../evil.exe'),replace(release,tag='v0.6.1'),
                        replace(release,download_url='https://evil.example/file.exe'),replace(release,size=-1),
                        replace(release,sha256=''),replace(release,url='http://github.com/other')):
            raises(updates.UpdateError,lambda invalid=invalid:updates.download_verified(invalid,cache))

print('Offline release updater: stable version ordering, official URLs/redirects, digest/size, verified cache, corruption cleanup, locked recheck before launch, no network or execution: PASS')
