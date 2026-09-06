import importlib.util,json,time
spec=importlib.util.spec_from_file_location('final','run-final-tests.py');f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f);t=f.t
t.OUT=t.ROOT/'evidence'/'advanced';t.OUT.mkdir(exist_ok=True)
def implicit():
 p=json.loads((t.ROOT/'evidence/matrix/02-webhook-allocation-runtime-basic-input.json').read_text());p['metadata']['name']='implicit-gpu';del p['spec']['containers'][0]['resources']['limits']['nvidia.com/gpu']
 (t.OUT/'implicit-input.json').write_text(json.dumps(p,indent=2));t.cmd(['kubectl','apply','-f','-'],json.dumps(p));t.active.append('implicit-gpu');p=t.ready('implicit-gpu')
 assert p['spec']['containers'][0]['resources']['limits']['nvidia.com/gpu']=='1' and len(t.alloc(p))==1
 return 'Webhook adds gpu=1 when only gpumem/gpucores are requested'
def defaults():
 p=t.ready(t.pod('default-gpu',mem=None,cores=None,node=t.W1));a=t.alloc(p)
 assert a[0][2]=='40960';return {'allocation':a,'meaning':'GPU count alone receives full device memory'}
def scaling():
 chart=str(t.ROOT/'src/HAMi/charts/hami');values=str(t.ROOT/'hami-values.yaml')
 def helm(extra):
  out=t.cmd(['helm','upgrade','hami',chart,'-n','hami-system','-f',values,*extra,'--wait','--timeout','120s']);(t.OUT/('helm-scale.log' if extra else 'helm-restore.log')).write_text(out)
 def waitmem(want):
  end=time.monotonic()+65
  while time.monotonic()<end:
   p=json.loads(t.cmd(['kubectl','get','node',t.W1,'-o','json']));ds=json.loads(p['metadata']['annotations']['hami.io/node-nvidia-register'])
   if all(d['devmem']==want for d in ds):return
   time.sleep(1)
  raise AssertionError('Registration memory did not converge')
 try:
  helm(['--set','devicePlugin.deviceMemoryScaling=2']);waitmem(81920)
  p=t.ready(t.pod('oversub',mem=61440,node=t.W1));assert t.alloc(p)[0][2]=='61440';t.delete('oversub')
  return '2x scaling advertises 81920 MiB and admits 61440 MiB on physical 40960 MiB; scheduling only, no real memory allocation'
 finally:
  for n in t.active[:]:t.save(n);t.delete(n)
  helm([]);waitmem(40960)
t.check('30-implicit-gpu',implicit)
t.check('31-default-full-memory',defaults)
t.check('32-memory-oversubscription',scaling)
