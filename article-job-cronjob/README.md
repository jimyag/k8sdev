# Job 与 CronJob 控制器实验

验证四个可以观察的结果：

- Indexed Job 为四个完成项创建索引 0 到 3 的 Pod。
- `podFailurePolicy` 命中退出码 42 时直接判定 Job 失败，不再按普通退避重试。
- `backoffLimit=1` 最多创建两个 Pod，然后写入 `BackoffLimitExceeded`。
- `concurrencyPolicy: Forbid` 在前一个 Job 仍运行时不再创建重叠 Job。

## 准备与运行

先按[公共环境](../article-next-common/README.md)创建 `article-next` 集群并导出
`KUBECONFIG`、`KUBECTL`。

```bash
python3 article-job-cronjob/run.py
```

CronJob 使用每分钟一次的调度周期，脚本需要等待两个调度点。全部条件使用带超时的
轮询，不使用固定 sleep 判断 Job 完成；只有重叠检查需要跨过一个真实调度周期。

## 结果

`evidence/` 保存 Job、Pod、条件和索引：

- `indexed-job.json`
- `pod-failure-policy.json`
- `backoff-limit.json`
- `cronjob-forbid.json`
- `result.json`

脚本没有测试 CronJob 错过多个调度窗口、时区变化和 TTL 清理。

## 清理

脚本删除自己的 namespace。
