# Pod 生命周期源码实验

在 Linux amd64 上编译带日志的 Kubernetes v1.37.1，以 kind 运行创建、就绪变化、容器重启、sandbox 重建、控制器补副本与删除场景。源码固定为 `f78e722310e50bcaca9276be22276d9e91d91308`，插桩补丁为 `instrumentation.patch`。

## 环境与构建

需要 Docker、Git、kind v0.33.0、kubectl、Python 3 和 GNU tar。构建容器使用 Go 1.27.1，最多使用 8 个 CPU；预留 16 GiB 内存和 20 GiB 磁盘空间。所有命令从 k8sdev 仓库根目录执行，先检出博客链接固定的提交。

```bash
bash pod-lifecycle-source/build.sh
docker pull python:3.12-alpine
bash pod-lifecycle-source/setup.sh
export KUBECONFIG="$PWD/tmp/pod-lifecycle/kubeconfig"
python3 pod-lifecycle-source/run.py
python3 pod-lifecycle-source/failure-paths.py
```

网络需要镜像代理时，给构建脚本传入可访问的镜像源。例如本次 zj 环境：

```bash
BASE_IMAGE=localhost:10110/kindest/base:v20260820-69b56db7 \
K8S_MIRROR=localhost:10114 \
DOCKER_MIRROR=localhost:10110 \
bash pod-lifecycle-source/build.sh
```

这三个地址是 zj 的本地镜像服务，其他机器不要照抄。kind builder 仍可能联网解析基础镜像与附加镜像。实验 Kubernetes 镜像只供本地使用，不向镜像仓库推送。组件镜像使用 kind 基础镜像以提供 kube-proxy 所需工具，体积大于官方发行镜像。

`build.sh` 克隆源码并校验提交，在 `tmp/pod-lifecycle` 内应用补丁、编译二进制、打包组件镜像，再调用 kind 的原生 tarball builder。Go 的 VCS 自动标记因容器挂载的目录所有权而禁用；Kubernetes 版本字段显式写入 release、提交与 `gitTreeState=dirty`。源文件修改仅添加日志，不修改业务分支。

`setup.sh` 创建专用双节点集群 `pod-lifecycle`，使用独立 kubeconfig。不要对已有的同名集群重复执行；先按下文清理。

## 场景与结果

`workload.yaml` 包含 Deployment、普通 init、原生 sidecar、带三种探针的应用容器、Service、ServiceAccount、ConfigMap、测试 Secret、PVC、普通/内存 emptyDir 和 downwardAPI。默认准入还会注入 ServiceAccount projected 卷。

`run.py` 依次执行：

- 创建并等待 Pod、PVC 与 EndpointSlice 就绪。
- 令 readiness 失败，核对端点变化和容器 ID 不变。
- 杀死应用进程，核对同一 Pod UID、sandbox 与 init 容器得到保留。
- 令 liveness 失败，核对容器重启与卷数据保留。
- 令应用退出 42，触发 `RestartAllContainers`，比较普通 init、sidecar 和应用容器的新 ID。
- 停止 sandbox，比较同一 UID 下的新 sandbox、容器与卷数据。
- 添加实验 Finalizer 后删除 Pod，观察旧对象终止、EndpointSlice 变化以及 ReplicaSet 创建的新 UID。
- 去掉 Finalizer，缩容到零，等待两个 UID 的节点目录清理，检查独立引用对象仍然存在。
- 创建 `restartPolicy: Never` 的裸 Pod，分别验证 `Succeeded`、`Failed` 与零重启次数。

输出写入 `pod-lifecycle-source/evidence/`。`result.json` 只有断言全部通过才生成；`timeline.json` 对照每个阶段的 UID、sandbox/container ID、IP、PID 与重启计数。各阶段的 API/CRI JSON 和节点文本提供原始依据；`*-trace.log` 保存新增的 `LIFECYCLE` 日志。所有日志均使用实验命名空间；不读取 token 文件或真实 Secret 内容。

`failure-paths.py` 在主场景之后运行：等待旧 UID 的运行时对象被 GC 回收，确认网络命名空间和 Pod cgroup 消失；再验证调度失败、缺失 ConfigMap 阻塞挂载、补齐后同一 UID 恢复，以及内存超限导致的 OOMKilled/OnFailure 重启。通过后生成 `failure-paths-result.json`。

本次 zj 运行的两个结果文件均为 `passed: true`。构建和运行版本见 `evidence/build.json`、`evidence/version.json`。日志可能包含同一集群内的前期调试记录，以 `timeline.json` 中的 UID 筛选本次完成的主场景，不按相邻时间或同名资源拼接调用链。

一次运行会修改实验对象。重跑前删除整个实验命名空间并确认删除完成；若上次在 Finalizer 场景中断，先手动移除实验 Pod 上的 `lab.example.com/observe` Finalizer。不要批量移除其他业务 Finalizer。

```bash
kubectl -n lifecycle-lab get pods
# 仅当上一次运行留下实验 Finalizer 时，对列出的那个 Pod 执行：
kubectl -n lifecycle-lab patch pod <pod-name> --type=merge \
  -p '{"metadata":{"finalizers":null}}'
kubectl delete namespace lifecycle-lab --wait=true
python3 pod-lifecycle-source/run.py
python3 pod-lifecycle-source/failure-paths.py
```

## 清理

保存需要的 evidence 后，删除本实验集群。构建缓存、源码与打包文件都在专用目录内，可随后删除；不清理其他集群或 Docker 数据卷。

```bash
kind delete cluster --name pod-lifecycle
rm -r tmp/pod-lifecycle
```

本实验使用 kindnet 与 local-path 卷。CSI 的 attach/detach、设备插件、DRA、独占 CPU/NUMA、Windows 容器不由这些运行结果证明；相关可选路径应另外配备对应驱动或节点条件。Pod 引用某个对象，也不代表 Pod 拥有或负责删除它。
