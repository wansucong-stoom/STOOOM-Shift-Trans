import sys,types
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]));import main
v=types.SimpleNamespace(CurrentIsReadOnly=False,CurrentValue='old')
w=types.SimpleNamespace(iface_value=v,iface_text=object()); info=types.SimpleNamespace(control_type='Edit')
main.focused_element=lambda:((1,2),info,w)
main.range_access.capture=lambda *a:types.SimpleNamespace(text='old')
rid,text,context=main.capture_input();assert rid==(1,2) and context[0]=='range'
def no_range(*a): raise RuntimeError('not provided')
main.range_access.capture=no_range
assert main.capture_input()[2][0]=='value'
info.control_type='Document'
try: main.capture_input(); raise AssertionError('full document value must not be used')
except ValueError:pass
print('text range preferred; value fallback limited to non-document: PASS')

