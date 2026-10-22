#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
cluster=pod-network-calico
kind_bin=${KIND_BIN:-$HOME/.local/bin/kind}
mkdir -p ../tmp/pod-network-calico
"$kind_bin" create cluster --name "$cluster" --image kindest/node:v1.35.1 --config kind.yaml
k() { docker exec -i "$cluster-control-plane" kubectl --kubeconfig=/etc/kubernetes/admin.conf "$@"; }
# 宿主机拉取一次，再导入各节点，避免三个 containerd 重复下载。
for image in quay.io/calico/calico:v3.33.0 quay.io/calico/node:v3.33.0 quay.io/calico/third-party-cni-plugins:v3.33.0 python:3.12-alpine; do
  docker pull "$image"
  "$kind_bin" load docker-image "$image" --name "$cluster"
done
# kubectl 使用节点内置版本；kustomize 在节点中下载固定发行版清单。
docker cp . "$cluster-control-plane:/root/pod-network-calico"
k kustomize /root/pod-network-calico > ../tmp/pod-network-calico/calico-rendered.yaml
k apply --server-side -f - < ../tmp/pod-network-calico/calico-rendered.yaml
k -n kube-system rollout status daemonset/calico-node --timeout=300s
k wait --for=condition=Ready nodes --all --timeout=180s
k apply -f - < workloads.yaml
k -n pod-network wait --for=condition=Ready pod --all --timeout=180s
# 工具只装进本次 kind 节点，不修改宿主机软件。
for node in "$cluster-worker" "$cluster-worker2"; do
  docker exec "$node" sh -c 'apt-get update -qq && apt-get install -y -qq tcpdump conntrack ipset'
done
