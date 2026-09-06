#!/usr/bin/env bash
# 从固定源码构建独立实验环境，不读取或修改其他集群的 kubeconfig。
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
: "${VOLCANO_LAB_DIR:?Set VOLCANO_LAB_DIR to an empty directory}"
for tool in docker kind kubectl helm git python3 go; do command -v "$tool" >/dev/null; done
python3 -c 'import yaml'
[[ $(uname -sm) == 'Linux x86_64' ]]
if kind get clusters 2>/dev/null | grep -qx volcano-lab; then
  echo 'volcano-lab already exists; refusing to overwrite it.' >&2
  exit 1
fi
mkdir -p "$VOLCANO_LAB_DIR"
[[ -z $(ls -A "$VOLCANO_LAB_DIR") ]]
cd "$VOLCANO_LAB_DIR"
export KUBECONFIG="$PWD/kubeconfig"
mkdir src evidence
cp "$SCRIPT_DIR"/*.yaml "$SCRIPT_DIR"/*.py .
git clone https://github.com/NVIDIA/k8s-test-infra.git src/k8s-test-infra
git -C src/k8s-test-infra checkout --detach 874ab0319732981bc79cbc9b01c22c8fd00656e6
git clone --depth 1 --branch v1.15.0 https://github.com/volcano-sh/volcano.git src/volcano
[[ $(git -C src/volcano rev-parse HEAD) == 8fc394c11e8db0d0ada5c17816b58bced9d7213d ]]
git clone --depth 1 --branch v1.12.0 https://github.com/Project-HAMi/volcano-vgpu-device-plugin.git src/volcano-vgpu-device-plugin
[[ $(git -C src/volcano-vgpu-device-plugin rev-parse HEAD) == afefcc2ff7944e9e68275e83217cf5eb7fb4a585 ]]
# 不使用发布镜像或旧构建层，包含所固定主分支提交中的修复。
docker build --no-cache -t volcano-lab/nvml-mock:874ab03 \
  -f src/k8s-test-infra/deployments/nvml-mock/Dockerfile src/k8s-test-infra 2>&1 | tee evidence/build-mock.log
docker build -t volcano-lab/kind-nvidia:local src/k8s-test-infra/deployments/kind-nvidia-cdi 2>&1 | tee evidence/build-kind.log
kind create cluster --name volcano-lab --image volcano-lab/kind-nvidia:local \
  --config kind.yaml --kubeconfig "$KUBECONFIG" 2>&1 | tee evidence/cluster-create.log
images=(volcanosh/vc-controller-manager:v1.15.0 volcanosh/vc-scheduler:v1.15.0 \
  volcanosh/vc-webhook-manager:v1.15.0 projecthami/volcano-vgpu-device-plugin:v1.12.0 ubuntu:22.04)
for img in "${images[@]}"; do docker pull "$img"; done
kind load docker-image --name volcano-lab volcano-lab/nvml-mock:874ab03 "${images[@]}"
chart=src/k8s-test-infra/deployments/nvml-mock/helm/nvml-mock
helm upgrade --install mock1 "$chart" -n mock-system --create-namespace \
  -f mock-worker1-values.yaml --wait --timeout 180s
# 每个节点的物理 UUID 必须不同。
{ echo '# 第二个 worker 的模拟设备属性；修改 UUID 前缀以保持跨节点唯一。';
  sed 's/GPU-12345678/GPU-22345678/g' "$chart/profiles/a100.yaml"; } > worker2-a100.yaml
helm upgrade --install mock2 "$chart" -n mock-system -f mock-worker2-values.yaml \
  --set-file gpu.customConfig=worker2-a100.yaml --wait --timeout 180s
helm upgrade --install volcano src/volcano/installer/helm/chart/volcano \
  -n volcano-system --create-namespace -f volcano-values.yaml --wait --timeout 180s
python3 prepare-plugin.py src/volcano-vgpu-device-plugin/volcano-vgpu-device-plugin.yml vgpu-plugin.yaml
kubectl --context kind-volcano-lab apply -f vgpu-plugin.yaml
kubectl --context kind-volcano-lab -n kube-system rollout status ds/volcano-device-plugin --timeout=180s
# 重新加载 device-config 中的显存粒度；测试脚本也会显式重启调度器。
kubectl --context kind-volcano-lab -n volcano-system rollout restart deployment/volcano-scheduler
kubectl --context kind-volcano-lab -n volcano-system rollout status deployment/volcano-scheduler --timeout=90s
kubectl --context kind-volcano-lab get nodes -o json > evidence/nodes.json
