# pdb 实验

比较 Eviction API、直接 DELETE、滚动更新和不健康 Pod 驱逐策略。

## 准备

先按[共用环境说明](../deep-dive-common/README.md)创建 `deep-dive` 集群。使用 Linux、Docker、kind、kubectl、Python 3、Git 和 curl；所有命令从本仓库根目录执行。

## 运行

```sh
export KUBECONFIG="$PWD/tmp/k8s-deep-dive/kubeconfig"
python3 deep-dive-pdb/run.py
```

脚本固定使用 `kind-deep-dive` context，每次运行会删除并重建 `dd-pdb` namespace。不要在该 namespace 存放需要保留的数据。条件等待或断言失败时，脚本非零退出；不能只看最后一次 apply 是否成功。

## 结果

运行入口会重建 `dd-pdb`。`evidence/eviction-denied.json` 保存拒绝信息，`direct-delete.json` 保存被删除的旧名称和新 Pod 名称，`rollout-complete.json` 保存发布后的对象。实验检查每一步确实发生，而不是仅检查 YAML 中出现了 PDB 字段。

重新运行会覆盖本目录 `evidence/` 中的同名结果。仓库中已有结果是历史测量记录；本次是否通过，以本次脚本退出状态与新记录为准。

## 清理

只清理本主题的资源：

```sh
kubectl --context kind-deep-dive delete namespace dd-pdb
```

所有主题结束后，按[共用环境说明](../deep-dive-common/README.md#清理)删除专用集群。
