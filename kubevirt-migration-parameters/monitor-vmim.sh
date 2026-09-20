#!/usr/bin/env bash
set -euo pipefail

export KUBECONFIG=${KV_MIGRATION_KUBECONFIG:-${TMPDIR:-/tmp}/kv-migration-params.kubeconfig}

if (($# != 3)); then
  echo "usage: $0 <vm-name> <vmim-name> <result-directory>" >&2
  exit 2
fi

vm_name=$1
vmim_name=$2
result_dir=$3
namespace=migration-parameters
experiment_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

mkdir -p "$result_dir"
printf 'timestamp\tphase\tmode\tnode\tpolicy\n' >"$result_dir/timeline.tsv"
start_epoch=$(date +%s)
deadline=$((SECONDS + 1800))
phase=""

while ((SECONDS < deadline)); do
  phase=$(kubectl -n "$namespace" get vmim "$vmim_name" -o jsonpath='{.status.phase}')
  mode=$(kubectl -n "$namespace" get vmi "$vm_name" -o jsonpath='{.status.migrationState.mode}' 2>/dev/null || true)
  node=$(kubectl -n "$namespace" get vmi "$vm_name" -o jsonpath='{.status.nodeName}')
  policy=$(kubectl -n "$namespace" get vmi "$vm_name" -o jsonpath='{.status.migrationState.migrationPolicyName}' 2>/dev/null || true)
  printf '%s\t%s\t%s\t%s\t%s\n' \
    "$(date -Ins)" "$phase" "$mode" "$node" "$policy" \
    >>"$result_dir/timeline.tsv"
  case "$phase" in
    Succeeded|Failed) break ;;
  esac
  sleep 2
done

end_epoch=$(date +%s)
cat >"$result_dir/request.txt" <<EOF
vm=$vm_name
vmim=$vmim_name
phase=$phase
start_epoch=$start_epoch
end_epoch=$end_epoch
observed_duration_seconds=$((end_epoch - start_epoch))
EOF

"$experiment_dir/collect-migration.sh" "$vm_name" "$result_dir"

[[ "$phase" == "Succeeded" ]]
