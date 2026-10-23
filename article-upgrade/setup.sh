#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
repo_root="$PWD"
export TMPDIR="$repo_root/tmp/article-upgrade"
export KUBECONFIG="$TMPDIR/kubeconfig"
mkdir -p "$TMPDIR/bin" article-upgrade/evidence
export PATH="$repo_root/tmp/article-tools:$HOME/.local/bin:$PATH"
test "$(hostname)" = zj
mkdir -p "$repo_root/tmp/article-tools"
curl -fsSL https://dl.k8s.io/release/v1.35.1/bin/linux/amd64/kubectl -o "$repo_root/tmp/article-tools/kubectl"
expected="$(curl -fsSL https://dl.k8s.io/release/v1.35.1/bin/linux/amd64/kubectl.sha256)"
actual="$(sha256sum "$repo_root/tmp/article-tools/kubectl")"
test "${actual%% *}" = "$expected"
chmod +x "$repo_root/tmp/article-tools/kubectl"
kubectl version --client -o json
if kind get clusters | grep -Fxq article-upgrade; then
  echo '专用集群已存在，请先检查并按 README 清理后重建。' >&2
  exit 1
fi
for binary in kubeadm kubelet kubectl; do
  curl -fsSL "https://dl.k8s.io/release/v1.35.2/bin/linux/amd64/$binary" -o "$TMPDIR/bin/$binary"
  curl -fsSL "https://dl.k8s.io/release/v1.35.2/bin/linux/amd64/$binary.sha256" -o "$TMPDIR/bin/$binary.sha256"
  expected="$(cat "$TMPDIR/bin/$binary.sha256")"
  actual="$(sha256sum "$TMPDIR/bin/$binary")"
  test "${actual%% *}" = "$expected"
  chmod +x "$TMPDIR/bin/$binary"
done
kind create cluster --name article-upgrade --image kindest/node:v1.35.1 \
  --config article-upgrade/kind.yaml --kubeconfig "$KUBECONFIG" --wait 180s
kubectl --context kind-article-upgrade wait --for=condition=Ready nodes --all --timeout=180s
kubectl --context kind-article-upgrade version -o json
