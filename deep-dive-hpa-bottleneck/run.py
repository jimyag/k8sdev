import sys,json,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deep-dive-common'))
from lab import Lab,pod,deployment,service,SERVER,wait,k,CTX

l=Lab('hpa-bottleneck')
# 单线程下游每个请求固定处理 0.2 秒，服务能力约为 5 请求/秒。
l.apply(deployment('backend',SERVER.replace('http.server.ThreadingHTTPServer','http.server.HTTPServer')))
l.apply(service('backend')); l.rollout('backend')
front=SERVER.replace("if self.path == '/proxy':", "if self.path == '/proxy':\n   end=time.thread_time()+0.01\n   while time.thread_time()<end: pass")
d=deployment('frontend',front)
c=d['spec']['template']['spec']['containers'][0]
c['env']=[{'name':'BACKEND','value':'http://backend:8080'}]
c['resources']={'requests':{'cpu':'5m'},'limits':{'cpu':'500m'}}
l.apply(d); l.apply(service('frontend')); l.rollout('frontend')
l.apply(pod('client')); l.ready('client')
load='''import concurrent.futures,time,urllib.request,json
end=time.monotonic()+DURATION
def worker(_):
 n=0; errors=0; times=[]
 while time.monotonic()<end:
  t=time.monotonic()
  try:
   with urllib.request.urlopen('http://frontend:8080/proxy',timeout=15) as r: r.read()
   n+=1; times.append(time.monotonic()-t)
  except Exception: errors+=1
 return n,errors,times
t=time.monotonic()
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool: rows=list(pool.map(worker,range(8)))
elapsed=time.monotonic()-t; times=sorted(x for row in rows for x in row[2])
print(json.dumps({'requests':sum(r[0] for r in rows),'errors':sum(r[1] for r in rows),'elapsed':elapsed,'rps':sum(r[0] for r in rows)/elapsed,'p50':times[len(times)//2],'p95':times[int(len(times)*.95)]}))
'''
l.save('one-replica-load',json.loads(l.exec('client','python','-c',load.replace('DURATION','20')).stdout))
l.apply({'apiVersion':'autoscaling/v2','kind':'HorizontalPodAutoscaler','metadata':{'name':'frontend'},'spec':{
 'scaleTargetRef':{'apiVersion':'apps/v1','kind':'Deployment','name':'frontend'},'minReplicas':1,'maxReplicas':4,
 'metrics':[{'type':'Resource','resource':{'name':'cpu','target':{'type':'Utilization','averageUtilization':50}}}]}})
proc=subprocess.Popen(['kubectl','--context',CTX,'exec','-n',l.ns,'client','--','python','-c',load.replace('DURATION','100')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
try:
    wait(lambda:l.get('deployment','frontend').get('status',{}).get('readyReplicas',0)==4,150)
    l.save('scaled-hpa',l.get('hpa','frontend')); l.save('scaled-deployment',l.get('deployment','frontend'))
finally:
    out,err=proc.communicate(timeout=150)
    if proc.returncode: raise RuntimeError(err)
l.save('during-scaling-load',json.loads(out))
l.save('four-replica-load',json.loads(l.exec('client','python','-c',load.replace('DURATION','20')).stdout))
l.snapshot('finished')
