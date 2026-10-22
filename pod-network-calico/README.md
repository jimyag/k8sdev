# Calico 与 kube-proxy 的 Pod 网络路径

使用 Calico 作为主 CNI，验证同节点 Pod、跨节点 Pod、ClusterIP、DNS、hairpin、出站 NAT、NodePort 与 NetworkPolicy。Service 只有一个远端后端，避免负载均衡随机选端点影响抓包判断。

## 环境

实测主机为 `zj`，Linux `6.12.74+deb13+1-amd64`，kind `v0.33.0`。需要 Docker、Python 3 和可执行的 kind；不要求宿主机安装 kubectl，脚本使用控制面节点内的 kubectl 与 admin kubeconfig。需要能访问官方 Calico 清单、镜像仓库与节点的 Debian 软件源。

- Kubernetes：官方 `kindest/node:v1.35.1`，源码提交 `8fea90b45245ef5c8ba54e7ae044d3e777c22500`。
- Calico：`v3.33.0`，源码提交 `fbaa371111636a37ecc82625fce8453064a7fff2`。
- 网络：IPv4，Pod CIDR `10.244.0.0/16`，Service CIDR `10.96.0.0/12`。
- kube-proxy：iptables 模式。Calico：标准 iptables 数据面，VXLAN Always，禁用 BGP、IPIP、eBPF 和原生 nftables 数据面。

三节点集群名固定为 `pod-network-calico`，工作负载通过 nodeName 放到两个 worker。运行前确认不存在同名集群，且本实验网段不会与主机已有网络冲突。脚本不会接管或重置已有集群。

## 启动与验证

在 `zj` 的本仓库根目录执行：

```bash
KIND_BIN="$HOME/.local/bin/kind" bash pod-network-calico/setup.sh
python3 pod-network-calico/verify.py
```

`setup.sh` 先创建不带 kindnet 的集群，将固定版本 Calico 镜像导入节点，再用 kustomize 修改官方清单后安装。地址池参数在首次启动前设置；事后修改 DaemonSet 环境变量不会自动迁移已经存在的 IPPool。工具 tcpdump、conntrack、ipset 仅安装在本次 worker 节点容器中。

验证脚本在新建 TCP 连接上检查：

| 场景 | 通过条件 |
| --- | --- |
| 同节点与跨节点直连 | 服务端返回正确客户端 Pod IP |
| ClusterIP 与 DNS 名称 | 远端服务端返回客户端 Pod IP |
| Service 前后抓包 | 客户端 veth 上可见 ClusterIP:80；节点 eth0 的 VXLAN 内层可见后端 Pod IP:8080 |
| 跨节点封装 | 捕获 UDP 4789，内层包含实际客户端和后端地址 |
| 后端访问自己的 Service | 请求成功且源地址发生转换 |
| Pod 访问集群外目标 | 独立 Docker 容器看到客户端节点 eth0 地址 |
| 外部访问 NodePort | 后端看到入口节点去往远端 Pod 路由所选的源地址 |
| ingress 策略 | 无允许标签时，Pod IP 与 Service 均超时；同节点其他后端仍能访问；添加标签后两条路径恢复 |

外部目标是加入 kind Docker 网络的临时 Python HTTP 容器，不是公网服务。验证脚本在 `finally` 中移除它，并撤销测试策略与标签。HTTP 服务返回对端 IP，供脚本断言；这里没有做公网、BGP、IPIP 或 eBPF 数据面验证。

所有失败返回非零状态。抓包等待 tcpdump 明确进入监听后才发请求；策略变更按请求结果进行有截止时间的轮询。测试中的每次 urllib 请求都关闭连接，避免已有 conntrack 状态影响新策略判断。

## 查看结果

脚本将本次输出写入 `evidence/`，重复运行会覆盖该目录中的对应结果。仓库内的文件是 2026-10-23 在 `zj` 的实测快照，不是固定地址预期值。

- `results.json`：各访问路径的返回值及策略结果。
- `topology.json`、`versions.txt`、`ippools.json`、`kube-proxy.txt`：运行条件。
- `pod-network.txt`、`proxy-arp.txt`：Pod /32 地址、默认路由及宿主机 proxy ARP。
- `*-routes.txt`：节点路由、VXLAN 设备、FDB 与邻居表。
- `clusterip-before-dnat.txt`、`clusterip-vxlan.txt`、`cross-node-vxlan.txt`：文本抓包。
- `nat-rules.txt`、`remote-nat-rules.txt`、`conntrack.txt`、`remote-route-get.json`：NAT、连接状态和源地址选择。
- `policy-*-rules.txt`、`policy-*-ipsets.txt`：策略拒绝与标签放行后的过滤规则、地址集合。

查看实时状态可以使用：

```bash
docker exec pod-network-calico-control-plane \
  kubectl --kubeconfig=/etc/kubernetes/admin.conf -n pod-network get pods,svc,endpointslices -o wide
docker exec pod-network-calico-worker ip route
docker exec pod-network-calico-worker iptables-save -t nat
```

tcpdump 在发送方向可能显示 checksum offload 尚未完成时的校验和提示；应结合接收方向、连接完成和业务响应判断，不能仅凭发送侧的 `incorrect` 字样认定传输损坏。

## 源码入口

- [Calico CNI ADD 与地址分配](https://github.com/projectcalico/calico/blob/v3.33.0/cni-plugin/pkg/k8s/k8s.go)：`CmdAddK8s`、`DoNetworking` 调用与端点更新。
- [Calico Linux 接口和路由](https://github.com/projectcalico/calico/blob/v3.33.0/cni-plugin/pkg/dataplane/linux/dataplane_linux.go)：`DoWorkloadNetnsSetUp`、`SetupRoutes`、`configureSysctls`。
- [WorkloadEndpoint 的 Kubernetes 存储](https://github.com/projectcalico/calico/blob/v3.33.0/libcalico-go/lib/backend/k8s/resources/workloadendpoint.go)：Pod annotations 更新。
- [Felix 路由计算](https://github.com/projectcalico/calico/blob/v3.33.0/felix/calc/l3_route_resolver.go)与 [VXLAN 编程](https://github.com/projectcalico/calico/blob/v3.33.0/felix/dataplane/linux/vxlan_mgr.go)：IPAM block、VTEP、路由及 FDB。
- [Calico NAT](https://github.com/projectcalico/calico/blob/v3.33.0/felix/rules/nat.go)与[端点策略](https://github.com/projectcalico/calico/blob/v3.33.0/felix/rules/endpoints.go)：地址集合、masquerade 与 ingress/egress 链。
- [kube-proxy iptables proxier](https://github.com/kubernetes/kubernetes/blob/v1.35.1/pkg/proxy/iptables/proxier.go)：缓存同步、规则生成、DNAT、masquerade。

本实验使用发行版二进制，未插入自定义日志。源码用于解释实现，路径结论由路由、规则、连接状态和抓包交叉验证。

## 清理

先确认名称属于本实验，再删除这个集群：

```bash
"$HOME/.local/bin/kind" delete cluster --name pod-network-calico
```

若强行中断 Python 进程导致清理未执行，用 `docker ps -a --filter name=pod-network-calico-outside` 确认后，删除同名实验容器。宿主机 Docker 镜像缓存不属于集群资源，默认保留。
