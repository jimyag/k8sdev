# Kubernetes 镜像拉取与回收实验

验证三件事：镜像拉取失败如何进入 `ImagePullBackOff`；kind 节点上的镜像由 containerd
保存；kubelet 在镜像文件系统超过阈值后评估未使用镜像，并保留正在使用的镜像。

## 准备

镜像回收实验使用独立 `article-image` 单节点 kind 集群。kubelet 配置把镜像 GC 阈值设为
1% 和 0%，只用于隔离实验。

先按[从文章固定提交复现实验](../article-labs-reproduction.md)创建独立工作目录，
再在该目录执行后续命令。

```bash
export ARTICLE_TMP="$PWD/tmp/article-image"
bash article-image-lifecycle/setup.sh
export KUBECONFIG="$ARTICLE_TMP/kubeconfig"
export KUBECTL="$ARTICLE_TMP/tools/kubectl"
export KIND="$ARTICLE_TMP/tools/kind"
```

## 运行

```bash
python3 article-image-lifecycle/run.py
```

脚本会创建一个正常 Pod 和一个使用无效镜像的 Pod，按当前 ImageFS 用量构造未使用的
随机镜像层，载入 kind 节点后重启 kubelet 触发回收。构造大小不超过 6 GiB；所需空间
超过这个上限时脚本停止。`kind load` 后 containerd 不一定保留 repo tag，脚本按 Docker
镜像 ID 在节点镜像列表中确认载入结果。结果保存在 `evidence/`。

kind 节点的 ImageFS 与宿主机 Docker 数据目录共用整块磁盘，本次没有把宿主机用量压到
1% 以下。因此实验只能证明 kubelet 进入镜像 GC 评估、保留使用中的镜像，并可能删除部分
未使用镜像；`result.json` 里的 `low_threshold_reached` 和
`partial_unused_image_eviction_observed` 分别记录是否释放到低阈值、是否观察到删除记录。

## 结果

- `pull-failure.json`：`ImagePullBackOff` 等待原因与 Pod 事件。
- `images-before.json`、`images-loaded.json`、`images-after.json`：节点 containerd
  镜像列表。
- `kubelet-gc-lines.json`：kubelet 镜像回收评估日志。
- `result.json`：断言使用的容量、未使用镜像大小和最终镜像列表。

hostpath 无关，本实验不测试生产镜像仓库、跨节点镜像缓存或私有仓库凭据。

## 清理

```bash
"$KIND" delete cluster --name article-image
rm -r "$ARTICLE_TMP"
```
