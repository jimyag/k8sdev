# cpu 实验

在相同 request 下比较有无 CPU limit，测量 1 CPU 秒计算的实际耗时和 throttling 增量。

## 准备

先按[共用环境说明](../deep-dive-common/README.md)创建 `deep-dive` 集群。使用 Linux、Docker、kind、kubectl、Python 3、Git 和 curl；所有命令从本仓库根目录执行。

## 运行

```sh
export KUBECONFIG="$PWD/tmp/k8s-deep-dive/kubeconfig"
python3 deep-dive-cpu/run.py
```

脚本固定使用 `kind-deep-dive` context，每次运行会删除并重建 `dd-cpu` namespace。不要在该 namespace 存放需要保留的数据。条件等待或断言失败时，脚本非零退出；不能只看最后一次 apply 是否成功。

## 结果

脚本会重建 `dd-cpu` namespace。`evidence/one-cpu-second.json` 保存原始时间和计数器增量；两份 `input-pod-*.json` 保存实际提交的配置。断言要求受限组发生 throttling，且耗时显著高于对照组，而不是要求每次运行都恰好得到同一个小数。

重新运行会覆盖本目录 `evidence/` 中的同名结果。仓库中已有结果是历史测量记录；本次是否通过，以本次脚本退出状态与新记录为准。

## 清理

只清理本主题的资源：

```sh
kubectl --context kind-deep-dive delete namespace dd-cpu
```

所有主题结束后，按[共用环境说明](../deep-dive-common/README.md#清理)删除专用集群。
