#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export KUBECONFIG="$PWD/../tmp/article-control/kubeconfig"
K="$PWD/../tmp/article-tools/kubectl"
node=article-control-control-plane
id=$(docker exec "$node" crictl ps --name etcd -q)
ec() { docker exec "$node" crictl exec "$id" etcdctl --endpoints=https://127.0.0.1:2379 --cacert=/etc/kubernetes/pki/etcd/ca.crt --cert=/etc/kubernetes/pki/etcd/server.crt --key=/etc/kubernetes/pki/etcd/server.key --command-timeout=5s "$@"; }
ec version
ec put /article/before snapshot-value
ec snapshot save /var/lib/etcd/article-snapshot.db
ec put /article/after after-snapshot
docker pause article-control-control-plane2
trap 'docker unpause article-control-control-plane2 >/dev/null 2>&1 || true; docker unpause article-control-control-plane3 >/dev/null 2>&1 || true' EXIT
ec put /article/one-down quorum-ok
docker pause article-control-control-plane3
if ec put /article/two-down must-fail; then
  echo 'ERROR: minority unexpectedly accepted write' >&2
  exit 1
fi
echo 'two members unavailable: write rejected'
ec get /article/before --consistency=s
docker unpause article-control-control-plane2
docker unpause article-control-control-plane3
trap - EXIT
"$K" wait node --all --for=condition=Ready --timeout=120s
ec endpoint health
docker exec "$node" crictl exec "$id" etcdutl snapshot restore /var/lib/etcd/article-snapshot.db --data-dir=/var/lib/etcd/article-restored --name=restored --initial-cluster=restored=http://127.0.0.1:3380 --initial-advertise-peer-urls=http://127.0.0.1:3380 --bump-revision=1000000000 --mark-compacted
echo 'snapshot restored into isolated data directory; start restored.sh for readback'
