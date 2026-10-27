#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
tmp_dir="$repo_root/tmp/article-next"
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

if ! "$KIND" get clusters | grep -qx article-next; then
  "$KIND" create cluster --name article-next --image kindest/node:v1.35.1 \
    --config "$repo_root/article-next-common/kind.yaml" --kubeconfig "$KUBECONFIG"
fi

"$KUBECTL" get nodes -o wide
"$KUBECTL" wait --for=condition=Ready nodes --all --timeout=300s

for image in alpine:3.20 python:3.12-alpine; do
  docker pull "$image"
  "$KIND" load docker-image "$image" --name article-next
done

csi_dir="$tmp_dir/csi-driver-host-path"
if [[ ! -d "$csi_dir/.git" ]]; then
  git clone --depth 1 --branch v1.19.0 \
    https://github.com/kubernetes-csi/csi-driver-host-path.git "$csi_dir"
fi

for resource in volumesnapshotclasses volumesnapshotcontents volumesnapshots; do
  "$KUBECTL" apply -f \
    "https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/v8.7.0/client/config/crd/snapshot.storage.k8s.io_${resource}.yaml"
done
bash "$csi_dir/deploy/kubernetes-1.35/deploy.sh" >/dev/null
"$KUBECTL" rollout status statefulset/csi-hostpathplugin --timeout=300s

printf 'KUBECONFIG=%s\nKIND=%s\nKUBECTL=%s\n' "$KUBECONFIG" "$KIND" "$KUBECTL"
