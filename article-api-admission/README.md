# 准入、Webhook 故障与 Pod Security Admission

## 固定提交准备

先按[固定提交复现步骤](../article-labs-reproduction.md)设置文章链接中的 `ARTICLE_LABS_REV`，取得并核对独立工作目录。后续命令从该流程设置的 `$ARTICLE_ROOT` 执行；新终端也要先完成版本准备，不能直接使用当前分支目录。

2026-10-23 在 `zj` 的专用 kind 集群 `article-api` 验证。kind v0.33.0，节点镜像 `kindest/node:v1.35.1`；客户端和服务端 Kubernetes v1.35.1（`8fea90b45245ef5c8ba54e7ae044d3e777c22500`）。需要宿主机 Python 3、OpenSSL、Docker，以及预置 `python:3.12-alpine` 镜像。镜像仅运行 Python 标准库 TLS 实验服务，不承担业务服务。

匹配客户端的下载、SHA-256 校验、集群创建与独立 kubeconfig 见相邻 `article-api-rbac/README.md`。准备实验服务镜像并从 k8sdev 根目录运行：

```sh
export TMPDIR="$PWD/tmp/article-api"
export KUBECONFIG="$PWD/tmp/article-api/kubeconfig"
export KUBECTL="$PWD/tmp/article-tools/kubectl"
docker pull python:3.12-alpine
python3 article-api-admission/run.py
```

服务使用独立 Docker 容器 `article-api-webhook`，共享本实验 control-plane 容器的网络，在 19443 端口接受 TLS AdmissionReview。自签名测试证书写入忽略目录 `tmp/article-api/tls/`，SAN 对应本次节点 IP，caBundle 由运行时生成。无需修改宿主机防火墙。脚本退出会删除证书、服务容器和两个 WebhookConfiguration；不保存私钥。

Webhook 只匹配带 `article-admission=enabled` 标签的 Namespace 内 ConfigMap CREATE。修改器增加 annotation，校验器拒绝 `data.deny=true`；`timeout-` 前缀模拟处理耗时超过 `timeoutSeconds=1`。依次验证修改、显式拒绝、超时 Ignore（确认新策略已实际生效）、Ignore 不忽略显式拒绝、超时 Fail、服务停机 Fail、未匹配 Namespace 不受影响、服务停机 Ignore。另在 `article-psa` 验证内置 restricted 策略拒绝特权 Pod，并允许显式满足策略的 Pod。

结果与 Webhook 最小请求记录在 `evidence/result.json`，包含对象名和 AdmissionReview UID，不记录完整对象、token 或 TLS 私钥。脚本使用实际 annotation 检查配置传播，失败非零退出。测试服务仅为最小 fixture，没有生产服务的请求限制、并发保护或证书轮换。这里没有验证所有内置 admission 插件的相对顺序，也没有验证真实故障下的业务吞吐。

重新运行前或实验结束后清理：

```sh
"$KUBECTL" delete namespace article-admission article-psa --ignore-not-found --wait=true
"$KUBECTL" -n default delete configmap unmatched --ignore-not-found
```

全部 API 主题结束后删除专用集群：`kind delete cluster --name article-api`。
