import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deep-dive-common'))
from lab import Lab, deployment, k, wait, command

l = Lab('node-failure')
target = 'deep-dive-worker'
# 先把唯一副本放到 worker；随后移除调度约束，允许故障后转移。
d = deployment('app', tolerations=[{'key': key, 'operator': 'Exists', 'effect': 'NoExecute', 'tolerationSeconds': 15}
    for key in ['node.kubernetes.io/not-ready', 'node.kubernetes.io/unreachable']])
k('cordon', 'deep-dive-worker2')
try:
    l.apply(d)
    l.rollout('app')
finally:
    k('uncordon', 'deep-dive-worker2')
old = l.pods('app')[0]
assert old['spec']['nodeName'] == target
l.save('before', old)
start = time.monotonic()
command(['docker', 'pause', target])
try:
    def lost():
        node = __import__('json').loads(k('get', 'node', target, '-o', 'json').stdout)
        return node if any(c['type'] == 'Ready' and c['status'] == 'Unknown' for c in node['status']['conditions']) else None
    l.save('node-unknown', wait(lost, 120))
    unknown = time.monotonic() - start
    def replaced():
        return next((p for p in l.pods('app') if p['metadata']['uid'] != old['metadata']['uid']
            and any(c['type'] == 'Ready' and c['status'] == 'True' for c in p.get('status', {}).get('conditions', []))), None)
    new = wait(replaced, 180)
    l.save('replacement', new)
    l.snapshot('while-paused')
    l.save('timing', {'unknown_seconds': round(unknown, 2), 'replacement_ready_seconds': round(time.monotonic()-start, 2),
                     'toleration_seconds': 15, 'injection': 'docker pause worker (not host power failure)'})
finally:
    command(['docker', 'unpause', target])
k('wait', '--for=condition=Ready', 'node/' + target, '--timeout=180s')
k('wait', '-n', l.ns, '--for=delete', 'pod/' + old['metadata']['name'], '--timeout=180s')
l.snapshot('recovered')
