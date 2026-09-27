# k8sdev

Kubernetes 自定义资源、调度和设备插件实验。

[![Check](https://github.com/jimyag/k8sdev/actions/workflows/check.yaml/badge.svg)](https://github.com/jimyag/k8sdev/actions/workflows/check.yaml)

## 实验

- [自定义调度器](./scheduler/)
- [Extended Resource Device Plugin 实验](./extended-resource/)：用模拟 FPGA 设备验证节点资源注册、Pod 调度和 Device Plugin 分配。
- [HAMi mock GPU 测试](./hami-mock-gpu/)：共享、配额、调度与资源回收实验；[操作说明](https://jimyag.com/posts/hami-mock-gpu-testing/)。
- [kind HPA 扩缩容实验](./hpa/)：CPU、自定义指标、真实队列、多指标决策与扩缩容边界。

## 开发

仓库使用 Go 1.23。CI 使用 golangci-lint 检查新增问题、编译全部 Go 包，并运行设备插件测试；其他实验依赖各自的 Kubernetes 环境。

```bash
go build ./...
go test ./extended-resource
```
