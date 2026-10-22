import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deep-dive-common'))
from lab import Lab,pod,k,wait,IMAGE

l=Lab('ephemeral')
p=pod('target',"import pathlib,time; pathlib.Path('/application-only').write_text('app-private-root'); time.sleep(3600)")
l.apply(p); l.ready('target')
k('debug','-n',l.ns,'pod/target','--image='+IMAGE,'--target=app','--container=debugger','--profile=general','--attach=false','--','python','-c','import time; time.sleep(45)')
wait(lambda: any(s['name']=='debugger' and 'running' in s['state'] for s in l.get('pod','target')['status'].get('ephemeralContainerStatuses',[])))
code='''import pathlib,os,json
found=[]
for p in pathlib.Path('/proc').glob('[0-9]*/root/application-only'):
 try: found.append({'path':str(p),'content':p.read_text()})
 except (PermissionError,FileNotFoundError,ProcessLookupError): pass
print(json.dumps({'own_root_has_file':pathlib.Path('/application-only').exists(),'target_files':found,'uid':os.getuid(),'netns':os.readlink('/proc/self/ns/net')}))
'''
result=json.loads(l.exec('target','python','-c',code,container='debugger').stdout)
assert not result['own_root_has_file'] and result['target_files']
l.save('filesystem-view',result)
l.save('app-identity',json.loads(l.exec('target','python','-c',"import os,json; print(json.dumps({'uid':os.getuid(),'netns':os.readlink('/proc/self/ns/net')}))",container='app').stdout))
# 临时容器的命令自行结束；按状态等待，不用终端断线推断退出。
wait(lambda: 'terminated' in l.get('pod','target')['status']['ephemeralContainerStatuses'][0]['state'])
l.save('terminated',l.get('pod','target'))
