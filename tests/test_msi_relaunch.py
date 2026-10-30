"""MSI table and native condition checks, without installing or launching.

A tiny fake payload is packaged only in a temporary directory. Windows
Installer opens its session with machine state ignored; no install sequence,
custom action, installed application, registry change or document is invoked.
"""
import ctypes as C
from ctypes import wintypes as W
import gc
import msilib
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build_msi as builder


def rows(db, sql):
    view = db.OpenView(sql); view.Execute(None); result = []
    try:
        while True:
            row = view.Fetch()
            if row is None: return result
            result.append([row.GetString(i) for i in range(1, row.GetFieldCount() + 1)])
    finally:
        view.Close()


msi = C.WinDLL('msi')
msi.MsiOpenPackageExW.argtypes = [W.LPCWSTR, W.DWORD, C.POINTER(W.UINT)]
msi.MsiOpenPackageExW.restype = W.UINT
msi.MsiSetInternalUI.argtypes = [C.c_int, C.c_void_p]
msi.MsiSetInternalUI.restype = C.c_int
msi.MsiSetPropertyW.argtypes = [W.UINT, W.LPCWSTR, W.LPCWSTR]
msi.MsiSetPropertyW.restype = W.UINT
msi.MsiDoActionW.argtypes = [W.UINT, W.LPCWSTR]
msi.MsiDoActionW.restype = W.UINT
msi.MsiSetInstallLevel.argtypes = [W.UINT, C.c_int]
msi.MsiSetInstallLevel.restype = W.UINT
msi.MsiSetFeatureStateW.argtypes = [W.UINT, W.LPCWSTR, C.c_int]
msi.MsiSetFeatureStateW.restype = W.UINT
msi.MsiEvaluateConditionW.argtypes = [W.UINT, W.LPCWSTR]
msi.MsiEvaluateConditionW.restype = C.c_int
msi.MsiCloseHandle.argtypes = [W.UINT]
msi.MsiCloseHandle.restype = W.UINT


def check(code):
    assert code == 0, 'Windows Installer API returned ' + str(code)


cases = 0
with tempfile.TemporaryDirectory(prefix='sst-msi-relaunch-') as directory:
    root = Path(directory); payload = root / 'payload'; payload.mkdir()
    # Invalid as an executable on purpose: the test must never launch it.
    (payload / 'STOOMShiftTranslator.exe').write_bytes(b'fixture only; never executable')
    output = root / 'fixture.msi'
    with patch.object(builder, 'NAMESPACE', uuid.uuid4()), patch.object(builder, 'UPGRADE_CODE', '{' + str(uuid.uuid4()).upper() + '}'):
        manifest = builder.build_database('99.0.1', payload, output)
    assert manifest['custom_actions'] == 1 and manifest['post_install_launch']['type'] == 210
    assert not manifest['signed']
    db = msilib.OpenDatabase(str(output), msilib.MSIDBOPEN_READONLY)
    try:
        actions = rows(db, 'SELECT `Action`, `Type`, `Source`, `Target` FROM `CustomAction`')
        assert actions == [['LaunchSST', '210', builder.ident('F', 'STOOMShiftTranslator.exe'), '--after-update']]
        assert rows(db, "SELECT `File` FROM `File` WHERE `File` = '" + actions[0][2] + "'") == [[actions[0][2]]]
        assert rows(db, "SELECT `Value` FROM `Property` WHERE `Property` = 'SSTLAUNCH'") == [['1']]
        assert 'SSTLAUNCH' in rows(db, "SELECT `Value` FROM `Property` WHERE `Property` = 'SecureCustomProperties'")[0][0].split(';')
        execute = rows(db, "SELECT `Condition`, `Sequence` FROM `InstallExecuteSequence` WHERE `Action` = 'LaunchSST'")
        finalize = int(rows(db, "SELECT `Sequence` FROM `InstallExecuteSequence` WHERE `Action` = 'InstallFinalize'")[0][0])
        assert len(execute) == 1 and int(execute[0][1]) > finalize
        assert not rows(db, "SELECT `Action` FROM `InstallUISequence` WHERE `Action` = 'LaunchSST'")
        full_ui = rows(db, "SELECT `Dialog_`, `Control_`, `Argument`, `Condition`, `Ordering` FROM `ControlEvent` WHERE `Event` = 'DoAction'")
        assert full_ui == [['ExitDialog', 'Finish', 'LaunchSST', builder.RELAUNCH_FULL_UI, '1']]
        assert rows(db, "SELECT `Ordering` FROM `ControlEvent` WHERE `Dialog_` = 'ExitDialog' AND `Control_` = 'Finish' AND `Event` = 'EndDialog'") == [['2']]
        assert rows(db, "SELECT `Sequence` FROM `InstallUISequence` WHERE `Action` = 'ExitDialog'") == [['-1']]
        assert rows(db, "SELECT `Property`, `Value` FROM `CheckBox`") == [['SSTLAUNCH', '1']]
        assert rows(db, "SELECT `Property` FROM `Control` WHERE `Dialog_` = 'ExitDialog' AND `Control` = 'LaunchSST'") == [['SSTLAUNCH']]
        basic_condition = execute[0][0]; full_condition = full_ui[0][3]
    finally:
        del db
        gc.collect()

    previous_ui = msi.MsiSetInternalUI(2, None)  # No dialogs, including errors.
    session = W.UINT()
    try:
        check(msi.MsiOpenPackageExW(str(output), 1, C.byref(session)))  # IGNOREMACHINESTATE
        check(msi.MsiSetPropertyW(session, 'INSTALLDIR', str(root / 'unused-target')))
        # Initialize feature action states with costing only. Never execute
        # INSTALL, InstallExecute, InstallFinalize, or our launch action.
        for action in ('CostInitialize', 'FileCost', 'CostFinalize'):
            check(msi.MsiDoActionW(session, action))
        check(msi.MsiSetInstallLevel(session, 1))

        def evaluate(ui, changes=None, state=3):
            global cases
            properties = {'SSTLAUNCH':'1', 'Installed':'', 'REMOVE':'', 'UPGRADINGPRODUCTCODE':'',
                          'ReplacedInUseFiles':'', 'OLDPRODUCTS':'', 'REINSTALL':'', 'UILevel':str(ui)}
            properties.update(changes or {})
            for name, value in properties.items(): check(msi.MsiSetPropertyW(session, name, value))
            check(msi.MsiSetFeatureStateW(session, 'Main', state))
            actual = tuple(msi.MsiEvaluateConditionW(session, condition) for condition in (basic_condition, full_condition))
            assert all(value in (0,1) for value in actual), ('invalid MSI condition', actual, properties)
            cases += 1
            return actual

        for ui in (0,2,3,4,5,6):
            expected = (int(ui in (3,4)), int(ui == 5))
            assert evaluate(ui) == expected
            assert evaluate(ui, {'OLDPRODUCTS':'{OLD-PRODUCT}'}) == expected  # Major upgrade.
            assert evaluate(ui, {'SSTLAUNCH':''}) == (0,0)  # Unchecked full-UI box.
            assert evaluate(ui, {'SSTLAUNCH':'0'}) == (0,0)
            assert evaluate(ui, {'Installed':'1', 'REINSTALL':'ALL'}) == (0,0)  # Repair.
            assert evaluate(ui, {'Installed':'1'}) == (0,0)  # Maintenance/modify.
            assert evaluate(ui, {'REMOVE':'ALL'}) == (0,0)
            assert evaluate(ui, {'REMOVE':'all'}) == (0,0)
            assert evaluate(ui, {'UPGRADINGPRODUCTCODE':'{NEW-PRODUCT}'}) == (0,0)
            assert evaluate(ui, {'ReplacedInUseFiles':'1'}) == (0,0)
            assert evaluate(ui, state=2) == (0,0)  # Feature removal/absence.
        assert not (root / 'unused-target').exists(), 'condition checks created installed files'
    finally:
        if session.value: check(msi.MsiCloseHandle(session))
        msi.MsiSetInternalUI(previous_ui, None)

print(f'PASS: MSI installed-file Type210, success-only Finish ordering, after-Finalize passive path, '
      f'checkbox and {cases} native condition cases; no installer sequence/application executed')
