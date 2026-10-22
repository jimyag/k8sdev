# Kubernetes 深挖实验环境

`deep-dive-*` 主题共用一个专用三节点 kind 集群。各目录的 README 给出运行命令和结果说明；从博客进入时，使用链接中固定的提交，避免配置与文章结果不一致。

## 准备

在 Linux 主机上安装 Docker、kind、kubectl、Python 3、Git 和 curl。当前用户需要能够运行 Docker，主机需要能够下载 GitHub 上的清单和容器镜像。Python 脚本只使用标准库。

首次获取仓库时，将下面的占位符替换为博客链接中的提交号：

```sh
git clone https://github.com/jimyag/k8sdev.git k8sdev-deep-dive
cd k8sdev-deep-dive
git checkout '博客链接中的完整提交号'
```

以下命令均从仓库根目录执行。先检查工具和 Docker，再创建环境：

```sh
command -v kind kubectl python3 git curl
docker info
kind get clusters
bash deep-dive-common/setup.sh
export KUBECONFIG="$PWD/tmp/k8s-deep-dive/kubeconfig"
kubectl --context kind-deep-dive get nodes
```

`setup.sh` 创建名为 `deep-dive` 的集群，使用 Kubernetes v1.35.1，安装 Calico v3.31.2、CSI hostpath 测试驱动和 Metrics Server v0.8.0，并预加载 Python 镜像。它使用独立 kubeconfig，不修改默认 kubeconfig。Metrics Server 跳过 kubelet 证书校验的设置只用于这个实验环境。

同名集群已存在时，先检查是否就是本系列环境；准备完成的集群直接运行主题脚本，不要再次执行 setup。setup 中断时，保留错误输出检查对应组件；需要从头开始时，按下方清理步骤删除专用集群和下载目录，再重跑。

## 运行主题

例如运行 CPU 实验：

```sh
export KUBECONFIG="$PWD/tmp/k8s-deep-dive/kubeconfig"
python3 deep-dive-cpu/run.py
```

各主题会重建自己的 `dd-*` namespace，并覆盖主题目录中 `evidence/` 的同名文件。逐个运行主题，尤其不要同时执行暂停节点、停止 kubelet 与其他实验。节点故障和终止实验需要直接操作本机 Docker 中的 kind 节点，因此应在创建集群的主机上运行脚本。

历史环境与镜像记录见 [environment.json](evidence/environment.json)。记录说明历史测量条件，不表示当前主机已经启动对应集群；新一轮是否成功应以脚本退出状态和新结果为准。

## 清理

确认不再需要这个集群内的测试数据后，在创建集群的主机执行：

```sh
kind delete cluster --name deep-dive
```

需要重新运行 setup 时，再清除它下载的 CSI 仓库和独立 kubeconfig：

```sh
rm -r tmp/k8s-deep-dive
```

这里删除的是本系列专用环境，不要把路径或集群名替换成业务环境。各主题 `evidence/` 中的测量记录保留在工作目录中，可用 `git diff` 查看。
