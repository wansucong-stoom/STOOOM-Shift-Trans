"""Preserve Marian's unknown-token search policy for converted OPUS packs.

The pinned native archives omit allow-unk, whose Marian default is false.
CTranslate2 defaults disable_unk to false, so the opposite policy must be
requested explicitly after conversion. This changes decoding, not model
weights or postprocessed words. It does not guarantee translation quality.

Marian: https://github.com/marian-nmt/marian/blob/master/src/translator/beam_search.cpp
CTranslate2: https://opennmt.net/CTranslate2/python/ctranslate2.Translator.html
"""

OPUS_PACKS = frozenset(('ko_en_opus_big', 'en_ko_opus_big'))


def translate_part(pack_id, tokenizer, translator, text):
    options = {'beam_size': 4, 'max_decoding_length': 256}
    native_opus = pack_id in OPUS_PACKS
    if native_opus:
        # Match native Marian allow-unk=false. Otherwise the same converted
        # weights can select high-scoring <unk> beams, displayed as U+2047.
        options['disable_unk'] = True
    tokens = tokenizer.encode(text, out_type=str)
    result = translator.translate_batch([tokens], **options)[0].hypotheses[0]
    if native_opus and '<unk>' in result:
        raise ValueError('번역 엔진이 해석할 수 없는 결과를 반환했습니다. 다른 언어팩을 선택해 주세요.')
    translated = tokenizer.decode(result)
    if not translated.strip():
        raise ValueError('일부 번역 결과가 비어 있어 교체하지 않습니다.')
    if native_opus and not translated.replace('\u2047', '').strip():
        raise ValueError('번역 엔진이 해석할 수 없는 결과를 반환했습니다. 다른 언어팩을 선택해 주세요.')
    return translated
