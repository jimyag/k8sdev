# storage 实验

验证 Bound 后被其他卷阻塞、同节点 RWO 共享、延迟绑定和 RWOP 排他。

## 准备

先按[共用环境说明](../deep-dive-common/README.md)创建 `deep-dive` 集群。使用 Linux、Docker、kind、kubectl、Python 3、Git 和 curl；所有命令从本仓库根目录执行。

## 运行

```sh
export KUBECONFIG="$PWD/tmp/k8s-deep-dive/kubeconfig"
python3 deep-dive-storage/run.py
```

脚本固定使用 `kind-deep-dive` context，每次运行会删除并重建 `dd-storage` namespace。不要在该 namespace 存放需要保留的数据。条件等待或断言失败时，脚本非零退出；不能只看最后一次 apply 是否成功。

使用 CSI hostpath 测试驱动；数据只保存在专用 kind 环境中，不用于生产存储。脚本还会创建实验 StorageClass，完整清理由删除专用集群完成。

## 结果

脚本会重建 `dd-storage`，依次验证 Bound 但未启动、同节点 RWO 共享、延迟绑定和 RWOP 排他。`attachments.json` 保存实际 VolumeAttachment，`driver-rpc-log.json` 保存驱动调用日志，`rwop-blocked-events.json` 保存第二个 RWOP 消费者被阻止的事件。

重新运行会覆盖本目录 `evidence/` 中的同名结果。仓库中已有结果是历史测量记录；本次是否通过，以本次脚本退出状态与新记录为准。

## 清理

只清理本主题的资源：

```sh
kubectl --context kind-deep-dive delete namespace dd-storage
```

所有主题结束后，按[共用环境说明](../deep-dive-common/README.md#清理)删除专用集群。
