"""Offscreen updater workflow: no network, real installer, hooks or user data."""
import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import types
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


class Tap:
    def __init__(self, bridge):
        self.listener = types.SimpleNamespace(start=lambda: None, stop=lambda: None)


class Tray:
    ActivationReason = types.SimpleNamespace(Trigger=1, DoubleClick=2)
    MessageIcon = types.SimpleNamespace(Information=1, Warning=2)

    def __init__(self, *args):
        self.activated = types.SimpleNamespace(connect=lambda fn: None)
        self.messages = []

    def setContextMenu(self, value): pass
    def setToolTip(self, value): pass
    def show(self): pass
    def hide(self): pass
    def showMessage(self, *args): self.messages.append(args)


class UpdateRequest:
    def requested(self): return False
    def close(self): pass


with tempfile.TemporaryDirectory() as directory:
    previous_data = os.environ.get('LOCALAPPDATA')
    os.environ['LOCALAPPDATA'] = directory
    try:
        import main
    finally:
        if previous_data is None: del os.environ['LOCALAPPDATA']
        else: os.environ['LOCALAPPDATA'] = previous_data
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFontDatabase

    main.APP = pathlib.Path(directory) / 'app'
    main.APP.mkdir()
    main.MODELS = main.APP / 'models'
    main.MODELS.mkdir()
    sentinel = main.MODELS / 'installed-model.bin'
    sentinel.write_bytes(b'model must survive updater tests')
    main.Tap = Tap
    main.QSystemTrayIcon = Tray
    main.tsf_bridge.Client = lambda handle: types.SimpleNamespace()
    main.tsf_bridge.activate_installed = lambda: 'test: TSF not activated'
    main.update_control.UpdateRequest = UpdateRequest
    main.App.begin_engine_preflight = lambda self: setattr(self, 'engine_initializing', False)
    qt = QApplication.instance() or QApplication([])
    # The offscreen platform does not always enumerate Windows system fonts.
    font=pathlib.Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'malgun.ttf'
    if font.is_file():QFontDatabase.addApplicationFont(str(font))
    gui_thread = threading.get_ident()
    settings = main.APP / 'settings.json'

    def spin_until(predicate, timeout=3):
        end = time.monotonic() + timeout
        while not predicate() and time.monotonic() < end:
            qt.processEvents()
            time.sleep(.005)
        qt.processEvents()
        assert predicate(), 'Qt workflow did not finish'

    def make_window():
        window = main.App()
        qt.processEvents()
        # Exercise manual and deterministic auto calls only. A render must
        # never start a real network timer in the background.
        window._release_start_timer.stop()
        window._release_timer.stop()
        return window

    checks = []
    def no_update(current_version):
        assert threading.get_ident() != gui_thread
        checks.append(current_version)
        return None

    with mock.patch.object(main.release_updates, 'check_latest', side_effect=no_update):
        w = make_window()
        assert w.stack.count() == 4 and w.nav[3].text() == '업데이트'
        assert w.check_updates.isChecked() and not w.auto_install_updates.isChecked()
        assert w.model_choices['ko_en'].currentData() == 'ko_en_opus_big'
        assert w.model_choices['en_ko'].currentData() == 'en_ko_opus_big'
        assert not checks, 'startup must not synchronously check the network'
        w.check_updates.setChecked(False)
        w.check_release(False)
        assert not checks
        w.auto_install_updates.setChecked(True)
        assert w.check_updates.isChecked(), 'automatic install must imply checks'
        spin_until(lambda: not w._release_check_inflight)
        assert checks == [main.release_updates.VERSION]
        w.check_updates.setChecked(False)
        assert not w.auto_install_updates.isChecked()
        assert json.loads(settings.read_text(encoding='utf-8'))['auto_install_updates'] is False

    # Settings without or with invalid model IDs use OPUS. Explicit old model
    # choices and unknown future settings survive an update and subsequent save.
    data=json.loads(settings.read_text(encoding='utf-8'))
    data.update(models={'ko_en':'ko_en','en_ko':'wrong-language-id'},future_setting={'keep':True})
    settings.write_text(json.dumps(data), encoding='utf-8')
    w.load()
    assert w.model_choices['ko_en'].currentData() == 'ko_en'
    assert w.model_choices['en_ko'].currentData() == 'en_ko_opus_big'
    w.save()
    saved=json.loads(settings.read_text(encoding='utf-8'))
    assert saved['models']['ko_en']=='ko_en' and saved['future_setting']=={'keep':True}
    assert sentinel.read_bytes()==b'model must survive updater tests'
    main.VARIANTS.clear()
    assert main.selected_model('ko_en')=='ko_en_opus_big'
    main.VARIANTS['en_ko']='ko_en'
    assert main.selected_model('en_ko')=='en_ko_opus_big'

    release=types.SimpleNamespace(version='0.7.0',tag='v0.7.0',url='https://github.com/wansucong-stoom/STOOOM-Shift-Trans/releases/tag/v0.7.0',size=100,sha256='a'*64)
    check_gate=threading.Event()
    check_started=threading.Event()
    def check_new(current_version):
        assert threading.get_ident()!=gui_thread
        checks.append(current_version);check_started.set()
        assert check_gate.wait(3)
        return release

    with mock.patch.object(main.release_updates,'check_latest',side_effect=check_new):
        w.check_updates.setChecked(True)
        w.check_release(True)
        spin_until(check_started.is_set)
        count=len(checks)
        w.check_release(True)
        assert len(checks)==count, 'overlapping checks must be ignored'
        ticks=[]
        timer=QTimer();timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(1));timer.start()
        spin_until(lambda:len(ticks)>=3)
        timer.stop()
        assert w._release_check_inflight, 'fake network check should still be pending'
        check_gate.set()
        spin_until(lambda:not w._release_check_inflight)
        assert w._release_candidate.tag==release.tag and w.release_install_button.isEnabled()
        assert len(w.tray.messages)==1 and '0.7.0' in w.tray.messages[0][1]
        assert json.loads(settings.read_text(encoding='utf-8'))['notified_release']=='v0.7.0'
        w.check_release(True)
        spin_until(lambda:not w._release_check_inflight)
        assert len(w.tray.messages)==1, 'same release must not notify twice'

    download_gate=threading.Event();download_started=threading.Event();installer_gate=threading.Event()
    verified=[];launches=[]
    update_path=main.APP/'updates'/'verified-test.exe'
    def fake_download(candidate,cache_dir,progress=None):
        assert threading.get_ident()!=gui_thread and candidate is release
        assert cache_dir==main.APP/'updates'
        progress(50,100);download_started.set()
        assert download_gate.wait(3)
        cache_dir.mkdir(exist_ok=True);update_path.write_bytes(b'fixture only; never execute')
        verified.append(update_path)
        return update_path
    class Process:
        def wait(self):
            assert installer_gate.wait(3)
            return 1
    def fake_launch(path):
        assert threading.get_ident()!=gui_thread
        assert path in verified, 'installer cannot run before verification completes'
        assert w._release_installing, 'UI must reserve install before launching the worker'
        launches.append(path)
        return Process()
    with mock.patch.object(main.release_updates,'download_verified',side_effect=fake_download),mock.patch.object(main.release_updates,'launch_installer',side_effect=fake_launch):
        w.auto_install_updates.setChecked(True)
        spin_until(download_started.is_set)
        w.download_release(True)
        assert w._release_download_inflight and not launches
        w.auto_install_updates.setChecked(False)
        download_gate.set()
        spin_until(lambda:not w._release_download_inflight)
        assert w._release_ready and not launches, 'revoking auto install during download must be respected'
        assert '꺼져 있어' in w.release_status.text()
        # Every busy state must defer installation even after an explicit click.
        for attribute,value in [('busy',True),('downloading',True),('engine_initializing',True),('_clipboard_lease',object()),('_pending_input',object()),('_tsf_request',object())]:
            setattr(w,attribute,value)
            w.download_release(True)
            assert not launches
            setattr(w,attribute,False if isinstance(value,bool) else None)
        metadata_gate=threading.Event();metadata_started=threading.Event()
        def pending_metadata(current_version):
            assert threading.get_ident()!=gui_thread
            metadata_started.set();assert metadata_gate.wait(3);return release
        with mock.patch.object(main.release_updates,'check_latest',side_effect=pending_metadata):
            w.check_release(True);spin_until(metadata_started.is_set)
            w.install_ready_release()
            assert not launches and not w.release_install_button.isEnabled(), 'metadata check must serialize with a ready installation'
            metadata_gate.set();spin_until(lambda:len(launches)==1)
        assert not w._quitting, 'spawning an installer must not force an early app quit'
        assert w._release_installing
        w.install_ready_release()
        assert len(launches)==1, 'ready timer must not start duplicate installers'
        installer_gate.set()
        spin_until(lambda:not w._release_installing)
        assert '완료되지 않았습니다' in w.release_status.text()

    # Failed verification never creates a ready file or runs an installer.
    w._release_ready=None
    def failed_verification(*args,**kwargs):raise main.release_updates.UpdateError('SHA-256 mismatch (test)')
    with mock.patch.object(main.release_updates,'download_verified',side_effect=failed_verification),mock.patch.object(main.release_updates,'launch_installer',side_effect=AssertionError('unverified execution')):
        w.download_release(True)
        spin_until(lambda:not w._release_download_inflight)
        assert w._release_ready is None and 'SHA-256 mismatch' in w.release_status.text()

    # MSI does not use the EXE installer's cooperative shutdown event. A
    # successful launch must release loaded files, but failure must keep UI.
    with mock.patch.object(w,'quit') as shutdown:
        w.release_event({'kind':'launched','package_kind':'msi','error':'test failure'})
        shutdown.assert_not_called()
        w.release_event({'kind':'launched','package_kind':'msi','error':''})
        shutdown.assert_called_once()

    # Late worker completion after shutdown must not restart any work.
    w._quitting=True
    with mock.patch.object(main.release_updates,'check_latest',side_effect=AssertionError('check after quit')),mock.patch.object(main.release_updates,'launch_installer',side_effect=AssertionError('launch after quit')):
        w.check_release(True)
        w.release_event({'kind':'downloaded','release':release,'manual':True,'path':update_path,'error':''})
        assert w._release_ready is None
    w._quitting=False

    # Optional review artifact: render only this synthetic settings window.
    if '--screenshot' in sys.argv:
        target=pathlib.Path(sys.argv[sys.argv.index('--screenshot')+1]).resolve()
        target.parent.mkdir(parents=True,exist_ok=True)
        w.check_updates.setChecked(True)
        w.auto_install_updates.setChecked(False)
        w.release_status.setText('새 버전이 있으면 여기에서 알려드립니다.')
        w.release_install_button.setText('다운로드 후 업데이트');w.release_install_button.setEnabled(False)
        w.release_notes_button.setEnabled(False)
        w.select_page(3);w.resize(850,590);w.show();qt.processEvents()
        assert w.grab().save(str(target))
        w.hide()
    w._release_wait_timer.stop();w._release_start_timer.stop();w._release_timer.stop();w._update_timer.stop()
    w._quitting=True;w.deleteLater();qt.processEvents()
    assert sentinel.read_bytes()==b'model must survive updater tests'

print('updater UI: responsive workers, opt-in persistence, once-only notice, verified download, revoke consent, idle install, no duplicate launch, failure/shutdown guards and OPUS defaults: PASS')
