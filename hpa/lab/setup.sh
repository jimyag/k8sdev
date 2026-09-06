#!/usr/bin/env bash
# 任何命令失败立即停止；未设置变量或管道前半段失败也视为错误。
set -euo pipefail
# 以脚本所在目录为基准解析 YAML 和构建上下文，允许从其他目录调用。
cd "$(dirname "$0")"
# 必须由调用者提供专用 kubeconfig，避免修改日常使用的集群配置。
: "${KUBECONFIG:?Set KUBECONFIG to a dedicated lab kubeconfig path}"
# 拒绝覆盖同名集群，保留已有实验状态供检查。
if kind get clusters 2>/dev/null | grep -qx hpa-lab; then
  echo 'hpa-lab already exists; inspect or delete that lab before rerunning setup.' >&2
  exit 1
fi
mkdir -p "$(dirname "$KUBECONFIG")"
# 固定 Kubernetes 节点版本，创建单节点、可删除的实验环境。
kind create cluster --name hpa-lab --image kindest/node:v1.35.0 --kubeconfig "$KUBECONFIG" --wait 120s
# 显式指定实验 context，避免调用者切换当前 context 后误操作其他集群。
k() { kubectl --context kind-hpa-lab "$@"; }
# 构建本机架构的演示程序，再导入 kind；无需推送镜像仓库。
docker build -t hpa-demo:v1 .
kind load docker-image hpa-demo:v1 --name hpa-lab
# 临时下载固定版本的 Metrics Server 清单，退出时删除临时文件。
metrics_manifest=$(mktemp)
trap 'rm -f "$metrics_manifest"' EXIT
curl -fsSL https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.8.1/components.yaml -o "$metrics_manifest"
# 先创建工作负载和采集配置，再安装或更新自定义指标适配器。
k apply -f "$metrics_manifest"
# 仅在本地实验中跳过 kubelet 证书校验；生产环境应配置可信证书。
k -n kube-system patch deployment metrics-server --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
# 先创建工作负载和采集配置，再安装或更新自定义指标适配器。
k apply -f workloads.yaml -f prometheus.yaml -f hpa-cpu.yaml
# 固定 chart 与镜像版本；等待 Adapter 就绪后再进入实验。
helm upgrade --install adapter prometheus-adapter \
  --repo https://prometheus-community.github.io/helm-charts --version 4.14.0 \
  --kube-context kind-hpa-lab --namespace hpa-demo \
  -f adapter-values.yaml --wait --timeout 180s
k -n kube-system rollout status deployment/metrics-server --timeout=120s
# 确认各 Deployment 已就绪；每个等待都有超时上限。
for deployment in worker queue prometheus; do
  k -n hpa-demo rollout status "deployment/$deployment" --timeout=120s
done
# APIService 就绪只表示接口可访问，首批指标仍可能需要等待采集。
k wait --for=condition=Available apiservice/v1beta1.metrics.k8s.io --timeout=120s
# APIService 就绪只表示接口可访问，首批指标仍可能需要等待采集。
k wait --for=condition=Available apiservice/v1beta1.custom.metrics.k8s.io --timeout=120s
k -n hpa-demo get hpa
