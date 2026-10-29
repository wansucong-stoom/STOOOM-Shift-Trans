"""IPC fault injection; no Windows clipboard APIs."""
import json,os,pathlib,sys,time
for line in sys.stdin.buffer:
 request=json.loads(line);op=request['op'];args=request['args']
 if op=='mutate_and_die':
  with pathlib.Path(args[0]).open('a') as log:log.write('one simulated write\n')
  os._exit(77)
 if op=='hang':time.sleep(10)
 value=args[0] if op=='echo' else {'pid':os.getpid()}
 response={'id':request['id'],'ok':True,'value':value}
 sys.stdout.buffer.write(json.dumps(response,ensure_ascii=True).encode()+b'\n');sys.stdout.buffer.flush()
