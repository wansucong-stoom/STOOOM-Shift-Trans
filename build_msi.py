"""Build a per-user Windows Installer package (Python 3.11 on Windows).

MSI has its own install directory and upgrade family. It never takes ownership
of an existing Inno installation or of downloaded models/settings. No custom
actions, elevation, security-setting changes, or application launch are used.
"""
from pathlib import Path
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import gc
import json
import msilib
from msilib import schema, sequence
import uuid
from release_updates import VERSION

ROOT = Path(__file__).resolve().parent
UPGRADE_CODE = '{34A9CBE3-280D-5941-915A-1D64B2E43C03}'
NAMESPACE = uuid.UUID('34a9cbe3-280d-5941-915a-1d64b2e43c03')


def guid(text):
    return '{' + str(uuid.uuid5(NAMESPACE, text)).upper() + '}'


def ident(prefix, text):
    return prefix + hashlib.sha256(text.encode('utf-8')).hexdigest()[:32]


def build_database(version, payload, output):
    assert payload.is_dir() and (payload / 'STOOMShiftTranslator.exe').is_file()
    assert not output.exists(), 'Use a new output filename; never replace a published MSI.'
    output.parent.mkdir(parents=True, exist_ok=True)
    product = guid('product:' + version)
    db = msilib.init_database(str(output), schema, 'STOOM Shift Translator',
                             product, version, 'STOOM')
    codepage=output.with_suffix('.codepage.idt')
    codepage.write_bytes(b'\r\n\r\n949\t_ForceCodepage\r\n')
    del db
    gc.collect()
    msi=C.WinDLL('msi')
    msi.MsiOpenDatabaseW.argtypes=[W.LPCWSTR,W.LPCWSTR,C.POINTER(W.UINT)]
    msi.MsiDatabaseImportW.argtypes=[W.UINT,W.LPCWSTR,W.LPCWSTR]
    msi.MsiDatabaseCommit.argtypes=[W.UINT]
    msi.MsiCloseHandle.argtypes=[W.UINT]
    handle=W.UINT()
    assert msi.MsiOpenDatabaseW(str(output),C.cast(C.c_void_p(1),W.LPCWSTR),C.byref(handle))==0
    try:
        assert msi.MsiDatabaseImportW(handle,str(codepage.parent),codepage.name)==0
        assert msi.MsiDatabaseCommit(handle)==0
    finally:msi.MsiCloseHandle(handle)
    db=msilib.OpenDatabase(str(output),msilib.MSIDBOPEN_TRANSACT)
    codepage.unlink()
    language=db.OpenView("UPDATE `Property` SET `Value` = '1042' WHERE `Property` = 'ProductLanguage'")
    language.Execute(None);language.Close()
    msilib.add_tables(db, sequence)
    summary = db.GetSummaryInformation(20)
    summary.SetProperty(msilib.PID_TEMPLATE, 'x64;1042')
    summary.SetProperty(msilib.PID_PAGECOUNT, 500)
    summary.SetProperty(msilib.PID_WORDCOUNT, 10)  # compressed + no elevation
    summary.Persist()
    msilib.add_data(db, 'Property', [
        ('UpgradeCode', UPGRADE_CODE), ('ARPPRODUCTICON', 'SST.ico'),
        ('ARPURLINFOABOUT', 'https://github.com/wansucong-stoom/STOOOM-Shift-Trans'),
        ('ARPNOMODIFY', '1'), ('MSIRESTARTMANAGERCONTROL', 'DisableShutdown'),
        ('SecureCustomProperties', 'OLDPRODUCTS;NEWERPRODUCTS'),
        ('DefaultUIFont', 'SegoeNormal'), ('INSTALLLEVEL', '1'),
    ])
    # Per-user scope: ALLUSERS is intentionally absent. Major upgrades are
    # transactional; this family does not match the previous EXE installer.
    msilib.add_data(db, 'Upgrade', [
        (UPGRADE_CODE, None, version, None, 1, 'ALL', 'OLDPRODUCTS'),
        (UPGRADE_CODE, version, None, None, 2, None, 'NEWERPRODUCTS'),
    ])
    for table in ('InstallExecuteSequence', 'InstallUISequence'):
        view = db.OpenView(f"UPDATE `{table}` SET `Sequence` = 250 WHERE `Action` = 'LaunchConditions'")
        view.Execute(None); view.Close()
    view = db.OpenView("UPDATE `InstallExecuteSequence` SET `Sequence` = 1510 WHERE `Action` = 'RemoveExistingProducts'")
    view.Execute(None); view.Close()
    msilib.add_data(db, 'LaunchCondition', [
        ('VersionNT64 >= 603', '64비트 Windows가 필요합니다.'),
        ('NOT NEWERPRODUCTS', '더 새로운 STOOM Shift Translator가 이미 설치되어 있습니다.'),
    ])
    msilib.add_data(db, 'Directory', [
        ('TARGETDIR', None, 'SourceDir'), ('LocalAppDataFolder', 'TARGETDIR', '.'),
        ('ProgramsDir', 'LocalAppDataFolder', 'Programs'),
        ('INSTALLDIR', 'ProgramsDir', 'SSTMSI|STOOM Shift Translator MSI'),
        ('ProgramMenuFolder', 'TARGETDIR', '.'), ('DesktopFolder', 'TARGETDIR', '.'),
    ])
    msilib.add_data(db, 'Feature', [('Main', None, 'STOOM Shift Translator',
                                   'Offline translator application', 1, 1, 'INSTALLDIR', 0)])
    files = [(p.relative_to(payload).as_posix(), p) for p in sorted(payload.rglob('*')) if p.is_file()]
    # Shell paths are deliberately independent of PyInstaller's _internal path.
    files.append(('branding/sst/stoom.ico', ROOT / 'branding/sst/stoom.ico'))
    files.append(('msi-install.json', ROOT / 'msi-install.json'))
    cab = msilib.CAB('payload.cab')
    directories = {'': 'INSTALLDIR'}
    records = []
    main_component = None
    for relative, path in files:
        parent = Path(relative).parent.as_posix()
        if parent == '.': parent = ''
        current = ''
        for part in parent.split('/') if parent else []:
            previous = current
            current = '/'.join(filter(None, (current, part)))
            if current not in directories:
                logical = ident('D', current)
                directories[current] = logical
                short = 'D' + hashlib.sha256(current.encode()).hexdigest()[:7].upper()
                msilib.add_data(db, 'Directory', [(logical, directories[previous], short + '|' + part)])
        component = ident('C', relative)
        reg = ident('R', relative)
        file_id = ident('F', relative)
        msilib.add_data(db, 'Component', [(component, guid('component:' + relative),
            directories[parent], 260, None, reg)])
        msilib.add_data(db, 'Registry', [(reg, 1, r'Software\STOOM\ShiftTranslatorMSI\Files',
                                        relative, '[INSTALLDIR]' + relative.replace('/', '\\'), component)])
        msilib.add_data(db, 'FeatureComponents', [('Main', component)])
        seq, _ = cab.append(str(path), path.name, file_id)
        short = 'F' + hashlib.sha256(relative.encode()).hexdigest()[:7].upper()
        msilib.add_data(db, 'File', [(file_id, component, short + '|' + path.name,
                                    path.stat().st_size, None, None, 512, seq)])
        records.append({'path': relative, 'id': file_id, 'size': path.stat().st_size,
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        if relative == 'STOOMShiftTranslator.exe': main_component = component
    assert main_component
    msilib.add_data(db, 'Icon', [('SST.ico', msilib.Binary(str(ROOT/'stoom.ico')))])
    msilib.add_data(db, 'Shortcut', [
        ('StartSST', 'ProgramMenuFolder', 'SSTMSI|STOOM Shift Translator', main_component,
         '[INSTALLDIR]STOOMShiftTranslator.exe', None, 'STOOM Shift Translator', None, 'SST.ico', 0, 1, 'INSTALLDIR'),
        ('DesktopSST', 'DesktopFolder', 'SSTMSI|STOOM Shift Translator', main_component,
         '[INSTALLDIR]STOOMShiftTranslator.exe', None, 'STOOM Shift Translator', None, 'SST.ico', 0, 1, 'INSTALLDIR'),
    ])
    # Windows Installer 5 shortcut property table is absent in Python's older schema.
    table = msilib.Table('MsiShortcutProperty')
    table.add_field(1, 'MsiShortcutProperty', msilib.type_valid | msilib.type_string | msilib.type_key | 72)
    table.add_field(2, 'Shortcut_', msilib.type_valid | msilib.type_string | 72)
    table.add_field(3, 'PropertyKey', msilib.type_valid | msilib.type_string | 255)
    table.add_field(4, 'PropVariantValue', msilib.type_valid | msilib.type_string | 255)
    table.create(db)
    msilib.add_data(db, 'MsiShortcutProperty', [
        ('StartAppID', 'StartSST', 'System.AppUserModel.ID', 'STOOM.ShiftTranslator'),
        ('DesktopAppID', 'DesktopSST', 'System.AppUserModel.ID', 'STOOM.ShiftTranslator'),
    ])
    msilib.add_data(db, 'TextStyle', [('SegoeNormal','Malgun Gothic',9,0,0),
                                     ('SegoeTitle','Malgun Gothic',15,0,1)])
    msilib.add_data(db, 'Binary', [('SSTBadge',msilib.Binary(str(ROOT/'branding/sst/installer-small.bmp')))])
    welcome=msilib.Dialog(db,'WelcomeSST',50,50,370,270,3,
                         '[ProductName]','Install','Install','Cancel')
    welcome.bitmap('Badge',304,15,50,50,'SSTBadge')
    welcome.text('Title',20,24,275,42,3,'{\\SegoeTitle}STOOM Shift Translator')
    welcome.text('Notice',20,85,325,123,3,
        '현재 Windows 계정에 설치합니다. Python을 따로 설치할 필요가 없습니다.\r\n\r\n'
        '기존 번역기를 트레이 메뉴에서 종료한 뒤 설치해 주세요.\r\n\r\n'
        '기존 EXE 버전과 별도 폴더에 설치됩니다. 기존 버전을 자동으로 삭제하지 않습니다. '
        '다운로드한 언어팩과 설정은 함께 사용하며 유지합니다.')
    welcome.line('Line',0,229,370,1)
    welcome.pushbutton('Install',218,243,65,18,3,'설치','Cancel').event('EndDialog','Return')
    welcome.pushbutton('Cancel',290,243,65,18,3,'취소','Install').event('EndDialog','Exit')
    msilib.add_data(db,'InstallUISequence',[('WelcomeSST','NOT Installed',1290)])
    for name,message in (('ExitDialog','작업이 완료되었습니다. 설치한 경우 시작 메뉴의 STOOM Shift Translator를 실행해 주세요.'),
                         ('FatalError','설치를 완료하지 못했습니다. 실행 중인 번역기가 있다면 종료한 뒤 다시 시도해 주세요.'),
                         ('UserExit','설치를 취소했습니다.')):
        dlg=msilib.Dialog(db,name,50,50,370,270,3,'[ProductName]','Finish','Finish','Finish')
        dlg.bitmap('Badge',304,15,50,50,'SSTBadge')
        dlg.text('Title',20,24,275,42,3,'{\\SegoeTitle}STOOM Shift Translator')
        dlg.text('Message',20,90,325,90,3,message)
        dlg.line('Line',0,229,370,1)
        dlg.pushbutton('Finish',290,243,65,18,3,'마침',None).event('EndDialog','Return')
    cab.commit(db)
    db.Commit()
    # Query back package invariants without installing or executing any action.
    def query(sql):
        view = db.OpenView(sql);view.Execute(None);out=[]
        while True:
            row=view.Fetch()
            if row is None:break
            out.append([row.GetString(i) for i in range(1,row.GetFieldCount()+1)])
        view.Close();return out
    assert len(query('SELECT `File` FROM `File`')) == len(files)
    assert not query("SELECT `Value` FROM `Property` WHERE `Property` = 'ALLUSERS'")
    assert not query('SELECT `Action` FROM `CustomAction`')
    assert len(query('SELECT `Shortcut` FROM `Shortcut`')) == 2
    assert query("SELECT `Value` FROM `Property` WHERE `Property` = 'ProductName'")==[['STOOM Shift Translator']]
    assert query('SELECT `Name` FROM `Shortcut`')==[['SSTMSI|STOOM Shift Translator']]*2
    assert len(query('SELECT `UpgradeCode` FROM `Upgrade`')) == 2
    assert query("SELECT `Text` FROM `Control` WHERE `Dialog_` = 'WelcomeSST' AND `Control` = 'Install'")==[['설치']]
    assert query("SELECT `Value` FROM `Property` WHERE `Property` = 'ProductLanguage'")==[['1042']]
    assert query("SELECT `Sequence` FROM `InstallExecuteSequence` WHERE `Action` = 'RemoveExistingProducts'")==[['1510']]
    manifest={'version':version,'product_code':product,'upgrade_code':UPGRADE_CODE,
              'scope':'per-user','directory':'%LOCALAPPDATA%/Programs/STOOM Shift Translator MSI',
              'files':records,'custom_actions':0,'signed':False,
              'validation':'MSI database tables; no install/uninstall executed',
              'limitations':['Separate MSI family; EXE migration is not automatic.',
                             'Optional native TSF component is not registered by this MSI.',
                             'Unsigned MSI does not eliminate Windows security warnings.']}
    # Dialog objects retain the database; close every reference before hashing
    # the final compound-storage file (MSI finalizes it on handle close).
    welcome.db=None
    dlg.db=None
    del summary, db
    gc.collect()
    return manifest


def build(version,payload,output):
    manifest=build_database(version,payload,output)
    gc.collect()
    manifest['msi_bytes']=output.stat().st_size
    manifest['sha256']=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in manifest.items() if k!='files'},ensure_ascii=True))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',default=VERSION)
    parser.add_argument('--payload',type=Path,default=ROOT/'dist/STOOMShiftTranslator')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    output=args.output or ROOT/'dist'/('STOOM-Translator-v'+args.version.replace('.','')+'-TSF-setup.msi')
    build(args.version,args.payload.resolve(),output.resolve())
