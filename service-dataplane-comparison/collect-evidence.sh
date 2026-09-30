#!/usr/bin/env bash
set -euo pipefail

image=python:3.13.7-alpine3.22
docker pull "$image" >/dev/null

for cluster in svc-ipvs svc-nftables; do
  context="kind-$cluster"
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

  echo '-- runtime mode --'
  kubectl --context "$context" -n kube-system get configmap kube-proxy \
    -o jsonpath='{.data.config\.conf}' | grep -E '^(mode:|  scheduler:)'
  kubectl --context "$context" -n kube-system logs daemonset/kube-proxy \
    --tail=120 --prefix | grep -E 'Using .* Proxier|deprecated|scheduler' || true

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

  if [[ "$cluster" == svc-ipvs ]]; then
    echo '-- IPVS virtual servers from /proc/net/ip_vs --'
    docker exec "$cluster-worker" cat /proc/net/ip_vs
    echo '-- kube-ipvs0 addresses --'
    docker exec "$cluster-worker" ip -brief address show kube-ipvs0
    echo '-- IPVS capture rules --'
    docker exec "$cluster-worker" iptables-save -t nat |
      grep -E 'service-dataplane/echo-server|KUBE-NODE-PORT|KUBE-SERVICES' || true
  else
    echo '-- nftables kube-proxy rules for this Service --'
    docker exec "$cluster-worker" nft list table ip kube-proxy |
      grep -E -B2 -A5 'service-dataplane/echo-server|30081'
  fi
done
