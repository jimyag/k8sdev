#!/usr/bin/env bash
set -euo pipefail
node=article-control-control-plane
# 独立数据目录、独立端口；不替换 Kubernetes 使用的任何成员。
docker exec "$node" ctr -n k8s.io run --rm --net-host --mount type=bind,src=/var/lib/etcd/article-restored,dst=/restore,options=rbind:rw registry.k8s.io/etcd:3.6.6-0 article-etcd-restored /usr/local/bin/etcd --name=restored --data-dir=/restore --listen-client-urls=http://127.0.0.1:3379 --advertise-client-urls=http://127.0.0.1:3379 --listen-peer-urls=http://127.0.0.1:3380 --initial-advertise-peer-urls=http://127.0.0.1:3380 --initial-cluster=restored=http://127.0.0.1:3380
