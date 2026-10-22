#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
root="$PWD"
lab="$root/tmp/pod-lifecycle"
export TMPDIR="$lab/build-tmp"
mkdir -p "$TMPDIR" "$lab/gocache" "$lab/bin" "$lab/package/kubernetes/server/bin"
release=v1.37.1
commit=f78e722310e50bcaca9276be22276d9e91d91308
base="${BASE_IMAGE:-kindest/base:v20260820-69b56db7}"
if [[ ! -d "$lab/kubernetes/.git" ]]; then
  git clone --depth 1 --branch "$release" https://github.com/kubernetes/kubernetes.git "$lab/kubernetes"
fi
test "$(git -C "$lab/kubernetes" rev-parse HEAD)" = "$commit"
if ! git -C "$lab/kubernetes" apply --unidiff-zero --reverse --check "$root/pod-lifecycle-source/instrumentation.patch" 2>/dev/null; then
  git -C "$lab/kubernetes" diff --exit-code
  git -C "$lab/kubernetes" apply --unidiff-zero --check "$root/pod-lifecycle-source/instrumentation.patch"
  git -C "$lab/kubernetes" apply --unidiff-zero "$root/pod-lifecycle-source/instrumentation.patch"
fi
docker run --rm --cpus 8 -v "$lab:/lab" -w /lab/kubernetes \
  -e TMPDIR=/lab/build-tmp -e GOCACHE=/lab/gocache -e CGO_ENABLED=0 golang:1.27.1 \
  go build -buildvcs=false -p 8 -mod=vendor \
  -ldflags="-X k8s.io/component-base/version.gitVersion=$release -X k8s.io/component-base/version.gitMajor=1 -X k8s.io/component-base/version.gitMinor=37 -X k8s.io/component-base/version.gitCommit=$commit -X k8s.io/component-base/version.gitTreeState=dirty" \
  -o /lab/bin/ ./cmd/kube-apiserver ./cmd/kube-controller-manager ./cmd/kube-scheduler ./cmd/kubelet ./cmd/kube-proxy ./cmd/kubeadm ./cmd/kubectl

# 使用原生 kind tarball builder；附加镜像一并打包，减少构建节点时的拉取。
images=(registry.k8s.io/coredns/coredns:v1.14.6 registry.k8s.io/etcd:3.7.0-0 registry.k8s.io/pause:3.10
  docker.io/kindest/kindnetd:v20260820-69b56db7
  docker.io/kindest/local-path-provisioner:v20260820-69b56db7
  docker.io/kindest/local-path-helper:v20260131-7181c60a)
for image in "${images[@]}"; do
  source="$image"
  if [[ "$image" == registry.k8s.io/* && -n "${K8S_MIRROR:-}" ]]; then
    source="$K8S_MIRROR/${image#registry.k8s.io/}"
  elif [[ "$image" == docker.io/* && -n "${DOCKER_MIRROR:-}" ]]; then
    source="$DOCKER_MIRROR/${image#docker.io/}"
  fi
  docker pull "$source"
  if [[ "$source" != "$image" ]]; then docker tag "$source" "$image"; fi
done
for component in kube-apiserver kube-controller-manager kube-scheduler kube-proxy; do
  docker build --build-arg "BASE_IMAGE=$base" --build-arg "COMPONENT=$component" \
    -f pod-lifecycle-source/component.Dockerfile -t "registry.k8s.io/$component:$release" "$lab/bin"
  extra=()
  if [[ "$component" == kube-apiserver ]]; then extra=("${images[@]}"); fi
  docker save -o "$lab/package/kubernetes/server/bin/$component.tar" "registry.k8s.io/$component:$release" "${extra[@]}"
done
cp "$lab/bin/kubeadm" "$lab/bin/kubelet" "$lab/bin/kubectl" "$lab/package/kubernetes/server/bin/"
printf '%s\n' "$release" > "$lab/package/kubernetes/version"
tar -czf "$lab/kubernetes-server-linux-amd64.tar.gz" -C "$lab/package" kubernetes
kind build node-image --type file --base-image "$base" --image kindest/node:pod-lifecycle-v1.37.1 "$lab/kubernetes-server-linux-amd64.tar.gz"
