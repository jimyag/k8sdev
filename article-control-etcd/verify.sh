#!/usr/bin/env bash
set -euo pipefail
node=article-control-control-plane
id=$(docker exec "$node" crictl ps --name etcd -q)
ec() { docker exec "$node" crictl exec "$id" etcdctl --endpoints=http://127.0.0.1:3379 --command-timeout=3s "$@"; }
deadline=$((SECONDS + 60))
until ec endpoint health; do
  if (( SECONDS >= deadline )); then exit 1; fi
done
before=$(ec get /article/before --print-value-only)
after=$(ec get /article/after --print-value-only)
test "$before" = snapshot-value
test -z "$after"
echo "restored before=$before; after-snapshot key absent"
ec endpoint status -w json
# 旧 revision 的历史读取应被拒绝，而非把过期缓存当成当前状态。
if ec get /article/before --rev=2; then
  echo 'ERROR: old revision unexpectedly readable' >&2
  exit 1
fi
echo 'old revision rejected after mark-compacted'
test "$(ec get /registry/deployments/control-ha/baseline --keys-only)" = /registry/deployments/control-ha/baseline
echo 'snapshot contains Kubernetes Deployment storage key'
if ec watch /article/ --prefix --rev=2; then
  echo 'ERROR: old watch unexpectedly accepted' >&2
  exit 1
fi
echo 'old watch rejected after mark-compacted'
