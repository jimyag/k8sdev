"""在专用 namespace 对照三种删除传播方式，以断言检查对象状态。"""
import json
import os
import subprocess
import time

os.environ['KUBECONFIG'] = os.path.abspath('../tmp/article-control/kubeconfig')
K = os.path.abspath('../tmp/article-tools/kubectl')
NS = 'control-gc'

def k(*args, data=None):
    return subprocess.check_output([K, '-n', NS, *args], input=data, text=True)

def get(name):
    out = k('get', 'cm', name, '--ignore-not-found', '-o', 'json')
    return json.loads(out) if out.strip() else None

def until(check, description):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if check():
            print(description, flush=True)
            return
        time.sleep(0.5)
    raise RuntimeError(description)

subprocess.run([K, 'create', 'namespace', NS], check=True)
for policy in ['foreground', 'background', 'orphan']:
    owner = policy + '-owner'
    child = policy + '-child'
    k('create', 'cm', owner)
    uid = get(owner)['metadata']['uid']
    obj = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {
        'name': child, 'namespace': NS, 'finalizers': ['article.example/hold'],
        'ownerReferences': [{'apiVersion': 'v1', 'kind': 'ConfigMap', 'name': owner,
                             'uid': uid, 'blockOwnerDeletion': True}]}}
    k('create', '-f', '-', data=json.dumps(obj))
    k('delete', 'cm', owner, '--cascade=' + policy, '--wait=false')
    if policy == 'foreground':
        until(lambda: get(child)['metadata'].get('deletionTimestamp'), 'foreground: child terminating')
        assert get(owner)['metadata'].get('deletionTimestamp')
        assert 'foregroundDeletion' in get(owner)['metadata']['finalizers']
        print('foreground: owner retained by blocking child', flush=True)
    elif policy == 'background':
        until(lambda: get(owner) is None, 'background: owner absent')
        until(lambda: get(child)['metadata'].get('deletionTimestamp'), 'background: child terminating with finalizer')
    else:
        until(lambda: get(owner) is None, 'orphan: owner absent')
        until(lambda: not get(child)['metadata'].get('ownerReferences'), 'orphan: child ownerReferences removed')
        assert not get(child)['metadata'].get('deletionTimestamp')
    k('patch', 'cm', child, '--type=merge', '-p', '{"metadata":{"finalizers":[]}}')
    if policy == 'orphan':
        k('delete', 'cm', child)
    until(lambda: get(owner) is None and get(child) is None, policy + ': cleanup complete')
