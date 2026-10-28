import os, subprocess, sys
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]))
import singleton
h=singleton.acquire(); assert h
probe='import sys;sys.path.insert(0,sys.argv[1]);import singleton; h=singleton.acquire();print("acquired" if h else "blocked");singleton.release(h)'
args=[sys.executable,'-c',probe,str(__import__('pathlib').Path(__file__).resolve().parents[1])]
blocked=subprocess.check_output(args,text=True).strip(); assert blocked=='blocked',blocked
singleton.release(h)
allowed=subprocess.check_output(args,text=True).strip(); assert allowed=='acquired',allowed
print('Second process blocked; after release new process allowed: PASS')

