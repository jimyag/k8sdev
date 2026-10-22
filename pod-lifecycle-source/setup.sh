#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export TMPDIR="$PWD/tmp/pod-lifecycle/build-tmp"
export KUBECONFIG="$PWD/tmp/pod-lifecycle/kubeconfig"
mkdir -p "$TMPDIR"
kind create cluster --name pod-lifecycle --image kindest/node:pod-lifecycle-v1.37.1 \
  --config pod-lifecycle-source/kind.yaml --kubeconfig "$KUBECONFIG" --wait 180s
kubectl wait --for=condition=Ready nodes --all --timeout=180s
docker image inspect python:3.12-alpine >/dev/null
kind load docker-image python:3.12-alpine --name pod-lifecycle
kubectl -n local-path-storage rollout status deployment/local-path-provisioner --timeout=180s
