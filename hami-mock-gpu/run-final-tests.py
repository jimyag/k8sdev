import importlib.util,json,time
spec=importlib.util.spec_from_file_location('suite','run-tests.py');t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
t.OUT=t.ROOT/'evidence'/'final';t.OUT.mkdir(exist_ok=True)
def metrics():
 t.ready(t.pod('metrics',node=t.W1,ann={'nvidia.com/use-gpuuuid':t.U0}))
 path='/api/v1/namespaces/hami-system/services/'
 def scrape():return t.cmd(['kubectl','get','--raw',path+'hami-scheduler:31993/proxy/metrics'])
 def value(s):return [float(l.rsplit(' ',1)[1]) for l in s.splitlines() if l.startswith('hami_gpu_memory_allocated_bytes{') and t.U0 in l]
 end=time.monotonic()+40
 while time.monotonic()<end:
  s=scrape()
  if value(s)==[4096*1024**2]:break
  time.sleep(1)
 (t.OUT/'scheduler-allocated.prom').write_text(s);assert value(s)==[4096*1024**2],value(s)
 d=t.cmd(['kubectl','get','--raw',path+'hami-device-plugin-monitor:31992/proxy/metrics']);(t.OUT/'monitor.prom').write_text(d)
 assert 'hami_build_info' in d and 'hami_host_gpu_memory_used_bytes' in d,d[:1000]
 t.delete('metrics');end=time.monotonic()+40
 while time.monotonic()<end:
  s=scrape()
  if value(s)==[0]:break
  time.sleep(1)
 (t.OUT/'scheduler-released.prom').write_text(s);assert value(s)==[0]
 return 'Observed exact 4 GiB allocation, monitor GPU metrics, and zero after deletion; waited for metrics cache refresh'
def view(index):
 uuid=[t.U0,t.U1][index];n=f'view{index}'
 p=t.ready(t.pod(n,node=t.W1,ann={'nvidia.com/use-gpuuuid':uuid}))
 r=t.cmd(['kubectl','-n',t.NS,'exec',n,'--','env','MOCK_NVML_CONFIG=/etc/nvml-mock/config.yaml','LIBCUDA_LOG_LEVEL=4','nvidia-smi','--query-gpu=index,uuid,memory.total','--format=csv,noheader'],check=False)
 (t.OUT/f'{n}-query.log').write_text(r.stdout+r.stderr)
 assert r.returncode==0 and '4096 MiB' in r.stdout,r.stdout
 return r.stdout

def quota():
 q={'apiVersion':'v1','kind':'ResourceQuota','metadata':{'name':'gpu-quota','namespace':t.NS},'spec':{'hard':{'requests.nvidia.com/gpu':'1','requests.nvidia.com/gpumem':'8192'}}}
 t.cmd(['kubectl','apply','-f','-'],json.dumps(q))
 try:
  t.ready(t.pod('quota-holder'))
  src=json.loads((t.OUT/f'{t.case}-quota-holder-input.json').read_text());src['metadata']['name']='quota-overflow'
  r=t.cmd(['kubectl','apply','-f','-'],json.dumps(src),check=False)
  (t.OUT/'quota-rejection.txt').write_text(r.stdout+r.stderr)
  assert r.returncode!=0 and 'quota' in (r.stdout+r.stderr).lower(),r
  (t.OUT/'quota.json').write_text(t.k('get','resourcequota','gpu-quota','-o','json'))
  return 'Namespace request quota rejects second GPU Pod'
 finally:t.k('delete','resourcequota','gpu-quota')

def cuda():
 src=json.loads((t.ROOT/'evidence/matrix/02-webhook-allocation-runtime-basic-input.json').read_text());src['metadata']['name']='cuda-vectoradd';src['spec']['restartPolicy']='Never'
 c=src['spec']['containers'][0];c['image']='nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0';c.pop('command');c['env']=[{'name':'MOCK_CUDA_DEBUG','value':'1'}]
 (t.OUT/'cuda-vectoradd-input.json').write_text(json.dumps(src,indent=2));t.cmd(['kubectl','apply','-f','-'],json.dumps(src));t.active.append('cuda-vectoradd')
 end=time.monotonic()+60
 while time.monotonic()<end:
  p=t.obj('cuda-vectoradd')
  if p['status'].get('phase') in ['Failed','Succeeded']:break
  time.sleep(1)
 p=t.save('cuda-vectoradd');log=t.k('logs','cuda-vectoradd');assert p['status'].get('phase')=='Succeeded',log
 return log

if __name__=='__main__':
 t.check('26-monitoring-rechecked',metrics)
 t.check('27a-nvml-index0',lambda:view(0))
 t.check('27b-nvml-index1',lambda:view(1))
 t.check('28-namespace-quota',quota)
 t.check('29-cuda-vectoradd',cuda)
