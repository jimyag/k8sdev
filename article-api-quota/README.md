# LimitRange、ResourceQuota 与调度容量

## 固定提交准备

先按[固定提交复现步骤](../article-labs-reproduction.md)设置文章链接中的 `ARTICLE_LABS_REV`，取得并核对独立工作目录。后续命令从该流程设置的 `$ARTICLE_ROOT` 执行；新终端也要先完成版本准备，不能直接使用当前分支目录。

2026-10-23 在 `zj` 的独立 kind 集群 `article-api` 验证；kind v0.33.0，`kindest/node:v1.35.1`，服务端与客户端 Kubernetes v1.35.1（`8fea90b45245ef5c8ba54e7ae044d3e777c22500`）。需要 Python 3、Docker 和匹配版本 kubectl。集群创建方法见相邻 `article-api-rbac/README.md`。

先按相邻 `article-api-rbac/README.md` 下载并校验 v1.35.1 客户端、创建专用集群，再从 k8sdev 根目录执行：

```sh
export TMPDIR="$PWD/tmp/article-api"
export KUBECONFIG="$PWD/tmp/article-api/kubeconfig"
export KUBECTL="$PWD/tmp/article-tools/kubectl"
python3 article-api-quota/run.py
```

`policy.yaml` 同时设置单容器默认值、单容器上限与 Namespace 总配额。`article-quota` 验证默认值注入、单容器 CPU 上限拒绝和两个 Pod 后配额拒绝；`article-quota-capacity` 使用宽松配额，创建请求 10000 CPU 的 Pod，以 `kubectl wait` 等待 `Unschedulable`，证明准入成功不保证可调度。该 CPU 请求用于制造确定的资源不足，不代表实际消耗宿主机 CPU。

`evidence/result.json` 保存实际 Pod 资源值、拒绝消息、quota status 和调度条件；每项行为由脚本断言，失败非零退出。不依赖容器镜像成功运行来证明 API 准入行为。未测试并发 quota 竞争、删除后回收延迟或 Pod 级资源预算。

重复运行前或本主题结束后：

```sh
"$KUBECTL" delete namespace article-quota article-quota-capacity --wait=true
```

所有 API 主题完成后才删除共享专用集群 `kind delete cluster --name article-api`。
