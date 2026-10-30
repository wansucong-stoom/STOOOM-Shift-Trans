"""User-requested input metadata policy; this does not touch real windows."""
import os,pathlib,sys,tempfile,types
from unittest import mock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory() as root:
    old=os.environ.get('LOCALAPPDATA');os.environ['LOCALAPPDATA']=root
    import main
    if old is None:os.environ.pop('LOCALAPPDATA',None)
    else:os.environ['LOCALAPPDATA']=old
import comtypes,comtypes.client
asked=[]
class Focused:
    def GetCurrentPropertyValue(self,property_id):
        asked.append(property_id)
        # A provider may report password/read-only metadata even for a
        # custom editing surface. Neither is an exclusion in this mode.
        return {30010:True,30019:True,30046:True}.get(property_id)
api=types.SimpleNamespace(CUIAutomation=object(),IUIAutomation=object())
automation=types.SimpleNamespace(GetFocusedElement=lambda:Focused())
with mock.patch.object(comtypes,'CoInitializeEx'),mock.patch.object(comtypes,'CoUninitialize'), \
     mock.patch.object(comtypes.client,'GetModule',return_value=api), \
     mock.patch.object(comtypes.client,'CreateObject',return_value=automation):
    assert main.keyboard_safety() is True
assert asked==[],asked
env=types.SimpleNamespace(safety=lambda:True)
main.keyboard_access.Windows.safe(env)
print('Common route requires no UIA COM calls; Win32 focus is checked by the driver: PASS')
