#!/usr/bin/env bash
# 任何命令失败立即停止；未设置变量或管道前半段失败也视为错误。
set -euo pipefail
# 以脚本所在目录为基准解析 YAML 和构建上下文，允许从其他目录调用。
cd "$(dirname "$0")"
# 必须由调用者提供专用 kubeconfig，避免修改日常使用的集群配置。
: "${KUBECONFIG:?Use the dedicated kubeconfig from ../lab/setup.sh}"
k() { kubectl --context kind-hpa-lab -n hpa-demo "$@"; }
# 确认基础实验已安装；进阶安装不另建集群。
k get deployment worker >/dev/null
# 构建本机架构的演示程序，再导入 kind；无需推送镜像仓库。
docker build -t hpa-advanced:v1 .
kind load docker-image hpa-advanced:v1 --name hpa-lab
# 先创建工作负载和采集配置，再安装或更新自定义指标适配器。
k apply -f workloads.yaml -f prometheus.yaml
# 给 Prometheus 配置读取 Pod 服务发现的受限服务账号。
k patch deployment prometheus --type=merge -p '{"spec":{"template":{"spec":{"serviceAccountName":"prometheus"}}}}'
# 重启 Prometheus，使更新后的抓取配置立即生效。
k rollout restart deployment/prometheus
k rollout status deployment/prometheus --timeout=180s
# 固定 chart 与镜像版本；等待 Adapter 就绪后再进入实验。
helm upgrade adapter prometheus-adapter \
  --repo https://prometheus-community.github.io/helm-charts --version 4.14.0 \
  --kube-context kind-hpa-lab --namespace hpa-demo \
  -f adapter-values.yaml --wait --timeout 180s
# 确认各 Deployment 已就绪；每个等待都有超时上限。
for d in broker consumer web; do k rollout status "deployment/$d" --timeout=120s; done
