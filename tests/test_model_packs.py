"""Language-pack installation checks using tiny archives, never real models."""
import hashlib
import io
import json
import pathlib
import stat
import sys
import tempfile
import types
from unittest import mock
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import model_packs


PACK_ID = 'ko_en_opus_big'
DECODER = 'models:\n  - model.npz\nvocabs:\n  - source.yml\n  - target.yml\n'
ORDERED_TOKENS = ['<unk>', '<s>', '</s>', 'word:colon', '"double"', "single'quote",
                  '한글', r'literal\t', r'\x41', '? starts', ' white space ']


def archive(path, *, decoder=DECODER, extra=(), root='native/'):
    files = {
        root + 'decoder.yml': decoder.encode('utf-8'),
        root + 'model.npz': b'native weights',
        root + 'source.yml': b'source: 0\n',
        root + 'target.yml': b'target: 0\n',
        root + 'source.spm': b'source tokenizer',
        root + 'target.spm': b'target tokenizer',
        root + 'do-not-extract.txt': b'unrelated archive file',
    }
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as output:
        for name, content in files.items():
            output.writestr(name, content)
        for name, content in extra:
            output.writestr(name, content)
    return path


def source(path, *, digest=None, size=None):
    content = path.read_bytes()
    return model_packs.Source(
        'https://example.invalid/fixture.zip',
        digest if digest is not None else hashlib.sha256(content).hexdigest(),
        size if size is not None else len(content),
    )


def fake_converter(calls):
    def convert(model_path, vocab_paths, output_dir):
        model_path, output_dir = pathlib.Path(model_path), pathlib.Path(output_dir)
        vocab_paths = tuple(pathlib.Path(path) for path in vocab_paths)
        calls.append((model_path.name, tuple(path.name for path in vocab_paths)))
        assert model_path.read_bytes() == b'native weights'
        assert [path.read_bytes() for path in vocab_paths] == [b'source: 0\n', b'target: 0\n']
        assert not list(model_path.parent.rglob('do-not-extract.txt'))
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / 'model.bin').write_bytes(b'converted int8 weights')
        (output_dir / 'config.json').write_text('{}', encoding='utf-8')
        (output_dir / 'shared_vocabulary.json').write_text('["word"]', encoding='utf-8')
    return convert


def install_archive(*args, **kwargs):
    # Tokenizer compatibility has direct unit tests below; archive fixtures are not real SPM binaries.
    kwargs.setdefault('validator', lambda files: None)
    return model_packs.install_archive(*args, **kwargs)


def tree_bytes(path):
    return {str(item.relative_to(path)): item.read_bytes()
            for item in path.rglob('*') if item.is_file()}


def expect_failure(call):
    try:
        call()
    except Exception:
        return
    raise AssertionError('unsafe or invalid archive must fail')


def test_catalog_and_legacy_layout(root):
    expected = {'en_ja', 'en_ko', 'ja_en', 'ko_en', 'ko_en_opus_big', 'en_ko_opus_big'}
    assert set(model_packs.CATALOG) == expected
    assert {item.id for item in model_packs.choices('ko', 'en')} == {'ko_en', 'ko_en_opus_big'}
    assert {item.id for item in model_packs.choices('en', 'ko')} == {'en_ko', 'en_ko_opus_big'}
    assert {item.id for item in model_packs.choices('ja', 'en')} == {'ja_en'}
    assert not model_packs.choices('ko', 'ja')

    models = root / 'legacy-models'
    model_dir = models / 'ko_en' / 'model'
    model_dir.mkdir(parents=True)
    (model_dir / 'model.bin').write_bytes(b'legacy model')
    (model_dir / 'shared_vocabulary.txt').write_text('word\n', encoding='utf-8')
    tokenizer = models / 'ko_en' / 'sentencepiece.model'
    tokenizer.write_bytes(b'legacy tokenizer')
    assert model_packs.installed(models, 'ko_en')
    runtime = model_packs.runtime_files(models, 'ko_en')
    assert tuple(runtime) == (model_dir, tokenizer, tokenizer)
    assert not model_packs.installed(models, PACK_ID)


def test_native_conversion_and_selective_extraction(root):
    compressed = archive(root / 'native.zip')
    models = root / 'native-models'
    calls = []
    destination = install_archive(
        PACK_ID, compressed, models, source=source(compressed), converter=fake_converter(calls))
    assert pathlib.Path(destination) == models / PACK_ID
    assert len(calls) == 1
    assert model_packs.installed(models, PACK_ID)
    model_dir, source_spm, target_spm = model_packs.runtime_files(models, PACK_ID)
    assert (model_dir / 'model.bin').read_bytes() == b'converted int8 weights'
    assert source_spm != target_spm
    assert source_spm.read_bytes() == b'source tokenizer'
    assert target_spm.read_bytes() == b'target tokenizer'
    assert (pathlib.Path(destination) / 'pack.json').is_file()
    json.loads((pathlib.Path(destination) / 'pack.json').read_text(encoding='utf-8'))
    assert not list(pathlib.Path(destination).rglob('*.npz'))
    assert not list(pathlib.Path(destination).rglob('do-not-extract.txt'))


def test_argos_archive_compatibility(root):
    compressed = root / 'legacy.argosmodel'
    with zipfile.ZipFile(compressed, 'w') as output:
        output.writestr('ko_en/sentencepiece.model', b'legacy tokenizer')
        output.writestr('ko_en/model/model.bin', b'legacy weights')
        output.writestr('ko_en/model/shared_vocabulary.txt', 'word\n')
        output.writestr('ko_en/ignored.txt', b'do not extract')
    models = root / 'legacy-installed-models'
    install_archive('ko_en', compressed, models, source=source(compressed))
    assert model_packs.installed(models, 'ko_en')
    model, source_spm, target_spm = model_packs.runtime_files(models, 'ko_en')
    assert source_spm == target_spm
    assert (model / 'model.bin').read_bytes() == b'legacy weights'
    assert not (models / 'ko_en' / 'ignored.txt').exists()


def test_ordered_vocab_yaml_roundtrip(root):
    from ctranslate2.converters.marian import load_vocab
    path = root / 'ordered.vocab'
    path.write_text('\n'.join(ORDERED_TOKENS) + '\n', encoding='utf-8')
    model_packs._ordered_vocab_to_yaml(path)
    assert load_vocab(str(path)) == ORDERED_TOKENS, 'tokens and numeric positions must survive CT2 parsing'


def test_plain_vocab_archive_adapter(root):
    from ctranslate2.converters.marian import load_vocab
    compressed = root / 'plain-vocab.zip'
    source_tokens = ORDERED_TOKENS
    target_tokens = ORDERED_TOKENS[:3] + list(reversed(ORDERED_TOKENS[3:]))
    decoder = 'models: [model.npz]\nvocabs: [source.vocab, target.vocab]\n'
    with zipfile.ZipFile(compressed, 'w') as output:
        output.writestr('plain/decoder.yml', decoder)
        output.writestr('plain/model.npz', b'native weights')
        output.writestr('plain/source.vocab', '\n'.join(source_tokens) + '\n')
        output.writestr('plain/target.vocab', '\n'.join(target_tokens) + '\n')
        output.writestr('plain/source.spm', b'source tokenizer')
        output.writestr('plain/target.spm', b'target tokenizer')
    calls = []

    def converter(model_path, vocab_paths, output_dir):
        assert pathlib.Path(model_path).read_bytes() == b'native weights'
        assert [load_vocab(str(path)) for path in vocab_paths] == [source_tokens, target_tokens]
        calls.append(tuple(pathlib.Path(path).name for path in vocab_paths))
        output_dir = pathlib.Path(output_dir)
        output_dir.mkdir(parents=True)
        (output_dir / 'model.bin').write_bytes(b'converted int8 weights')
        (output_dir / 'config.json').write_text('{}', encoding='utf-8')
        (output_dir / 'source_vocabulary.json').write_text(json.dumps(source_tokens), encoding='utf-8')
        (output_dir / 'target_vocabulary.json').write_text(json.dumps(target_tokens), encoding='utf-8')

    models = root / 'plain-vocab-models'
    install_archive(PACK_ID, compressed, models, source=source(compressed), converter=converter)
    assert len(calls) == 1
    assert model_packs.installed(models, PACK_ID)


def test_download_abstraction_and_size_bound(root):
    compressed = archive(root / 'download.zip')
    manifest = source(compressed)
    models = root / 'download-models'
    progress = []

    def opener(request, timeout):
        assert request.full_url == manifest.url and timeout == 60
        return io.BytesIO(compressed.read_bytes())

    model_packs.install(PACK_ID, models, source=manifest, opener=opener,
                        converter=fake_converter([]), validator=lambda files: None,
                        progress=progress.append)
    assert '다운로드를 시작' in progress[0]
    assert any('MiB' in message for message in progress)
    assert '설치가 완료' in progress[-1]
    before = tree_bytes(models / PACK_ID)
    expect_failure(lambda: model_packs.install(
        PACK_ID, models, source=manifest,
        opener=lambda request, timeout: io.BytesIO(compressed.read_bytes() + b'oversize'),
        converter=fake_converter([]), validator=lambda files: None))
    assert tree_bytes(models / PACK_ID) == before
    assert not list(models.glob('*.download'))


def test_verification_and_failed_conversion_preserve_existing(root):
    compressed = archive(root / 'preserve.zip', root='')
    models = root / 'preserve-models'
    install_archive(
        PACK_ID, compressed, models, source=source(compressed), converter=fake_converter([]))
    before = tree_bytes(models / PACK_ID)
    calls = []
    for untrusted in (source(compressed, digest='0' * 64),
                      source(compressed, size=compressed.stat().st_size + 1)):
        expect_failure(lambda: install_archive(
            PACK_ID, compressed, models, source=untrusted, converter=fake_converter(calls)))
        assert tree_bytes(models / PACK_ID) == before
    assert not calls, 'verification must happen before conversion'
    unverified = model_packs.Source('https://example.invalid/unverified.zip', None, None)
    assert not unverified.verified
    expect_failure(lambda: install_archive(
        PACK_ID, compressed, models, source=unverified, converter=fake_converter(calls)))
    assert not calls and tree_bytes(models / PACK_ID) == before

    def broken_converter(*args):
        raise RuntimeError('fixture conversion failed')

    expect_failure(lambda: install_archive(
        PACK_ID, compressed, models, source=source(compressed), converter=broken_converter))
    assert tree_bytes(models / PACK_ID) == before
    assert model_packs.installed(models, PACK_ID)


def test_decoder_paths_and_yaml_are_rejected(root):
    invalid = [
        ('traversal', 'models: [../../outside.npz]\nvocabs: [source.yml, target.yml]\n',
         [('../../outside.npz', b'native weights')]),
        ('absolute', 'models: [/outside.npz]\nvocabs: [source.yml, target.yml]\n',
         [('/outside.npz', b'native weights')]),
        ('windows-absolute', 'models: [C:/outside.npz]\nvocabs: [source.yml, target.yml]\n',
         [('C:/outside.npz', b'native weights')]),
        ('yaml-object', '!!python/object/apply:os.system ["must never run"]\n', []),
        ('multi-model', 'models: [model.npz, second.npz]\nvocabs: [source.yml, target.yml]\n',
         [('native/second.npz', b'other weights')]),
        ('missing-vocab', 'models: [model.npz]\nvocabs: [source.yml]\n', []),
    ]
    for name, decoder, extra in invalid:
        compressed = archive(root / (name + '.zip'), decoder=decoder, extra=extra)
        models = root / (name + '-models')
        calls = []
        expect_failure(lambda: install_archive(
            PACK_ID, compressed, models, source=source(compressed), converter=fake_converter(calls)))
        assert not calls
        assert not model_packs.installed(models, PACK_ID)
    assert not (root / 'outside.npz').exists()


def test_selected_symlink_is_rejected(root):
    compressed = root / 'symlink.zip'
    link = zipfile.ZipInfo('native/model.npz')
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(compressed, 'w') as output:
        output.writestr('native/decoder.yml', DECODER)
        output.writestr(link, '../../outside.npz')
        output.writestr('native/source.yml', 'source: 0\n')
        output.writestr('native/target.yml', 'target: 0\n')
        output.writestr('native/source.spm', b'source tokenizer')
        output.writestr('native/target.spm', b'target tokenizer')
    calls = []
    models = root / 'symlink-models'
    expect_failure(lambda: install_archive(
        PACK_ID, compressed, models, source=source(compressed), converter=fake_converter(calls)))
    assert not calls
    assert not model_packs.installed(models, PACK_ID)


class FakeProcessor:
    def __init__(self, pieces):
        self.pieces = pieces

    def get_piece_size(self):
        return len(self.pieces)

    GetPieceSize = get_piece_size

    def id_to_piece(self, index):
        return self.pieces[index]

    IdToPiece = id_to_piece

    def is_control(self, index):
        return self.pieces[index] in ('<s>', '</s>')

    IsControl = is_control

    def is_unknown(self, index):
        return self.pieces[index] == '<unk>'

    def is_unused(self, index):
        return False


def test_native_tokenizer_vocabulary_alignment(root):
    location = root / 'tokenizer-alignment'
    model = location / 'model'
    model.mkdir(parents=True)
    source_spm, target_spm = location / 'source.spm', location / 'target.spm'
    source_spm.write_bytes(b'fake source SPM')
    target_spm.write_bytes(b'fake target SPM')
    files = model_packs.RuntimeFiles(model, source_spm, target_spm)
    pieces = {'source.spm': ['<unk>', '<s>', '</s>', '▁source'],
              'target.spm': ['<unk>', '<s>', '</s>', '▁target']}

    def processor_factory(model_file=None, **kwargs):
        return FakeProcessor(pieces[pathlib.Path(model_file).name])

    def vocab(name, values):
        (model / name).write_text(json.dumps(values), encoding='utf-8')

    vocab('source_vocabulary.json', ['<unk>', '▁source', '▁extra'])
    vocab('target_vocabulary.json', ['<unk>', '▁target', '▁extra'])
    model_packs.validate_tokenizers(files, processor_factory=processor_factory)
    vocab('source_vocabulary.json', ['<unk>', '▁wrong'])
    expect_failure(lambda: model_packs.validate_tokenizers(files, processor_factory=processor_factory))
    vocab('source_vocabulary.json', ['<unk>', '▁source'])
    vocab('target_vocabulary.json', ['<unk>', '▁wrong'])
    expect_failure(lambda: model_packs.validate_tokenizers(files, processor_factory=processor_factory))

    # A shared CT2 vocabulary is allowed when it covers both SP token sets.
    (model / 'source_vocabulary.json').unlink()
    (model / 'target_vocabulary.json').unlink()
    vocab('shared_vocabulary.json', ['<unk>', '▁source', '▁target'])
    model_packs.validate_tokenizers(files, processor_factory=processor_factory)


def test_unicode_paths_load_tokenizer_bytes(root):
    location = root / '한글 경로의 언어팩'
    location.mkdir()
    compressed = archive(location / 'native.zip')
    models = location / 'models'
    install_archive(PACK_ID, compressed, models, source=source(compressed), converter=fake_converter([]))
    files = model_packs.runtime_files(models, PACK_ID)
    seen = []
    translators = []

    def processor_factory(**kwargs):
        assert 'model_file' not in kwargs, 'native SentencePiece filename conversion must be avoided'
        assert set(kwargs) == {'model_proto'}
        seen.append(kwargs['model_proto'])
        return FakeProcessor(['<unk>', '<s>', '</s>', 'word'])

    marker = object()

    def translator_factory(path, **kwargs):
        translators.append((path, kwargs))
        return marker

    fake_modules = {
        'sentencepiece': types.SimpleNamespace(SentencePieceProcessor=processor_factory),
        'ctranslate2': types.SimpleNamespace(Translator=translator_factory),
    }
    with mock.patch.dict(sys.modules, fake_modules):
        model_packs.validate_tokenizers(files)
        assert seen == [b'source tokenizer', b'target tokenizer']
        seen.clear()
        source_sp, target_sp, translator = model_packs.load_runtime(models, PACK_ID, intra_threads=3)
        assert seen == [b'source tokenizer', b'target tokenizer']
        assert source_sp is not target_sp and translator is marker
        assert translators[-1] == (str(files.model_dir), {'compute_type': 'int8', 'intra_threads': 3})

        # A legacy pack shares one SPM; byte loading should instantiate it only once.
        legacy = models / 'ko_en'
        legacy_model = legacy / 'model'
        legacy_model.mkdir(parents=True)
        (legacy_model / 'model.bin').write_bytes(b'legacy weights')
        (legacy_model / 'shared_vocabulary.txt').write_text('word\n', encoding='utf-8')
        (legacy / 'sentencepiece.model').write_bytes(b'legacy tokenizer')
        seen.clear()
        source_sp, target_sp, translator = model_packs.load_runtime(models, 'ko_en')
        assert seen == [b'legacy tokenizer']
        assert source_sp is target_sp and translator is marker


def test_publish_failure_rolls_back_existing(root):
    compressed = archive(root / 'rollback.zip')
    models = root / 'rollback-models'
    install_archive(PACK_ID, compressed, models, source=source(compressed), converter=fake_converter([]))
    destination = models / PACK_ID
    before = tree_bytes(destination)
    real_replace = model_packs.os.replace

    def failed_replacement(src, dst):
        if pathlib.Path(src).parent.name.startswith('.' + PACK_ID + '.stage-'):
            raise OSError('fixture final publication failed')
        return real_replace(src, dst)

    with mock.patch.object(model_packs.os, 'replace', side_effect=failed_replacement):
        expect_failure(lambda: install_archive(
            PACK_ID, compressed, models, source=source(compressed), converter=fake_converter([])))
    assert tree_bytes(destination) == before
    assert model_packs.installed(models, PACK_ID)


if __name__ == '__main__':
    work = pathlib.Path(__file__).resolve().parents[1] / 'work'
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stoom-pack-tests-', dir=work) as directory:
        root = pathlib.Path(directory)
        test_catalog_and_legacy_layout(root)
        test_native_conversion_and_selective_extraction(root)
        test_argos_archive_compatibility(root)
        test_ordered_vocab_yaml_roundtrip(root)
        test_plain_vocab_archive_adapter(root)
        test_download_abstraction_and_size_bound(root)
        test_verification_and_failed_conversion_preserve_existing(root)
        test_decoder_paths_and_yaml_are_rejected(root)
        test_selected_symlink_is_rejected(root)
        test_native_tokenizer_vocabulary_alignment(root)
        test_unicode_paths_load_tokenizer_bytes(root)
        test_publish_failure_rolls_back_existing(root)
    print('model packs: catalog, legacy/new install, tokenizers, bounded download, safe extraction and rollback: PASS')
