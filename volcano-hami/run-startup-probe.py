#!/usr/bin/env python3
"""区分调度器重启后的首次分配失败与设备心跳更新后的分配。"""
import importlib.util
import json
from pathlib import Path
import time
s=importlib.util.spec_from_file_location('lab',Path(__file__).with_name('run-tests.py'))
t=importlib.util.module_from_spec(s);s.loader.exec_module(t)

def handshakes():
    return {n['metadata']['name']:n['metadata'].get('annotations',{}).get('volcano.sh/node-vgpu-handshake')
            for n in t.get('nodes',ns=False)['items'] if n['metadata'].get('labels',{}).get('gpu')=='on'}

def observe(name):
    t.apply(t.job(name,n=2,gpu={'number':1,'memory':3000,'cores':20}))
    t.wait(lambda:len(t.pods(name))==2 and all(p.get('status',{}).get('phase') in ['Running','Failed'] for p in t.pods(name)),45)
    ps=t.pods(name)
    d=t.OUT/t.CASE
    (d/(name+'-pods.json')).write_text(json.dumps(ps,indent=2))
    (d/(name+'-scheduler.log')).write_text(t.k('-n','volcano-system','logs','deployment/volcano-scheduler'))
    rows=[{'name':p['metadata']['name'],'node':p['spec'].get('nodeName'),'phase':p['status']['phase'],
           'message':p['status'].get('message'),'allocation':p['metadata'].get('annotations',{}).get('volcano.sh/vgpu-ids-new')} for p in ps]
    t.delete_job(name)
    return rows

def probe():
    trials=[]
    for i in range(3):
        t.config(gpu_policy='spread',gpu_weight=100)
        first=observe('early-'+str(i))
        before=handshakes()
        # 等待两个设备插件真实心跳改变 Node 注解，不按猜测固定 sleep。
        t.wait(lambda:all(handshakes().get(n)!=v for n,v in before.items()),45)
        after=observe('after-heartbeat-'+str(i))
        trials.append({'trial':i,'immediate':first,'after_heartbeat':after})
        (t.OUT/t.CASE/'trials.json').write_text(json.dumps(trials,indent=2))
        assert all(x['phase']=='Running' and x['allocation'] for x in after),after
        assert len({x['allocation'].split(',')[0] for x in after})==2,after

if __name__=='__main__':
    t.case('39-restart-heartbeat-probe',probe)
    t.clean()
    raise SystemExit(any(r['status']=='FAIL' for r in t.RESULTS))
