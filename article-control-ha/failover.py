"""重新验证单控制面故障，记录切换期间失败和恢复后的成功。"""
import json
import os
import subprocess
import time

os.environ['KUBECONFIG'] = os.path.abspath('../tmp/article-control/kubeconfig')
K = os.path.abspath('../tmp/article-tools/kubectl')

def k(*args):
    return subprocess.check_output([K, '--request-timeout=8s', *args], text=True)

before = json.loads(k('-n', 'kube-system', 'get', 'lease', 'kube-scheduler', '-o', 'json'))['spec']['holderIdentity']
node = before.split('_')[0]
print('pause scheduler leader node:', node, flush=True)
subprocess.run(['docker', 'pause', node], check=True)
try:
    deadline = time.monotonic() + 150
    while True:
        result = subprocess.run([K, '--request-timeout=8s', '-n', 'control-ha', 'create', 'cm', 'failover-verified', '--from-literal=value=ok'], text=True, capture_output=True)
        print(result.stdout + result.stderr, flush=True)
        if result.returncode == 0 or 'AlreadyExists' in result.stderr:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError('write recovery timeout')
    k('-n', 'control-ha', 'scale', 'deployment/baseline', '--replicas=4')
    print(k('-n', 'control-ha', 'rollout', 'status', 'deployment/baseline', '--timeout=150s'), flush=True)
    print(k('-n', 'kube-system', 'get', 'lease', 'kube-scheduler', 'kube-controller-manager', '-o', 'custom-columns=NAME:.metadata.name,HOLDER:.spec.holderIdentity'), flush=True)
    print(k('-n', 'control-ha', 'get', 'pods', '-o', 'wide'), flush=True)
finally:
    subprocess.run(['docker', 'unpause', node], check=True)
