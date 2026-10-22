import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deep-dive-common'))
from lab import Lab, pod, wait, k

l = Lab('scheduling')
p=pod('too-large')
p['spec']['containers'][0]['resources']={'requests':{'cpu':'1000'}}
l.apply(p)
wait(lambda: any(e.get('reason')=='FailedScheduling' and 'Insufficient cpu' in e.get('message','') for e in l.get('events')['items']))
l.snapshot('request-does-not-fit')
# 同一个宿主上的 kind 节点共享物理 CPU；这里只验证调度准入，不测物理隔离。
p=pod('affinity', nodeSelector={'lab.example.com/zone':'missing'})
l.apply(p)
wait(lambda: any(c['type']=='PodScheduled' and c['status']=='False' for c in l.get('pod','affinity')['status'].get('conditions',[])))
l.save('selector-mismatch', l.get('pod','affinity'))
k('label','node','deep-dive-worker2','lab.example.com/zone=missing','--overwrite')
try:
    l.ready('affinity')
    assert l.get('pod','affinity')['spec']['nodeName']=='deep-dive-worker2'
    l.save('selector-recovered',l.get('pod','affinity'))
finally:
    k('label','node','deep-dive-worker2','lab.example.com/zone-')
