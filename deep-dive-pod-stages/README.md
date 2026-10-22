# pod-stages 实验

比较节点标签不匹配、ConfigMap 卷缺失和补齐配置后的同一 Pod 恢复。

## 准备

先按[共用环境说明](../deep-dive-common/README.md)创建 `deep-dive` 集群。使用 Linux、Docker、kind、kubectl、Python 3、Git 和 curl；所有命令从本仓库根目录执行。

## 运行

```sh
export KUBECONFIG="$PWD/tmp/k8s-deep-dive/kubeconfig"
python3 deep-dive-pod-stages/run.py
```

脚本固定使用 `kind-deep-dive` context，每次运行会删除并重建 `dd-pod-stages` namespace。不要在该 namespace 存放需要保留的数据。条件等待或断言失败时，脚本非零退出；不能只看最后一次 apply 是否成功。

## 结果

命令在本系列 `k8sdev` 实验仓库根目录执行。`evidence/unscheduled.json` 保存调度阻塞，`mount-blocked-events.json` 保存 FailedMount，`mount-recovered.json` 保存修复后的状态。脚本补齐 ConfigMap 后等待原 Pod Ready，验证恢复确实来自缺失条件被满足。

重新运行会覆盖本目录 `evidence/` 中的同名结果。仓库中已有结果是历史测量记录；本次是否通过，以本次脚本退出状态与新记录为准。

## 清理

只清理本主题的资源：

```sh
kubectl --context kind-deep-dive delete namespace dd-pod-stages
```

所有主题结束后，按[共用环境说明](../deep-dive-common/README.md#清理)删除专用集群。
