import importlib.util, json, time
spec=importlib.util.spec_from_file_location('suite','run-tests.py'); t=importlib.util.module_from_spec(spec); spec.loader.exec_module(t)
t.OUT=t.ROOT/'evidence'/'extra'; t.OUT.mkdir(exist_ok=True)
def plain():
 p={'apiVersion':'v1','kind':'Pod','metadata':{'name':'plain','namespace':t.NS},'spec':{'terminationGracePeriodSeconds':0,'containers':[{'name':'cpu','image':'ubuntu:22.04','command':['sleep','3600']}]}}
 t.cmd(['kubectl','apply','-f','-'],json.dumps(p)); t.active.append('plain'); p=t.ready('plain')
 assert p['spec']['schedulerName']=='default-scheduler' and not p['spec'].get('runtimeClassName')
 assert not t.alloc(p); return 'CPU-only Pod remains on default-scheduler'
def node():
 p=t.ready(t.pod('node-selected',node=t.W2)); assert p['spec']['nodeName']==t.W2
 assert t.alloc(p)[0][0].startswith('GPU-22345678'); return t.alloc(p)
t.check('24-cpu-only-webhook',plain)
t.check('25-node-selection',node)
