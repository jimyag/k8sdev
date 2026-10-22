import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deep-dive-common'))
from lab import Lab,deployment,k,wait

l=Lab('pdb')
l.apply(deployment('app',replicas=2)); l.rollout('app')
l.apply({'apiVersion':'policy/v1','kind':'PodDisruptionBudget','metadata':{'name':'keep-two'},
 'spec':{'minAvailable':2,'selector':{'matchLabels':{'app':'app'}}}})
wait(lambda: l.get('pdb','keep-two').get('status',{}).get('currentHealthy')==2)
l.save('budget',l.get('pdb','keep-two'))
name=l.pods('app')[0]['metadata']['name']
eviction={'apiVersion':'policy/v1','kind':'Eviction','metadata':{'name':name,'namespace':l.ns}}
r=k('create','--raw',f'/api/v1/namespaces/{l.ns}/pods/{name}/eviction','-f','-',data=json.dumps(eviction),check=False)
assert r.returncode and 'disruption budget' in r.stderr.lower()
l.save('eviction-denied',{'code':r.returncode,'stderr':r.stderr})
k('delete','pod',name,'-n',l.ns,'--wait=true')
l.rollout('app')
l.save('direct-delete',{'old_name':name,'new_names':[p['metadata']['name'] for p in l.pods('app')]})
assert name not in [p['metadata']['name'] for p in l.pods('app')]
l.patch('deployment','app',{'spec':{'template':{'metadata':{'annotations':{'lab.example.com/revision':'2'}}}}})
l.rollout('app')
l.snapshot('rollout-complete')
l.save('result',{'eviction_blocked':True,'direct_delete_completed':True,'deployment_rollout_completed':True})

# 让一个副本失去 readiness，比较默认策略与 AlwaysAllow。
l.patch('deployment','app',{'spec':{'template':{'spec':{'containers':[{'name':'app','image':'python:3.12-alpine',
 'command':['python','-c','import time; time.sleep(3600)'],
 'readinessProbe':{'exec':{'command':['python','-c',"import pathlib,sys; sys.exit(pathlib.Path('/unhealthy').exists())"]},'periodSeconds':2,'failureThreshold':1}}]}}}})
l.rollout('app')
wait(lambda:l.get('pdb','keep-two').get('status',{}).get('currentHealthy')==2)
unhealthy=l.pods('app')[0]['metadata']['name']
l.exec(unhealthy,'touch','/unhealthy')
wait(lambda:l.get('pdb','keep-two')['status']['currentHealthy']==1)
eviction['metadata']['name']=unhealthy
endpoint=f'/api/v1/namespaces/{l.ns}/pods/{unhealthy}/eviction'
r=k('create','--raw',endpoint,'-f','-',data=json.dumps(eviction),check=False)
assert r.returncode and 'disruption budget' in r.stderr.lower()
l.save('unhealthy-default-denied',{'stderr':r.stderr,'budget':l.get('pdb','keep-two')})
l.patch('pdb','keep-two',{'spec':{'unhealthyPodEvictionPolicy':'AlwaysAllow'}})
k('create','--raw',endpoint,'-f','-',data=json.dumps(eviction))
k('wait','-n',l.ns,'--for=delete','pod/'+unhealthy,'--timeout=60s')
l.rollout('app')
l.save('unhealthy-always-allow',{'old_pod':unhealthy,'evicted':True,'budget':l.get('pdb','keep-two')})
