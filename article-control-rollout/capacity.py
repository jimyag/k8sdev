"""在已完成慢启动实验的 Deployment 上验证新版本容量不足。"""
import json
import os
import subprocess
import time

os.environ['KUBECONFIG'] = os.path.abspath('../tmp/article-control/kubeconfig')
K = os.path.abspath('../tmp/article-tools/kubectl')
def k(*args):
    return subprocess.check_output([K, '-n', 'control-rollout', *args], text=True)
patch = {'spec': {'template': {'spec': {'containers': [{'name': 'app',
    'resources': {'requests': {'cpu': '100000'}}}]}}}}
k('patch', 'deployment', 'slow', '--type=strategic', '-p', json.dumps(patch))
end = time.monotonic() + 90
while time.monotonic() < end:
    pods = json.loads(k('get', 'pods', '-l', 'app=slow', '-o', 'json'))['items']
    if any(c.get('reason') == 'Unschedulable' for p in pods for c in p.get('status', {}).get('conditions', [])):
        break
    time.sleep(0.5)
else:
    raise RuntimeError('did not observe Unschedulable')
assert json.loads(k('get', 'deployment', 'slow', '-o', 'json'))['status'].get('availableReplicas') == 2
print('capacity blocked: new Pod Unschedulable, old available=2', flush=True)
print(k('get', 'events', '--field-selector=reason=FailedScheduling'), flush=True)
k('rollout', 'undo', 'deployment/slow')
print(k('rollout', 'status', 'deployment/slow', '--timeout=120s').rstrip(), flush=True)
