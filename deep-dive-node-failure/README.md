# node-failure 实验

暂停一个 kind worker，记录 Node Unknown、旧 Pod 删除和替代副本 Ready 的时间线。

## 准备

先按[共用环境说明](../deep-dive-common/README.md)创建 `deep-dive` 集群。使用 Linux、Docker、kind、kubectl、Python 3、Git 和 curl；所有命令从本仓库根目录执行。

## 运行

```sh
export KUBECONFIG="$PWD/tmp/k8s-deep-dive/kubeconfig"
python3 deep-dive-node-failure/run.py
```

脚本固定使用 `kind-deep-dive` context，每次运行会删除并重建 `dd-node-failure` namespace。不要在该 namespace 存放需要保留的数据。条件等待或断言失败时，脚本非零退出；不能只看最后一次 apply 是否成功。

本实验会暂停 `deep-dive-worker` 容器，并在 `finally` 中恢复。进程被强行中断时，可执行 `docker unpause deep-dive-worker`，再等待节点 Ready。这里不是宿主机断电测试。

## 结果

`before.json`、`node-unknown.json`、`while-paused.json`、`replacement.json` 和 `recovered.json` 保存各阶段对象，`timing.json` 保存测量条件。脚本使用 `finally` 恢复暂停的 worker，并等原节点重新 Ready、旧 Pod 删除后才退出。

重新运行会覆盖本目录 `evidence/` 中的同名结果。仓库中已有结果是历史测量记录；本次是否通过，以本次脚本退出状态与新记录为准。

## 清理

只清理本主题的资源：

```sh
kubectl --context kind-deep-dive delete namespace dd-node-failure
```

所有主题结束后，按[共用环境说明](../deep-dive-common/README.md#清理)删除专用集群。
