"""在业务 worker 正常的前提下，验证所有 API Server 停止后的直接 Pod 请求。"""
import json
import os
import subprocess
import time

os.environ['KUBECONFIG'] = os.path.abspath('../tmp/article-control/kubeconfig')
K = os.path.abspath('../tmp/article-tools/kubectl')
nodes = ['article-control-control-plane' + suffix for suffix in ['', '2', '3']]
obj = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'existing-http', 'namespace': 'control-ha'},
       'spec': {'containers': [{'name': 'http', 'image': 'registry.k8s.io/e2e-test-images/busybox:1.29-4',
           'command': ['sh', '-c', 'mkdir -p /www; echo alive > /www/index.html; httpd -f -p 8080 -h /www']}]}}
subprocess.run([K, 'create', '-f', '-'], input=json.dumps(obj), text=True, check=True)
subprocess.run([K, '-n', 'control-ha', 'wait', 'pod/existing-http', '--for=condition=Ready', '--timeout=120s'], check=True)
before = json.loads(subprocess.check_output([K, '-n', 'control-ha', 'get', 'pod', 'existing-http', '-o', 'json'], text=True))
ip = before['status']['podIP']
disabled = []
try:
    for node in nodes:
        subprocess.run(['docker', 'exec', node, 'mv', '/etc/kubernetes/manifests/kube-apiserver.yaml', '/etc/kubernetes/article-disabled/'], check=True)
        disabled.append(node)
    end = time.monotonic() + 120
    while any(subprocess.check_output(['docker', 'exec', node, 'crictl', 'ps', '--name', 'kube-apiserver', '-q'], text=True).strip() for node in nodes):
        if time.monotonic() >= end:
            raise RuntimeError('API process stop timed out')
        time.sleep(1)
    result = subprocess.run([K, '--request-timeout=3s', 'get', 'pods', '-n', 'control-ha'], capture_output=True, text=True)
    assert result.returncode != 0
    print('all API Server processes stopped; API request failed', flush=True)
    print(subprocess.check_output(['docker', 'exec', 'article-control-worker', 'curl', '--fail', '--max-time', '3', '-s', 'http://' + ip + ':8080'], text=True), flush=True)
finally:
    for node in disabled:
        subprocess.run(['docker', 'exec', node, 'mv', '/etc/kubernetes/article-disabled/kube-apiserver.yaml', '/etc/kubernetes/manifests/'], check=True)
end = time.monotonic() + 120
while True:
    result = subprocess.run([K, '--request-timeout=3s', '-n', 'control-ha', 'get', 'pod', 'existing-http', '-o', 'json'], capture_output=True, text=True)
    if result.returncode == 0:
        after = json.loads(result.stdout)
        assert after['metadata']['uid'] == before['metadata']['uid']
        assert after['status']['containerStatuses'][0]['containerID'] == before['status']['containerStatuses'][0]['containerID']
        print('API recovered; Pod UID and container ID unchanged', flush=True)
        break
    if time.monotonic() >= end:
        raise RuntimeError('API recovery timed out')
