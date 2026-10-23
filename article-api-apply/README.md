# Server-Side Apply 实验

2026-10-23 在 `zj` 的 `article-api` kind 集群验证；kind v0.33.0，节点镜像 `kindest/node:v1.35.1`，客户端与服务端均为 v1.35.1（`8fea90b45245ef5c8ba54e7ae044d3e777c22500`）。需要 Docker、kind、Python 3 和匹配版本 kubectl。

匹配客户端的下载、SHA-256 校验和集群创建完整命令见相邻 `article-api-rbac/README.md`，完成后从 k8sdev 根目录运行：

```sh
export TMPDIR="$PWD/tmp/article-api"
export KUBECONFIG="$PWD/tmp/article-api/kubeconfig"
export KUBECTL="$PWD/tmp/article-tools/kubectl"
python3 article-api-apply/run.py
```

脚本创建 `article-apply`，在 ConfigMap 上依次验证两个 manager 修改同字段被拒绝、不同字段共存、原 manager 省略字段导致删除、强制接管、原 manager 再次冲突，以及普通 Merge Patch 可以修改 Apply 管理的字段。断言失败返回非零，完整字段归属保存在 `evidence/result.json`，组件版本在 `evidence/version.json`。这不是 Deployment 控制器实验，也没有测试所有 CRD 列表合并拓扑。

重新运行前清理本主题 Namespace：

```sh
"$KUBECTL" delete namespace article-apply --wait=true
```

全部 API 主题完成后删除专用集群 `kind delete cluster --name article-api`。不要删除其他集群或 Namespace。
