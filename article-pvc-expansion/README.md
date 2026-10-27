# PVC 扩容与 CSI 调用实验

使用 CSI hostpath 测试驱动观察 PVC 扩容的控制面与节点侧步骤：

- StorageClass 未开启 `allowVolumeExpansion` 时拒绝修改容量。
- 开启后，PVC 请求从 64 MiB 改为 128 MiB，external-resizer 调用
  `ControllerExpandVolume`，PV 更新到 128 MiB。
- hostpath 驱动下，已运行 Pod 先进入 `FileSystemResizePending`；重建消费者后
  kubelet 调用 `NodeExpandVolume`，PVC status capacity 才更新到 128 MiB。
- 扩容后原数据仍可读取；把 PVC 请求改小会被 API 拒绝。

hostpath 驱动只更新记录的卷容量，目录仍然位于节点文件系统上，所以容器里的 `df`
不会显示 128 MiB 配额。实验证明的是 Kubernetes/CSI 调用链，不是某个生产存储后端
文件系统的实际扩容结果。

## 准备与运行

先按[公共环境](../article-next-common/README.md)创建 `article-next` 集群并导出
`KUBECONFIG`、`KUBECTL`。

```bash
python3 article-pvc-expansion/run.py
```

消费 Pod 与 CSI 驱动调度在同一节点，因为 hostpath 驱动只支持单节点访问。

## 结果

- `before.json`、`after-expand.json`：扩容前后的 PVC、PV、事件和容器内 `df`。
- `shrink-rejected.json`：PVC 缩容请求的拒绝信息。
- `storageclass-disallowed.json`：StorageClass 未允许扩容时的拒绝信息。
- `csi-log.json`：驱动与 external-resizer 的扩容调用日志。

生产卷还要根据 CSI 驱动选择文件系统扩容、块设备在线扩容或离线扩容流程，并确认后端
容量、节点文件系统和应用可容忍的维护窗口。

## 清理

脚本删除实验 namespace 和两个 StorageClass。
