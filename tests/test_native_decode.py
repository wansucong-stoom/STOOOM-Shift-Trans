"""Native unknown-token decoding must not replace source with marker output."""
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_decode


class Tokenizer:
    def encode(self, text, out_type):
        assert out_type is str
        return ['SOURCE', text]
    def decode(self, tokens):
        return ' '.join(tokens).replace('<unk>', '\u2047')


class Translator:
    def __init__(self, output=None):
        self.output = output
        self.calls = []
    def translate_batch(self, batches, **options):
        self.calls.append((batches, options))
        tokens = self.output
        if tokens is None:
            tokens = ['Research', 'recommendation'] if options.get('disable_unk') else ['<unk>', '<unk>']
        return [SimpleNamespace(hypotheses=[tokens])]


for pack in ('ko_en_opus_big', 'en_ko_opus_big'):
    translator = Translator()
    assert native_decode.translate_part(pack, Tokenizer(), translator, 'fixed title') == 'Research recommendation'
    assert translator.calls == [([['SOURCE', 'fixed title']],
                                 {'beam_size': 4, 'max_decoding_length': 256, 'disable_unk': True})]

# Do not change the decoding options of existing Argos packs.
translator = Translator(['Hello'])
assert native_decode.translate_part('ko_en', Tokenizer(), translator, 'hello') == 'Hello'
assert 'disable_unk' not in translator.calls[0][1]

# Invalid native results raise before the translation pipeline can paste.
for output in (['<unk>'], ['Hello', '<unk>'], ['\u2047', '\u2047'], [' ']):
    try:
        native_decode.translate_part('ko_en_opus_big', Tokenizer(), Translator(output), 'fixed title')
    except ValueError:
        pass
    else:
        raise AssertionError('Invalid native result accepted')

# Ordinary question marks and usable text are not rejected.
assert native_decode.translate_part('ko_en_opus_big', Tokenizer(), Translator(['Who', 'am', 'I?']), 'fixed question') == 'Who am I?'
print('PASS: OPUS unknown-token exclusion, unchanged Argos decoding, invalid native output and normal punctuation')
