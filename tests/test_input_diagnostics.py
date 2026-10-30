"""Diagnostics must stay bounded, omit document/key data, and never break input."""
import concurrent.futures
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import input_diagnostics as d


def read(path):
    return [json.loads(line) for line in path.read_text('ascii').splitlines()]


# AppContainer's redirected system temp permits append but denies replacing an
# existing file. Use this writable source workspace for the real rotation test.
with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as root:
    root = Path(root)
    path = root / 'diagnostics.jsonl'
    trace = d.Trace(path, max_bytes=8192)
    focus = SimpleNamespace(foreground=42, keyboard_window=43, thread_id=44, text='SECRET')
    assert trace.record('capture.ready', job='job-1', revision=7, current_revision=7,
                        focus=focus, current_focus={'foreground': 42, 'text': 'SECRET'},
                        source_chars=5, text='SECRET', selected_text='SECRET',
                        translation='SECRET', rawkey='SECRET', key='SECRET',
                        model_ids=['ko_en_opus_big', '/private/path', 'SECRET WORDS'])
    assert trace.flush()
    row = read(path)[0]
    assert row['focus'] == {'foreground': 42, 'keyboard_window': 43, 'thread_id': 44}
    assert row['current_focus'] == {'foreground': 42}
    assert row['model_ids'] == ['ko_en_opus_big']
    assert 'SECRET' not in path.read_text('ascii')
    assert not trace.record('document text should not be a phase')

    # Repeated events rotate by whole JSON records and retain the newest error.
    for index in range(300):
        assert trace.record('copy.pending', job=index, revision=index, duration_ms=index / 10)
    assert trace.record('error', job=300, cause='timeout', error_message='Input timed out.\n' + 'x' * 800)
    assert trace.flush()
    rows = read(path)
    assert rows[-1]['phase'] == 'error' and rows[-1]['job'] == 300
    assert len(rows[-1]['error_message']) == 500 and '\n' not in rows[-1]['error_message']
    assert path.stat().st_size <= 8192 and not path.with_name(path.name + '.tmp').exists()
    assert len(rows) < 301

    # Thread safety applies even when callers independently construct a Trace
    # for the same destination. No malformed/interleaved JSON lines are allowed.
    parallel = root / 'parallel.jsonl'
    tracers = [d.Trace(parallel, max_bytes=256 * 1024) for _ in range(4)]
    def record(index):
        return tracers[index % 4].record('worker.event', job=index,
            accepted=4, expected=4, same_output=False, duration_ms=.25)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(record, range(400)))
    assert tracers[0].flush()
    rows = read(parallel)
    assert len(rows) == 400 and {row['job'] for row in rows} == set(range(400))

    # Invalid values and hostile repr objects never turn into logged contents.
    class Secret:
        def __repr__(self):raise AssertionError('arbitrary repr serialized')
    assert trace.record('invalid.values', job=Secret(), focus=Secret(),
                        source_chars=True, output_chars=-1, duration_ms=float('nan'),
                        cause='SECRET WORDS', error_message=Secret())
    assert trace.flush()
    row = read(path)[-1]
    assert set(row) == {'time_utc', 'phase'}

    # A partial previous write is repaired without propagating a parse failure.
    broken = root / 'broken.jsonl'
    broken.write_bytes(b'{incomplete')
    recovered=d.Trace(broken)
    assert recovered.record('recovered', job=1) and recovered.flush()
    assert read(broken)[-1]['phase'] == 'recovered'

    # Unwritable destination and replacement failure are diagnostics loss only.
    blocker = root / 'not-a-directory'
    blocker.write_text('fixture')
    blocked=d.Trace(blocker / 'trace.jsonl')
    assert blocked.record('error', error_message='Generic error') and not blocked.flush()
    with mock.patch.object(Path, 'open', side_effect=PermissionError('fixture')):
        assert trace.record('error', error_message='Generic error') and not trace.flush()

    # A blocked disk writer never blocks callers or grows memory without a cap.
    bounded=d.Trace(root/'bounded.jsonl', queue_size=2)
    entered=threading.Event();release=threading.Event()
    original=bounded._writer._write_batch
    def slow_write(lines):
        entered.set();assert release.wait(5);original(lines)
    bounded._writer._write_batch=slow_write
    assert bounded.record('first') and entered.wait(2)
    assert bounded.record('second') and bounded.record('third')
    started=time.perf_counter()
    assert bounded.record('dropped') is False
    assert time.perf_counter()-started<.1
    assert bounded.flush(.01) is False
    release.set();assert bounded.flush(5)
    assert [row['phase'] for row in read(bounded.path)]==['first','second','third']

    # Bursts are enqueued while the writer is stopped, independently of disk speed.
    fast=d.Trace(root/'fast.jsonl')
    entered=threading.Event();release=threading.Event();original=fast._writer._write_batch
    def stopped_write(lines):
        entered.set();assert release.wait(5);original(lines)
    fast._writer._write_batch=stopped_write
    assert fast.record('first') and entered.wait(2)
    started=time.perf_counter()
    assert all(fast.record('burst',job=index) for index in range(300))
    elapsed=time.perf_counter()-started
    assert elapsed<.5, elapsed
    release.set();assert fast.close(5) and not fast.record('after.close')
    assert len(read(fast.path))==301

print(f'Input diagnostics: bounded retention/queue, content allowlist, retained error, concurrent valid JSON, flush/close, partial-write repair and harmless I/O failure: PASS; 300 queued records {elapsed*1000:.2f} ms')
