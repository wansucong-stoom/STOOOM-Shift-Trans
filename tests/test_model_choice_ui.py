"""Offscreen model selection/persistence and paired-tokenizer integration."""

import json
import os
import pathlib
import sys
import tempfile
import types
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def forbidden_download(*args, **kwargs):
    raise AssertionError('model choice checks must not download anything')


class Listener:
    def start(self):
        pass

    def stop(self):
        pass


class Tap:
    def __init__(self, bridge):
        self.listener = Listener()


class Tray:
    ActivationReason = types.SimpleNamespace(DoubleClick=2)
    MessageIcon = types.SimpleNamespace(Information=1, Warning=2)

    def __init__(self, *args):
        self.activated = types.SimpleNamespace(connect=lambda callback: None)

    def setContextMenu(self, menu):
        pass

    def show(self):
        pass

    def setToolTip(self, text):
        pass

    def hide(self):
        pass

    def showMessage(self, *args):
        raise AssertionError('stubbed preflight must not emit desktop notifications')


def fake_preflight(self):
    self.engine_initializing = False
    self.engine_readiness.setText('test preflight skipped')


def expect_missing(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError('a selected unavailable model must fail rather than fall back')


with tempfile.TemporaryDirectory() as directory:
    previous_data = os.environ.get('LOCALAPPDATA')
    os.environ['LOCALAPPDATA'] = directory
    try:
        import main
    finally:
        if previous_data is None:
            del os.environ['LOCALAPPDATA']
        else:
            os.environ['LOCALAPPDATA'] = previous_data

    from PySide6.QtWidgets import QApplication

    main.APP = pathlib.Path(directory) / 'settings'
    main.APP.mkdir()
    main.MODELS = main.APP / 'models'
    main.MODELS.mkdir()
    main.Tap = Tap
    main.QSystemTrayIcon = Tray
    main.tsf_bridge.activate_installed = lambda: 'test: TSF activation skipped'
    main.App.begin_engine_preflight = fake_preflight
    main.install_pack = forbidden_download
    qt = QApplication.instance() or QApplication([])
    settings_path = main.APP / 'settings.json'

    with mock.patch.object(main.urllib.request, 'urlopen', side_effect=forbidden_download):
        # A pre-model-selection settings file retains existing language and
        # shortcut preferences, and now defaults Korean/English to OPUS Big.
        settings_path.write_text(json.dumps({
            'shift': '영어', 'ctrl': '일본어', 'source': '한국어',
            'engine': '기본 오프라인 엔진', 'external_path': '',
        }, ensure_ascii=False), encoding='utf-8')
        first = main.App()
        qt.processEvents()
        assert not first.isVisible(), 'settings check must stay offscreen'
        assert first.model_choices['ko_en'].currentData() == 'ko_en_opus_big'
        assert first.model_choices['en_ko'].currentData() == 'en_ko_opus_big'
        assert first.target['ctrl'].currentText() == '일본어'
        assert first.source.currentText() == '한국어'
        assert main.VARIANTS == {'ko_en': 'ko_en_opus_big', 'en_ko': 'en_ko_opus_big'}
        for pair in ('ko_en', 'en_ko'):
            box = first.model_choices[pair]
            assert {box.itemData(i) for i in range(box.count())} == {pair, pair + '_opus_big'}

        # An explicit English -> Korean Argos choice remains available.
        # User-visible labels may include
        # installation status, so stable model IDs drive selection and save.
        en_ko = first.model_choices['en_ko']
        en_ko.setCurrentIndex(en_ko.findData('en_ko'))
        qt.processEvents()
        saved = json.loads(settings_path.read_text(encoding='utf-8'))
        assert saved['models'] == {'ko_en': 'ko_en_opus_big', 'en_ko': 'en_ko'}
        assert first.model_choices['en_ko'].currentData() == 'en_ko'
        assert main.VARIANTS == saved['models']

        # A fresh window loads the persisted independent choices.  No model
        # or language-pack file has been downloaded by these UI changes.
        first.deleteLater()
        qt.processEvents()
        second = main.App()
        qt.processEvents()
        assert second.model_choices['ko_en'].currentData() == 'ko_en_opus_big'
        assert second.model_choices['en_ko'].currentData() == 'en_ko'
        assert main.VARIANTS == saved['models']
        assert not list(main.MODELS.iterdir())
        second.deleteLater()
        qt.processEvents()

        # Choosing OPUS must not run installed Argos as a silent fallback.
        installed = {'ko_en', 'en_ko', 'en_ja', 'ja_en'}
        queried = []
        def is_installed(pack_id):
            queried.append(pack_id)
            return pack_id in installed
        with mock.patch.object(main, 'pack_installed', side_effect=is_installed):
            expect_missing(lambda: main.path_for('ko', 'en'))
            assert queried == ['ko_en_opus_big']
            queried.clear()
            assert main.path_for('en', 'ko') == ['en_ko']
            assert queried == ['en_ko']

            # Both pivot legs honor their selected IDs, independently of the
            # corresponding installed legacy alternative.
            queried.clear()
            expect_missing(lambda: main.path_for('ko', 'ja'))
            assert 'ko_en' not in queried and 'ko_en_opus_big' in queried
            installed.add('ko_en_opus_big')
            assert main.path_for('ko', 'ja') == ['ko_en_opus_big', 'en_ja']
            main.VARIANTS['en_ko'] = 'en_ko_opus_big'
            queried.clear()
            expect_missing(lambda: main.path_for('ja', 'ko'))
            assert 'en_ko' not in queried and 'en_ko_opus_big' in queried
            installed.add('en_ko_opus_big')
            assert main.path_for('ja', 'ko') == ['ja_en', 'en_ko_opus_big']

        # Load the real model-selection branch against tiny fixture files.
        # Runtime constructors are faked: these files are not real SPM/models.
        root = main.MODELS / 'ko_en_opus_big'
        model = root / 'model'
        model.mkdir(parents=True)
        (model / 'model.bin').write_bytes(b'fixture weights')
        (model / 'config.json').write_text('{}', encoding='utf-8')
        (model / 'shared_vocabulary.json').write_text('["piece"]', encoding='utf-8')
        (root / 'source.spm').write_bytes(b'fixture source')
        (root / 'target.spm').write_bytes(b'fixture target')
        (root / 'pack.json').write_text(json.dumps({
            'id': 'ko_en_opus_big', 'format': 'native-marian-int8',
        }), encoding='utf-8')
        calls = []
        class SP:
            def __init__(self, model_file):
                self.side = pathlib.Path(model_file).name
                calls.append(('tokenizer', self.side))

            def encode(self, text, **kwargs):
                calls.append(('encode', self.side, text, kwargs))
                assert self.side == 'source.spm'
                return ['source-piece']

            def decode(self, tokens, **kwargs):
                calls.append(('decode', self.side, tokens, kwargs))
                assert self.side == 'target.spm'
                return 'target sentence'

        class Translator:
            def __init__(self, path, **kwargs):
                calls.append(('translator', pathlib.Path(path).name, kwargs))

        main._load_model_cached.cache_clear()
        with mock.patch.dict(sys.modules, {
            'sentencepiece': types.SimpleNamespace(SentencePieceProcessor=SP),
            'ctranslate2': types.SimpleNamespace(Translator=Translator),
        }):
            tokenizer, translator = main.load_model('ko_en_opus_big')
            assert isinstance(tokenizer, main.PairedTokenizer)
            assert tokenizer.source is not tokenizer.target
            assert tokenizer.encode('원문', out_type=str) == ['source-piece']
            assert tokenizer.decode(['target-piece']) == 'target sentence'
            assert ('encode', 'source.spm', '원문', {'out_type': str}) in calls
            assert ('decode', 'target.spm', ['target-piece'], {}) in calls
            assert ('translator', 'model', {'compute_type': 'int8', 'intra_threads': 4}) in calls
            assert main.load_model('ko_en_opus_big') == (tokenizer, translator)
            assert len([call for call in calls if call[0] == 'tokenizer']) == 2
        main._load_model_cached.cache_clear()

print('model choice UI: legacy migration, per-direction persistence/restart, no route fallback, paired source/target tokenizers: PASS')
