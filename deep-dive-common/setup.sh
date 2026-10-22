#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
repo_root="$PWD"
mkdir -p tmp/k8s-deep-dive
export TMPDIR="$repo_root/tmp/k8s-deep-dive"
export KUBECONFIG="$TMPDIR/kubeconfig"

# 只创建本系列专用集群，避免覆盖默认 kubeconfig。
kind create cluster --name deep-dive --image kindest/node:v1.35.1 \
  --config deep-dive-common/kind.yaml --kubeconfig "$KUBECONFIG"
curl -fsSL https://raw.githubusercontent.com/projectcalico/calico/v3.31.2/manifests/calico.yaml -o "$TMPDIR/calico.yaml"
kubectl apply -f "$TMPDIR/calico.yaml"
kubectl wait --for=condition=Ready nodes --all --timeout=600s
kubectl rollout status daemonset/calico-node -n kube-system --timeout=600s
kubectl rollout status deployment/calico-kube-controllers -n kube-system --timeout=600s
docker pull python:3.12-alpine
kind load docker-image python:3.12-alpine --name deep-dive

# 官方测试驱动只用于观察 CSI 调用，不能作为生产存储方案。
git clone --depth 1 --branch v1.17.0 https://github.com/kubernetes-csi/csi-driver-host-path.git "$TMPDIR/csi-hostpath"
for resource in volumesnapshotclasses volumesnapshotcontents volumesnapshots; do
  kubectl apply -f "https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v8.2.0/client/config/crd/snapshot.storage.k8s.io_${resource}.yaml"
done
bash "$TMPDIR/csi-hostpath/deploy/kubernetes-1.30/deploy.sh"

curl -fsSL https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.8.0/components.yaml -o "$TMPDIR/metrics-server.yaml"
kubectl apply -f "$TMPDIR/metrics-server.yaml"
# kind kubelet 使用测试证书；仅在此隔离实验集群跳过证书校验。
kubectl patch deployment metrics-server -n kube-system --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
kubectl rollout status deployment/metrics-server -n kube-system --timeout=300s
kubectl wait --for=condition=Available apiservice/v1beta1.metrics.k8s.io --timeout=180s
printf 'KUBECONFIG=%s\n' "$KUBECONFIG"
