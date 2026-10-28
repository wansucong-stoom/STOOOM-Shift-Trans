import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from input_settle import Settler


# No capture is requested before modifier-release grace and typing quiet time.
s = Settler(started=1.0, revision=4)
assert s.observe(1.10, 4, .9) == 'wait'
assert s.observe(1.16, 4, .95) == 'wait'
assert s.observe(1.25, 4, .95) == 'sample'
assert s.observe(1.25, 4, .95, ('field', '안녕하세')) == 'wait'

# A provider's final Korean syllable can settle after the gesture.  Only the
# final stable text becomes ready; changing samples never trigger translation.
assert s.observe(1.40, 4, .95, ('field', '안녕하세요')) == 'wait'
assert s.observe(1.55, 4, .95, ('field', '안녕하세요')) == 'wait'
assert s.observe(1.61, 4, .95, ('field', '안녕하세요')) == 'ready'

# Late key-up activity restarts quiet and stability without a new key-down.
s = Settler(started=0, revision=1)
assert s.observe(.30, 1, 0, ('field', 'text')) == 'wait'
assert s.observe(.40, 1, .35) == 'wait'
assert s.observe(.61, 1, .35) == 'sample'
assert s.observe(.61, 1, .35, ('field', 'text')) == 'wait'
assert s.observe(.82, 1, .35, ('field', 'text')) == 'ready'

# A key-up observed only after its quiet time still invalidates earlier samples.
s = Settler(started=0, revision=1)
assert s.observe(.30, 1, 0, 'same') == 'wait'
assert s.observe(.70, 1, .40, 'same') == 'wait'
assert s.observe(.91, 1, .40, 'same') == 'ready'

# New typing cancels permanently, including if the caller later passes the old
# revision again.  A separate request can work normally afterwards.
s = Settler(started=0, revision=3)
assert s.observe(.30, 4, 0) == 'cancel'
assert s.observe(1.0, 3, 0, 'stable') == 'cancel'
fresh = Settler(started=1.0, revision=4)
assert fresh.observe(1.3, 4, 1.0, 'stable') == 'wait'
assert fresh.observe(1.51, 4, 1.0, 'stable') == 'ready'

# A provider that keeps changing cannot defer a request forever.
s = Settler(started=0, revision=1)
assert s.observe(.30, 1, 0, 'first') == 'wait'
assert s.observe(2.10, 1, 0, 'last') == 'wait'
assert s.observe(2.20, 1, 0, 'last') == 'timeout'
assert s.observe(3.0, 1, 0, 'last') == 'timeout'

# With the default quiet interval already satisfied, min_delay still applies.
s = Settler(started=2.0, revision=1)
assert s.observe(2.10, 1, 0) == 'wait'
assert s.observe(2.16, 1, 0) == 'sample'

print('passive input settle: provider lag, late release, cancellation, timeout and fresh request: PASS')
