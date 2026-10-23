# OwnerReference 与垃圾回收实验

依赖相邻 `article-control-ha/README.md` 中的准备和 `setup.sh`、`run.sh`，使用专用 `article-control` 集群、`tmp/article-control/kubeconfig` 和已校验的 kubectl v1.35.1。运行主机为 `zj`，服务端 Kubernetes v1.35.1。

```bash
cd /home/jimyag/src/github.com/jimyag/k8sdev/article-control-gc
python3 run.py
```

要求 Python 3 标准库。脚本创建专用 `control-gc` namespace，以 ConfigMap 构造所有者和阻塞型依赖；依赖带实验 Finalizer。逐组验证 foreground 保留所有者、background 先移除所有者、orphan 移除引用保留依赖，最后移除实验 Finalizer 并断言清理完成。条件轮询有 90 秒截止时间，失败返回非零。

`evidence/results.log` 是本次实际通过的输出，未包含凭据。实验不涉及业务 Pod、进程或云资源，因此只能支持 API 对象生命周期结论。

重跑前使用专用 kubeconfig 删除 `control-gc` namespace，确认删除完成；失败遗留的实验 ConfigMap 若仍有 `article.example/hold`，应先检查后只移除该实验标记。完整清理按 HA README 删除自己的集群；不要操作其他集群。
