# network-policy 实验

验证默认访问、入站隔离、允许规则并集、出站隔离和 DNS 放行。

## 准备

先按[共用环境说明](../deep-dive-common/README.md)创建 `deep-dive` 集群。使用 Linux、Docker、kind、kubectl、Python 3、Git 和 curl；所有命令从本仓库根目录执行。

## 运行

```sh
export KUBECONFIG="$PWD/tmp/k8s-deep-dive/kubeconfig"
python3 deep-dive-network-policy/run.py
```

脚本固定使用 `kind-deep-dive` context，每次运行会删除并重建 `dd-network-policy` namespace。不要在该 namespace 存放需要保留的数据。条件等待或断言失败时，脚本非零退出；不能只看最后一次 apply 是否成功。

## 结果

脚本重建实验 namespace，`ingress.json` 和 `egress.json` 保存通过的访问断言，`policies.json` 保存最终策略。真实排障时，可以沿同样顺序先验证应用与 Pod IP，再核对双向策略、Service 访问和 DNS，把每个失败定位到具体的一段路径。

重新运行会覆盖本目录 `evidence/` 中的同名结果。仓库中已有结果是历史测量记录；本次是否通过，以本次脚本退出状态与新记录为准。

## 清理

只清理本主题的资源：

```sh
kubectl --context kind-deep-dive delete namespace dd-network-policy
```

所有主题结束后，按[共用环境说明](../deep-dive-common/README.md#清理)删除专用集群。
