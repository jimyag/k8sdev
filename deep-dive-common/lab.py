"""zj kind 实验共用的命令、条件等待和证据记录；不连接默认集群。"""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parent.parent
IMAGE = 'python:3.12-alpine'
CTX = 'kind-deep-dive'


def command(args, data=None, check=True):
    r = subprocess.run(args, input=data, text=True, capture_output=True, timeout=180)
    if check and r.returncode:
        raise RuntimeError(f'{args}: {r.stderr}\n{r.stdout}')
    return r


def k(*args, data=None, check=True):
    return command(['kubectl', '--context', CTX, *args], data, check)


def wait(fn, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(2)
    raise TimeoutError(f'condition did not converge in {timeout}s')


class Lab:
    def __init__(self, topic):
        self.ns = 'dd-' + topic
        self.out = ROOT / ('deep-dive-' + topic) / 'evidence'
        self.out.mkdir(parents=True, exist_ok=True)
        assert os.environ.get('KUBECONFIG'), '请显式设置本实验 KUBECONFIG'
        assert json.loads(k('get', 'node', '-o', 'json').stdout)['items'][0]['metadata']['name'].startswith('deep-dive-')
        # 每次重跑只清理当前主题的 namespace。
        k('delete', 'namespace', self.ns, '--ignore-not-found', '--wait=true')
        k('create', 'namespace', self.ns)
        self.save('version', json.loads(k('version', '-o', 'json').stdout))

    def save(self, name, value):
        (self.out / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        print(name + ': ' + json.dumps(value, ensure_ascii=False)[:1600], flush=True)

    def apply(self, obj):
        self.save('input-' + obj['kind'].lower() + '-' + obj['metadata']['name'], obj)
        return k('apply', '-n', self.ns, '-f', '-', data=json.dumps(obj))

    def get(self, kind, name=None):
        args = ['get', kind]
        if name:
            args.append(name)
        return json.loads(k(*args, '-n', self.ns, '-o', 'json').stdout)

    def patch(self, kind, name, value):
        return k('patch', kind, name, '-n', self.ns, '--type=merge', '-p', json.dumps(value))

    def ready(self, name):
        k('wait', '-n', self.ns, '--for=condition=Ready', 'pod/' + name, '--timeout=180s')

    def exec(self, name, *args, check=True, container=None):
        extra = ['-c', container] if container else []
        return k('exec', '-n', self.ns, name, *extra, '--', *args, check=check)

    def pods(self, app):
        return [p for p in self.get('pods')['items'] if p['metadata'].get('labels', {}).get('app') == app]

    def rollout(self, name):
        k('rollout', 'status', '-n', self.ns, 'deployment/' + name, '--timeout=180s')

    def snapshot(self, name):
        self.save(name, self.get('pods'))
        self.save(name + '-events', self.get('events'))


def pod(name, code='import time; time.sleep(3600)', **spec):
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'labels': {'app': name}},
            'spec': {'terminationGracePeriodSeconds': 2, 'containers': [{'name': 'app', 'image': IMAGE,
            'imagePullPolicy': 'IfNotPresent', 'command': ['python', '-u', '-c', code]}], **spec}}


def deployment(name, code='import time; time.sleep(3600)', replicas=1, **spec):
    p = pod(name, code, **spec)
    return {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': name},
            'spec': {'replicas': replicas, 'selector': {'matchLabels': {'app': name}},
                     'template': {'metadata': {'labels': {'app': name}}, 'spec': p['spec']}}}


def service(name):
    return {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': name},
            'spec': {'selector': {'app': name}, 'ports': [{'port': 8080, 'targetPort': 8080}]}}


SERVER = '''import http.server, pathlib, time, os, urllib.request
class H(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  status=200; body=b'ok'
  if self.path == '/ready' and pathlib.Path('/state/not-ready').exists(): status=503
  if self.path == '/live' and pathlib.Path('/state/not-live').exists(): status=503
  if self.path == '/startup' and not pathlib.Path('/state/started').exists(): status=503
  if self.path == '/work':
   end=time.thread_time()+0.02
   while time.thread_time()<end: pass
  if self.path == '/slow': time.sleep(0.2)
  if self.path == '/proxy':
   with urllib.request.urlopen(os.environ['BACKEND']+'/slow',timeout=10) as r: body=r.read()
  self.send_response(status); self.end_headers(); self.wfile.write(body)
 def log_message(self,*args): pass
http.server.ThreadingHTTPServer(('0.0.0.0',8080),H).serve_forever()
'''
