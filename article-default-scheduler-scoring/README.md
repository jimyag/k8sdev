# 默认 kube-scheduler 的软污点与节点亲和打分

两个等容量的候选节点都能接纳 Pod。两份 Pod 都偏好 a，区别只在是否容忍 a 的 `PreferNoSchedule` 污点。脚本核对两项插件的加权分及 `spec.nodeName`，输出总分与其他插件日志。

本次在本机 OrbStack arm64、kind v0.33.0 运行。节点容器基底为 `kindest/node:v1.37.0`，配置要求控制面使用 v1.37.2。脚本核对 API Server 和调度器的实际版本。实验的两个候选都是 API 中的合成 Node；无需工作节点加入，验证到 `PodScheduled` 为止。未在 `zj` 运行。

从仓库根目录执行，使用独立的 `default-score` 集群名：

```sh
mkdir -p tmp/default-score-lab
kind create cluster --name default-score --image kindest/node:v1.37.0 \
  --config article-default-scheduler-scoring/kind.yaml \
  --kubeconfig "$PWD/tmp/default-score-lab/kubeconfig" --retain
```

在 OrbStack arm64 上可给 `kind` 设置 `DOCKER_DEFAULT_PLATFORM=linux/arm64`。本次节点内拉取 v1.37.2 镜像耗时超过初始化等待，使用了 Docker 侧预拉并导入：将 `registry.k8s.io/kube-apiserver:v1.37.2`、`registry.k8s.io/kube-controller-manager:v1.37.2`、`registry.k8s.io/kube-scheduler:v1.37.2` 预拉到本地；启动 kind 后，一旦控制面节点的 `ctr version` 可用，将本地镜像导入它的 `k8s.io` namespace。不要复用已有集群。

```sh
docker save --platform linux/arm64 registry.k8s.io/kube-apiserver:v1.37.2 \
  registry.k8s.io/kube-controller-manager:v1.37.2 registry.k8s.io/kube-scheduler:v1.37.2 |
  docker exec -i default-score-control-plane ctr -n k8s.io images import --platform linux/arm64 -
```

API Server 就绪、调度器开始工作后运行脚本：

```sh
bash article-default-scheduler-scoring/run.sh
```

脚本只接受名为 `default-score` 的 kind 控制面，创建两个合成节点和两个 Pod，退出时移除这些对象。成功输出见 [evidence.txt](evidence.txt)。最后清理集群：

```sh
kind delete cluster --name default-score --kubeconfig "$PWD/tmp/default-score-lab/kubeconfig"
```
