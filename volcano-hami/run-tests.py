#!/usr/bin/env python3
"""在独立 kind-volcano-lab 上验证调度行为，保存输入、快照和明确断言。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import traceback
import yaml

NS = 'volcano-tests'
OUT = Path(os.environ.get('RESULT_DIR', 'results'))
OUT.mkdir(exist_ok=True)
CASE = ''
RESULTS = []

def k(*args, obj=None, check=True):
    p = subprocess.run(['kubectl', '--context', 'kind-volcano-lab', *args],
                       input=json.dumps(obj) if obj is not None else None,
                       text=True, capture_output=True, timeout=100)
    if check and p.returncode:
        raise RuntimeError(p.stderr or p.stdout)
    return p.stdout if check else p

def get(kind, name=None, ns=True):
    args = (['-n', NS] if ns else []) + ['get', kind] + ([name] if name else []) + ['-o', 'json']
    return json.loads(k(*args))

def apply(obj):
    p = OUT / CASE
    p.mkdir(exist_ok=True)
    f = p / (obj['kind'].lower() + '-' + obj['metadata']['name'] + '.yaml')
    f.write_text('# 本用例的实际输入；资源请求与策略字段用于验证调度边界。\n'
                 '# CPU 单位为核，vgpu-memory 每单位为 100 MiB，vgpu-cores 为百分比。\n'
                 + yaml.safe_dump(obj, sort_keys=False, allow_unicode=True))
    return k('apply', '-f', '-', obj=obj)

def wait(fn, timeout=70):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(1)
    raise AssertionError(f'condition timed out after {timeout}s: {last}')

def pods(job=None):
    items = get('pods')['items']
    return [p for p in items if not job or p['metadata'].get('labels', {}).get('volcano.sh/job-name') == job]

def running(job):
    return [p for p in pods(job) if p.get('status', {}).get('phase') == 'Running']

def pending(job, count):
    wait(lambda: len(pods(job)) == count)
    for _ in range(6):
        pp = pods(job)
        assert len(pp) == count and all(not p['spec'].get('nodeName') for p in pp), pp
        time.sleep(1)

def delete_job(name):
    k('-n', NS, 'delete', 'jobs.batch.volcano.sh', name, '--wait=true', '--timeout=45s')
    wait(lambda: not pods(name))

def clean():
    k('-n', NS, 'delete', 'jobs.batch.volcano.sh,pods,podgroups', '--all', '--wait=true', '--timeout=45s', check=False)
    wait(lambda: not pods(), 45)
    k('delete', 'queues', '-l', 'lab=volcano', '--wait=true', '--timeout=30s', check=False)

def queue(name='lab', **spec):
    return {'apiVersion':'scheduling.volcano.sh/v1beta1','kind':'Queue',
            'metadata':{'name':name,'labels':{'lab':'volcano'}},'spec':{'weight':1,'reclaimable':True,**spec}}

def job(name, n=1, minimum=None, cpu='100m', q='lab', gpu=None, node=None, command=None, annotations=None, **extra):
    c = {'name':'work','image':'ubuntu:22.04','imagePullPolicy':'IfNotPresent',
         'command':command or ['sleep','3600'], 'resources':{'requests':{'cpu':str(cpu),'memory':'32Mi'}}}
    spec = {'restartPolicy':'Never','terminationGracePeriodSeconds':0,'containers':[c]}
    if node: spec['nodeSelector'] = {'kubernetes.io/hostname': node}
    if gpu:
        c['resources']['limits'] = {'volcano.sh/vgpu-'+key: (val // 100 if key == 'memory' else val) for key,val in gpu.items()}
        spec['runtimeClassName'] = 'nvidia'
        spec['volumes'] = [{'name':'cuda','hostPath':{'path':'/var/lib/nvml-mock/driver/usr/lib64/libcuda.so.1','type':'File'}}]
        c['volumeMounts'] = [{'name':'cuda','mountPath':'/usr/lib/x86_64-linux-gnu/libcuda.so.1','readOnly':True}]
    return {'apiVersion':'batch.volcano.sh/v1alpha1','kind':'Job','metadata':{'name':name,'namespace':NS},
            'spec':{'schedulerName':'volcano','minAvailable':n if minimum is None else minimum,'queue':q,
                    'tasks':[{'name':'worker','replicas':n,'template':{'metadata':{'annotations':annotations or {}},'spec':spec}}],**extra}}

def config(mode='proportion', **kw):
    plugins = [{'name':'drf','enablePreemptable':False},{'name':'predicates'},{'name':mode},{'name':'nodeorder'},
               {'name':'binpack','arguments':{'binpack.weight':10}},
               {'name':'deviceshare','arguments':{'deviceshare.VGPUEnable':True,'deviceshare.SchedulePolicy':kw.get('gpu_policy','binpack'),'deviceshare.ScheduleWeight':kw.get('gpu_weight',0)}}]
    if kw.get('extra'): plugins += kw['extra']
    conf = {'actions':'enqueue, reclaim, allocate, backfill, preempt','tiers':[{'plugins':[{'name':'priority'},{'name':'gang'},{'name':'conformance'}]},{'plugins':plugins}]}
    cm = json.loads(k('-n','volcano-system','get','cm','volcano-scheduler-configmap','-o','json'))
    cm['data']['volcano-scheduler.conf'] = yaml.safe_dump(conf, sort_keys=False)
    cm['metadata'] = {'name':'volcano-scheduler-configmap','namespace':'volcano-system'}
    apply(cm)
    k('-n','volcano-system','rollout','restart','deployment/volcano-scheduler')
    k('-n','volcano-system','rollout','status','deployment/volcano-scheduler','--timeout=90s')

def snapshot():
    d = OUT / CASE
    d.mkdir(exist_ok=True)
    for kind in ['pods','jobs.batch.volcano.sh','podgroups','events']:
        (d/(kind+'.json')).write_text(k('-n',NS,'get',kind,'-o','json'))
    (d/'queues.json').write_text(k('get','queues','-o','json'))
    (d/'scheduler.log').write_text(k('-n','volcano-system','logs','deployment/volcano-scheduler','--tail=120',check=False).stdout)

def case(name, fn, mode=None):
    global CASE
    CASE = name
    print('START',name,flush=True)
    t = time.monotonic()
    error = None
    try:
        clean()
        if mode: config(mode)
        apply(queue())
        fn()
    except Exception:
        error = traceback.format_exc()
    try: snapshot()
    except Exception: error = (error or '') + traceback.format_exc()
    RESULTS.append({'case':name,'status':'FAIL' if error else 'PASS','seconds':round(time.monotonic()-t,2),'error':error})
    (OUT/'results.json').write_text(json.dumps(RESULTS,ensure_ascii=False,indent=2))
    print(RESULTS[-1],flush=True)

def complete():
    apply(job('complete',n=2,command=['sh','-c','echo complete']))
    wait(lambda: get('jobs.batch.volcano.sh','complete').get('status',{}).get('state',{}).get('phase')=='Completed')

def gang():
    apply(job('holder',n=2,cpu='9'))
    wait(lambda: len(running('holder'))==2)
    apply(job('gang',n=3,cpu='5'))
    pending('gang',3)
    snapshot()
    delete_job('holder')
    wait(lambda:len(running('gang'))==3)

def elastic():
    apply(job('elastic',n=5,minimum=2,cpu='5'))
    wait(lambda:len(running('elastic'))==4)
    assert len(pods('elastic'))==5

def quota():
    apply(queue('limited',capability={'cpu':'5'}))
    apply(job('first',cpu='4',q='limited'))
    wait(lambda:len(running('first'))==1)
    apply(job('second',cpu='4',q='limited'))
    blocked_job('second')
    snapshot()
    delete_job('first')
    wait(lambda:len(running('second'))==1)

def blocked_job(name):
    wait(lambda: get('jobs.batch.volcano.sh',name).get('status',{}).get('state',{}).get('phase')=='Pending')
    for _ in range(6):
        assert not any(p['spec'].get('nodeName') for p in pods(name))
        time.sleep(1)

def queue_command(name, action):
    q=get('queue',name,ns=False)
    ref={'apiVersion':'scheduling.volcano.sh/v1beta1','kind':'Queue','name':name,'uid':q['metadata']['uid'],'controller':True,'blockOwnerDeletion':True}
    apply({'apiVersion':'bus.volcano.sh/v1alpha1','kind':'Command',
           'metadata':{'name':name+'-'+action.lower(),'namespace':'default','ownerReferences':[ref]},
           'target':ref,'action':action})

def closed():
    apply(queue('closed'))
    queue_command('closed','CloseQueue')
    wait(lambda:get('queue','closed',ns=False).get('status',{}).get('state')=='Closed')
    # 关闭队列会被 admission 拒绝，不能把拒绝误判成 Pending。
    p=k('create','-f','-',obj=job('closed',q='closed'),check=False)
    (OUT/CASE/'admission.log').write_text(p.stderr)
    assert p.returncode and 'closed' in p.stderr.lower(), p.stderr
    queue_command('closed','OpenQueue')
    wait(lambda:get('queue','closed',ns=False).get('status',{}).get('state')=='Open')
    apply(job('closed',q='closed'))
    wait(lambda:len(running('closed'))==1)

def preempt():
    for name,val in [('lab-low',10),('lab-high',100)]:
        apply({'apiVersion':'scheduling.k8s.io/v1','kind':'PriorityClass','metadata':{'name':name},'value':val,'globalDefault':False})
    apply(job('low',n=4,minimum=1,cpu='5',priorityClassName='lab-low'))
    wait(lambda:len(running('low'))==4)
    apply(job('high',cpu='5',priorityClassName='lab-high'))
    wait(lambda:len(running('high'))==1)
    assert len(running('low'))<4

def reclaim():
    apply(queue('borrower',deserved={'cpu':'10'},capability={'cpu':'24'}))
    apply(queue('owner',deserved={'cpu':'10'},capability={'cpu':'24'}))
    apply(job('borrow',n=4,minimum=1,cpu='5',q='borrower'))
    wait(lambda:len(running('borrow'))==4)
    apply(job('owner',n=2,cpu='5',q='owner'))
    wait(lambda:len(running('owner'))==2)
    assert len(running('borrow'))<=2

def binpack():
    apply(job('packed',n=4,cpu='1'))
    wait(lambda:len(running('packed'))==4)
    assert len({p['spec']['nodeName'] for p in running('packed')})==1

def affinity():
    o=job('spread',n=2)
    t=o['spec']['tasks'][0]['template']
    t['metadata']['labels']={'app':'spread-test'}
    t['spec']['affinity']={'podAntiAffinity':{'requiredDuringSchedulingIgnoredDuringExecution':[{'labelSelector':{'matchLabels':{'app':'spread-test'}},'topologyKey':'kubernetes.io/hostname'}]}}
    apply(o)
    wait(lambda:len(running('spread'))==2)
    assert len({p['spec']['nodeName'] for p in running('spread')})==2

def plugins():
    apply(job('plugins',n=2,plugins={'env':[],'svc':[],'ssh':[]}))
    wait(lambda:len(running('plugins'))==2)
    p=running('plugins')[0]['metadata']['name']
    env=k('-n',NS,'exec',p,'--','env')
    (OUT/CASE/'env.log').write_text(env)
    assert 'VC_TASK_INDEX=' in env
    assert get('service','plugins')['spec']['clusterIP']=='None'
    assert get('secrets')['items']

def abort():
    apply(job('abort',command=['sh','-c','exit 7'],policies=[{'event':'PodFailed','action':'AbortJob'}]))
    wait(lambda:get('jobs.batch.volcano.sh','abort').get('status',{}).get('state',{}).get('phase')=='Aborted')

def ttl():
    apply(job('ttl',command=['true'],ttlSecondsAfterFinished=5))
    wait(lambda:get('jobs.batch.volcano.sh','ttl').get('status',{}).get('state',{}).get('phase')=='Completed')
    wait(lambda:not any(x['metadata']['name']=='ttl' for x in get('jobs.batch.volcano.sh')['items']))

def gpu_basic():
    apply(job('gpu',gpu={'number':1,'memory':3000,'cores':25}))
    wait(lambda:len(running('gpu'))==1)
    p=running('gpu')[0]
    env=k('-n',NS,'exec',p['metadata']['name'],'--','env')
    (OUT/CASE/'env.log').write_text(env)
    assert 'CUDA_DEVICE_MEMORY_LIMIT_0=3000m' in env and 'CUDA_DEVICE_SM_LIMIT=25' in env,env
    assert 'volcano.sh/vgpu-ids-new' in p['metadata']['annotations'],p['metadata']['annotations']

def gpu_reject(which):
    req={'number':1,'memory':3000,'cores':25}
    req[which]={'number':3,'memory':50000,'cores':101}[which]
    apply(job('reject',gpu=req,node='volcano-lab-worker'))
    pending('reject',1)

def gpu_share():
    apply(job('share',n=3,gpu={'number':1,'memory':3000,'cores':20},node='volcano-lab-worker'))
    wait(lambda:len(running('share'))==3)
    allocations=[p['metadata']['annotations']['volcano.sh/vgpu-ids-new'] for p in running('share')]
    (OUT/CASE/'allocations.json').write_text(json.dumps(allocations,indent=2))
    assert len(set(allocations))==1,allocations

def gpu_spread():
    apply(job('gpu-spread',n=2,gpu={'number':1,'memory':3000,'cores':20},node='volcano-lab-worker',annotations={'volcano.sh/vgpu-podgroup-policy':'spread'}))
    wait(lambda:len(running('gpu-spread'))==2)
    a=[p['metadata']['annotations']['volcano.sh/vgpu-ids-new'] for p in running('gpu-spread')]
    assert len(set(a))==2,a

def gpu_full():
    apply(job('full',n=2,gpu={'number':1,'memory':40000,'cores':100},node='volcano-lab-worker'))
    wait(lambda:len(running('full'))==2)
    apply(job('waiting',gpu={'number':1,'memory':1000,'cores':1},node='volcano-lab-worker'))
    pending('waiting',1)
    delete_job('full')
    wait(lambda:len(running('waiting'))==1)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--only',default='')
    args=parser.parse_args()
    k('create','namespace',NS,check=False)
    tests=[('01-job-completion',complete,'proportion'),('02-gang-release',gang,None),
           ('03-elastic-minavailable',elastic,None),('04-queue-capability',quota,None),
           ('05-queue-close-open',closed,None),('06-priority-preemption',preempt,None),
           ('07-capacity-borrow-reclaim',reclaim,'capacity'),('08-binpack',binpack,'proportion'),
           ('09-pod-antiaffinity',affinity,None),('10-env-svc-ssh',plugins,None),
           ('11-failure-abort',abort,None),('12-ttl-cleanup',ttl,None),
           ('13-vgpu-allocation',gpu_basic,None),('14-vgpu-sharing',gpu_share,None),
           ('15-vgpu-device-spread',gpu_spread,None),('16-vgpu-memory-reject',lambda:gpu_reject('memory'),None),
           ('17-vgpu-core-reject',lambda:gpu_reject('cores'),None),('18-vgpu-count-reject',lambda:gpu_reject('number'),None),
           ('19-vgpu-release',gpu_full,None)]
    for name,fn,mode in tests:
        if not args.only or any(name.startswith(x) for x in args.only.split(',')):
            case(name,fn,mode)
    clean()
    raise SystemExit(any(r['status']=='FAIL' for r in RESULTS))
