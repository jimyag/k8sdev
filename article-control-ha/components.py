"""只暂停本实验集群的指定静态 Pod，检查各层职责，退出时恢复清单。"""
import json
import os
import subprocess
import time

os.environ['KUBECONFIG'] = os.path.abspath('../tmp/article-control/kubeconfig')
K = os.path.abspath('../tmp/article-tools/kubectl')
NODES = ['article-control-control-plane' + suffix for suffix in ['', '2', '3']]
NS = 'control-ha'

def k(*args):
    return subprocess.check_output([K, '--request-timeout=8s', '-n', NS, *args], text=True)

def until(check, label):
    end = time.monotonic() + 150
    while time.monotonic() < end:
        if check():
            print(label, flush=True)
            return
        time.sleep(1)
    raise RuntimeError(label)

def containers_empty(component):
    return all(not subprocess.check_output(['docker', 'exec', node, 'crictl', 'ps', '--name', component, '-q'], text=True).strip() for node in NODES)

for component in ['kube-scheduler', 'kube-controller-manager']:
    stopped = []
    try:
        for node in NODES:
            subprocess.run(['docker', 'exec', node, 'mkdir', '-p', '/etc/kubernetes/article-disabled'], check=True)
            subprocess.run(['docker', 'exec', node, 'mv', '/etc/kubernetes/manifests/' + component + '.yaml', '/etc/kubernetes/article-disabled/'], check=True)
            stopped.append(node)
        until(lambda: containers_empty(component), component + ': all processes stopped')
        if component == 'kube-scheduler':
            k('run', 'needs-scheduler', '--image=registry.k8s.io/pause:3.10.1')
            p = json.loads(k('get', 'pod', 'needs-scheduler', '-o', 'json'))
            assert not p['spec'].get('nodeName')
            print('scheduler absent: API accepted Pod; nodeName empty', flush=True)
        else:
            before = len(json.loads(k('get', 'pods', '-l', 'app=baseline', '-o', 'json'))['items'])
            k('scale', 'deployment', 'baseline', '--replicas=3')
            d = json.loads(k('get', 'deployment', 'baseline', '-o', 'json'))
            assert d['spec']['replicas'] == 3
            assert len(json.loads(k('get', 'pods', '-l', 'app=baseline', '-o', 'json'))['items']) == before
            print('controller absent: desired=3; actual=' + str(before), flush=True)
    finally:
        for node in stopped:
            subprocess.run(['docker', 'exec', node, 'mv', '/etc/kubernetes/article-disabled/' + component + '.yaml', '/etc/kubernetes/manifests/'], check=True)
    if component == 'kube-scheduler':
        k('wait', 'pod/needs-scheduler', '--for=condition=Ready', '--timeout=150s')
    else:
        k('rollout', 'status', 'deployment/baseline', '--timeout=150s')
    print(component + ': restored and convergence confirmed', flush=True)
