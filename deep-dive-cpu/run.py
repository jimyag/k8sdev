import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deep-dive-common'))
from lab import Lab, pod

l=Lab('cpu')
measure='''import time,json,pathlib
def stat(): return dict((k,int(v)) for k,v in (line.split() for line in pathlib.Path('/sys/fs/cgroup/cpu.stat').read_text().splitlines()))
a=stat(); wall=time.monotonic(); cpu=time.process_time()
while time.process_time()-cpu < 1: pass
b=stat()
print(json.dumps({'wall_seconds':time.monotonic()-wall,'cpu_seconds':time.process_time()-cpu,'cpu_max':pathlib.Path('/sys/fs/cgroup/cpu.max').read_text().strip(),'delta':{k:b[k]-a[k] for k in a}}))
'''
results={}
for name,limit in [('limited','100m'),('unlimited',None)]:
    p=pod(name)
    p['spec']['containers'][0]['resources']={'requests':{'cpu':'100m'}}
    if limit: p['spec']['containers'][0]['resources']['limits']={'cpu':limit}
    l.apply(p); l.ready(name)
    results[name]=json.loads(l.exec(name,'python','-c',measure).stdout)
assert results['limited']['delta']['nr_throttled']>0
assert results['limited']['wall_seconds']>results['unlimited']['wall_seconds']*2
l.save('one-cpu-second',results)
# 两组任务都只消耗约 1 CPU 秒；平均 CPU 使用率不能代替单次任务的等待时间。
