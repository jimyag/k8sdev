#!/usr/bin/env python3
"""验证策略负例、层级队列和 admission 边界。"""
import importlib.util
import json
from pathlib import Path
import time
import yaml
spec=importlib.util.spec_from_file_location('lab',Path(__file__).with_name('run-tests.py'))
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)

def weighted():
    t.config()
    t.apply(t.queue('weight-a',weight=1))
    t.apply(t.queue('weight-b',weight=3))
    t.k('-n','volcano-system','scale','deployment/volcano-scheduler','--replicas=0')
    t.k('-n','volcano-system','wait','--for=delete','pod','-l','app=volcano-scheduler','--timeout=40s')
    try:
        t.apply(t.job('weight-a',n=12,minimum=1,cpu='2',q='weight-a'))
        t.apply(t.job('weight-b',n=12,minimum=1,cpu='2',q='weight-b'))
    finally: t.k('-n','volcano-system','scale','deployment/volcano-scheduler','--replicas=1')
    t.wait(lambda:len(t.running('weight-a'))+len(t.running('weight-b'))==10)
    counts={n:len(t.running(n)) for n in ['weight-a','weight-b']}
    (t.OUT/t.CASE/'counts.json').write_text(json.dumps(counts))
    assert counts['weight-b']>counts['weight-a']>0,counts

def namespace_quota():
    t.config(extra=[{'name':'resourcequota'}])
    t.apply({'apiVersion':'v1','kind':'ResourceQuota','metadata':{'name':'cpu','namespace':t.NS},'spec':{'hard':{'requests.cpu':'1'}}})
    try:
        t.apply(t.job('quota',n=2,cpu='1'))
        t.blocked_job('quota')
        assert not t.pods('quota')
        t.snapshot()
    finally: t.k('-n',t.NS,'delete','resourcequota','cpu')
    t.wait(lambda:len(t.running('quota'))==2)

def hierarchy():
    t.config('capacity')
    cm=json.loads(t.k('-n','volcano-system','get','cm','volcano-scheduler-configmap','-o','json'))
    c=yaml.safe_load(cm['data']['volcano-scheduler.conf'])
    for tier in c['tiers']:
        for p in tier['plugins']:
            if p['name']=='capacity':p['enableHierarchy']=True
    cm['data']['volcano-scheduler.conf']=yaml.safe_dump(c,sort_keys=False)
    cm['metadata']={'name':'volcano-scheduler-configmap','namespace':'volcano-system'}
    t.apply(cm)
    t.k('-n','volcano-system','rollout','restart','deployment/volcano-scheduler')
    t.k('-n','volcano-system','rollout','status','deployment/volcano-scheduler','--timeout=90s')
    t.apply(t.queue('parent',capability={'cpu':'6'},deserved={'cpu':'6'}))
    t.apply(t.queue('child-a',parent='parent',capability={'cpu':'6'},deserved={'cpu':'3'}))
    t.apply(t.queue('child-b',parent='parent',capability={'cpu':'6'},deserved={'cpu':'3'}))
    t.apply(t.job('child-a',cpu='4',q='child-a'))
    t.wait(lambda:len(t.running('child-a'))==1)
    t.apply(t.job('child-b',cpu='4',q='child-b'))
    t.blocked_job('child-b')
    t.delete_job('child-a')
    t.wait(lambda:len(t.running('child-b'))==1)

def least_allocated():
    t.config(extra=[{'name':'resource-strategy-fit','arguments':{'resourceStrategyFitWeight':100,'resources':{'cpu':{'type':'LeastAllocated','weight':1}}}}])
    t.apply(t.job('load',cpu='5',node='volcano-lab-worker'))
    t.wait(lambda:len(t.running('load'))==1)
    t.apply(t.job('fit',cpu='1'))
    t.wait(lambda:len(t.running('fit'))==1)
    assert t.running('fit')[0]['spec']['nodeName']=='volcano-lab-worker2'

def backfill():
    t.config()
    t.apply(t.job('large',n=3,cpu='10'))
    t.pending('large',3)
    t.apply(t.job('small',cpu='100m',command=['sh','-c','echo small']))
    t.wait(lambda:t.get('jobs.batch.volcano.sh','small').get('status',{}).get('state',{}).get('phase')=='Completed')
    assert not any(p['spec'].get('nodeName') for p in t.pods('large'))

def invalid():
    o=t.job('invalid',n=1,minimum=2)
    p=t.k('create','-f','-',obj=o,check=False)
    (t.OUT/t.CASE/'admission.log').write_text(p.stderr)
    assert p.returncode and 'minAvailable' in p.stderr,p.stderr

def taints():
    t.k('taint','node','volcano-lab-worker','lab=reserved:NoSchedule','--overwrite')
    try:
        t.apply(t.job('taint',node='volcano-lab-worker'))
        t.pending('taint',1)
        t.snapshot()
        t.delete_job('taint')
        o=t.job('tolerated',node='volcano-lab-worker')
        o['spec']['tasks'][0]['template']['spec']['tolerations']=[{'key':'lab','operator':'Equal','value':'reserved','effect':'NoSchedule'}]
        t.apply(o)
        t.wait(lambda:len(t.running('tolerated'))==1)
    finally:t.k('taint','node','volcano-lab-worker','lab-')

def gpu_nvml():
    t.apply(t.job('nvml',gpu={'number':1,'memory':3000,'cores':25}))
    t.wait(lambda:len(t.running('nvml'))==1)
    p=t.running('nvml')[0]['metadata']['name']
    out=t.k('-n',t.NS,'exec',p,'--','env','MOCK_NVML_CONFIG=/etc/nvml-mock/config.yaml','nvidia-smi','--query-gpu=uuid,memory.total','--format=csv,noheader')
    (t.OUT/t.CASE/'nvidia-smi.log').write_text(out)
    assert 'GPU-' in out
    # 这里只证明 NVML 路径可调用；不把返回值当成真实 CUDA 显存隔离证据。

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--only',default='');args=p.parse_args()
    tests=[('31-weighted-queues',weighted),('32-namespace-quota',namespace_quota),('33-hierarchical-queue',hierarchy),
           ('34-resource-strategy-fit',least_allocated),('35-small-job-progress',backfill),('36-invalid-job',invalid),
           ('37-taint-toleration',taints),('38-nvml-observation',gpu_nvml)]
    for name,fn in tests:
        if not args.only or any(name.startswith(x) for x in args.only.split(',')):t.case(name,fn)
    t.clean()
    raise SystemExit(any(r['status']=='FAIL' for r in t.RESULTS))
