# Pod Sandbox 与业务容器实验

## 固定提交准备

先按[固定提交复现步骤](../article-labs-reproduction.md)设置文章链接中的 `ARTICLE_LABS_REV`，取得并核对独立工作目录。后续命令从该流程设置的 `$ARTICLE_ROOT` 执行；新终端也要先完成版本准备，不能直接使用当前分支目录。

检验三个彼此独立的问题：双容器是否共享 netns 并通过 localhost 通信；人为触发一个容器主进程退出时是否仅重启该容器；已就绪的 Sandbox 是否仍可能有启动失败的业务容器。

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

## 执行与结果

```bash
cd "$ARTICLE_ROOT/article-resources-runtime"
python3 run.py
cat results.json
"$KUBECTL" get events -n article-runtime --sort-by=.lastTimestamp
```

`pods.yaml` 创建 server、peer 双容器 Pod，以及指定不存在可执行文件的 Pod。脚本使用真实 API 和 CRI 状态断言，超时或不符合结果即失败。它向 server 内 PID 1 发送 Python HTTP server 能处理的 SIGINT，人为触发退出；这不是对 CRI StopContainer 或 Sandbox 失效恢复的验证。

本次双容器的 netns 标识相同（具体值见 `results.json`），HTTP 为 200；局部重启保持 Pod UID、peer 容器 ID 和 Sandbox ID，server 容器 ID 改变，serverRestartCount=1。无效命令报错来自 CRI StartContainer 内的 OCI task 创建阶段，先出现 RunContainerError，随后可能进入 CrashLoopBackOff；对应 Sandbox 仍为 READY。结果保存断言所需的标识与无效命令事件，不保存认证数据。

初次排查曾尝试 CRI stop：Python 作为命名空间 PID 1 对默认 TERM 的处理使 stop RPC 超时；该尝试不作为通过证据。随后验证使用 SIGINT，最终脚本不再调用 stop。重复运行会累计重启退避时间；需要完整重跑时，先删除本目录创建的两个 Pod：
```bash
"$KUBECTL" delete pod runtime-pair runtime-bad-command -n article-runtime --wait=true
python3 run.py
```

## 清理

本篇单独清理：
```bash
"$KUBECTL" delete namespace article-runtime --wait=true
```

四组实验全部结束后，由创建者核对名称，再删除唯一的专用集群：
```bash
"$KIND" delete cluster --name article-resources
```

仅清理本次专用目录下工具和 kubeconfig，不删除其他实验或集群。没有测试 Sandbox 故障、容器运行时重启或网络插件故障。
