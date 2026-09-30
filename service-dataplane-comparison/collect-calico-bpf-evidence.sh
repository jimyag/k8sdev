#!/usr/bin/env bash
set -euo pipefail

cluster=svc-calico-bpf
context=kind-svc-calico-bpf
image=python:3.13.7-alpine3.22

echo "===== cluster=$cluster ====="
kind load docker-image "$image" --name "$cluster"

kubectl --context "$context" label node \
  "$cluster-control-plane" \
  service-lab/backend- \
  service-lab/client- >/dev/null 2>&1 || true
kubectl --context "$context" label node \
  "$cluster-worker" \
  service-lab/backend=true \
  service-lab/client- \
  --overwrite >/dev/null
kubectl --context "$context" label node \
  "$cluster-worker2" \
  service-lab/backend=true \
  service-lab/client=true \
  --overwrite >/dev/null

kubectl --context "$context" apply -f 01-service.yaml
kubectl --context "$context" -n service-dataplane rollout status \
  daemonset/echo-server --timeout=120s
kubectl --context "$context" -n service-dataplane wait \
  --for=condition=Ready pod/client --timeout=120s

echo '-- Calico and kube-proxy replacement status --'
kubectl --context "$context" get tigerastatus calico ippools kubeproxy-monitor
kubectl --context "$context" get installation default \
  -o jsonpath='linuxDataplane={.spec.calicoNetwork.linuxDataplane}{" bpfNetworkBootstrap="}{.spec.calicoNetwork.bpfNetworkBootstrap}{" kubeProxyManagement="}{.spec.calicoNetwork.kubeProxyManagement}{"\n"}'
kubectl --context "$context" get felixconfiguration default \
  -o jsonpath='bpfEnabled={.spec.bpfEnabled}{" bpfConnectTimeLoadBalancing="}{.spec.bpfConnectTimeLoadBalancing}{"\n"}'

echo '-- kube-proxy DaemonSet --'
kubectl --context "$context" -n kube-system get daemonset kube-proxy -o wide

echo '-- service and endpoints --'
kubectl --context "$context" -n service-dataplane get service echo-server -o wide
kubectl --context "$context" -n service-dataplane get endpointslice \
  -l kubernetes.io/service-name=echo-server -o wide

echo '-- twelve new ClusterIP connections --'
kubectl --context "$context" -n service-dataplane exec client -- python -c '
from urllib.request import urlopen
for _ in range(12):
    print(urlopen("http://echo-server/hostname").read().decode().strip())
'

echo '-- source IP observed by backend --'
client_ip=$(kubectl --context "$context" -n service-dataplane get pod client \
  -o jsonpath='{.status.podIP}')
observed=$(kubectl --context "$context" -n service-dataplane exec client -- python -c \
  'from urllib.request import urlopen; print(urlopen("http://echo-server/clientip").read().decode(), end="")')
echo "client_ip=$client_ip backend_observed=$observed"

calico_node=$(kubectl --context "$context" -n calico-system get pod \
  -l k8s-app=calico-node \
  --field-selector "spec.nodeName=$cluster-worker2" \
  -o jsonpath='{.items[0].metadata.name}')

echo '-- Calico BPF NAT table --'
kubectl --context "$context" -n calico-system exec "$calico_node" \
  -c calico-node -- calico-node -bpf nat dump

echo '-- legacy kube-proxy service chains on worker --'
if docker exec "$cluster-worker2" iptables-save -t nat | grep -E 'KUBE-SVC|KUBE-SEP'; then
  true
else
  echo 'no KUBE-SVC or KUBE-SEP chains'
fi
