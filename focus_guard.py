"""Read the Windows foreground thread's real keyboard focus.

This is an additional identity check, not proof that a window is editable.
"""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass

class RECT(ctypes.Structure):
 _fields_=[('left',wintypes.LONG),('top',wintypes.LONG),('right',wintypes.LONG),('bottom',wintypes.LONG)]
class GUITHREADINFO(ctypes.Structure):
 _fields_=[('cbSize',wintypes.DWORD),('flags',wintypes.DWORD),('hwndActive',wintypes.HWND),('hwndFocus',wintypes.HWND),('hwndCapture',wintypes.HWND),('hwndMenuOwner',wintypes.HWND),('hwndMoveSize',wintypes.HWND),('hwndCaret',wintypes.HWND),('rcCaret',RECT)]
@dataclass(frozen=True)
class Focus:
 foreground: int
 keyboard_window: int
 thread_id: int

def capture():
 user=ctypes.WinDLL('user32',use_last_error=True)
 user.GetForegroundWindow.restype=wintypes.HWND
 user.GetWindowThreadProcessId.argtypes=(wintypes.HWND,ctypes.POINTER(wintypes.DWORD))
 user.GetWindowThreadProcessId.restype=wintypes.DWORD
 user.GetGUIThreadInfo.argtypes=(wintypes.DWORD,ctypes.POINTER(GUITHREADINFO))
 user.GetGUIThreadInfo.restype=wintypes.BOOL
 foreground=user.GetForegroundWindow()
 if not foreground:raise ValueError('활성 창을 확인할 수 없습니다.')
 tid=user.GetWindowThreadProcessId(foreground,None)
 info=GUITHREADINFO();info.cbSize=ctypes.sizeof(GUITHREADINFO)
 if not tid or not user.GetGUIThreadInfo(tid,ctypes.byref(info)) or not info.hwndFocus:
  raise ValueError('키보드 입력 위치를 확인할 수 없습니다.')
 keyboard_tid=user.GetWindowThreadProcessId(info.hwndFocus,None)
 if not keyboard_tid:raise ValueError('키보드 입력 스레드를 확인할 수 없습니다.')
 return Focus(int(foreground),int(info.hwndFocus),int(keyboard_tid))

def unchanged(snapshot):
 try:return capture()==snapshot
 except (OSError,ValueError):return False
