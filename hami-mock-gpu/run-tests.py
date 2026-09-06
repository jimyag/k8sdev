#!/usr/bin/env python3
import json, os, pathlib, subprocess, time, traceback
ROOT=pathlib.Path(os.environ['HAMI_LAB_DIR']).resolve()
os.environ['KUBECONFIG']=str(ROOT/'kubeconfig')
os.environ['PATH']=str(ROOT/'bin')+':'+os.environ['PATH']
NS='hami-tests'; W1='hami-test-worker'; W2='hami-test-worker2'
U0='GPU-12345678-1234-1234-1234-123456780000'; U1=U0[:-1]+'1'
OUT=ROOT/'evidence'/'matrix'; OUT.mkdir(exist_ok=True)
results=[]; case=''; active=[]
def cmd(args, data=None, check=True):
 p=subprocess.run(args,input=data,text=True,capture_output=True,timeout=150)
 if check and p.returncode: raise RuntimeError(f'{args}: {p.stderr} {p.stdout}')
 return p.stdout if check else p

def k(*args): return cmd(['kubectl','--context','kind-hami-test','-n',NS,*args])
def obj(name): return json.loads(k('get','pod',name,'-o','json'))
def save(name):
 p=obj(name); (OUT/f'{case}-{name}.json').write_text(json.dumps(p,indent=2))
 (OUT/f'{case}-{name}-events.json').write_text(k('get','events','--field-selector',f'involvedObject.name={name}','-o','json'))
 for c in p['spec']['containers']:
  r=cmd(['kubectl','-n',NS,'logs',name,'-c',c['name']],check=False)
  (OUT/f'{case}-{name}-{c["name"]}.log').write_text(r.stdout+r.stderr)
 return p

def alloc(p):
 s=p['metadata'].get('annotations',{}).get('hami.io/vgpu-devices-allocated','')
 return [d.split(',') for group in s.split(';') for d in group.split(':') if d]
def ready(name):
 end=time.monotonic()+80
 while time.monotonic()<end:
  p=obj(name)
  if p['status'].get('phase')=='Running' and all(c.get('ready') for c in p['status'].get('containerStatuses',[])) and p['status'].get('containerStatuses'): return save(name)
  time.sleep(1)
 save(name); raise AssertionError(f'{name} not Ready')
def pending(name):
 end=time.monotonic()+35
 while time.monotonic()<end:
  p=obj(name)
  assert not p['spec'].get('nodeName'), f'{name} unexpectedly scheduled'
  ev=json.loads(k('get','events','--field-selector',f'involvedObject.name={name}','-o','json'))['items']
  if any(e.get('reason')=='FailedScheduling' for e in ev):
   time.sleep(3); p=save(name); assert not p['spec'].get('nodeName'); return p
  time.sleep(1)
 save(name); raise AssertionError('No FailedScheduling event')

def pod(name,mem=4096,cores=25,gpus=1,node=None,ann=None,pct=None,containers=1):
 limits={'nvidia.com/gpu':gpus}
 if mem is not None: limits['nvidia.com/gpumem']=mem
 if pct is not None: limits['nvidia.com/gpumem-percentage']=pct
 if cores is not None: limits['nvidia.com/gpucores']=cores
 cs=[{'name':f'gpu{i}','image':'ubuntu:22.04','command':['bash','-c','env | sort; ls -l /dev/nvidia*; nvidia-smi -L; exec sleep 3600'], 'resources':{'limits':limits},'volumeMounts':[{'name':'mock-cuda','mountPath':'/usr/lib/x86_64-linux-gnu/libcuda.so.1','readOnly':True}]} for i in range(containers)]
 p={'apiVersion':'v1','kind':'Pod','metadata':{'name':name,'namespace':NS,'annotations':ann or {}},'spec':{'terminationGracePeriodSeconds':0,'containers':cs,'volumes':[{'name':'mock-cuda','hostPath':{'path':'/var/lib/nvml-mock/driver/usr/lib64/libcuda.so.1','type':'File'}}]}}
 if node: p['spec']['nodeSelector']={'kubernetes.io/hostname':node}
 (OUT/f'{case}-{name}-input.json').write_text(json.dumps(p,indent=2))
 cmd(['kubectl','-n',NS,'apply','-f','-'],json.dumps(p))
 active.append(name); return name

def delete(name):
 k('delete','pod',name,'--wait=true','--timeout=30s'); active.remove(name)
def check(test,fn):
 global case
 case=test; start=time.monotonic()
 try:
  detail=fn(); status='PASS'
 except Exception as e:
  detail=str(e); status='FAIL'; traceback.print_exc()
 finally:
  for name in active[:]:
   try: save(name); delete(name)
   except Exception as e: print('cleanup',e,flush=True)
 results.append({'case':case,'status':status,'detail':detail,'seconds':round(time.monotonic()-start,1)})
 (OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print(json.dumps(results[-1],ensure_ascii=False),flush=True)
 time.sleep(2)

def base():
 ns=json.loads(cmd(['kubectl','get','nodes','-o','json']))['items']
 ids=[]
 for n in ns:
  if n['metadata']['name'] not in (W1,W2):continue
  assert n['status']['allocatable']['nvidia.com/gpu']=='20'
  ds=json.loads(n['metadata']['annotations']['hami.io/node-nvidia-register']); assert len(ds)==2
  assert all(d['devmem']==40960 and d['health'] and d['count']==10 for d in ds)
  ids += [d['id'] for d in ds]
 assert len(set(ids))==4
 return '2 nodes x 2 unique A100 40960 MiB; each node advertises 20 shares'
def basic():
 p=ready(pod('basic')); a=alloc(p); assert len(a)==1 and a[0][2:]==['4096','25']
 assert p['spec']['schedulerName']=='hami-scheduler' and p['spec']['runtimeClassName']=='nvidia'
 s=k('exec','basic','--','bash','-c','cat /etc/ld.so.preload; echo "$CUDA_DEVICE_MEMORY_LIMIT_0 $CUDA_DEVICE_SM_LIMIT"; MOCK_NVML_CONFIG=/etc/nvml-mock/config.yaml nvidia-smi --query-gpu=uuid,memory.total --format=csv,noheader')
 (OUT/'basic-runtime.txt').write_text(s)
 assert '4096m 25' in s and 'libvgpu.so' in s
 return s

def shared():
 aa=[]
 for i in range(3): aa.append(alloc(ready(pod(f'share{i}',node=W1,ann={'nvidia.com/use-gpuuuid':U0})))[0][0])
 assert aa==[U0]*3
 return '3 Running pods share one physical UUID'
def multi():
 p=ready(pod('multi',gpus=2,node=W1)); a=alloc(p)
 assert len(a)==2 and len({d[0] for d in a})==2 and all(d[2:]==['4096','25'] for d in a)
 s=k('exec','multi','--','env','MOCK_NVML_CONFIG=/etc/nvml-mock/config.yaml','nvidia-smi','-L'); (OUT/'multi-smi.txt').write_text(s); assert s.count('UUID:')==2
 return a
def percent():
 a=alloc(ready(pod('percent',mem=None,pct=25)))[0]; assert a[2]=='10240'; return a

def reject(kind):
 kwargs={'node':W1}
 if kind=='memory':kwargs.update(mem=40961)
 if kind=='cores':
  p=ready(pod('core-clamp',cores=101,node=W1)); assert alloc(p)[0][3]=='100'
  s=k('exec','core-clamp','--','printenv','CUDA_DEVICE_SM_LIMIT'); assert s.strip()=='100'
  return 'gpucores=101 is clamped to 100 by HAMi, matching device.go Fit implementation'
 if kind=='cards':kwargs.update(gpus=3)
 pending(pod('reject-'+kind,**kwargs)); return 'FailedScheduling; nodeName absent'
def budget(resource):
 kw={'node':W1,'ann':{'nvidia.com/use-gpuuuid':U0}}
 if resource=='memory': kw.update(mem=30000,cores=10)
 else: kw.update(mem=1024,cores=60)
 ready(pod('holder',**kw))
 if resource=='memory':kw['mem']=12000
 else:kw['cores']=50
 pending(pod('blocked',**kw)); delete('holder'); p=ready('blocked'); return 'Blocked while budget exhausted; scheduled automatically after holder deletion: '+str(alloc(p))
def exclusive():
 kw={'node':W1,'ann':{'nvidia.com/use-gpuuuid':U0}}
 ready(pod('exclusive',mem=None,pct=100,cores=100,**kw)); pending(pod('blocked',mem=1,cores=1,**kw)); return '100% memory and cores exclude a second request on same UUID'
def select(key,value,expected=None,negative=False):
 n=pod('selection',node=W1,ann={key:value})
 if negative: pending(n); return 'rejected with FailedScheduling'
 p=ready(n); ids=[d[0] for d in alloc(p)]
 if expected:assert ids==[expected]
 return ids

def policy(scope,policy):
 ps=[]
 for i in range(2):
  ps.append(ready(pod(f'policy{i}',node=W1 if scope=='gpu' else None,ann={f'hami.io/{scope}-scheduler-policy':policy})))
 values=[p['spec']['nodeName'] if scope=='node' else alloc(p)[0][0] for p in ps]
 assert (values[0]==values[1]) == (policy=='binpack'),values
 return values

def multicontainer():
 p=ready(pod('two-containers',containers=2,node=W1)); a=alloc(p)
 assert len(a)==2 and len(p['status']['containerStatuses'])==2
 return a

def slots():
 kw={'node':W1,'ann':{'nvidia.com/use-gpuuuid':U0},'mem':64,'cores':1}
 for i in range(10):ready(pod(f'slot{i}',**kw))
 pending(pod('slot-overflow',**kw)); delete('slot0'); ready('slot-overflow'); return '10 shares accepted, 11th blocked, deletion releases share'

def restart():
 p=ready(pod('survivor',node=W1)); uid=p['metadata']['uid']; a=alloc(p)
 for resource in ['deployment/hami-scheduler','daemonset/hami-device-plugin']:
  cmd(['kubectl','-n','hami-system','rollout','restart',resource]); cmd(['kubectl','-n','hami-system','rollout','status',resource,'--timeout=100s'])
 p=ready('survivor'); assert p['metadata']['uid']==uid and alloc(p)==a
 assert all(c['restartCount']==0 for c in p['status']['containerStatuses'])
 ready(pod('after-restart')); return 'Existing Pod allocation survives; new Pod schedules after scheduler and plugin restart'

if __name__=='__main__':
 k('delete','pod','--all','--wait=true','--timeout=40s')
 check('01-device-registration',base)
 check('02-webhook-allocation-runtime',basic)
 check('03-share-one-gpu',shared)
 check('04-multi-gpu',multi)
 check('05-memory-percentage',percent)
 for i,r in enumerate(['memory','cores','cards'],6):check(f'{i:02d}-'+('core-clamp' if r=='cores' else 'reject-'+r),lambda r=r:reject(r))
 check('09-memory-budget-reclaim',lambda:budget('memory'))
 check('10-core-budget-reclaim',lambda:budget('cores'))
 check('11-exclusive',exclusive)
 check('12-type-allow',lambda:select('nvidia.com/use-gputype','A100'))
 check('13-type-mismatch',lambda:select('nvidia.com/use-gputype','T4',negative=True))
 check('14-type-deny',lambda:select('nvidia.com/nouse-gputype','A100',negative=True))
 check('15-uuid-allow',lambda:select('nvidia.com/use-gpuuuid',U1,expected=U1))
 check('16-uuid-deny',lambda:select('nvidia.com/nouse-gpuuuid',U0,expected=U1))
 for i,(s,p) in enumerate([('gpu','binpack'),('gpu','spread'),('node','binpack'),('node','spread')],17):check(f'{i}-{s}-{p}',lambda s=s,p=p:policy(s,p))
 check('21-multi-container',multicontainer)
 check('22-share-count-reclaim',slots)
 check('23-restart-recovery',restart)
 print('SUMMARY',len(results),'cases;',sum(x['status']=='PASS' for x in results),'PASS',flush=True)
