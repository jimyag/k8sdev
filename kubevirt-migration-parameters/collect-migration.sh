#!/usr/bin/env bash
set -euo pipefail

export KUBECONFIG=${KV_MIGRATION_KUBECONFIG:-${TMPDIR:-/tmp}/kv-migration-params.kubeconfig}

if (($# != 2)); then
  echo "usage: $0 <vm-name> <result-directory>" >&2
  exit 2
fi

vm_name=$1
result_dir=$2
namespace=migration-parameters
mkdir -p "$result_dir"

kubectl -n "$namespace" get vm "$vm_name" -o yaml >"$result_dir/vm.yaml"
kubectl -n "$namespace" get vmi "$vm_name" -o yaml >"$result_dir/vmi.yaml"
kubectl -n "$namespace" get vmim -o yaml >"$result_dir/vmims.yaml"
kubectl -n "$namespace" get pod -o wide >"$result_dir/pods.txt"
kubectl -n "$namespace" get event --sort-by=.lastTimestamp >"$result_dir/events.txt"
kubectl -n kubevirt get kubevirt kubevirt -o yaml >"$result_dir/kubevirt.yaml"
kubectl get migrationpolicy -o yaml >"$result_dir/migration-policies.yaml"

# 记录源、目标 virt-launcher 的日志；单个 Pod 已删除时允许继续采集其余证据。
while read -r pod_name; do
  kubectl -n "$namespace" logs "$pod_name" --all-containers=true \
    >"$result_dir/${pod_name}.log" 2>&1 || true
done < <(kubectl -n "$namespace" get pod \
  -l "kubevirt.io/domain=$vm_name" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')
