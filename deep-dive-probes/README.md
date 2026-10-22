# probes 实验

依次控制 startup、readiness 和 liveness，观察启动状态、EndpointSlice 和重启次数。

## 准备

先按[共用环境说明](../deep-dive-common/README.md)创建 `deep-dive` 集群。使用 Linux、Docker、kind、kubectl、Python 3、Git 和 curl；所有命令从本仓库根目录执行。

## 运行

```sh
export KUBECONFIG="$PWD/tmp/k8s-deep-dive/kubeconfig"
python3 deep-dive-probes/run.py
```

脚本固定使用 `kind-deep-dive` context，每次运行会删除并重建 `dd-probes` namespace。不要在该 namespace 存放需要保留的数据。条件等待或断言失败时，脚本非零退出；不能只看最后一次 apply 是否成功。

## 结果

`evidence/startup-blocked.json`、`readiness-failed.json` 和 `liveness-restarted.json` 保存三个阶段的容器状态，`not-ready-endpoint.json` 保存未就绪时的 EndpointSlice。脚本同时验证 readiness 失败不增加重启次数，以及恢复标记后 Pod 重新 Ready。

重新运行会覆盖本目录 `evidence/` 中的同名结果。仓库中已有结果是历史测量记录；本次是否通过，以本次脚本退出状态与新记录为准。

## 清理

只清理本主题的资源：

```sh
kubectl --context kind-deep-dive delete namespace dd-probes
```

所有主题结束后，按[共用环境说明](../deep-dive-common/README.md#清理)删除专用集群。
