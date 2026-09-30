#!/usr/bin/env bash
set -euo pipefail

# 本脚本在 m6 上运行，并要求当前 kubeconfig 包含 kind-svc-iptables。
kubectl config use-context kind-svc-iptables >/dev/null
docker pull python:3.13.7-alpine3.22 >/dev/null
docker pull curlimages/curl:8.15.0 >/dev/null
kind load docker-image python:3.13.7-alpine3.22 --name svc-iptables
kubectl apply -f 01-source-ip.yaml
kubectl -n service-path rollout status deployment/source-ip-server --timeout=120s
kubectl apply -f 02-clusterip-clients.yaml
kubectl -n service-path wait \
  --for=condition=Ready \
  pod/client-local-node \
  pod/client-remote-node \
  --timeout=120s

endpoint_node=$(kubectl -n service-path get pod \
  -l app.kubernetes.io/name=source-ip-server \
  -o jsonpath='{.items[0].spec.nodeName}')
other_node=svc-iptables-worker2
endpoint_ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$endpoint_node")
other_ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$other_node")

client=service-path-client
docker rm -f "$client" >/dev/null 2>&1 || true
trap 'docker rm -f "$client" >/dev/null 2>&1 || true' EXIT
docker run -d --rm \
  --name "$client" \
  --network kind \
  --entrypoint sleep \
  curlimages/curl:8.15.0 300 >/dev/null
client_ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$client")

wait_for_policy_rules() {
  local policy=$1
  local rules
  for _ in $(seq 1 30); do
    rules=$(docker exec "$endpoint_node" iptables-save -t nat)
    if [[ "$policy" == Local ]] && grep -q 'KUBE-SVL-.*service-path/source-ip' <<<"$rules"; then
      return 0
    fi
    if [[ "$policy" == Cluster ]] && ! grep -q 'KUBE-SVL-.*service-path/source-ip' <<<"$rules"; then
      return 0
    fi
    sleep 1
  done
  echo "timed out waiting for externalTrafficPolicy=$policy rules" >&2
  return 1
}

show_rules() {
  local policy=$1
  echo "iptables rules for externalTrafficPolicy=$policy"
  for node in "$endpoint_node" "$other_node"; do
    echo "node=$node"
    docker exec "$node" iptables-save -t nat |
      grep -E 'service-path/source-ip|KUBE-NODEPORTS|KUBE-MARK-MASQ|KUBE-POSTROUTING'
  done
}

echo "endpoint_node=$endpoint_node endpoint_node_ip=$endpoint_ip"
echo "other_node=$other_node other_node_ip=$other_ip"
echo "client_container=$client client_ip=$client_ip"
echo 'ClusterIP requests from Pods'
for pod in client-local-node client-remote-node; do
  pod_ip=$(kubectl -n service-path get pod "$pod" -o jsonpath='{.status.podIP}')
  observed=$(kubectl -n service-path exec "$pod" -- python -c \
    'from urllib.request import urlopen; print(urlopen("http://source-ip/clientip").read().decode(), end="")')
  echo "pod=$pod pod_ip=$pod_ip backend_observed=$observed"
done
backend_pod=$(kubectl -n service-path get pod \
  -l app.kubernetes.io/name=source-ip-server \
  -o jsonpath='{.items[0].metadata.name}')
backend_pod_ip=$(kubectl -n service-path get pod "$backend_pod" -o jsonpath='{.status.podIP}')
backend_observed=$(kubectl -n service-path exec "$backend_pod" -- python -c \
  'from urllib.request import urlopen; print(urlopen("http://source-ip/clientip").read().decode(), end="")')
echo "pod=$backend_pod pod_ip=$backend_pod_ip self_via_service_observed=$backend_observed"

wait_for_policy_rules Cluster
echo 'externalTrafficPolicy=Cluster'
docker exec "$client" curl -fsS "http://$endpoint_ip:30080/clientip"
docker exec "$client" curl -fsS "http://$other_ip:30080/clientip"
show_rules Cluster

kubectl -n service-path patch service source-ip \
  --type merge \
  -p '{"spec":{"externalTrafficPolicy":"Local"}}' >/dev/null

wait_for_policy_rules Local
echo 'externalTrafficPolicy=Local'
docker exec "$client" curl -fsS "http://$endpoint_ip:30080/clientip"
if docker exec "$client" curl \
  --connect-timeout 2 -fsS "http://$other_ip:30080/clientip"; then
  echo 'unexpected: node without a local endpoint accepted the request' >&2
  exit 1
else
  echo 'expected: node without a local endpoint rejected or dropped the request'
fi
show_rules Local

echo 'service and endpoint state'
kubectl -n service-path get service source-ip -o wide
kubectl -n service-path get endpointslice \
  -l kubernetes.io/service-name=source-ip \
  -o wide

echo 'backend connection log'
kubectl -n service-path logs deployment/source-ip-server --tail=20
