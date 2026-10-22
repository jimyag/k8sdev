import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deep-dive-common'))
from lab import Lab, pod, k, wait, command
import json

l = Lab('terminating')
p = pod('held')
p['metadata']['finalizers'] = ['lab.example.com/cleanup']
l.apply(p)
l.ready('held')
k('delete', 'pod', 'held', '-n', l.ns, '--wait=false')
wait(lambda: l.get('pod', 'held')['metadata'].get('deletionTimestamp'))
l.save('deletion-requested', l.get('pod', 'held'))
# --force 不会代替 finalizer 的清理责任。
r = k('delete', 'pod', 'held', '-n', l.ns, '--force', '--grace-period=0', '--wait=false')
l.save('force-result', {'stdout': r.stdout, 'stderr': r.stderr})
l.save('after-force', l.get('pod', 'held'))
assert l.get('pod', 'held')['metadata']['finalizers'] == ['lab.example.com/cleanup']
# 这里的自定义 finalizer 没有外部资源，确认后才能移除。
l.patch('pod', 'held', {'metadata': {'finalizers': []}})
k('wait', '-n', l.ns, '--for=delete', 'pod/held', '--timeout=60s')
l.save('result', {'force_did_not_remove_finalizer': True, 'deleted_after_cleanup': True})

# 第二个场景只停 kind worker2 内的 kubelet，容器运行时继续工作。
l.apply(pod('orphan-process',nodeName='deep-dive-worker2'))
l.ready('orphan-process')
cid=l.get('pod','orphan-process')['status']['containerStatuses'][0]['containerID'].split('://')[1]
command(['docker','exec','deep-dive-worker2','systemctl','stop','kubelet'])
try:
    k('delete','pod','orphan-process','-n',l.ns,'--force','--grace-period=0','--wait=true')
    state=json.loads(command(['docker','exec','deep-dive-worker2','crictl','inspect',cid]).stdout)
    assert state['status']['state']=='CONTAINER_RUNNING'
    l.save('force-object-gone-process-running',{'api_object_exists':False,'container_state':state['status']['state'],'container_id':cid})
finally:
    command(['docker','exec','deep-dive-worker2','systemctl','start','kubelet'])
def stopped():
    r=command(['docker','exec','deep-dive-worker2','crictl','inspect',cid],check=False)
    return r.returncode!=0 or json.loads(r.stdout)['status']['state']!='CONTAINER_RUNNING'
wait(stopped)
l.save('orphan-cleaned',{'kubelet_restarted':True,'old_container_running':False})
