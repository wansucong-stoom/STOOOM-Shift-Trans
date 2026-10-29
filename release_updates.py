"""Stable GitHub release checks and verified, opt-in installer handoff.

No check or download executes anything. The UI owns consent and idle scheduling.
Only this repository's published stable installer with GitHub's SHA-256 digest
can enter the launch registry; cached files are verified again on every use.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION='0.6.1'
BUILD='20261029.2'
REPOSITORY='wansucong-stoom/STOOOM-Shift-Trans'
API_URL=f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
MAX_INSTALLER_SIZE=300*1024*1024
MAX_METADATA_SIZE=1024*1024
NETWORK_TIMEOUT=20
DOWNLOAD_DEADLINE=600
CHUNK_SIZE=64*1024
_VERSION=r'(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})'
_verified={}
_registry_lock=threading.Lock()


class UpdateError(Exception):pass


class NoInstaller(UpdateError):
    def __init__(self,version,url,reason):
        self.version=version;self.url=url
        super().__init__(f'새 버전 {version}이 있지만 자동 설치 파일을 확인하지 못했습니다: {reason}')


@dataclass(frozen=True)
class Release:
    version:str
    tag:str
    url:str
    asset_name:str
    download_url:str
    size:int
    sha256:str


def _version(value,tag=False):
    if not isinstance(value,str):raise UpdateError('버전 형식이 올바르지 않습니다.')
    match=re.fullmatch(('v' if tag else '')+_VERSION,value)
    if not match:raise UpdateError('안정 버전 형식(vX.Y.Z)이 아닌 업데이트는 설치하지 않습니다.')
    return tuple(int(part) for part in match.groups())


def _split_url(url):
    if not isinstance(url,str) or not url or '\\' in url or any(ord(c)<=32 or ord(c)==127 for c in url):
        raise UpdateError('업데이트 주소 형식이 올바르지 않습니다.')
    try:
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme!='https' or parsed.username is not None or parsed.password is not None or parsed.port not in (None,443) or parsed.fragment:
            raise ValueError('unsafe URL')
        return parsed
    except ValueError as error:raise UpdateError('HTTPS GitHub 업데이트 주소만 허용합니다.') from error


def _api_destination(url):
    _split_url(url)
    if url!=API_URL:raise UpdateError('다른 저장소 또는 서버의 업데이트 응답은 사용하지 않습니다.')


def _asset_destination(url,release):
    parsed=_split_url(url)
    if parsed.hostname not in ('github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'):
        raise UpdateError('허용되지 않은 서버로 다운로드가 이동했습니다.')
    if parsed.hostname=='github.com' and url!=release.download_url:
        raise UpdateError('다른 GitHub 파일로 다운로드가 이동했습니다.')


def _validate_release(release):
    if not isinstance(release,Release):raise UpdateError('업데이트 정보가 올바르지 않습니다.')
    parts=_version(release.version)
    if _version(release.tag,True)!=parts or release.tag!='v'+release.version:
        raise UpdateError('업데이트 태그와 버전이 일치하지 않습니다.')
    expected={f'STOOM-Translator-v{"".join(str(p) for p in parts)}-TSF-setup.exe',
              f'STOOM-Translator-v{release.version}-TSF-setup.exe'}
    if release.asset_name not in expected:raise UpdateError('해당 버전의 공식 설치 파일 이름과 일치하지 않습니다.')
    if release.url!=f'https://github.com/{REPOSITORY}/releases/tag/{release.tag}':
        raise UpdateError('공식 저장소의 릴리스 페이지가 아닙니다.')
    if release.download_url!=f'https://github.com/{REPOSITORY}/releases/download/{release.tag}/{release.asset_name}':
        raise UpdateError('공식 저장소의 설치 파일 주소가 아닙니다.')
    _split_url(release.url);_asset_destination(release.download_url,release)
    if type(release.size) is not int or not 0<release.size<=MAX_INSTALLER_SIZE:
        raise UpdateError('설치 파일 크기가 허용 범위(최대 300 MiB)를 벗어났습니다.')
    if not isinstance(release.sha256,str) or not re.fullmatch(r'[0-9a-f]{64}',release.sha256):
        raise UpdateError('설치 파일의 SHA-256 검증값이 없습니다.')


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self,release=None):self.release=release
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if self.release is None:_api_destination(newurl)
        else:_asset_destination(newurl,self.release)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def _open(url,release=None):
    if release is None:_api_destination(url)
    else:_asset_destination(url,release)
    request=urllib.request.Request(url,headers={
        'User-Agent':f'STOOM-Shift-Translator/{VERSION}',
        'Accept':'application/vnd.github+json' if release is None else 'application/octet-stream',
        'Accept-Encoding':'identity','X-GitHub-Api-Version':'2022-11-28'})
    return urllib.request.build_opener(_SafeRedirect(release)).open(request,timeout=NETWORK_TIMEOUT)


def _length(response):
    value=response.headers.get('Content-Length')
    if value is None:return None
    if not re.fullmatch(r'[0-9]{1,12}',str(value)):raise UpdateError('다운로드 크기 응답이 올바르지 않습니다.')
    return int(value)


def _read_chunks(response,limit,deadline):
    total=0
    # HTTPResponse.read1 performs at most one socket read. Unlike read(n), it
    # lets the total deadline be checked even when a server dribbles bytes.
    read=getattr(response,'read1',response.read)
    while True:
        if time.monotonic()>deadline:raise UpdateError('업데이트 다운로드 제한 시간이 초과되었습니다.')
        chunk=read(min(CHUNK_SIZE,limit-total+1))
        if not chunk:return
        total+=len(chunk)
        if total>limit:raise UpdateError('업데이트 파일이 안내된 크기를 초과했습니다.')
        yield chunk


def check_latest(current_version=VERSION):
    """Return only a newer stable release with one verified-download candidate."""
    current=_version(current_version)
    try:
        with _open(API_URL) as response:
            _api_destination(response.geturl())
            if getattr(response,'status',200)!=200:raise UpdateError('GitHub 릴리스 확인 응답이 올바르지 않습니다.')
            size=_length(response)
            if size is not None and size>MAX_METADATA_SIZE:raise UpdateError('GitHub 릴리스 응답이 너무 큽니다.')
            raw=b''.join(_read_chunks(response,MAX_METADATA_SIZE,time.monotonic()+60))
        data=json.loads(raw.decode('utf-8'))
    except urllib.error.HTTPError as error:
        if error.code==404:return None
        raise UpdateError(f'GitHub 업데이트 확인 실패 (HTTP {error.code}). 잠시 후 다시 확인하세요.') from error
    except (urllib.error.URLError,TimeoutError,OSError) as error:
        raise UpdateError('GitHub 업데이트 서버에 연결하지 못했습니다. 네트워크 연결을 확인하세요.') from error
    except (ValueError,UnicodeError) as error:raise UpdateError('GitHub 릴리스 응답을 읽지 못했습니다.') from error
    if not isinstance(data,dict):raise UpdateError('GitHub 릴리스 정보 형식이 올바르지 않습니다.')
    if data.get('draft') is True or data.get('prerelease') is True:return None
    if data.get('draft') is not False or data.get('prerelease') is not False:
        raise UpdateError('공개 안정 릴리스인지 확인할 수 없습니다.')
    parts=_version(data.get('tag_name'),True)
    if parts<=current:return None
    version='.'.join(str(part) for part in parts);tag='v'+version
    page=f'https://github.com/{REPOSITORY}/releases/tag/{tag}'
    if data.get('html_url')!=page:raise UpdateError('공식 저장소의 릴리스 페이지와 일치하지 않습니다.')
    expected={f'STOOM-Translator-v{"".join(str(p) for p in parts)}-TSF-setup.exe',f'STOOM-Translator-v{version}-TSF-setup.exe'}
    assets=data.get('assets')
    if not isinstance(assets,list):raise NoInstaller(version,page,'설치 파일 목록이 없습니다.')
    matches=[asset for asset in assets if isinstance(asset,dict) and isinstance(asset.get('name'),str) and asset['name'] in expected]
    if len(matches)!=1:raise NoInstaller(version,page,'일치하는 설치 파일이 없거나 여러 개입니다.')
    asset=matches[0]
    if asset.get('state')!='uploaded':raise NoInstaller(version,page,'설치 파일 업로드가 완료되지 않았습니다.')
    digest=asset.get('digest')
    if not isinstance(digest,str) or not re.fullmatch(r'sha256:[0-9a-fA-F]{64}',digest):
        raise NoInstaller(version,page,'GitHub SHA-256 검증값이 아직 없습니다.')
    release=Release(version,tag,page,asset['name'],asset.get('browser_download_url'),asset.get('size'),digest[7:].lower())
    try:_validate_release(release)
    except UpdateError as error:raise NoInstaller(version,page,str(error)) from error
    return release


def _verify_stream(stream,release):
    if os.fstat(stream.fileno()).st_size!=release.size:raise UpdateError('설치 파일 크기 검증에 실패했습니다.')
    digest=hashlib.sha256();total=0
    first=True
    while True:
        chunk=stream.read(CHUNK_SIZE)
        if not chunk:break
        if first and not chunk.startswith(b'MZ'):raise UpdateError('다운로드한 파일이 Windows 설치 실행 파일이 아닙니다.')
        first=False;total+=len(chunk)
        if total>release.size:raise UpdateError('설치 파일 크기 검증에 실패했습니다.')
        digest.update(chunk)
    if total!=release.size or digest.hexdigest()!=release.sha256:raise UpdateError('설치 파일 SHA-256 검증에 실패했습니다.')


def _remember(path,release):
    with _registry_lock:_verified[path]=release
    return path


def download_verified(release,cache_dir,progress=None):
    """Stream to a private temp file, check size+SHA256, then atomically cache.

    progress(received_bytes,total_bytes) runs on the calling worker thread.
    The filename is generated locally; Content-Disposition is never used.
    """
    _validate_release(release)
    try:
        cache=Path(cache_dir).resolve();cache.mkdir(parents=True,exist_ok=True)
    except OSError as error:raise UpdateError('업데이트 파일을 저장할 폴더를 만들지 못했습니다.') from error
    path=cache/f'stoom-update-{release.version}-{release.sha256[:16]}.exe'
    with _registry_lock:_verified.pop(path,None)
    if path.is_symlink():raise UpdateError('업데이트 캐시의 파일 경로가 올바르지 않습니다.')
    try:
        if path.is_file():
            try:
                with path.open('rb') as stream:_verify_stream(stream,release)
                if progress:progress(release.size,release.size)
                return _remember(path,release)
            except UpdateError:pass  # A corrupt cache is replaced only after a good download.
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(mode='wb',prefix='.stoom-update-',suffix='.part',dir=cache,delete=False) as out:
                temporary=Path(out.name)
                with _open(release.download_url,release) as response:
                    _asset_destination(response.geturl(),release)
                    if getattr(response,'status',200)!=200:raise UpdateError('설치 파일 다운로드 응답이 올바르지 않습니다.')
                    size=_length(response)
                    if size is not None and size!=release.size:raise UpdateError('서버의 설치 파일 크기가 릴리스 정보와 다릅니다.')
                    received=0
                    if progress:progress(0,release.size)
                    for chunk in _read_chunks(response,release.size,time.monotonic()+DOWNLOAD_DEADLINE):
                        out.write(chunk);received+=len(chunk)
                        if progress:progress(received,release.size)
                out.flush();os.fsync(out.fileno())
            with temporary.open('rb') as stream:_verify_stream(stream,release)
            os.replace(temporary,path);temporary=None
            return _remember(path,release)
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)
    except (urllib.error.URLError,TimeoutError,OSError) as error:
        raise UpdateError('업데이트 파일을 내려받거나 저장하지 못했습니다. 설치 파일은 실행하지 않았습니다.') from error


@contextmanager
def _locked_reader(path):
    if os.name!='nt':
        with path.open('rb') as stream:yield stream
        return
    # Deny writes and deletes until CreateProcess has opened the verified image.
    # The normal CRT open() share mode does not provide this guarantee.
    import ctypes as C
    from ctypes import wintypes as W
    import msvcrt
    kernel=C.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=(W.LPCWSTR,W.DWORD,W.DWORD,C.c_void_p,W.DWORD,W.DWORD,W.HANDLE)
    kernel.CreateFileW.restype=W.HANDLE
    kernel.CloseHandle.argtypes=(W.HANDLE,);kernel.CloseHandle.restype=W.BOOL
    handle=kernel.CreateFileW(str(path),0x80000000,1,None,3,0x80,None)
    if handle==W.HANDLE(-1).value:raise C.WinError(C.get_last_error())
    try:fd=msvcrt.open_osfhandle(handle,os.O_RDONLY|os.O_BINARY)
    except Exception:
        kernel.CloseHandle(handle);raise
    with os.fdopen(fd,'rb') as stream:yield stream


def launch_installer(path):
    """Launch only a retained, freshly reverified download; UI supplies consent."""
    try:
        candidate=Path(path)
        if candidate.is_symlink():raise UpdateError('업데이트 설치 파일 경로가 변경되었습니다.')
        candidate=candidate.resolve(strict=True)
        with _registry_lock:release=_verified.get(candidate)
        if release is None:raise UpdateError('이 실행에서 검증한 업데이트 설치 파일이 아닙니다. 다시 다운로드하세요.')
        _validate_release(release)
        with _locked_reader(candidate) as stream:
            _verify_stream(stream,release)
            return subprocess.Popen([str(candidate),'/STOOMUPDATE=1','/SP-','/SILENT','/NORESTART'],
                                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),close_fds=True)
    except OSError as error:raise UpdateError('검증한 업데이트 설치 파일을 실행하지 못했습니다.') from error
