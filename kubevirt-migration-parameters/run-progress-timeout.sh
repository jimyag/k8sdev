#!/usr/bin/env bash
set -euo pipefail

export KUBECONFIG=${KV_MIGRATION_KUBECONFIG:-${TMPDIR:-/tmp}/kv-migration-params.kubeconfig}

result_dir=${1:-results/16-progress-timeout}
namespace=migration-parameters
vm_name=migration-main
experiment_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$result_dir"

original_claim=$(kubectl -n "$namespace" get vm "$vm_name" \
  -o jsonpath='{.spec.template.spec.volumes[?(@.name=="datadisk")].persistentVolumeClaim.claimName}')
source_node=$(kubectl -n "$namespace" get vmi "$vm_name" -o jsonpath='{.status.nodeName}')
case "$original_claim" in
  *-source) target_claim=${original_claim%-source}-target ;;
  *-target) target_claim=${original_claim%-target}-source ;;
  *) echo "unexpected current claim: $original_claim" >&2; exit 1 ;;
esac

target_address=""
blocked_ports=()

cleanup() {
  for port in "${blocked_ports[@]}"; do
    docker exec "$source_node" iptables -D FORWARD -d "$target_address" \
      -p tcp --dport "$port" -j DROP >/dev/null 2>&1 || true
  done
  kubectl -n kubevirt patch kubevirt kubevirt --type=merge \
    -p '{"spec":{"configuration":{"migrations":{"progressTimeout":150}}}}' >/dev/null 2>&1 || true
}
trap cleanup EXIT

kubectl -n kubevirt patch kubevirt kubevirt --type=merge \
  --patch-file "$experiment_dir/14-progress-timeout-patch.yaml"
existing_vmims=$(kubectl -n "$namespace" get vmim \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')
kubectl -n "$namespace" patch vm "$vm_name" --type=merge \
  -p '{"spec":{"template":{"metadata":{"labels":{"migration.kubevirt.io/profile":"bandwidth-high"}}}}}'
kubectl -n "$namespace" label vmi "$vm_name" --overwrite \
  migration.kubevirt.io/profile=bandwidth-high
kubectl -n "$namespace" patch vm "$vm_name" --type=json \
  -p "[{\"op\":\"replace\",\"path\":\"/spec/template/spec/volumes/1/persistentVolumeClaim/claimName\",\"value\":\"$target_claim\"}]"

vmim_name=""
for _ in $(seq 1 120); do
  while read -r candidate; do
    [[ -z "$candidate" ]] && continue
    if ! grep -Fxq "$candidate" <<<"$existing_vmims"; then vmim_name=$candidate; fi
  done < <(kubectl -n "$namespace" get vmim --sort-by=.metadata.creationTimestamp \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')
  [[ -n "$vmim_name" ]] && break
  sleep 1
done
[[ -n "$vmim_name" ]]
kubectl -n "$namespace" wait --for=jsonpath='{.status.phase}'=Running \
  "vmim/$vmim_name" --timeout=120s

# VMIM 进入 Running 时目标 Pod 可能仍在准备；等 libvirt 真正开始传输后再断流。
for _ in $(seq 1 120); do
  start_timestamp=$(kubectl -n "$namespace" get vmi "$vm_name" \
    -o jsonpath='{.status.migrationState.startTimestamp}' 2>/dev/null || true)
  [[ -n "$start_timestamp" ]] && break
  sleep 1
done
[[ -n "$start_timestamp" ]]

# 在源 Kind 节点丢弃直连迁移端口的流量，制造超过 progressTimeout 的零进展窗口。
target_address=$(kubectl -n "$namespace" get vmi "$vm_name" \
  -o jsonpath='{.status.migrationState.targetNodeAddress}')
mapfile -t blocked_ports < <(kubectl -n "$namespace" get vmi "$vm_name" -o json |
  jq -r '.status.migrationState.targetDirectMigrationNodePorts | to_entries[] | select(.value != 0) | .key')
for port in "${blocked_ports[@]}"; do
  docker exec "$source_node" iptables -I FORWARD -d "$target_address" \
    -p tcp --dport "$port" -j DROP
done
sleep 20
for port in "${blocked_ports[@]}"; do
  docker exec "$source_node" iptables -D FORWARD -d "$target_address" \
    -p tcp --dport "$port" -j DROP
done
blocked_ports=()

phase=""
for _ in $(seq 1 120); do
  phase=$(kubectl -n "$namespace" get vmim "$vmim_name" -o jsonpath='{.status.phase}' 2>/dev/null || true)
  case "$phase" in Succeeded|Failed) break ;; esac
  sleep 1
done
kubectl -n "$namespace" get vmim "$vmim_name" -o yaml >"$result_dir/vmim.yaml"
kubectl -n "$namespace" get event --sort-by=.lastTimestamp >"$result_dir/events.txt"

cat >"$result_dir/summary.txt" <<EOF
vmim=$vmim_name
phase=$phase
source_node=$source_node
blocked_target_address=$target_address
blocked_seconds=20
progress_timeout_seconds=5
EOF

[[ "$phase" == Failed ]]
