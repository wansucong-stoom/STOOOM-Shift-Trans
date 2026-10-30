"""Extract and hash-check a generated MSI cabinet without running installation."""
from pathlib import Path
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import subprocess


def verify(package, destination):
    assert package.is_file()
    assert not destination.exists(), 'Choose a new verification directory.'
    manifest=json.loads(package.with_suffix('.manifest.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(package.read_bytes()).hexdigest()==manifest['sha256']
    destination.mkdir(parents=True)
    msi=C.WinDLL('msi')
    msi.MsiOpenDatabaseW.argtypes=[W.LPCWSTR,W.LPCWSTR,C.POINTER(W.UINT)]
    msi.MsiDatabaseOpenViewW.argtypes=[W.UINT,W.LPCWSTR,C.POINTER(W.UINT)]
    msi.MsiViewExecute.argtypes=[W.UINT,W.UINT]
    msi.MsiViewFetch.argtypes=[W.UINT,C.POINTER(W.UINT)]
    msi.MsiRecordReadStream.argtypes=[W.UINT,W.UINT,C.c_void_p,C.POINTER(W.DWORD)]
    msi.MsiCloseHandle.argtypes=[W.UINT]
    handles=[]
    def check(code):
        if code:raise OSError('MSI read API returned '+str(code))
    try:
        db=W.UINT();check(msi.MsiOpenDatabaseW(str(package),None,C.byref(db)));handles.append(db)
        view=W.UINT();check(msi.MsiDatabaseOpenViewW(db,"SELECT `Data` FROM `_Streams` WHERE `Name` = 'payload.cab'",C.byref(view)));handles.append(view)
        check(msi.MsiViewExecute(view,0))
        record=W.UINT();check(msi.MsiViewFetch(view,C.byref(record)));handles.append(record)
        cabinet=destination/'payload.cab'
        with cabinet.open('wb') as stream:
            while True:
                buffer=C.create_string_buffer(1024*1024);count=W.DWORD(len(buffer))
                check(msi.MsiRecordReadStream(record,1,buffer,C.byref(count)))
                if not count.value:break
                stream.write(buffer.raw[:count.value])
    finally:
        for handle in reversed(handles):msi.MsiCloseHandle(handle)
    extracted=destination/'files';extracted.mkdir()
    subprocess.run(['expand.exe','-F:*',str(cabinet),str(extracted)],check=True,capture_output=True)
    entries=list(extracted.iterdir())
    assert len(entries)==len(manifest['files'])
    for item in manifest['files']:
        path=extracted/item['id']
        assert path.stat().st_size==item['size'],item['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256'],item['path']
    result={'msi':package.name,'files_verified':len(entries),'cabinet_bytes':cabinet.stat().st_size,
            'all_payload_hashes_match':True,'installation_executed':False,'sha256':manifest['sha256']}
    (destination/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package',type=Path);parser.add_argument('destination',type=Path)
    args=parser.parse_args();verify(args.package.resolve(),args.destination.resolve())
