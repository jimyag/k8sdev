import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deep-dive-common'))
from lab import Lab, pod, wait

l = Lab('pod-stages')
p = pod('unscheduled', nodeSelector={'lab.example.com/missing': 'true'})
l.apply(p)
wait(lambda: any(c['type']=='PodScheduled' and c['status']=='False' for c in l.get('pod','unscheduled')['status'].get('conditions',[])))
l.save('unscheduled', l.get('pod','unscheduled'))
p = pod('mount-blocked', volumes=[{'name':'config','configMap':{'name':'missing-config'}}])
p['spec']['containers'][0]['volumeMounts']=[{'name':'config','mountPath':'/config'}]
l.apply(p)
wait(lambda: l.get('pod','mount-blocked')['spec'].get('nodeName'))
wait(lambda: any(e.get('reason')=='FailedMount' for e in l.get('events')['items']))
l.snapshot('mount-blocked')
l.apply({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'missing-config'},'data':{'value':'ready'}})
l.ready('mount-blocked')
l.save('mount-recovered', l.get('pod','mount-blocked'))
