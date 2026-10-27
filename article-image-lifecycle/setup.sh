#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
tmp_dir="$repo_root/tmp/article-image"
mkdir -p "$tmp_dir/tools"

kind_bin="${KIND:-$tmp_dir/tools/kind}"
kubectl_bin="${KUBECTL:-$tmp_dir/tools/kubectl}"
kubeconfig="${KUBECONFIG:-$tmp_dir/kubeconfig}"

if [[ ! -x "$kind_bin" ]]; then
  curl -fsSLo "$kind_bin" \
    https://github.com/kubernetes-sigs/kind/releases/download/v0.33.0/kind-linux-amd64
  chmod +x "$kind_bin"
fi
if [[ ! -x "$kubectl_bin" ]]; then
  curl -fsSLo "$kubectl_bin" \
    https://dl.k8s.io/release/v1.35.1/bin/linux/amd64/kubectl
  chmod +x "$kubectl_bin"
fi

export KIND="$kind_bin"
export KUBECTL="$kubectl_bin"
export KUBECONFIG="$kubeconfig"
export PATH="$(dirname "$kind_bin"):$PATH"

if ! "$KIND" get clusters | grep -qx article-image; then
  "$KIND" create cluster --name article-image --image kindest/node:v1.35.1 \
    --config "$repo_root/article-image-lifecycle/kind.yaml" --kubeconfig "$KUBECONFIG"
fi
"$KUBECTL" wait --for=condition=Ready nodes --all --timeout=300s
"$KUBECTL" get nodes -o wide

printf 'KUBECONFIG=%s\nKIND=%s\nKUBECTL=%s\n' "$KUBECONFIG" "$KIND" "$KUBECTL"
