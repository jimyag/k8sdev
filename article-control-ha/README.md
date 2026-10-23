# 控制面职责与故障实验

## 固定提交准备

先按[固定提交复现步骤](../article-labs-reproduction.md)设置文章链接中的 `ARTICLE_LABS_REV`，取得并核对独立工作目录。后续命令从该流程设置的 `$ARTICLE_ROOT` 执行；新终端也要先完成版本准备，不能直接使用当前分支目录。

已验证环境：SSH 主机 `zj`，kind v0.33.0，Kubernetes v1.35.1，containerd 2.2.1，三个 stacked-etcd 控制面和一个 worker。所有操作只针对 `article-control`，不能替换成生产集群。实验 Python 使用系统 Python 3 标准库，不需要安装包。

## 准备与运行

完成固定提交准备，在 `zj` 的 `$ARTICLE_ROOT` 工作目录中运行。要求 Docker 可用、`~/.local/bin/kind` 已安装且版本匹配，网络可拉取 kind 节点与 busybox 镜像。

```bash
cd "$ARTICLE_ROOT/article-control-ha"
bash setup.sh
bash run.sh
python3 components.py
python3 failover.py
python3 api-outage.py
```

`setup.sh` 下载官方 kubectl v1.35.1 到仓库已忽略的 `tmp/article-tools/`，核验官方 SHA-256，再报告客户端、kind 和 Docker 版本。`run.sh` 设置 `TMPDIR` 和独立 kubeconfig 到 `tmp/article-control/`，创建集群和 baseline，再暂停一个控制面。写入切换可能超时，脚本按截止时间重试并通过读回处理已经提交的请求。脚本包含 `trap`，保证故障时尝试恢复暂停节点。

`components.py` 依次移出本实验节点中的 Scheduler、Controller Manager 静态清单，等待对应进程全部停止，验证 API 写入和执行能力的区别，再恢复并等待收敛。`failover.py` 按 Scheduler Lease 找当前 leader 节点并暂停，验证新的 ConfigMap 与扩容。`api-outage.py` 停止全部 API Server 后从 worker 访问已有 HTTP Pod，恢复后核对 Pod UID 和容器 ID。

上述命令需要顺序运行。其他三个 `article-control-*` 实验复用这个测试集群；不能在控制面故障阶段并发运行，否则会混淆其他实验结果。脚本面向干净运行，重复实验前按清理步骤删除集群再创建；不能对现有运行中集群重复执行初始化。

## 证据与结论

`evidence/` 保存 2026-10-23 实际运行输出。首次测试使用主机默认 kubectl v1.37.1，输出包含版本偏差警告，且首次单节点故障写入超时；后续实验改用匹配的 v1.35.1。文章引用后续匹配版本验证，并保留首次失败作为切换窗口证据，不能声称客户端从始至终都已匹配。

Scheduler 全停时新 Pod 没有 nodeName，恢复后 Ready；Controller Manager 全停时副本数写入成功但实际数量未变，恢复后收敛；单节点暂停后其余控制面接管并完成四副本部署；API 全停时直接 Pod HTTP 请求仍返回 `alive`，恢复后 UID 与容器 ID 未变。

该 HTTP 验证绕过 Service、DNS 和 Ingress。所有 kind 节点共用物理机，不能证明主机或可用区容灾。没有运行修改后的 Kubernetes 二进制，源码分析与原版运行观察分别注明。

## 清理

先完成依赖这个集群的 GC、rollout 和 etcd 实验，再执行：

```bash
export TMPDIR="$ARTICLE_ROOT/tmp/article-control"
~/.local/bin/kind delete cluster --name article-control
rm -f "$ARTICLE_ROOT/tmp/article-control/kubeconfig"
```

删除该集群会一并删除测试 etcd 快照、恢复数据和容器。`tmp/article-tools` 为其他并行文章共用的临时工具，不由本实验自动删除。不要把 kubeconfig、证书、数据库或快照复制进实验 Git 目录。
