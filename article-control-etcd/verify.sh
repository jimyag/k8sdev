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
# 必须识别 compaction 错误，连接失败或其他错误不能算验证通过。
expect_compacted() {
  local output
  if output=$(ec "$@" 2>&1); then
    echo 'ERROR: old revision unexpectedly accepted' >&2
    return 1
  fi
  printf '%s\n' "$output"
  if [[ "$output" != *"required revision has been compacted"* ]]; then
    echo 'ERROR: expected a compaction error' >&2
    return 1
  fi
}
expect_compacted get /article/before --rev=2
echo 'old revision rejected after mark-compacted'
test "$(ec get /registry/deployments/control-ha/baseline --keys-only)" = /registry/deployments/control-ha/baseline
echo 'snapshot contains Kubernetes Deployment storage key'
expect_compacted watch /article/ --prefix --rev=2
echo 'old watch rejected after mark-compacted'
