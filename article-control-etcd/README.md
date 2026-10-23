# etcd 多数派、快照与隔离恢复

先按相邻 `article-control-ha/README.md` 完成工具准备与测试集群初始化。运行主机 `zj`，kind v0.33.0、Kubernetes v1.35.1、etcd/etcdctl/etcdutl 3.6.6。脚本通过本实验节点内的 CRI 调用镜像自带工具，不额外安装 etcd 二进制。

```bash
cd /home/jimyag/src/github.com/jimyag/k8sdev/article-control-etcd
bash run.sh
```

脚本创建 `/article/` 前缀的合成测试键，保存快照，再写快照后测试键。分别暂停第二和第三个控制面，验证剩余两个可写、剩余一个时写请求超时但仍可 Serializable 读。超时只表示未获得提交确认，不表示已经撤回提案；退出 trap 恢复两个暂停节点，恢复多数派后检查 endpoint health，并读回超时请求的键，单独记录最终观察结果，不固定断言该键一定不存在。

快照保存在测试节点的 `/var/lib/etcd/article-snapshot.db`，恢复数据在同一测试节点的 `/var/lib/etcd/article-restored`，均不复制到 Git 工作区。恢复使用 revision bump=1,000,000,000 和 mark-compacted，这个增量只适用于本次实验。

在另一个 SSH 终端运行以下前台服务：

```bash
cd /home/jimyag/src/github.com/jimyag/k8sdev/article-control-etcd
bash restored.sh
```

它在测试节点 containerd 中启动独立 `article-etcd-restored`，挂载恢复目录，使用 3379/3380 端口，不改变原来的三个 etcd 成员与 API Server 配置。原终端继续执行：

```bash
bash verify.sh
```

脚本以有截止时间的健康检查确认恢复实例可用，断言快照前键存在、快照后键不存在、Kubernetes Deployment 存储键存在，检查 revision，并断言旧历史 Range 与旧 revision Watch 被 compacted 错误拒绝。结果在 `evidence/`。

2026-10-23 的复查重跑保存在 `evidence/review-run.log` 与 `evidence/review-verify.log`。本次写请求先返回 `context deadline exceeded`，恢复多数派后却读回已提交的键，说明超时不能解释为确定拒绝。恢复实例的 Range 与 Watch 均返回 `required revision has been compacted`，修订脚本检查了这个具体错误，而不是仅检查命令非零退出。该次恢复后的 revision 为 1000001272；revision 随快照状态变化，不是固定验收值。

没有把恢复实例接回 Kubernetes，没有证明控制器和 Informer 完整恢复；只验证数据边界、隔离启动和历史失效机制。没有执行真实集群成员替换或磁盘损坏实验。

结束时在服务终端中断前台命令，并确认测试节点中的 `article-etcd-restored` 任务退出；也可以按 HA README 删除整个 `article-control`，同时清除测试快照、恢复目录和所有凭据。不要删除其他节点或数据库目录。重跑恢复前重新创建自己的测试集群，避免覆盖已存在的恢复数据。
