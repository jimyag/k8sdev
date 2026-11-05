#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
control=default-score-control-plane
if [[ "$(docker inspect -f '{{index .Config.Labels "io.x-k8s.kind.cluster"}}' "$control")" != default-score ]]; then
  echo "expected the disposable kind cluster default-score" >&2
  exit 1
fi
kube() { docker exec -i "$control" kubectl --kubeconfig /etc/kubernetes/admin.conf "$@"; }

scheduler_id=$(docker exec "$control" crictl ps --name '^kube-scheduler$' -q)
server=$(kube get --raw /version | jq -er .gitVersion)
scheduler=$(docker exec "$control" crictl exec "$scheduler_id" kube-scheduler --version)
[[ "$server" == v1.37.2 && "$scheduler" == "Kubernetes v1.37.2" ]]
printf 'api-server=%s scheduler=%s\n' "$server" "$scheduler"

a="score-candidate-a"
b="score-candidate-b"
[[ -z "$(kube get node "$a" "$b" --ignore-not-found -o name)" ]]
[[ -z "$(kube get pod tolerate-soft-taint avoid-soft-taint --ignore-not-found -o name)" ]]
cleanup() {
  local result=$?
  trap - EXIT
  # 两个 Pod 绑定到合成节点，没有 kubelet 处理优雅终止。
  kube delete pod tolerate-soft-taint avoid-soft-taint --ignore-not-found --grace-period=0 --force --wait=false >&2 || result=1
  kube delete node "$a" "$b" --ignore-not-found --wait=false >&2 || result=1
  exit "$result"
}
trap cleanup EXIT

started=$(docker exec "$control" date -u '+%Y-%m-%dT%H:%M:%S')
kube create -f - <nodes.yaml >&2
for node in "$a" "$b"; do
  [[ "$(kube get node "$node" -o jsonpath='{.status.allocatable.cpu}')" == 8 ]]
done
kube create -f - <pods.yaml >&2
kube wait --for=condition=PodScheduled --timeout=25s pod/tolerate-soft-taint pod/avoid-soft-taint >&2
kube get pod tolerate-soft-taint avoid-soft-taint -o custom-columns=NAME:.metadata.name,NODE:.spec.nodeName
[[ "$(kube get pod tolerate-soft-taint -o jsonpath='{.spec.nodeName}')" == "$a" ]]
[[ "$(kube get pod avoid-soft-taint -o jsonpath='{.spec.nodeName}')" == "$b" ]]

logs=$(docker exec "$control" crictl logs --since "$started" "$scheduler_id" 2>&1)
assert_score() {
  local pod=$1 plugin=$2 node=$3 score=$4
  grep -Fxq "pod=\"default/$pod\" plugin=\"$plugin\" node=\"$node\" score=$score" \
    <<<"$(sed -n 's/^.*"Plugin scored node for pod" //p' <<<"$logs")"
}
assert_score tolerate-soft-taint NodeAffinity "$a" 200
assert_score tolerate-soft-taint NodeAffinity "$b" 0
assert_score tolerate-soft-taint TaintToleration "$a" 300
assert_score tolerate-soft-taint TaintToleration "$b" 300
assert_score avoid-soft-taint NodeAffinity "$a" 200
assert_score avoid-soft-taint NodeAffinity "$b" 0
assert_score avoid-soft-taint TaintToleration "$a" 0
assert_score avoid-soft-taint TaintToleration "$b" 300
grep -E '(Plugin scored node for pod|Calculated node.s final score for pod).*pod="default/(tolerate-soft-taint|avoid-soft-taint)"' <<<"$logs" |
  sed -E 's/^.*schedule_one\.go:[0-9]+\] //'
