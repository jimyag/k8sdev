# 请求量抢占与不可满足硬约束

## 固定提交准备

先按[固定提交复现步骤](../article-labs-reproduction.md)设置文章链接中的 `ARTICLE_LABS_REV`，取得并核对独立工作目录。后续命令从该流程设置的 `$ARTICLE_ROOT` 执行；新终端也要先完成版本准备，不能直接使用当前分支目录。

单节点隔离集群上，以 node allocatable CPU 的四分之三作为每个 Pod request。容器只运行 sleep，不通过真实 CPU 压力制造调度失败。集群需默认 scheduler profile，不能在业务集群执行。

## 环境准备（只执行一次）

在 Linux amd64 主机 `zj` 上执行，要求 Docker 服务可用、当前用户可操作 Docker，并安装 Python 3、curl 和 sha256sum。不会操作其他 kind 集群。本文固定 Kubernetes v1.35.1，不声称使用最新版本。

```bash
set -euo pipefail
cd "$ARTICLE_ROOT"
mkdir -p "$ARTICLE_ROOT/tmp/article-resources/tools"
export TMPDIR="$ARTICLE_ROOT/tmp/article-resources"
export KUBECONFIG="$TMPDIR/kubeconfig"
export KUBECTL="$TMPDIR/tools/kubectl"
export KIND="$TMPDIR/tools/kind-linux-amd64"
cd "$TMPDIR/tools"
curl -fsSLo kubectl https://dl.k8s.io/release/v1.35.1/bin/linux/amd64/kubectl
curl -fsSLo kubectl.sha256 https://dl.k8s.io/release/v1.35.1/bin/linux/amd64/kubectl.sha256
printf '%s  kubectl\n' "$(cat kubectl.sha256)" | sha256sum --check
curl -fsSLo kind-linux-amd64 https://github.com/kubernetes-sigs/kind/releases/download/v0.33.0/kind-linux-amd64
curl -fsSLo kind-linux-amd64.sha256sum https://github.com/kubernetes-sigs/kind/releases/download/v0.33.0/kind-linux-amd64.sha256sum
sha256sum --check kind-linux-amd64.sha256sum
chmod +x "$KUBECTL" "$KIND"
cd "$ARTICLE_ROOT"
"$KIND" get clusters
# 仅当 article-resources 尚不存在时创建；同名已有集群先确认归属，不自动删除。
"$KIND" create cluster --name article-resources --image kindest/node:v1.35.1 --kubeconfig "$KUBECONFIG" --wait 120s
docker pull python:3.12-alpine
"$KIND" load docker-image python:3.12-alpine --name article-resources
"$KUBECTL" version -o json
"$KUBECTL" get nodes -o wide
for name in memory runtime storage scheduling; do
  "$KUBECTL" create namespace "article-$name"
done
```

本次版本为 kind v0.33.0、Kubernetes v1.35.1（`8fea90b45245ef5c8ba54e7ae044d3e777c22500`）、containerd v2.2.1，Linux 内核为 6.12.74。单节点 kind 没有阻止工作负载调度的 control-plane taint；先检查节点 taint，不要为让实验成功而修改其他集群。Python 镜像本次 ID 为 `sha256:f4b7b8044a873fcc0f348549a19b9075cd77bd56ead7177192cfec38d85bce4a`，标签未来可能漂移，复现时应记录实际镜像 ID。

工具、kubeconfig 和 kind 临时输出都放在项目已忽略的 `tmp/`，不得将 kubeconfig 加入版本控制。新的终端需要重新设置上述环境变量；不要使用默认 kubeconfig。

## 执行与证据

```bash
cd "$ARTICLE_ROOT/article-resources-scheduling"
python3 run.py
cat results.json
```

`classes.yaml` 定义优先级 100 与 1000。脚本用标准 JSON 序列化动态 Pod 请求体并经 stdin 提交，不修改固定 YAML。先运行 low，再创建带不存在 nodeSelector 的 impossible，检查 Unschedulable 且 low 未被删除；再创建不带该约束的 high，按 low UID 检查 Preempted 事件并等待 high Ready，同时断言 impossible 仍 Pending。

本次 allocatable=12 CPU，各 Pod request=9000m。两个请求总和超过节点容量，因此需要移除低优先级 Pod；高优先级不能让节点获得不存在的标签。`results.json` 保留请求量、UID、抢占事件和不匹配节点标签的条件消息。

脚本通过行为断言验证，不依赖固定 sleep 推测成功；轮询有超时。没有测试多节点抢占候选选择、PDB 违约、复杂 affinity 或拓扑分布组合。

## 重跑与清理

抢占后的 low 通常已经不存在，重跑前清理当前实验 Pod：
```bash
"$KUBECTL" delete pods --all -n article-scheduling --wait=true
python3 run.py
```

完成取证后：
```bash
"$KUBECTL" delete namespace article-scheduling --wait=true
"$KUBECTL" delete priorityclass article-low article-high
```

四篇共享专用集群，全部结束后才按 [运行时实验 README](../article-resources-runtime/README.md#清理) 删除 `article-resources`。不清理他人资源。
