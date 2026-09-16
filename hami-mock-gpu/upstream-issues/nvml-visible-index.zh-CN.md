# 设备过滤后，NVML 返回的索引无法获取原设备

在 `874ab0319732981bc79cbc9b01c22c8fd00656e6` 上，配置两张 mock GPU，只向容器提供 `/dev/nvidia1`，出现以下结果：

```text
DeviceGetCount_v2()          → 1
DeviceGetHandleByIndex_v2(0) → 成功，返回句柄 h
DeviceGetIndex(h)            → 1
DeviceGetHandleByIndex_v2(1) → NVML_ERROR_INVALID_ARGUMENT
```

## 复现

使用 [测试 YAML](nvml-index-repro.yaml)，无需 HAMi 或真卡。节点需预先部署 mock 库；按实际环境修改 YAML 中的 `nodeSelector` 和 `hostPath.path`，并确保 `hami-tests` 命名空间存在。

```sh
kubectl --context kind-hami-test apply -f nvml-index-repro.yaml
kubectl --context kind-hami-test -n hami-tests logs -f nvml-index-repro
# 测试后清理
kubectl --context kind-hami-test delete -f nvml-index-repro.yaml
```

YAML 用空文件模拟 `/dev/nvidia1`，触发 mock 的 `os.Stat` 过滤逻辑。若日志提示 `ContainerCreating`，等待容器启动后重试。

## 原因及预期

`GetHandleByIndex` 按 `visibleDevices` 映射索引，`GetIndex` 却返回原始 `d.index`。

预期在设备集合不变时，返回的索引能获取到同一设备。想确认这里是否有意保留原始索引，以及这两个接口应如何保持一致；并不预设容器中唯一设备的 NVML 索引必须为 0。

## 对照测试

[候选补丁](patches/01-nvml-visible-index.patch)单独维护可见索引，保留物理设备号、UUID 和 PCI 身份。同一 YAML 仅更换挂载的库，实测结果如下：

| 库 | 返回索引 | 用返回索引获取设备 | Pod 退出码 |
|---|---:|---|---:|
| 原始库 | 1 | 越界 | 1 |
| 补丁库 | 0 | 返回同一句柄，物理设备号仍为 1 | 0 |

日志：[修改前](evidence/yaml-baseline.log)、[修改后](evidence/yaml-patched.log)。补丁尚未与真驱动的容器行为对照。
