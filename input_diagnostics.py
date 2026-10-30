"""Bounded local input diagnostics, deliberately excluding document contents.

Use one process to record GUI and worker stages through Trace.record(). Multiple
Trace instances for the same path share a bounded queue and daemon writer. Unknown fields are ignored;
there is no arbitrary payload/repr serialization. The caller must pass only the
generic user-visible message in error_message, never engine payloads or text.
Diagnostic failures must not affect typing or translation.
"""
import atexit
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import queue
import threading
import time

DEFAULT_MAX_BYTES = 256 * 1024
_DROP = object()
_PHASE = re.compile(r'[a-z][a-z0-9_.:-]{0,63}\Z')
_IDENTIFIER = re.compile(r'[A-Za-z0-9_.:-]{1,80}\Z')
_CAUSES = frozenset(('typing', 'click', 'drag', 'scroll', 'focus', 'configuration',
                    'timeout', 'clipboard', 'shutdown', 'cancel', 'unknown', 'modifier'))
_INTEGER_FIELDS = frozenset(('revision', 'current_revision', 'source_chars',
                             'output_chars', 'accepted', 'expected'))
_ALLOWED_FIELDS = frozenset(('job', 'focus', 'current_focus', 'cause', 'same_output',
                            'model_ids', 'duration_ms', 'error_message')) | _INTEGER_FIELDS
_writers = {}
_writers_guard = threading.Lock()


def _integer(value, minimum=0, maximum=(1 << 64) - 1):
    return value if type(value) is int and minimum <= value <= maximum else _DROP


def _focus(value):
    if value is None:
        return None
    result = {}
    for name in ('foreground', 'keyboard_window', 'thread_id'):
        item = value.get(name, _DROP) if isinstance(value, dict) else getattr(value, name, _DROP)
        item = _integer(item)
        if item is not _DROP:
            result[name] = item
    return result if result else _DROP


def _field(name, value):
    if name in _INTEGER_FIELDS:
        return _integer(value, -1 if name in ('revision', 'current_revision') else 0)
    if name == 'job':
        if type(value) is int:
            return _integer(value)
        return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else _DROP
    if name in ('focus', 'current_focus'):
        return _focus(value)
    if name == 'cause':
        return value if isinstance(value, str) and value in _CAUSES else _DROP
    if name == 'same_output':
        return value if type(value) is bool else _DROP
    if name == 'model_ids':
        if not isinstance(value, (list, tuple)):
            return _DROP
        return [item for item in value[:8]
                if isinstance(item, str) and _IDENTIFIER.fullmatch(item)]
    if name == 'duration_ms':
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            return _DROP
        return round(min(value, 86400000), 3)
    if name == 'error_message':
        if not isinstance(value, str):
            return _DROP
        # One generic toast message, not a traceback or arbitrary object repr.
        return ''.join(char if ord(char) >= 32 else ' ' for char in value[:500])
    return _DROP


class _Barrier:
    def __init__(self):
        self.event = threading.Event()
        self.ok = False


class _Writer:
    def __init__(self, path, max_bytes, queue_size):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.queue = queue.Queue(maxsize=queue_size)
        self.failed = False
        self.thread = threading.Thread(target=self._run, name='STOOM-input-diagnostics', daemon=True)
        self.thread.start()

    def flush(self, timeout):
        deadline = time.monotonic() + max(0, timeout)
        barrier = _Barrier()
        try:
            self.queue.put(barrier, timeout=max(0, deadline-time.monotonic()))
            return barrier.event.wait(max(0, deadline-time.monotonic())) and barrier.ok
        except Exception:
            return False

    def _run(self):
        while True:
            item = self.queue.get()
            if isinstance(item, _Barrier):
                item.ok = not self.failed
                item.event.set()
                continue
            lines = [item]
            barrier = None
            for _ in range(31):
                try:
                    item = self.queue.get_nowait()
                except queue.Empty:
                    break
                if isinstance(item, _Barrier):
                    barrier = item
                    break
                lines.append(item)
            try:
                self._write_batch(lines)
            except Exception:
                # A broken diagnostics destination cannot affect translation.
                self.failed = True
            if barrier is not None:
                barrier.ok = not self.failed
                barrier.event.set()

    def _write_batch(self, lines):
        # Keep newest complete records if a test uses a very small retention cap.
        retained = []
        used = 0
        for line in reversed(lines):
            if used + len(line) > self.max_bytes:
                break
            retained.append(line)
            used += len(line)
        payload = b''.join(reversed(retained))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            size = 0
        repair = False
        if size:
            with self.path.open('rb') as stream:
                stream.seek(-1, os.SEEK_END)
                repair = stream.read(1) != b'\n'
        if size + len(payload) <= self.max_bytes and not repair:
            with self.path.open('ab') as stream:
                stream.write(payload)
        else:
            self._rewrite_tail(payload, size)

    def _rewrite_tail(self, payload, size):
        tail = b''
        offset = max(0, size - self.max_bytes)
        if size:
            with self.path.open('rb') as stream:
                stream.seek(offset)
                tail = stream.read(self.max_bytes)
        pieces = tail.splitlines(keepends=True)
        if offset and pieces:
            pieces.pop(0)  # The first line may start in the middle of a record.
        budget = max(0, self.max_bytes // 2 - len(payload))
        kept = []
        used = 0
        for previous in reversed(pieces):
            if not previous.endswith(b'\n'):
                continue  # A terminated process may have left a partial write.
            try:
                record = json.loads(previous)
                if not isinstance(record, dict) or not _PHASE.fullmatch(record.get('phase', '')):
                    continue
                if set(record) - (_ALLOWED_FIELDS | {'time_utc', 'phase'}):
                    continue
            except (ValueError, TypeError):
                continue
            if used + len(previous) > budget:
                break
            kept.append(previous)
            used += len(previous)
        payload = b''.join(reversed(kept)) + payload
        temporary = self.path.with_name(self.path.name + '.tmp')
        try:
            temporary.write_bytes(payload)
            temporary.replace(self.path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


class Trace:
    def __init__(self, path, max_bytes=DEFAULT_MAX_BYTES, queue_size=512):
        self.path = Path(path)
        self.max_bytes = max(512, int(max_bytes))
        self._closed = False
        key = os.path.normcase(os.path.abspath(os.fspath(self.path)))
        with _writers_guard:
            if key not in _writers:
                _writers[key] = _Writer(self.path, self.max_bytes, max(1, int(queue_size)))
            self._writer = _writers[key]
            self._writer.max_bytes = min(self._writer.max_bytes, self.max_bytes)

    def record(self, phase, **details):
        """Enqueue without filesystem I/O; False means rejection or a full queue."""
        try:
            if self._closed or not isinstance(phase, str) or not _PHASE.fullmatch(phase):
                return False
            row = {'time_utc': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                   'phase': phase}
            for name in _ALLOWED_FIELDS & details.keys():
                try:
                    value = _field(name, details[name])
                except Exception:
                    continue
                if value is not _DROP:
                    row[name] = value
            line = json.dumps(row, ensure_ascii=True, separators=(',', ':'),
                              allow_nan=False).encode('ascii') + b'\n'
            if len(line) > self._writer.max_bytes:
                return False
            self._writer.queue.put_nowait(line)
            return True
        except Exception:
            return False

    def flush(self, timeout=2.0):
        """Wait for previously accepted records; never called on the input path."""
        try:
            return self._writer.flush(float(timeout))
        except Exception:
            return False

    def close(self, timeout=2.0):
        self._closed = True
        return self.flush(timeout)


def shutdown(timeout=2.0):
    deadline = time.monotonic() + max(0, timeout)
    with _writers_guard:
        writers = tuple(_writers.values())
    for writer in writers:
        writer.flush(max(0, deadline-time.monotonic()))


atexit.register(shutdown)
