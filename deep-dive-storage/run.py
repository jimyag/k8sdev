import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deep-dive-common'))
from lab import Lab,pod,k,wait

l=Lab('storage')
driver=json.loads(k('get','pod','csi-hostpathplugin-0','-o','json').stdout)
node=driver['spec']['nodeName']
k('wait','--for=condition=Ready','pod/csi-hostpathplugin-0','--timeout=300s')
l.save('driver',driver)
for name,mode in [('dd-immediate','Immediate'),('dd-delayed','WaitForFirstConsumer')]:
    l.apply({'apiVersion':'storage.k8s.io/v1','kind':'StorageClass','metadata':{'name':name},
             'provisioner':'hostpath.csi.k8s.io','volumeBindingMode':mode,'reclaimPolicy':'Delete'})
def pvc(name,sc='dd-immediate',access='ReadWriteOnce'):
    return {'apiVersion':'v1','kind':'PersistentVolumeClaim','metadata':{'name':name},
      'spec':{'storageClassName':sc,'accessModes':[access],'resources':{'requests':{'storage':'64Mi'}}}}
def consumer(name,claim):
    p=pod(name,nodeSelector={'kubernetes.io/hostname':node},volumes=[{'name':'data','persistentVolumeClaim':{'claimName':claim}}])
    p['spec']['containers'][0]['volumeMounts']=[{'name':'data','mountPath':'/data'}]
    return p
l.apply(pvc('disk'))
wait(lambda:l.get('pvc','disk').get('status',{}).get('phase')=='Bound')
p=consumer('first','disk')
# PVC 已绑定，但另一个缺失的 Secret 仍能阻止容器启动。
p['spec']['volumes'].append({'name':'config','secret':{'secretName':'missing'}})
p['spec']['containers'][0]['volumeMounts'].append({'name':'config','mountPath':'/config'})
l.apply(p)
wait(lambda:any(e.get('reason')=='FailedMount' for e in l.get('events')['items']))
l.save('bound-before-running',{'pvc':l.get('pvc','disk'),'pod':l.get('pod','first')})
l.apply({'apiVersion':'v1','kind':'Secret','metadata':{'name':'missing'},'stringData':{'value':'ok'}})
l.ready('first')
l.exec('first','python','-c',"from pathlib import Path; Path('/data/proof').write_text('persistent')")
l.apply(consumer('second','disk')); l.ready('second')
assert l.exec('second','cat','/data/proof').stdout=='persistent'
l.save('rwo-two-pods',l.get('pods'))
l.save('attachments',json.loads(k('get','volumeattachments','-o','json').stdout))
k('delete','pod','first','-n',l.ns,'--wait=true')
assert l.exec('second','cat','/data/proof').stdout=='persistent'
l.apply(pvc('late','dd-delayed'))
wait(lambda:any(e.get('reason')=='WaitForFirstConsumer' for e in l.get('events')['items']))
l.save('delayed-before-consumer',l.get('pvc','late'))
assert l.get('pvc','late')['status']['phase']=='Pending'
l.apply(consumer('late','late')); l.ready('late')
l.save('delayed-after-consumer',l.get('pvc','late'))
l.apply(pvc('exclusive',access='ReadWriteOncePod'))
l.apply(consumer('exclusive-one','exclusive')); l.ready('exclusive-one')
l.apply(consumer('exclusive-two','exclusive'))
wait(lambda:any(c['type']=='PodScheduled' and c['status']=='False' for c in l.get('pod','exclusive-two')['status'].get('conditions',[])))
l.snapshot('rwop-blocked')
l.save('driver-rpc-log',{'text':k('logs','csi-hostpathplugin-0','-c','hostpath','--tail=350').stdout})
l.save('result',{'rwo_same_node_two_pods':True,'rwop_second_pod_blocked':True,'bound_not_running':True,'delayed_binding':True})
