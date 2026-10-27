# Kubernetes 机制实验公共环境

`article-watch-consistency`、`article-job-cronjob`、`article-crd-conversion` 和
`article-pvc-expansion` 共用 `article-next` 三节点 kind 集群。镜像生命周期实验需要修改
kubelet 的镜像回收阈值，使用自己的单节点集群。

## 准备

在 Linux amd64 主机 `zj` 上执行。要求 Docker、Git、curl、Python 3 和 Bash 可用。
先按[从文章固定提交复现实验](../article-labs-reproduction.md)创建独立工作目录，
再在该目录执行后续命令。这样可以避免当前分支的未提交改动改变实验输入。

```bash
export ARTICLE_TMP="$PWD/tmp/article-next"
bash article-next-common/setup.sh
export KUBECONFIG="$ARTICLE_TMP/kubeconfig"
export KUBECTL="$ARTICLE_TMP/tools/kubectl"
export KIND="$ARTICLE_TMP/tools/kind"
"$KUBECTL" --context kind-article-next get nodes
```

脚本只在集群不存在时创建 `article-next`，随后安装 CSI hostpath v1.19.0 测试驱动和
snapshot CRD。hostpath 只用于观察 CSI 调用，不是生产存储方案。

## 运行

四个主题逐个执行，避免同一时间修改集群状态：

```bash
python3 article-watch-consistency/run.py
python3 article-job-cronjob/run.py
python3 article-crd-conversion/run.py
python3 article-pvc-expansion/run.py
```

每个脚本会重建自己的 namespace，并把断言所需的对象、事件和驱动日志写入对应主题的
`evidence/`。脚本超时或断言失败时返回非零状态。

## 清理

```bash
"$KIND" delete cluster --name article-next
rm -r "$ARTICLE_TMP"
```

删除前确认没有其他实验正在使用该集群和目录。
