# scheduling 实验

验证 CPU request 准入、nodeSelector 拒绝，以及补齐节点标签后的重新调度。

## 准备

先按[共用环境说明](../deep-dive-common/README.md)创建 `deep-dive` 集群。使用 Linux、Docker、kind、kubectl、Python 3、Git 和 curl；所有命令从本仓库根目录执行。

## 运行

```sh
export KUBECONFIG="$PWD/tmp/k8s-deep-dive/kubeconfig"
python3 deep-dive-scheduling/run.py
```

脚本固定使用 `kind-deep-dive` context，每次运行会删除并重建 `dd-scheduling` namespace。不要在该 namespace 存放需要保留的数据。条件等待或断言失败时，脚本非零退出；不能只看最后一次 apply 是否成功。

## 结果

`request-does-not-fit-events.json` 和 `selector-mismatch.json` 保存失败条件，`selector-recovered.json` 保存恢复后的 nodeName。实验只修改专用 kind 节点标签，并在结束时移除它。

重新运行会覆盖本目录 `evidence/` 中的同名结果。仓库中已有结果是历史测量记录；本次是否通过，以本次脚本退出状态与新记录为准。

## 清理

只清理本主题的资源：

```sh
kubectl --context kind-deep-dive delete namespace dd-scheduling
```

所有主题结束后，按[共用环境说明](../deep-dive-common/README.md#清理)删除专用集群。
