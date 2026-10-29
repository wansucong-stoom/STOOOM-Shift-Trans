"""Verified offline model packs with paired tokenizers and staged installation.

Conversion of the two OPUS choices uses CTranslate2's native Marian converter;
PyTorch and Transformers are not needed by this module. Official source
archives are pinned to their measured byte size and SHA-256.
"""
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import NamedTuple
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import urllib.request
import uuid
import zipfile


@dataclass(frozen=True)
class Source:
    url: str
    sha256: str | None
    size: int | None

    @property
    def verified(self):
        return (isinstance(self.sha256, str)
                and re.fullmatch(r'[0-9a-fA-F]{64}', self.sha256) is not None
                and isinstance(self.size, int) and not isinstance(self.size, bool)
                and self.size > 0)


@dataclass(frozen=True)
class PackSpec:
    id: str
    source_language: str
    target_language: str
    label: str
    kind: str
    source: Source
    upstream: str
    revision: str
    license: str
    card_revision: str | None = None


_ARGOS = {
    'en_ja': ('16300cc4eaa85320520cabcf433b63d01be40ef6966251de72043a083408f716', 120470284),
    'en_ko': ('e03d8e65e6d44525ec5808c3409fcf8728c76c2c76925372b6d3dc3278de17fc', 120789009),
    'ja_en': ('623e3477959a815eb0a5ef53e09079ae8f1f9d3bbcd230473baf28c03fb83335', 117155716),
    'ko_en': ('6da8f3db6ca40f42b1875570a1c06856f6e17c7ef62845d85de217ba548c1471', 118852077),
}
CATALOG = {}
for _id, (_sha, _size) in _ARGOS.items():
    _src, _dst = _id.split('_')
    CATALOG[_id] = PackSpec(
        _id, _src, _dst, 'Argos 기본', 'argos',
        Source(f'https://argos-net.com/v1/translate-{_id}-1_1.argosmodel', _sha, _size),
        'https://www.argosopentech.com/', '1.1', 'See upstream package licence',
    )

for _src, _dst, _long, _card_revision, _sha, _size in (
    ('ko', 'en', 'kor-eng', 'fa26583a41d95346933f26b4cb8f9b700da0d445',
     '9132ed606b6964656520931d96a4a6afc7ddc7d55ca5438e1d403db0c05492ef', 776542556),
    ('en', 'ko', 'eng-kor', 'ae8606b7b29a495f31ce679cee2007f536a3a5ce',
     '41f771fa28e864428dd7589992867b2b6dfa402f1191670e818e019dddfceef7', 776413094),
):
    _id = f'{_src}_{_dst}_opus_big'
    CATALOG[_id] = PackSpec(
        _id, _src, _dst, 'OPUS-MT Big', 'marian',
        Source('https://object.pouta.csc.fi/Tatoeba-MT-models/' + _long
               + '/opusTCv20210807-sepvoc_transformer-big_2022-07-28.zip', _sha, _size),
        f'https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-{_src}-{_dst}',
        '2022-07-28', 'CC-BY-4.0', _card_revision,
    )


class RuntimeFiles(NamedTuple):
    model_dir: Path
    source_spm: Path
    target_spm: Path


def choices(source_language, target_language):
    return tuple(spec for spec in CATALOG.values()
                 if (spec.source_language, spec.target_language)
                 == (source_language, target_language))


def _spec(pack_id):
    try:
        return CATALOG[pack_id]
    except (KeyError, TypeError) as exc:
        raise ValueError('알 수 없는 언어팩입니다.') from exc


def runtime_files(models_dir, pack_id):
    spec = _spec(pack_id)
    root = Path(models_dir) / spec.id
    model = root / 'model'
    if spec.kind == 'argos':
        source_spm = target_spm = root / 'sentencepiece.model'
    else:
        source_spm, target_spm = root / 'source.spm', root / 'target.spm'
    required = [model / 'model.bin', source_spm, target_spm]
    vocabulary = [model / name for name in (
        'shared_vocabulary.txt', 'shared_vocabulary.json',
        'source_vocabulary.json',
    )]
    if not all(path.is_file() and path.stat().st_size > 0 for path in required):
        raise ValueError('언어팩 파일이 없거나 설치가 완료되지 않았습니다.')
    if not any(path.is_file() and path.stat().st_size > 0 for path in vocabulary):
        raise ValueError('언어팩 어휘 파일이 없습니다.')
    if ((model / 'source_vocabulary.json').is_file()
            and not (model / 'target_vocabulary.json').is_file()):
        raise ValueError('언어팩 목표 언어 어휘 파일이 없습니다.')
    if spec.kind == 'marian':
        if not (model / 'config.json').is_file() or not (root / 'pack.json').is_file():
            raise ValueError('언어팩 변환이 완료되지 않았습니다.')
        data = json.loads((root / 'pack.json').read_text(encoding='utf-8'))
        if not isinstance(data,dict) or data.get('id') != spec.id or data.get('format') != 'native-marian-int8':
            raise ValueError('언어팩 정보가 올바르지 않습니다.')
    return RuntimeFiles(model, source_spm, target_spm)


def installed(models_dir, pack_id):
    try:
        runtime_files(models_dir, pack_id)
        return True
    except (OSError, ValueError, TypeError):
        return False


def load_runtime(models_dir, pack_id, intra_threads=4):
    import ctranslate2
    import sentencepiece
    files = runtime_files(models_dir, pack_id)
    # Windows SentencePiece's native filename loader can reject Korean paths.
    # Passing the model bytes avoids that platform filename conversion.
    source = sentencepiece.SentencePieceProcessor(model_proto=files.source_spm.read_bytes())
    target = source if files.source_spm == files.target_spm else sentencepiece.SentencePieceProcessor(
        model_proto=files.target_spm.read_bytes())
    translator = ctranslate2.Translator(str(files.model_dir), compute_type='int8',
                                       intra_threads=intra_threads)
    return source, target, translator


def validate_tokenizers(files, processor_factory=None):
    """Reject source/target tokenizer swaps before a native pack is published.

    CTranslate2 consumes token strings. Raw SentencePiece integer IDs need not
    equal Marian IDs, but each normal piece must occur in that side's actual
    converted vocabulary. Control/unused/unknown pieces are not ordinary input.
    """
    if processor_factory is None:
        import sentencepiece
        processor_factory = lambda path: sentencepiece.SentencePieceProcessor(model_proto=Path(path).read_bytes())
    model, source_spm, target_spm = files
    for side, spm_path in (('source', source_spm), ('target', target_spm)):
        vocabulary_path = model / (side + '_vocabulary.json')
        if not vocabulary_path.is_file():
            vocabulary_path = model / 'shared_vocabulary.json'
        vocabulary = json.loads(vocabulary_path.read_text(encoding='utf-8'))
        if (not isinstance(vocabulary, list) or not vocabulary
                or not all(isinstance(piece, str) for piece in vocabulary)):
            raise ValueError('변환된 모델 어휘 형식이 올바르지 않습니다.')
        allowed = set(vocabulary)
        processor = processor_factory(spm_path)
        missing = [processor.id_to_piece(index)
                   for index in range(processor.get_piece_size())
                   if not (processor.is_control(index) or processor.is_unknown(index)
                           or processor.is_unused(index))
                   and processor.id_to_piece(index) not in allowed]
        if missing:
            raise ValueError(f'{side} SentencePiece와 모델 어휘가 일치하지 않습니다. ({len(missing)}개)')


def _verified_source(spec, source):
    source = spec.source if source is None else source
    if not isinstance(source, Source) or not source.verified:
        raise ValueError('이 언어팩의 다운로드 크기와 무결성이 아직 확인되지 않았습니다.')
    if not source.url.lower().startswith('https://'):
        raise ValueError('언어팩 다운로드 주소는 HTTPS여야 합니다.')
    return source


def _check_archive(path, source):
    if Path(path).stat().st_size != source.size:
        raise ValueError('언어팩 크기가 예상값과 다릅니다.')
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != source.sha256.lower():
        raise ValueError('언어팩 무결성 확인에 실패했습니다.')


def _archive_path(name):
    # ZIP paths are POSIX paths. Backslashes/drive names must never acquire
    # different meanings when the same archive is handled on Windows.
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or '\x00' in name:
        raise ValueError('언어팩에 안전하지 않은 파일 경로가 있습니다.')
    value = PurePosixPath(name)
    if value.is_absolute() or any(part in ('', '.', '..') for part in name.split('/')):
        raise ValueError('언어팩에 안전하지 않은 파일 경로가 있습니다.')
    return value


def _index(archive):
    result = {}
    for info in archive.infolist():
        name = info.filename[:-1] if info.is_dir() else info.filename
        value = _archive_path(name)
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ValueError('언어팩의 링크 파일은 허용되지 않습니다.')
        key = str(value)
        if key in result:
            raise ValueError('언어팩에 중복된 파일 경로가 있습니다.')
        result[key] = info
    return result


def _copy_member(archive, index, name, destination, maximum):
    info = index.get(str(name))
    if info is None or info.is_dir() or info.file_size <= 0 or info.file_size > maximum:
        raise ValueError('언어팩의 필수 파일이 없거나 크기가 올바르지 않습니다.')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    copied = 0
    with archive.open(info) as src, open(destination, 'wb') as dst:
        while True:
            block = src.read(1024 * 1024)
            if not block:
                break
            copied += len(block)
            if copied > maximum or copied > info.file_size:
                raise ValueError('언어팩 압축 파일 크기가 올바르지 않습니다.')
            dst.write(block)
    if copied != info.file_size:
        raise ValueError('언어팩 압축 해제가 완료되지 않았습니다.')


def _extract_argos(archive, index, spec, output):
    members = (
        ('sentencepiece.model', 32_000_000),
        ('model/model.bin', 512_000_000),
        ('model/shared_vocabulary.txt', 64_000_000),
    )
    for name, maximum in members:
        _copy_member(archive, index, PurePosixPath(spec.id) / name, output / name, maximum)


def _native_convert(model_path, vocab_paths, output_dir):
    from ctranslate2.converters import MarianConverter
    MarianConverter(str(model_path), [str(path) for path in vocab_paths]).convert(
        str(output_dir), quantization='int8')


def _ordered_vocab_to_yaml(path):
    """Adapt native ordered vocab text without changing any token or index."""
    path = Path(path)
    tokens = path.read_text(encoding='utf-8').split('\n')
    if tokens and tokens[-1] == '':
        tokens.pop()
    # The official archives are LF terminated; also accept an ordinary CRLF
    # file without stripping spaces from actual tokens.
    tokens = [token[:-1] if token.endswith('\r') else token for token in tokens]
    if not tokens or any(not token for token in tokens) or len(set(tokens)) != len(tokens):
        raise ValueError('순서형 어휘 파일이 올바르지 않습니다.')
    # MarianConverter has its own YAML reader. Single-quoted keys preserve
    # literal backslashes; JSON escape sequences such as \\t are not decoded
    # by that reader. A doubled single quote round-trips through its parser.
    path.write_text(''.join("'" + token.replace("'", "''") + "': " + str(index) + '\n'
                            for index, token in enumerate(tokens)), encoding='utf-8')
    from ctranslate2.converters.marian import load_vocab
    if load_vocab(str(path)) != tokens:
        raise ValueError('어휘 파일 변환 중 토큰 순서가 달라졌습니다.')


def _report(progress, message):
    if progress is not None:
        try:
            progress(message)
        except Exception:
            # A disappearing progress UI must not invalidate a good pack.
            pass


def _extract_marian(archive, index, temporary, output, converter, progress=None):
    import yaml
    decoders = [key for key, info in index.items()
                if not info.is_dir() and PurePosixPath(key).name == 'decoder.yml']
    if len(decoders) != 1:
        raise ValueError('Marian 설정 파일을 하나로 확인할 수 없습니다.')
    decoder_name = PurePosixPath(decoders[0])
    decoder_path = temporary / 'decoder.yml'
    _copy_member(archive, index, decoder_name, decoder_path, 1_000_000)
    config = yaml.safe_load(decoder_path.read_text(encoding='utf-8'))
    if not isinstance(config, dict):
        raise ValueError('Marian 설정이 올바르지 않습니다.')
    models, vocabs = config.get('models'), config.get('vocabs')
    if (not isinstance(models, list) or len(models) != 1
            or not isinstance(vocabs, list) or len(vocabs) != 2
            or not all(isinstance(value, str) for value in models + vocabs)):
        raise ValueError('Marian 모델과 어휘 경로가 올바르지 않습니다.')
    def resolve(reference):
        return decoder_name.parent / _archive_path(reference)
    model_name, vocab_names = resolve(models[0]), tuple(resolve(value) for value in vocabs)
    model_path = temporary / 'weights.npz'
    vocab_paths = (temporary / 'source.vocab.yml', temporary / 'target.vocab.yml')
    _copy_member(archive, index, model_name, model_path, 2_000_000_000)
    for name, path in zip(vocab_names, vocab_paths):
        _copy_member(archive, index, name, path, 64_000_000)
        if name.suffix == '.vocab':
            _ordered_vocab_to_yaml(path)
    for name in ('source.spm', 'target.spm'):
        _copy_member(archive, index, decoder_name.parent / name, output / name, 32_000_000)
    _report(progress, '번역 모델을 INT8로 변환하고 있습니다…')
    converter(model_path, vocab_paths, output / 'model')


def _write_manifest(output, spec, source):
    data = {'id': spec.id, 'format': 'native-marian-int8' if spec.kind == 'marian' else 'argos-ct2',
            'source_language': spec.source_language, 'target_language': spec.target_language,
            'source_url': source.url, 'source_sha256': source.sha256.lower(),
            'source_size': source.size, 'upstream': spec.upstream,
            'revision': spec.revision, 'license': spec.license,
            'model_card_revision': spec.card_revision,
            'tokenization': 'separate-sentencepiece' if spec.kind == 'marian' else 'shared-sentencepiece',
            'source_eos': 'implicit-native-converter'}
    (output / 'pack.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'LICENSE.txt').write_text(
        f'{spec.label}\nUpstream: {spec.upstream}\nVersion: {spec.revision}\n'
        f'Licence: {spec.license}\nConverted/repackaged for STOOM Shift Translator.\n'
        + ('By Language Technology Research Group, University of Helsinki.\n'
           'https://creativecommons.org/licenses/by/4.0/\n'
           'Changes: CTranslate2 native Marian conversion and INT8 quantization.\n'
           if spec.kind == 'marian' else ''), encoding='utf-8')


def _remove_inside(path, parent):
    path, parent = Path(path).resolve(), Path(parent).resolve()
    path.relative_to(parent)
    if path == parent:
        raise ValueError('언어팩 루트 폴더를 삭제할 수 없습니다.')
    if path.exists():
        shutil.rmtree(path)


def _publish(output, models_dir, spec):
    destination = models_dir / spec.id
    backup = models_dir / ('.' + spec.id + '.backup-' + uuid.uuid4().hex)
    moved_old = False
    try:
        if destination.exists():
            os.replace(destination, backup)
            moved_old = True
        os.replace(output, destination)
    except Exception:
        if moved_old and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    if moved_old:
        _remove_inside(backup, models_dir)
    return destination


def install_archive(pack_id, archive_path, models_dir, *, source=None, converter=None, validator=None, progress=None):
    spec = _spec(pack_id)
    source = _verified_source(spec, source)
    _report(progress, '언어팩 다운로드 파일을 확인하고 있습니다…')
    _check_archive(archive_path, source)
    models_dir = Path(models_dir).resolve()
    models_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.' + spec.id + '.stage-', dir=models_dir) as directory:
        stage = Path(directory)
        output = stage / spec.id
        output.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            index = _index(archive)
            _report(progress, '언어팩 파일을 풀고 있습니다…')
            if spec.kind == 'argos':
                _extract_argos(archive, index, spec, output)
            else:
                _extract_marian(archive, index, stage / 'native', output,
                                converter or _native_convert, progress)
        _write_manifest(output, spec, source)
        # Check the complete staged payload before moving any existing pack.
        _report(progress, '언어팩과 토크나이저 구성을 확인하고 있습니다…')
        files = runtime_files(stage, spec.id)
        if spec.kind == 'marian':
            (validator or validate_tokenizers)(files)
        result = _publish(output, models_dir, spec)
        _report(progress, '언어팩 설치가 완료되었습니다.')
        return result


def install(pack_id, models_dir, *, source=None, opener=None, converter=None, validator=None, progress=None):
    spec = _spec(pack_id)
    source = _verified_source(spec, source)
    models_dir = Path(models_dir).resolve()
    models_dir.mkdir(parents=True, exist_ok=True)
    fd, download = tempfile.mkstemp(prefix='.' + spec.id + '.', suffix='.download', dir=models_dir)
    os.close(fd)
    try:
        request = urllib.request.Request(source.url, headers={'User-Agent': 'STOOM-Translator/0.5'})
        total = 0
        last_report = 0
        _report(progress, '언어팩 다운로드를 시작합니다…')
        with (opener or urllib.request.urlopen)(request, timeout=60) as response, open(download, 'wb') as dst:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > source.size:
                    raise ValueError('언어팩 크기가 예상값을 초과했습니다.')
                dst.write(block)
                if total - last_report >= 4 * 1024 * 1024 or total == source.size:
                    _report(progress, f'언어팩 다운로드 {total / 1048576:.0f} / {source.size / 1048576:.0f} MiB')
                    last_report = total
        return install_archive(pack_id, download, models_dir, source=source,
                               converter=converter, validator=validator, progress=progress)
    finally:
        if os.path.exists(download):
            os.unlink(download)
