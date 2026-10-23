"""检查慢就绪保留旧副本，以及终止中 Pod 超出 surge 名义上限。"""
import json
import os
import subprocess
import time

os.environ['KUBECONFIG'] = os.path.abspath('../tmp/article-control/kubeconfig')
K = os.path.abspath('../tmp/article-tools/kubectl')
NS = 'control-rollout'

def k(*args):
    return subprocess.check_output([K, '-n', NS, *args], text=True)

def pods():
    return json.loads(k('get', 'pods', '-l', 'app=slow', '-o', 'json'))['items']

def until(check):
    end = time.monotonic() + 120
    while time.monotonic() < end:
        if check():
            return
        time.sleep(0.5)
    raise RuntimeError('condition timed out')

subprocess.run([K, 'create', 'namespace', NS], check=True)
k('apply', '-f', 'deployment.yaml')
k('rollout', 'status', 'deployment/slow', '--timeout=180s')
old = {p['metadata']['uid'] for p in pods()}
patch = {'spec': {'template': {'spec': {'containers': [{'name': 'app', 'command':
    ['sh', '-c', 'while true; do sleep 1; done']}]}}}}
k('patch', 'deployment', 'slow', '--type=strategic', '-p', json.dumps(patch))
until(lambda: len(pods()) == 3 and all(p['status'].get('containerStatuses') for p in pods()))
current = pods()
assert sum(p['metadata']['uid'] in old for p in current) == 2
print('new Pod unready: 2 old + 1 new, no old deletion', flush=True)
seen_overlap = False
end = time.monotonic() + 120
while time.monotonic() < end:
    current = pods()
    terminating = [p for p in current if p['metadata'].get('deletionTimestamp')]
    print(json.dumps({'pods': len(current), 'terminating': len(terminating),
                      'available': json.loads(k('get', 'deployment', 'slow', '-o', 'json'))['status'].get('availableReplicas', 0)}), flush=True)
    seen_overlap |= len(current) > 3 and bool(terminating)
    for p in current:
        if p['metadata']['uid'] not in old and not p['metadata'].get('deletionTimestamp'):
            subprocess.run([K, '-n', NS, 'exec', p['metadata']['name'], '--', 'touch', '/ready'],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    status = json.loads(k('get', 'deployment', 'slow', '-o', 'json'))['status']
    if seen_overlap and status.get('updatedReplicas') == 2 and status.get('availableReplicas') == 2 and not any(p['metadata']['uid'] in old and not p['metadata'].get('deletionTimestamp') for p in current):
        break
    time.sleep(1)
assert seen_overlap, 'did not observe terminating Pod overlap'
k('rollout', 'status', 'deployment/slow', '--timeout=180s')
print('rollout complete; terminating Pods are checked separately', flush=True)
subprocess.run(['python3', 'capacity.py'], check=True)
