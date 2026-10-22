# HPA 调优与排障实验

验证副本建议、稳定窗口、变化速率、多指标故障和 Pod 启动条件。本文对应 `hpa-lab` 集群，与 `deep-dive-*` 使用的集群独立。

## 准备

取得博客链接固定提交的仓库后，从仓库根目录执行。需要 Docker、kind、kubectl、Helm、Python 3 和 curl，并能下载镜像及 Helm chart。

```sh
mkdir -p tmp/hpa-lab
export TMPDIR="$PWD/tmp/hpa-lab"
export KUBECONFIG="$PWD/tmp/hpa-lab/kubeconfig"
bash hpa/lab/setup.sh
bash hpa/advanced/setup.sh
```

基础 setup 创建 Kubernetes v1.35.0 的 `hpa-lab` 集群，并安装应用、Prometheus、Metrics Server 和 Prometheus Adapter。已有同名基础实验集群时，不重复执行基础 setup；确认依赖就绪后运行进阶 setup。所有操作固定使用 `kind-hpa-lab` context 和 `hpa-demo` namespace。

## 运行

从仓库根目录执行以下 Bash 命令；失败立即停止，避免后续场景掩盖错误：

```bash
set -euo pipefail
export KUBECONFIG="$PWD/tmp/hpa-lab/kubeconfig"
mkdir -p tmp/hpa-lab/results
for case in steps policies multi failures scheduling; do
  python3 hpa/advanced/run.py "$case" --output "$PWD/tmp/hpa-lab/results"
done
```

`steps` 验证多个副本档位与稳定窗口，`policies` 对比 Pods/Percent 速率策略，`multi` 验证多指标选择，`failures` 暂停指标链路组件，`scheduling` 验证调度失败与 readiness 延迟。场景会修改实验工作负载，不与其他 HPA 实验并行执行。

单独重跑时，将循环换成一个命令，例如：

```sh
python3 hpa/advanced/run.py policies --output "$PWD/tmp/hpa-lab/results"
```

## 结果与清理

每个场景通过全部条件后才输出 `PASS`，失败以非零状态退出。结果目录中的 JSONL 记录动作、HPA 状态、期望副本、Ready 副本和指标查询。仓库已有历史结果位于 [evidence](evidence/)，本次输出保存在 `tmp/hpa-lab/results/`。

实验结束、不再需要集群内测试数据时执行：

```sh
kind delete cluster --name hpa-lab
```

保留结果文件用于分析；需要删除独立 kubeconfig 和本次输出时，再删除仓库根目录下的 `tmp/hpa-lab/`。
