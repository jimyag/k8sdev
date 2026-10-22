import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deep-dive-common'))
from lab import Lab,pod,SERVER,service,wait

l=Lab('network-policy')
for name in ['server','good','other']:
    l.apply(pod(name,SERVER if name=='server' else 'import time; time.sleep(3600)')); l.ready(name)
l.apply(service('server'))
ip=l.get('pod','server')['status']['podIP']
svc=l.get('service','server')['spec']['clusterIP']
def connects(client,host):
    return l.exec(client,'python','-c',f"import urllib.request; print(urllib.request.urlopen('http://{host}:8080',timeout=2).status)",check=False).returncode==0
def policy(name,selector,types,**rules):
    return {'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':name},
      'spec':{'podSelector':{'matchLabels':selector},'policyTypes':types,**rules}}
assert connects('good',ip) and connects('other',ip)
l.apply(policy('deny-server',{'app':'server'},['Ingress']))
wait(lambda: not connects('good',ip))
l.apply(policy('allow-good',{'app':'server'},['Ingress'],ingress=[{'from':[{'podSelector':{'matchLabels':{'app':'good'}}}],
 'ports':[{'protocol':'TCP','port':8080}]}]))
wait(lambda: connects('good',ip))
assert not connects('other',ip)
assert connects('good',svc)
l.save('ingress',{'default_open':True,'default_deny_blocks':True,'good_allowed':True,'other_blocked':True,'service_ip_allowed':True})
l.apply(policy('deny-good-egress',{'app':'good'},['Egress']))
wait(lambda: not connects('good',ip))
l.apply(policy('allow-server-egress',{'app':'good'},['Egress'],egress=[{'to':[{'podSelector':{'matchLabels':{'app':'server'}}}],
 'ports':[{'protocol':'TCP','port':8080}]}]))
wait(lambda: connects('good',ip))
assert not connects('good','server')
# DNS 策略同时约束 kube-system namespace 和 CoreDNS 标签。
l.apply(policy('allow-dns',{'app':'good'},['Egress'],egress=[{'to':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'kube-system'}},
 'podSelector':{'matchLabels':{'k8s-app':'kube-dns'}}}], 'ports':[{'protocol':'UDP','port':53},{'protocol':'TCP','port':53}]}]))
wait(lambda: connects('good','server'))
l.save('egress',{'ingress_alone_insufficient':True,'pod_ip_works_before_dns_rule':True,'dns_works_after_rule':True})
l.save('policies',l.get('networkpolicies'))
