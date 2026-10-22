import sys,json,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deep-dive-common'))
from lab import Lab,k

l=Lab('reconcile')
l.apply({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'desired'},'data':{'value':'one'}})
cached=l.get('configmap','desired')
l.patch('configmap','desired',{'data':{'value':'two'}})
stale=copy.deepcopy(cached); stale['data']['value']='stale-write'
r=k('replace','-n',l.ns,'-f','-',data=json.dumps(stale),check=False)
assert r.returncode and 'Conflict' in r.stderr
l.save('stale-update',{'cached_value':cached['data']['value'],'current_value':l.get('configmap','desired')['data']['value'],'error':r.stderr})
attempts=[]
def reconcile(crash=False):
    # 事件仅用于入队；调谐时读取当前值。外部资源用 ConfigMap 模拟，名称绑定 UID。
    desired=l.get('configmap','desired')
    name='effect-'+desired['metadata']['uid']
    obj={'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':name,'labels':{'app':'effect'}},'data':desired['data']}
    r=k('create','-n',l.ns,'-f','-',data=json.dumps(obj),check=False)
    if r.returncode:
        assert 'AlreadyExists' in r.stderr,r.stderr
        l.patch('configmap',name,{'data':desired['data']})
    attempts.append({'created':r.returncode==0,'name':name,'value':desired['data']['value'],'crash_before_ack':crash})
    if crash: return
    l.patch('configmap','desired',{'metadata':{'annotations':{'lab.example.com/observed':desired['data']['value']}}})
reconcile(crash=True)
reconcile()
reconcile()
effects=[c for c in l.get('configmaps')['items'] if c['metadata'].get('labels',{}).get('app')=='effect']
assert len(effects)==1 and effects[0]['data']['value']=='two'
l.save('attempts',attempts)
l.save('objects',l.get('configmaps'))
l.save('result',{'attempts':len(attempts),'effects':len(effects),'final_value':'two','note':'人工重复入队并模拟操作后未确认；不是 client-go 缓存延迟测量'})
