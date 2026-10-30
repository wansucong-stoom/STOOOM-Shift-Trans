"""Check real process identity and shell icon installation without opening UI."""
import ctypes
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import windows_identity as identity

assert identity.set_taskbar_identity()
shell = ctypes.WinDLL('shell32')
get_id = shell.GetCurrentProcessExplicitAppUserModelID
get_id.argtypes = [ctypes.POINTER(ctypes.c_wchar_p)]
get_id.restype = ctypes.c_long
free = ctypes.WinDLL('ole32').CoTaskMemFree
free.argtypes = [ctypes.c_void_p]
free.restype = None
value = ctypes.c_wchar_p()
assert get_id(ctypes.byref(value)) == 0
try:
    assert value.value == identity.APP_USER_MODEL_ID
finally:
    free(ctypes.cast(value, ctypes.c_void_p))

installer = (ROOT / 'installer.iss').read_text(encoding='utf-8')
shortcut_id = re.search(r'#define AppUserModelID "([^"]+)"', installer).group(1)
assert shortcut_id == identity.APP_USER_MODEL_ID
shortcuts = installer.split('[Icons]', 1)[1].split('[Tasks]', 1)[0]
assert shortcuts.count('AppUserModelID: "{#AppUserModelID}"') == 2
# Regression: an _internal-only ICO does not satisfy this shell-facing path.
files = installer.split('[Files]', 1)[1].split('[Icons]', 1)[0]
assert 'Source: "branding\\sst\\stoom.ico"; DestDir: "{app}\\branding\\sst"' in files
assert (ROOT / 'branding' / 'sst' / 'stoom.ico').read_bytes() == (ROOT / 'stoom.ico').read_bytes()
print('PASS: actual Windows taskbar identity, matching shortcuts and installed shell icon')
