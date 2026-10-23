#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/src/github.com/jimyag/k8sdev/tmp/article-tools:$HOME/.local/bin:$PATH"
cd "$(dirname "$0")"
mkdir -p ../tmp/article-control
export TMPDIR="$(cd ../tmp/article-control && pwd)"
export KUBECONFIG="$TMPDIR/kubeconfig"
cluster=article-control
kind create cluster --name "$cluster" --image kindest/node:v1.35.1 --config kind.yaml --kubeconfig "$KUBECONFIG" --wait 180s
kubectl wait node --all --for=condition=Ready --timeout=180s
kubectl create namespace control-ha
kubectl -n control-ha create deployment baseline --image=registry.k8s.io/pause:3.10.1
kubectl -n control-ha rollout status deploy/baseline --timeout=120s
kubectl version -o yaml
kubectl -n kube-system get lease kube-scheduler kube-controller-manager -o custom-columns=NAME:.metadata.name,HOLDER:.spec.holderIdentity
docker pause article-control-control-plane
trap 'docker unpause article-control-control-plane >/dev/null 2>&1 || true' EXIT
deadline=$((SECONDS + 90))
until kubectl --request-timeout=8s -n control-ha create configmap one-node-down --from-literal=result=write-ok; do
  if kubectl --request-timeout=8s -n control-ha get configmap one-node-down; then break; fi
  if (( SECONDS >= deadline )); then echo 'failover write timed out' >&2; exit 1; fi
done
kubectl -n control-ha scale deployment baseline --replicas=2
kubectl -n control-ha rollout status deploy/baseline --timeout=120s
kubectl -n kube-system get lease kube-scheduler kube-controller-manager -o custom-columns=NAME:.metadata.name,HOLDER:.spec.holderIdentity
kubectl -n control-ha get pods -o wide
docker unpause article-control-control-plane
trap - EXIT
kubectl wait node --all --for=condition=Ready --timeout=120s
