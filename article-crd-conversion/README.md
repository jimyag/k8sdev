# CRD 多版本、Conversion Webhook 与存储版本实验

实验创建一个 `Widget` CRD，同时提供 `v1alpha1` 和 `v1beta1`。`v1alpha1` 使用
`spec.label`，`v1beta1` 使用 `spec.displayName`，由 TLS Conversion Webhook 转换。

脚本验证：

- 未在 schema 声明的字段在写入时被 pruning。
- 读取旧版本对象时，API Server 通过 webhook 得到新版本表示。
- CRD storage version 切换后，`status.storedVersions` 包含新版本。
- 通过 `v1beta1` 更新对象后，停止服务 `v1alpha1` 仍可通过 `v1beta1` 读取。

## 准备与运行

先按[公共环境](../article-next-common/README.md)创建 `article-next` 集群并导出
`KUBECONFIG`、`KUBECTL`。

```bash
python3 article-crd-conversion/run.py
```

脚本在 `tmp/article-next/crd-tls/` 生成仅用于实验的 CA、服务端证书和私钥，不写入
`evidence/`。Webhook 代码和 CRD 定义随仓库保存。

## 结果

- `converted-read.json`：同一对象在旧、新版本下的表示。
- `storage-version-switched.json`：切换 storage version 后的 CRD 状态。
- `written-via-beta.json`：通过新版本写回对象后的结果。
- `old-version-unserved.json`：停止服务旧版本后的读取结果。
- `webhook-log.json`：Conversion Webhook 日志。

脚本没有证明 `storedVersions` 中的旧版本已经按某个生产流程完成全量重写；删除旧版本前
仍需按目标版本和存储驱动选择人工重写或迁移工具。

## 清理

脚本删除实验 CRD 和 namespace。
