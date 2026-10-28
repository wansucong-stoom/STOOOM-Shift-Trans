"""Passive input/provider stabilization before a translation snapshot is taken.

The caller supplies monotonic times and an immutable provider fingerprint.  This
module never reads user input, schedules work, or changes a document.
"""


class Settler:
    def __init__(
        self,
        started,
        revision,
        quiet_seconds=.25,
        stable_seconds=.20,
        timeout_seconds=2.2,
        min_delay=.15,
    ):
        self.started = started
        self.revision = revision
        self.quiet_seconds = quiet_seconds
        self.stable_seconds = stable_seconds
        self.timeout_seconds = timeout_seconds
        self.min_delay = min_delay
        self._last_activity = None
        self._fingerprint = None
        self._has_fingerprint = False
        self._stable_since = None
        self._terminal = None

    def _reset_stability(self):
        self._fingerprint = None
        self._has_fingerprint = False
        self._stable_since = None

    def discard_sample(self):
        """A failed provider read cannot count toward stable valid input."""
        self._reset_stability()

    def observe(self, now, revision, last_activity, sample=None):
        """Return wait/sample/ready/cancel/timeout without performing actions.

        ``revision`` counts ordinary key downs; a change cancels this request.
        ``last_activity`` also includes ordinary key ups, which restart quiet
        and provider-stability checks without cancelling the request.  A
        ``sample`` is an immutable fingerprint, not a live UIA range.

        Terminal decisions are sticky so an expired/cancelled request cannot
        become ready later.  The caller should remove it after any terminal
        result.
        """
        if self._terminal is not None:
            return self._terminal
        if revision != self.revision:
            self._terminal = 'cancel'
            return self._terminal
        if now - self.started >= self.timeout_seconds:
            self._terminal = 'timeout'
            return self._terminal

        # A delayed key-up can arrive between samples.  Even if its quiet
        # interval already elapsed by this poll, do not count earlier samples
        # as stability across that activity.
        if self._last_activity is not None and last_activity != self._last_activity:
            self._reset_stability()
        self._last_activity = last_activity

        if now - self.started < self.min_delay or now - last_activity < self.quiet_seconds:
            self._reset_stability()
            return 'wait'
        if sample is None:
            return 'sample'

        # Fail early if a mutable/unhashable object was accidentally supplied
        # instead of an immutable text/selection identity fingerprint.
        hash(sample)
        if not self._has_fingerprint or sample != self._fingerprint:
            self._fingerprint = sample
            self._has_fingerprint = True
            self._stable_since = now
            return 'wait'
        if now - self._stable_since >= self.stable_seconds:
            self._terminal = 'ready'
            return self._terminal
        return 'wait'
