#!/usr/bin/env python3
"""汇总每个编号最新一次执行，保留早期失败摘要；不收集 kubeconfig 或 Secret。"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import yaml

p=argparse.ArgumentParser()
p.add_argument('lab',type=Path)
p.add_argument('output',type=Path)
a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True)
latest={};history=[]
# 以结果文件实际更新时间排序，重跑旧分组时不会被历史修正结果覆盖。
for result in sorted(a.lab.glob('results*/results.json'), key=lambda f: f.stat().st_mtime):
    directory=result.parent.name
    for row in json.loads(result.read_text()):
        item={'round':directory,**row}
        history.append(item)
        latest[row['case'].split('-')[0]]=item

def strip_runtime(obj):
    if isinstance(obj,list):return [strip_runtime(x) for x in obj]
    if not isinstance(obj,dict):return obj
    obj={k:strip_runtime(v) for k,v in obj.items() if k!='managedFields'}
    m=obj.get('metadata')
    if isinstance(m,dict):
        for key in ['resourceVersion','creationTimestamp','uid','generation']:m.pop(key,None)
        m.get('annotations',{}).pop('kubectl.kubernetes.io/last-applied-configuration',None)
    return obj

for key,item in sorted(latest.items()):
    source=a.lab/item['round']/item['case']
    dest=a.output/item['case']
    dest.mkdir(exist_ok=True)
    if source.exists():
        object_names = {yaml.safe_load(f.read_text())['metadata']['name'] for f in source.glob('*.yaml')}
        for f in source.iterdir():
            if not f.is_file():continue
            if f.suffix=='.yaml':
                # 只规范化输入清单的服务端元数据；不改变请求值和调度配置。
                data=strip_runtime(yaml.safe_load(f.read_text()))
                (dest/f.name).write_text('# 实际测试输入；已移除服务端生成的 metadata，便于复现。\n'
                    '# CPU 为核；vgpu-memory 每单位代表 100 MiB；cores 为百分比。\n'
                    +yaml.safe_dump(data,sort_keys=False,allow_unicode=True))
            elif f.name=='events.json':
                data=json.loads(f.read_text())
                data['items'] = [event for event in data.get('items',[]) if any(event.get('involvedObject',{}).get('name','') == n or event.get('involvedObject',{}).get('name','').startswith(n+'-') for n in object_names)]
                data=strip_runtime(data)
                (dest/f.name).write_text(json.dumps(data,ensure_ascii=False,indent=2))
            else:shutil.copy2(f,dest/f.name)
    item['evidence']=item['case']+'/'
(a.output/'summary.json').write_text(json.dumps(list(latest.values()),ensure_ascii=False,indent=2))
(a.output/'attempts.json').write_text(json.dumps(history,ensure_ascii=False,indent=2))
for name in ['build-mock.log','build-kind.log','cluster-create.log','vgpu-grpc-limit.log',
             'spread-failure.json','upstream-unit.log','upstream-api-controllers.log']:
    f=a.lab/'evidence'/name
    if f.exists():shutil.copy2(f,a.output/name)
versions={'sources':{}}
for name in ['volcano','k8s-test-infra','volcano-vgpu-device-plugin']:
    versions['sources'][name]=subprocess.check_output(['git','-C',str(a.lab/'src'/name),'rev-parse','HEAD'],text=True).strip()
versions['go']=subprocess.check_output(['go','version'],text=True).strip()
images=['volcano-lab/nvml-mock:874ab03','volcano-lab/kind-nvidia:local','volcanosh/vc-scheduler:v1.15.0',
        'volcanosh/vc-controller-manager:v1.15.0','volcanosh/vc-webhook-manager:v1.15.0',
        'projecthami/volcano-vgpu-device-plugin:v1.12.0','ubuntu:22.04']
versions['images']=[{'tag':i,**json.loads(subprocess.check_output(['docker','image','inspect',i,'--format','{{json .}}'],text=True))} for i in images]
versions['images']=[{k:v for k,v in im.items() if k in ['tag','Id','RepoDigests','Architecture','Os']} for im in versions['images']]
(a.output/'versions.json').write_text(json.dumps(versions,indent=2))
print({status:sum(r['status']==status for r in latest.values()) for status in ['PASS','FAIL']})

# 原始日志仍保留在实验目录；提交副本统一换行并去掉无语义的行尾空白。
for log in a.output.rglob('*.log'):
    log.write_text('\n'.join(line.rstrip() for line in log.read_text().splitlines()).rstrip()+'\n')
