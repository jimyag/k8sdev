import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deep-dive-common'))
from lab import Lab, pod, SERVER, wait, service

l=Lab('probes')
p=pod('app', SERVER, volumes=[{'name':'state','emptyDir':{}}])
c=p['spec']['containers'][0]
c['volumeMounts']=[{'name':'state','mountPath':'/state'}]
for kind,path in [('startupProbe','startup'),('readinessProbe','ready'),('livenessProbe','live')]:
    c[kind]={'httpGet':{'path':'/'+path,'port':8080},'periodSeconds':2,'failureThreshold':60 if kind=='startupProbe' else 2}
l.apply(p)
l.apply(service('app'))
wait(lambda: l.get('pod','app')['status'].get('containerStatuses',[{}])[0].get('state',{}).get('running'))
wait(lambda: any(e.get('reason')=='Unhealthy' and 'Startup probe failed' in e.get('message','') for e in l.get('events')['items']))
l.snapshot('startup-blocked')
assert not l.get('pod','app')['status']['containerStatuses'][0]['started']
l.exec('app','touch','/state/started')
l.ready('app')
l.exec('app','touch','/state/not-ready')
wait(lambda: not l.get('pod','app')['status']['containerStatuses'][0]['ready'])
l.save('readiness-failed',l.get('pod','app'))
wait(lambda:any(e.get('conditions',{}).get('ready') is False for s in l.get('endpointslices')['items'] for e in s.get('endpoints',[])))
l.save('not-ready-endpoint',l.get('endpointslices'))
assert l.get('pod','app')['status']['containerStatuses'][0]['restartCount']==0
l.exec('app','rm','/state/not-ready')
l.ready('app')
l.exec('app','touch','/state/not-live')
wait(lambda: l.get('pod','app')['status']['containerStatuses'][0]['restartCount']>=1)
l.save('liveness-restarted',l.get('pod','app'))
wait(lambda:'running' in l.get('pod','app')['status']['containerStatuses'][0]['state'])
l.exec('app','rm','/state/not-live')
l.ready('app')
l.snapshot('recovered')
