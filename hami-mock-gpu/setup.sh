#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
: "${HAMI_LAB_DIR:?Set HAMI_LAB_DIR to an empty experiment directory}"
for tool in docker kind kubectl helm git python3; do
  command -v "$tool" >/dev/null || { echo "Missing: $tool" >&2; exit 1; }
done
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || {
  echo 'This reproduction targets Linux amd64.' >&2; exit 1;
}
clusters=$(kind get clusters)
if [[ $'\n'$clusters$'\n' == *$'\nhami-test\n'* ]]; then
  echo 'Cluster hami-test already exists; use it or remove it explicitly.' >&2
  exit 1
fi
mkdir -p "$HAMI_LAB_DIR"
HAMI_LAB_DIR=$(cd "$HAMI_LAB_DIR" && pwd)
if [[ -n $(ls -A "$HAMI_LAB_DIR") ]]; then
  echo "Directory must be empty: $HAMI_LAB_DIR" >&2; exit 1
fi
export HAMI_LAB_DIR KUBECONFIG="$HAMI_LAB_DIR/kubeconfig"
cd "$HAMI_LAB_DIR"
mkdir -p src evidence
cp "$SCRIPT_DIR"/*.yaml .

git clone https://github.com/NVIDIA/k8s-test-infra.git src/k8s-test-infra
git -C src/k8s-test-infra checkout --detach 874ab0319732981bc79cbc9b01c22c8fd00656e6
git clone --depth 1 --branch v2.10.0 https://github.com/Project-HAMi/HAMi.git src/HAMi
[[ $(git -C src/HAMi rev-parse HEAD) == 4707fb02c91c545bc7343ce26dba4c32919f9a3e ]]

docker build -t hami-test/nvml-mock:main \
  -f src/k8s-test-infra/deployments/nvml-mock/Dockerfile \
  src/k8s-test-infra 2>&1 | tee evidence/build-mock.log
docker build -t hami-test/kind-nvidia:local \
  src/k8s-test-infra/deployments/kind-nvidia-cdi 2>&1 | tee evidence/build-kind.log
kind create cluster --name hami-test --image hami-test/kind-nvidia:local \
  --config kind.yaml 2>&1 | tee evidence/cluster-create.log
for img in projecthami/hami:v2.10.0 ubuntu:22.04 \
  nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0; do
  docker pull "$img"
done
kind load docker-image --name hami-test hami-test/nvml-mock:main \
  projecthami/hami:v2.10.0 ubuntu:22.04 \
  nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0

MOCK_CHART=src/k8s-test-infra/deployments/nvml-mock/helm/nvml-mock
sed 's/GPU-12345678/GPU-22345678/g' "$MOCK_CHART/profiles/a100.yaml" > worker2-a100.yaml
helm upgrade --install nvml-mock "$MOCK_CHART" -n mock-system --create-namespace \
  -f mock-worker1-values.yaml --wait --timeout 180s
helm upgrade --install nvml-mock-worker2 "$MOCK_CHART" -n mock-system \
  -f mock-worker2-values.yaml --set-file gpu.customConfig=worker2-a100.yaml \
  --wait --timeout 180s
helm upgrade --install hami src/HAMi/charts/hami -n hami-system --create-namespace \
  -f hami-values.yaml --wait --timeout 240s
kubectl --context kind-hami-test create namespace hami-tests
kubectl --context kind-hami-test get nodes -o wide
echo "Ready. Use KUBECONFIG=$KUBECONFIG and run the test scripts from $SCRIPT_DIR."
