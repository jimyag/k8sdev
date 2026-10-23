# 身份认证与 RBAC 实验

## 固定提交准备

先按[固定提交复现步骤](../article-labs-reproduction.md)设置文章链接中的 `ARTICLE_LABS_REV`，取得并核对独立工作目录。后续命令从该流程设置的 `$ARTICLE_ROOT` 执行；新终端也要先完成版本准备，不能直接使用当前分支目录。

在 `zj` 的独立 kind 集群 `article-api` 上验证。2026-10-23 实际服务端和客户端均为 Kubernetes v1.35.1（`8fea90b45245ef5c8ba54e7ae044d3e777c22500`），kind v0.33.0。宿主机需要 Python 3、Docker，kind 节点镜像为 `kindest/node:v1.35.1`。不使用默认 kubeconfig。

在 Linux amd64 的 `zj` 上，从 k8sdev 根目录下载并校验匹配客户端（不依赖系统默认 kubectl）：

```sh
set -eu
mkdir -p tmp/article-tools tmp/article-api
export TMPDIR="$PWD/tmp/article-api"
curl -fsSL https://dl.k8s.io/release/v1.35.1/bin/linux/amd64/kubectl -o tmp/article-tools/kubectl
curl -fsSL https://dl.k8s.io/release/v1.35.1/bin/linux/amd64/kubectl.sha256 -o tmp/article-tools/kubectl.sha256
test "$(sha256sum tmp/article-tools/kubectl | cut -d ' ' -f 1)" = "$(cat tmp/article-tools/kubectl.sha256)"
chmod +x tmp/article-tools/kubectl
tmp/article-tools/kubectl version --client -o json
```

客户端应显示 `v1.35.1` 和提交 `8fea90b45245ef5c8ba54e7ae044d3e777c22500`。宿主机需预先安装 Docker、Python 3 和 kind v0.33.0，kind 命令在 `~/.local/bin/kind`。其他 API 主题共用专用集群，创建一次即可：

```sh
mkdir -p tmp/article-api
export TMPDIR="$PWD/tmp/article-api"
export KUBECONFIG="$PWD/tmp/article-api/kubeconfig"
export KUBECTL="$PWD/tmp/article-tools/kubectl"
~/.local/bin/kind create cluster --name article-api --image kindest/node:v1.35.1 --wait 120s
python3 article-api-rbac/run.py
```

`KUBECTL` 必须指向已经校验版本的 v1.35.1 客户端；用 `"$KUBECTL" version` 核对服务端和客户端。脚本新建 `article-rbac`、`article-rbac-other`，重复运行前删除这两个 Namespace。使用 TokenRequest 获取有效期 10 分钟的 ServiceAccount token，临时客户端配置位于忽略的 `tmp/article-api/reader-config.json`，退出时删除，不把 token 写进 evidence。

`evidence/result.json` 保存读取成功、日志/修改/跨 Namespace 拒绝、加入 `pods/log` 规则前后的权限检查和非法 token 的 Unauthorized。脚本对成功与拒绝结果做断言，失败时返回非零。实验没有测试外部 OIDC、客户端证书签发或真实 exec 会话。证书到身份的映射来自固定版本源码。

本实验资源清理：

```sh
"$KUBECTL" delete namespace article-rbac article-rbac-other --wait=true
```

四个 `article-api-*` 主题全部完成后才清理共享专用集群：`~/.local/bin/kind delete cluster --name article-api`。不要清理同主机其他集群。
