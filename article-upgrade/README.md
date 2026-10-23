# Kubernetes 维护与补丁升级实验

## 固定提交准备

先按[固定提交复现步骤](../article-labs-reproduction.md)设置文章链接中的 `ARTICLE_LABS_REV`，取得并核对独立工作目录。后续命令从该流程设置的 `$ARTICLE_ROOT` 执行；新终端也要先完成版本准备，不能直接使用当前分支目录。

在 `zj` 的独立 kind 集群中验证 PDB 阻塞维护、替代副本、已移除 API 端点，以及 Kubernetes v1.35.1 到 v1.35.2 的实际补丁升级。集群为一个控制面、两个工作节点，不代表生产高可用拓扑。本实验不验证跨小版本升级、etcd 升级、证书轮换、业务 HTTP 请求连续性或生产插件兼容性。

## 环境与准备

已验证条件：Linux 主机 `zj`，kind v0.33.0，Docker，Python 3，curl、sha256sum、Git、grep，以及 `kindest/node:v1.35.1`。kind 可执行文件位于 `$HOME/.local/bin`。需要能够下载 dl.k8s.io 二进制和 registry.k8s.io 镜像，且当前用户能够运行 Docker。脚本不依赖宿主默认 kubeconfig。

完成固定提交准备后，从 `zj` 的 `$ARTICLE_ROOT` 工作目录执行：

```sh
cd "$ARTICLE_ROOT"
export TMPDIR="$PWD/tmp/article-upgrade"
mkdir -p "$TMPDIR"
bash article-upgrade/setup.sh
python3 article-upgrade/run.py
```

`setup.sh` 下载 v1.35.1 kubectl 和 v1.35.2 kubeadm/kubelet/kubectl，并用官方 SHA-256 校验下载结果。它拒绝复用已经存在的 `article-upgrade` 集群，所有 kubeconfig、下载物和宿主临时文件均写入仓库 `tmp/`。v1.35.1 客户端位于 `tmp/article-tools`，避免误用本机 v1.37.1 kubectl。

kind 节点共享宿主内核，但默认不包含对应的 `/boot/config-$(uname -r)`。本轮第一次 kubeadm 预检因缺少该配置而失败；`run.py` 现在先检查宿主实际配置，再将它复制到本轮三个节点的同名路径。没有使用 `--ignore-preflight-errors`，不安装或加载宿主内核模块。宿主缺少匹配配置时脚本停止。

源码版本：起始 Kubernetes v1.35.1，提交 `8fea90b45245ef5c8ba54e7ae044d3e777c22500`；目标 v1.35.2，提交 `fdc9d74cbf2da6754ebf81d56f80ae2948cd6425`。目标 kubeadm 的 static Pod 升级与版本策略按 v1.35.2 源码解释。

## 执行与断言

脚本首先检查 context 内只有本实验的三个节点且 kubelet 均为 v1.35.1，防止把脚本作用到其他集群。它创建专用 Namespace、Deployment 和 PDB：

- 单副本、`minAvailable: 1` 时尝试 drain，必须因预算不足失败，并保留原 Pod UID。
- 解除 cordon 并扩为两个副本，确认分散在两个工作节点后再次 drain，必须成功；替代副本 UID 改变并在剩余工作节点 Ready。
- 请求 `/apis/extensions/v1beta1/deployments` 必须返回 NotFound，`apps/v1` discovery 必须可用。这个检查验证旧端点已移除，不执行历史对象的存储版本迁移。
- 安装匹配目标版本的 kubeadm，执行 `upgrade plan` 和 `upgrade apply`，显式关闭本轮不测的 etcd 升级与证书续期。
- 确认 API Server 已为 v1.35.2，再逐节点 drain、升级节点配置和 kubelet 二进制、重启 kubelet，等待新版本 Ready 后 uncordon。
- 最后确认三节点均报告 v1.35.2，kube-proxy rollout 完成，两副本恢复 Ready。

脚本采用条件轮询和明确超时；预期失败必须匹配预算错误或 NotFound，不能将任意错误都当作实验通过。脚本打印 `PASS` 只表示上述断言通过。升级过程中遇到意外失败会非零退出，保留集群供检查；不能在部分升级后直接重跑并声称从旧版本完整执行，应先检查状态，或清理本实验后重新开始。

## 查看结果

精简证据保存在 `article-upgrade/evidence/`：

| 文件 | 对应判断 |
| --- | --- |
| before-version.json | 起始客户端和 API Server 均为 v1.35.1 |
| drain-blocked.json | 预算拒绝和 drain 超时，不等于旧 Pod 已被删除 |
| drain-recovered.json | 维护前后 Pod UID 与节点位置 |
| removed-api.json | 旧端点拒绝与 apps/v1 可用 |
| upgrade-plan.txt、upgrade-apply.txt | kubeadm 计划及本轮实际执行阶段 |
| control-plane-upgraded.json | 控制面升级后 kubelet 仍为 v1.35.1 的中间状态 |
| after-version.json、after-nodes.json | API Server 与三节点 kubelet 的最终版本 |

可以用独立配置检查运行中的集群：

```sh
export KUBECONFIG="$PWD/tmp/article-upgrade/kubeconfig"
tmp/article-tools/kubectl --context kind-article-upgrade get nodes
tmp/article-tools/kubectl --context kind-article-upgrade get pods -n article-upgrade -o wide
tmp/article-tools/kubectl --context kind-article-upgrade get pods -n kube-system
```

本轮已实际通过全部断言。kind 的容器节点便于抛弃和重建，本轮对其内部执行 kubeadm 仅用于观察升级机制，不把这些容器内二进制安装方式作为生产系统的包管理方案。独立 Pod Ready 也不代表某个实际应用的数据一致性和请求 SLO 已经通过。

## 清理

只删除本实验集群；不要把名称替换为其他现有集群：

```sh
export PATH="$HOME/.local/bin:$PATH"
export TMPDIR="$PWD/tmp/article-upgrade"
kind delete cluster --name article-upgrade
python3 - <<'PY'
from pathlib import Path
import shutil
target = Path('tmp/article-upgrade')
assert target.resolve().parent == Path('tmp').resolve()
if target.exists():
    shutil.rmtree(target)
PY
```

`tmp/article-tools/kubectl` 是本轮文章实验的共享工具；确认其他文章实验不再使用后再清理。保留主题目录内的脚本、YAML 和精简证据，不保存 kubeconfig、下载二进制或集群证书。
