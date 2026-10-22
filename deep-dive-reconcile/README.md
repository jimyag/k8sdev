# reconcile 实验

验证旧 resourceVersion 写入冲突，以及操作成功但未确认时重复执行的幂等性。

## 准备

先按[共用环境说明](../deep-dive-common/README.md)创建 `deep-dive` 集群。使用 Linux、Docker、kind、kubectl、Python 3、Git 和 curl；所有命令从本仓库根目录执行。

## 运行

```sh
export KUBECONFIG="$PWD/tmp/k8s-deep-dive/kubeconfig"
python3 deep-dive-reconcile/run.py
```

脚本固定使用 `kind-deep-dive` context，每次运行会删除并重建 `dd-reconcile` namespace。不要在该 namespace 存放需要保留的数据。条件等待或断言失败时，脚本非零退出；不能只看最后一次 apply 是否成功。

## 结果

`evidence/stale-update.json` 保存真实 Conflict，`attempts.json` 保存三次调谐的动作，`result.json` 检查最后只有一个 effect。脚本人工重复调用调谐函数，没有运行完整的 Informer Controller；它把并发更新与副作用恢复拆开，便于确认每个结论来自哪个实验。

重新运行会覆盖本目录 `evidence/` 中的同名结果。仓库中已有结果是历史测量记录；本次是否通过，以本次脚本退出状态与新记录为准。

## 清理

只清理本主题的资源：

```sh
kubectl --context kind-deep-dive delete namespace dd-reconcile
```

所有主题结束后，按[共用环境说明](../deep-dive-common/README.md#清理)删除专用集群。
