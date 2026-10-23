# Deployment 慢启动、慢终止与容量实验

## 固定提交准备

先按[固定提交复现步骤](../article-labs-reproduction.md)设置文章链接中的 `ARTICLE_LABS_REV`，取得并核对独立工作目录。后续命令从该流程设置的 `$ARTICLE_ROOT` 执行；新终端也要先完成版本准备，不能直接使用当前分支目录。

冷启动先完成相邻 `article-control-ha/README.md` 的工具准备和集群初始化，使用专用 `article-control` 集群、kubectl v1.35.1 与 Kubernetes v1.35.1。脚本只需 Python 3 标准库，运行主机为 `zj`。

```bash
cd "$ARTICLE_ROOT/article-control-rollout"
python3 run.py
```

`deployment.yaml` 设置两个副本、surge=1、unavailable=0、minReadySeconds=5。新模板取消 readiness 文件自动创建，由脚本逐个打开就绪条件。旧容器 preStop 延迟 25 秒，终止总宽限期 40 秒。脚本断言慢启动保留旧副本，观察含终止中对象的 Pod 数超过 3，最后检查 rollout 完成。

脚本随后调用 `capacity.py`，把新模板 CPU request 改到 worker 无法满足的值，检查新 Pod Unschedulable、旧版本仍有两个 Available 副本，再 undo 并等待完成。`capacity.py` 也可以在前一阶段完成后独立运行。

`evidence/results-final.log` 是修正观察循环后重新创建 namespace 的实际慢启动/终止结果；`capacity.log` 为独立运行容量检查的结果。初版脚本在首次观察到重叠后就停止打开后续新 Pod 的 readiness，需人工打开第二个新 Pod，因而未把初版结果作为可重复主证据；最终脚本会一直观察到新版本就绪再退出。

本实验没有 HTTP 流量，不声称验证零中断；最大 Pod 数是一次时序观察，不是容量上界。终止中的对象仍可能在 rollout status 成功后存在。

重跑前通过专用 kubeconfig 删除 `control-rollout` namespace 并等待完成。完整清理按 HA README 删除测试集群；不要在控制面故障脚本运行时并发执行。
