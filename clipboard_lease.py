"""Temporarily place text on clipboard and restore the prior OLE data object.
Never restore over a newer clipboard change from another application.
"""
import ctypes
import pythoncom
import win32clipboard

class ClipboardLease:
 def __init__(self):
  self.original=None; self.original_empty=False; self.ours=None; self.initialized=False
 def put(self,text):
  pythoncom.OleInitialize(); self.initialized=True
  try:
   win32clipboard.OpenClipboard()
   try: self.original_empty=(win32clipboard.CountClipboardFormats()==0)
   finally: win32clipboard.CloseClipboard()
   if not self.original_empty: self.original=pythoncom.OleGetClipboard()
   win32clipboard.OpenClipboard()
   try:
    win32clipboard.EmptyClipboard()
    self.ours=ctypes.windll.user32.GetClipboardSequenceNumber()
    win32clipboard.SetClipboardText(text,win32clipboard.CF_UNICODETEXT)
    self.ours=ctypes.windll.user32.GetClipboardSequenceNumber()
   finally: win32clipboard.CloseClipboard()
  except Exception:
   self.restore()
   raise
 def restore(self):
  try:
   if self.ours is None or ctypes.windll.user32.GetClipboardSequenceNumber()!=self.ours:
    return False
   if self.original_empty:
    win32clipboard.OpenClipboard()
    try: win32clipboard.EmptyClipboard()
    finally: win32clipboard.CloseClipboard()
   else:
    pythoncom.OleSetClipboard(self.original)
    pythoncom.OleFlushClipboard()
   return True
  finally:
   self.original=None
   if self.initialized: pythoncom.OleUninitialize(); self.initialized=False
