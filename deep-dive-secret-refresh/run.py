import sys, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deep-dive-common'))
from lab import Lab,pod,wait

l=Lab('secret-refresh')
l.apply({'apiVersion':'v1','kind':'Secret','metadata':{'name':'settings'},'stringData':{'value':'old'}})
code='''import time,pathlib
p=pathlib.Path('/config/value'); cached=p.read_text(); pathlib.Path('/cached').write_text(cached)
while True: time.sleep(1)
'''
p=pod('reader',code,volumes=[{'name':'settings','secret':{'secretName':'settings'}}])
c=p['spec']['containers'][0]
c['env']=[{'name':'VALUE','valueFrom':{'secretKeyRef':{'name':'settings','key':'value'}}}]
c['volumeMounts']=[{'name':'settings','mountPath':'/config','readOnly':True},
 {'name':'settings','mountPath':'/subpath-value','subPath':'value','readOnly':True}]
l.apply(p); l.ready('reader')
read="import os,json,pathlib; print(json.dumps({'env':os.environ['VALUE'],'volume':pathlib.Path('/config/value').read_text(),'subPath':pathlib.Path('/subpath-value').read_text(),'cached':pathlib.Path('/cached').read_text()}))"
l.save('before',json.loads(l.exec('reader','python','-c',read).stdout))
l.patch('secret','settings',{'stringData':{'value':'new'}})
wait(lambda: json.loads(l.exec('reader','python','-c',read).stdout)['volume']=='new',180)
after=json.loads(l.exec('reader','python','-c',read).stdout)
assert after=={'env':'old','volume':'new','subPath':'old','cached':'old'}
l.save('after',after)
