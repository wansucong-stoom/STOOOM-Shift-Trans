"""Opt-in packaged model check without starting hooks or editing any input.

EXE --check-pack ID MODELS_DIRECTORY REPORT_JSON [VERIFIED_ARCHIVE]
The optional archive exercises the actual bundled converter before inference.
Only catalog IDs and their pinned archive hashes are accepted for installation.
"""
import json
import time
from pathlib import Path
import model_packs


def run(arguments, runtime):
    if len(arguments) not in (3,4):
        return 2
    pack_id, models, report = arguments[:3]
    result = {'id':pack_id,'ok':False,'frozen':bool(getattr(runtime.sys,'frozen',False))}
    started = time.perf_counter()
    try:
        spec = model_packs.CATALOG[pack_id]
        runtime.MODELS = Path(models).resolve()
        if len(arguments)==4:
            model_packs.install_archive(pack_id,arguments[3],runtime.MODELS)
        runtime._load_model_cached.cache_clear()
        text = {'ko':'저는 누구일까요?','en':'What time does the meeting start tomorrow?',
                'ja':'こんにちは。'}[spec.source_language]
        result['translation'] = runtime.translate_route(text,[pack_id])
        result['ok'] = bool(result['translation'].strip())
        result['model_bytes'] = sum(p.stat().st_size for p in (runtime.MODELS/pack_id).rglob('*') if p.is_file())
    except Exception as exc:
        result['error'] = str(exc)
    result['elapsed_seconds'] = round(time.perf_counter()-started,4)
    Path(report).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if result['ok'] else 1
