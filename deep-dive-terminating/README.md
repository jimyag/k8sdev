# terminating 实验

验证 Finalizer 阻塞删除，以及 API 对象消失后节点容器仍运行的情况。

## 准备

先按[共用环境说明](../deep-dive-common/README.md)创建 `deep-dive` 集群。使用 Linux、Docker、kind、kubectl、Python 3、Git 和 curl；所有命令从本仓库根目录执行。

## 运行

```sh
export KUBECONFIG="$PWD/tmp/k8s-deep-dive/kubeconfig"
python3 deep-dive-terminating/run.py
```

脚本固定使用 `kind-deep-dive` context，每次运行会删除并重建 `dd-terminating` namespace。不要在该 namespace 存放需要保留的数据。条件等待或断言失败时，脚本非零退出；不能只看最后一次 apply 是否成功。

本实验会停止 `deep-dive-worker2` 容器内部的 kubelet，并在 `finally` 中恢复。进程被强行中断时，可执行 `docker exec deep-dive-worker2 systemctl start kubelet` 恢复，再检查节点 Ready。

## 结果

脚本重建 `dd-terminating`，只操作 `deep-dive` 集群，并用 `finally` 恢复被停止的 kubelet。`after-force.json` 保存强制删除后仍在的 Finalizer，`force-object-gone-process-running.json` 保存 API 对象与运行时不一致的观察，`orphan-cleaned.json` 确认恢复后的旧容器已停止。

重新运行会覆盖本目录 `evidence/` 中的同名结果。仓库中已有结果是历史测量记录；本次是否通过，以本次脚本退出状态与新记录为准。

## 清理

只清理本主题的资源：

```sh
kubectl --context kind-deep-dive delete namespace dd-terminating
```

所有主题结束后，按[共用环境说明](../deep-dive-common/README.md#清理)删除专用集群。
