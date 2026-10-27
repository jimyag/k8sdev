# Kubernetes Watch 断线、旧 resourceVersion 与重新 List 实验

通过 `kubectl proxy` 直接请求 API 的 list/watch 接口，验证三件事：

- 压缩 etcd revision 并重启 API Server 清除旧 watch cache 后，从压缩前版本开始
  watch 会得到 410 Expired。
- List 返回的 `metadata.resourceVersion` 可以作为后续 watch 的起点。
- watch 连接断开后，可以从最后观察到的事件版本继续，并收到后续删除事件。

重启 API Server 会短暂中断该隔离集群的 Kubernetes API，不影响节点上已有容器。

## 准备与运行

先按[公共环境](../article-next-common/README.md)创建 `article-next` 集群并导出
`KUBECONFIG`、`KUBECTL`。

```bash
python3 article-watch-consistency/run.py
```

脚本使用 18081 端口启动临时 `kubectl proxy`，结束时关闭。结果写入 `evidence/`：

- `expired-watch.json`：旧版本 watch 的状态码和响应。
- `list.json`：List 得到的版本与对象。
- `watch-after-create.json`：从 List 版本开始收到的创建事件。
- `watch-reconnect-delete.json`：断线后从最后版本重连收到的删除事件。

## 清理

脚本会删除自己的 namespace，并只关闭自己启动的 proxy。
