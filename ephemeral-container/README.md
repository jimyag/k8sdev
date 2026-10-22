# Ephemeral Container 共享进程命名空间实验

目标 Pod 显式设置 `shareProcessNamespace: true`，用于观察应用与临时容器的进程和网络。只通过 `--target` 加入目标 PID namespace 的另一组对照见 [deep-dive-ephemeral](../deep-dive-ephemeral/README.md)。

## 准备与运行

需要 Docker、kind 和 kubectl。取得博客链接固定提交的仓库后，从仓库根目录执行：

```sh
mkdir -p tmp/ephemeral-container
export TMPDIR="$PWD/tmp/ephemeral-container"
export KUBECONFIG="$PWD/tmp/ephemeral-container/kubeconfig"
kind create cluster --name k8s-advanced-lab --image kindest/node:v1.35.0 \
  --kubeconfig "$KUBECONFIG" --wait 60s
kubectl --context kind-k8s-advanced-lab apply -f ephemeral-container/01-debug-target.yaml
kubectl --context kind-k8s-advanced-lab wait --for=condition=Ready \
  pod/ephemeral-debug-target --timeout=120s
kubectl --context kind-k8s-advanced-lab debug pod/ephemeral-debug-target \
  --image=nicolaka/netshoot --target=app --container=netshoot --attach=false \
  -- bash -lc 'echo netshoot-started; ip addr; ss -lntp; ps; sleep 60'
```

已有同名实验集群时，不重复创建。临时容器名不能重复追加；再次运行注入命令前，更换 `--container` 名称，或在这个专用集群中重建目标 Pod。`netshoot` 沿用原实验的未固定 tag 镜像，当前镜像内容可能与历史运行不同。

## 查看结果

```sh
kubectl --context kind-k8s-advanced-lab get pod ephemeral-debug-target -o yaml
kubectl --context kind-k8s-advanced-lab logs ephemeral-debug-target -c netshoot
```

日志中的 `ps` 应包含应用与调试容器的进程；临时容器结束后，检查 `status.ephemeralContainerStatuses` 中的 `Terminated`、退出码和 `restartCount`。目标 Pod 继续运行，临时容器定义保留。命令中的 60 秒只是调试进程的存活时长，不是判断启动或退出成功的依据。

## 清理

确认不再需要专用集群内的测试数据后执行：

```sh
kind delete cluster --name k8s-advanced-lab
```

独立 kubeconfig 位于仓库根目录的 `tmp/ephemeral-container/`，不再需要时可删除该目录。
