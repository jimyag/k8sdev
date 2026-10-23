# 容器 cgroup OOM 实验

使用 memory limit 32Mi 的容器尝试分配固定 64Mi 内存。只触发该容器限制，不耗尽节点或宿主机内存。`restartPolicy: Never` 避免持续分配循环。

## 环境准备（只执行一次）

在 Linux amd64 主机 `zj` 上执行，要求 Docker 服务可用、当前用户可操作 Docker，并安装 Python 3、curl 和 sha256sum。不会操作其他 kind 集群。本文固定 Kubernetes v1.35.1，不声称使用最新版本。

```bash
set -euo pipefail
cd /home/jimyag/src/github.com/jimyag/k8sdev
export ARTICLE_ROOT="$PWD"
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
cd "$ARTICLE_ROOT/article-resources-memory"
python3 run.py
cat results.json
```

断言 API phase 为 Failed、容器 reason 为 OOMKilled、exitCode 为 137，保存 UID、容器终止状态、版本和分配前的日志。本次日志为 `memory.max=33554432`、`oom_score_adj=999`；QoS 为 Burstable。没有 CPU request/limit，不能把只有 memory request 与 limit 的 Pod 当作 Guaranteed。

没有触发节点全局 OOM，也没有实测 MemoryPressure、QoS 驱逐次序或 MemoryQoS。源码分析不得写成这些分支已经通过运行验证。

## 重跑与清理

已有失败 Pod 不会因 apply 自动重新执行。完整重跑需要：
```bash
"$KUBECTL" delete pod memory-oom -n article-memory --wait=true
python3 run.py
```

只清理本篇资源：
```bash
"$KUBECTL" delete namespace article-memory --wait=true
```

四篇共享专用集群，全部结束后才按 [运行时实验 README](../article-resources-runtime/README.md#清理) 删除 `article-resources`。不清理他人资源。
