import importlib.util,json,time
spec=importlib.util.spec_from_file_location('s','run-tests.py');t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
t.OUT=t.ROOT/'evidence'/'cuda-control';t.OUT.mkdir(exist_ok=True);t.case='cuda-without-hami-hook'
p=json.loads((t.ROOT/'evidence/final/cuda-vectoradd-input.json').read_text());p['metadata']['name']='cuda-control';p['spec']['containers'][0]['env'].append({'name':'CUDA_DISABLE_CONTROL','value':'true'})
(t.OUT/'input.json').write_text(json.dumps(p,indent=2));t.cmd(['kubectl','apply','-f','-'],json.dumps(p));end=time.monotonic()+60
while time.monotonic()<end:
 q=t.obj('cuda-control')
 if q['status'].get('phase') in ['Failed','Succeeded']:break
 time.sleep(1)
t.save('cuda-control');log=t.k('logs','cuda-control');print(log)
t.k('delete','pod','cuda-control','--wait=true')
