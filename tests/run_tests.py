import pathlib, subprocess, sys
for p in sorted(pathlib.Path(__file__).parent.glob('test_*.py')):
 print(p.name,flush=True)
 subprocess.run([sys.executable,str(p)],check=True)
print('All checks passed.')
