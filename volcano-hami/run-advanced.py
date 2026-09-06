#!/usr/bin/env python3
"""补充队列、拓扑、原生工作负载与控制器行为实验。"""
import copy
import importlib.util
import json
from pathlib import Path
import time

spec=importlib.util.spec_from_file_location('lab',Path(__file__).with_name('run-tests.py'))
t=importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)

def nodegroup():
    t.config(extra=[{'name':'nodegroup','arguments':{'strict':False}}])
    t.k('label','node','volcano-lab-worker','volcano.sh/nodegroup-name=team-a','--overwrite')
    t.k('label','node','volcano-lab-worker2','volcano.sh/nodegroup-name=team-b','--overwrite')
    t.apply(t.queue('team-a',affinity={'nodeGroupAffinity':{'requiredDuringSchedulingIgnoredDuringExecution':['team-a']}}))
    t.apply(t.job('nodegroup',n=2,q='team-a'))
    t.wait(lambda:len(t.running('nodegroup'))==2)
    assert {p['spec']['nodeName'] for p in t.running('nodegroup')}=={'volcano-lab-worker'}

def hypernode():
    t.config(extra=[{'name':'network-topology-aware'}])
    for name,node in [('rack-a','volcano-lab-worker'),('rack-b','volcano-lab-worker2')]:
        t.apply({'apiVersion':'topology.volcano.sh/v1alpha1','kind':'HyperNode','metadata':{'name':name},
                 'spec':{'tier':1,'members':[{'type':'Node','selector':{'exactMatch':{'name':node}}}]}})
    t.apply({'apiVersion':'topology.volcano.sh/v1alpha1','kind':'HyperNode','metadata':{'name':'fabric'},
             'spec':{'tier':2,'members':[{'type':'HyperNode','selector':{'exactMatch':{'name':n}}} for n in ['rack-a','rack-b']]}})
    t.apply(t.job('topo',n=3,cpu='5',networkTopology={'mode':'hard','highestTierAllowed':1}))
    t.pending('topo',3)
    t.snapshot()
    t.delete_job('topo')
    t.apply(t.job('topo',n=3,cpu='5',networkTopology={'mode':'hard','highestTierAllowed':2}))
    t.wait(lambda:len(t.running('topo'))==3)
    assert len({p['spec']['nodeName'] for p in t.running('topo')})==2
    (t.OUT/t.CASE/'hypernodes.json').write_text(t.k('get','hypernodes','-o','json'))

def task_topology():
    t.config(extra=[{'name':'task-topology','arguments':{'task-topology.weight':100}}])
    o=t.job('task-topology',n=1)
    b=copy.deepcopy(o['spec']['tasks'][0]); b['name']='peer'
    o['spec']['tasks'].append(b); o['spec']['minAvailable']=2
    o['metadata']['annotations']={'volcano.sh/task-topology-anti-affinity':'worker,peer','volcano.sh/task-topology-task-order':'worker,peer'}
    t.apply(o)
    t.wait(lambda:len(t.running('task-topology'))==2)
    assert len({p['spec']['nodeName'] for p in t.running('task-topology')})==2

def native():
    t.config()
    p=t.job('native')['spec']['tasks'][0]['template']
    p['metadata']['annotations']={'scheduling.volcano.sh/queue-name':'lab'}
    p['spec']['schedulerName']='volcano'
    p['spec']['restartPolicy']='Always'
    t.apply({'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'native','namespace':t.NS},
             'spec':{'replicas':2,'selector':{'matchLabels':{'app':'native'}},'template':{**p,'metadata':{**p['metadata'],'labels':{'app':'native'}}}}})
    try:
        t.wait(lambda:get_ready()==2)
        assert all(p['spec'].get('nodeName') for p in t.pods())
        t.snapshot()
    finally:
        t.k('-n',t.NS,'delete','deployment','native','--wait=true')

def get_ready(): return t.get('deployment','native').get('status',{}).get('readyReplicas',0)

def restart():
    t.apply(t.job('restart',n=2,policies=[{'event':'PodEvicted','action':'RestartJob'}]))
    t.wait(lambda:len(t.running('restart'))==2)
    before={p['metadata']['uid'] for p in t.running('restart')}
    t.k('-n',t.NS,'delete','pod',t.running('restart')[0]['metadata']['name'],'--wait=true')
    t.wait(lambda:len(t.running('restart'))==2 and before.isdisjoint({p['metadata']['uid'] for p in t.running('restart')}))
    assert t.get('jobs.batch.volcano.sh','restart')['status'].get('version',0)>=1

def dependency():
    o=t.job('dependency',command=['sh','-c','sleep 4; echo first'],minimum=1)
    b=copy.deepcopy(o['spec']['tasks'][0]); b['name']='second';b['dependsOn']={'name':['worker']}
    b['template']['spec']['containers'][0]['command']=['sh','-c','echo second']
    o['spec']['tasks'].append(b)
    t.apply(o)
    t.wait(lambda:t.get('jobs.batch.volcano.sh','dependency').get('status',{}).get('state',{}).get('phase')=='Completed')
    pp=t.pods('dependency')
    assert len(pp)==2
    first=next(p for p in pp if p['metadata']['name'].endswith('worker-0'))
    second=next(p for p in pp if p['metadata']['name'].endswith('second-0'))
    assert second['status']['startTime']>=first['status']['startTime']

def cron():
    t.apply({'apiVersion':'batch.volcano.sh/v1alpha1','kind':'CronJob','metadata':{'name':'cron','namespace':t.NS},
             'spec':{'schedule':'* * * * *','concurrencyPolicy':'Forbid','jobTemplate':{'spec':t.job('unused',command=['true'])['spec']}}})
    try:
        t.wait(lambda:any(j.get('status',{}).get('state',{}).get('phase')=='Completed' for j in t.get('jobs.batch.volcano.sh')['items']),90)
        (t.OUT/t.CASE/'cron.json').write_text(t.k('-n',t.NS,'get','cronjobs.batch.volcano.sh','-o','json'))
    finally: t.k('-n',t.NS,'delete','cronjobs.batch.volcano.sh','cron')

def flow():
    for n in ['step-a','step-b']:
        t.apply({'apiVersion':'flow.volcano.sh/v1alpha1','kind':'JobTemplate','metadata':{'name':n,'namespace':t.NS},
                 'spec':t.job(n,command=['sh','-c','sleep 2; echo finished'])['spec']})
    t.apply({'apiVersion':'flow.volcano.sh/v1alpha1','kind':'JobFlow','metadata':{'name':'flow','namespace':t.NS},
             'spec':{'jobRetainPolicy':'retain','flows':[{'name':'step-a'},{'name':'step-b','dependsOn':{'targets':['step-a']}}]}})
    try:
        t.wait(lambda:sum(j.get('status',{}).get('state',{}).get('phase')=='Completed' for j in t.get('jobs.batch.volcano.sh')['items'])==2)
        (t.OUT/t.CASE/'flow.json').write_text(t.k('-n',t.NS,'get','jobflows','-o','json'))
    finally:
        t.k('-n',t.NS,'delete','jobflows,jobtemplates','--all')

def drf():
    t.config()
    t.k('-n','volcano-system','scale','deployment/volcano-scheduler','--replicas=0')
    t.wait(lambda:not json.loads(t.k('-n','volcano-system','get','pods','-l','app=volcano-scheduler','-o','json'))['items'])
    try:
        t.apply(t.job('fair-a',n=4,minimum=1,cpu='5'))
        t.apply(t.job('fair-b',n=4,minimum=1,cpu='5'))
    finally:t.k('-n','volcano-system','scale','deployment/volcano-scheduler','--replicas=1')
    t.wait(lambda:len(t.running('fair-a'))+len(t.running('fair-b'))==4)
    assert len(t.running('fair-a'))==2 and len(t.running('fair-b'))==2

def metrics():
    services=json.loads(t.k('-n','volcano-system','get','svc','-o','json'))['items']
    (t.OUT/t.CASE/'services.json').write_text(json.dumps(services,indent=2))
    svc=next(s for s in services if 'scheduler' in s['metadata']['name'])
    port=svc['spec']['ports'][0]['port']
    data=t.k('get','--raw',f'/api/v1/namespaces/volcano-system/services/{svc["metadata"]["name"]}:{port}/proxy/metrics')
    (t.OUT/t.CASE/'metrics.prom').write_text(data)
    assert 'volcano_' in data

def gpu_device_policy():
    t.config(gpu_policy='spread',gpu_weight=100)
    t.apply(t.job('node-spread',n=2,gpu={'number':1,'memory':3000,'cores':20}))
    t.wait(lambda:len(t.running('node-spread'))==2 or any(p.get('status',{}).get('phase')=='Failed' for p in t.pods('node-spread')))
    (t.OUT/t.CASE/'startup-scheduler.log').write_text(t.k('-n','volcano-system','logs','deployment/volcano-scheduler'))
    assert len(t.running('node-spread'))==2
    # spread 给未使用物理卡加分，不保证跨节点；两张空闲卡可能同属一个节点。
    ids={p['metadata']['annotations']['volcano.sh/vgpu-ids-new'].split(',')[0] for p in t.running('node-spread')}
    assert len(ids)==2

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--only',default='');args=p.parse_args()
    tests=[('20-nodegroup',nodegroup),('21-hypernode-hard',hypernode),('22-task-topology',task_topology),
           ('23-native-deployment',native),('24-job-restart',restart),('25-task-dependency',dependency),
           ('26-cronjob',cron),('27-jobflow',flow),('28-drf-fairness',drf),('29-metrics',metrics),('30-vgpu-spread-policy',gpu_device_policy)]
    for name,fn in tests:
        if not args.only or any(name.startswith(x) for x in args.only.split(',')):t.case(name,fn)
    t.clean()
    raise SystemExit(any(r['status']=='FAIL' for r in t.RESULTS))
