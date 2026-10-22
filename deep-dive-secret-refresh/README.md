# secret-refresh 实验

比较同一 Secret 更新后，环境变量、普通卷、subPath 和应用启动缓存的取值。

## 准备

先按[共用环境说明](../deep-dive-common/README.md)创建 `deep-dive` 集群。使用 Linux、Docker、kind、kubectl、Python 3、Git 和 curl；所有命令从本仓库根目录执行。

## 运行

```sh
export KUBECONFIG="$PWD/tmp/k8s-deep-dive/kubeconfig"
python3 deep-dive-secret-refresh/run.py
```

脚本固定使用 `kind-deep-dive` context，每次运行会删除并重建 `dd-secret-refresh` namespace。不要在该 namespace 存放需要保留的数据。条件等待或断言失败时，脚本非零退出；不能只看最后一次 apply 是否成功。

## 结果

命令在本系列 `k8sdev` 实验仓库根目录执行。`evidence/before.json` 和 `after.json` 保存四个位置的实际读值；脚本只在普通 volume 确认更新后才比较，避免把传播尚未完成误判为永久不更新。

重新运行会覆盖本目录 `evidence/` 中的同名结果。仓库中已有结果是历史测量记录；本次是否通过，以本次脚本退出状态与新记录为准。

## 清理

只清理本主题的资源：

```sh
kubectl --context kind-deep-dive delete namespace dd-secret-refresh
```

所有主题结束后，按[共用环境说明](../deep-dive-common/README.md#清理)删除专用集群。

## 其他手动检查

下面的检查应在隔离测试集群中进行。直接读取 etcd 或调整加密配置需要控制面权限，操作前应确认备份与回滚路径。

### 1. 验证 API 表示

创建一个不含真实凭据的测试 Secret：

```bash
kubectl create secret generic secret-demo \
  --from-literal=username=demo \
  --from-literal=password=not-a-real-password

kubectl get secret secret-demo -o jsonpath='{.data.password}' | base64 -d
```

这只能证明 API 字段是可逆的 Base64，不代表 etcd 是否加密。

### 2. 验证静态数据加密

先检查每个 kube-apiserver 是否设置 `--encryption-provider-config`，再确认 `secrets` 的第一个 provider 不是 `identity`。最后从 etcd 读取测试对象的原始值，检查是否以 `k8s:enc:` 开头（如 `k8s:enc:aesgcm:v1:`、`k8s:enc:kms:v2:`）；未配置加密时原始值没有该前缀。

只检查启动参数仍不够：旧对象可能是在启用加密前写入的。应按官方迁移流程重写历史对象，并抽样验证 etcd 原始数据。

### 3. 验证 volume 与 env 更新差异

让测试 Pod 同时通过环境变量和 volume 使用同一个 Secret，更新 Secret 后分别观察：

```bash
kubectl patch secret secret-demo \
  --type merge \
  -p '{"stringData":{"password":"rotated-test-value"}}'
```

预期结果是：volume 文件最终变化，原进程的环境变量保持旧值。测试时不要用 `subPath`，否则 volume 也不会自动更新。
