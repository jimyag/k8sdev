#!/usr/bin/env bash
set -euo pipefail

export KUBECONFIG=${KV_MIGRATION_KUBECONFIG:-${TMPDIR:-/tmp}/kv-migration-params.kubeconfig}

if (($# != 3)); then
  echo "usage: $0 <vm-name> <profile> <result-directory>" >&2
  exit 2
fi

vm_name=$1
profile=$2
result_dir=$3
namespace=migration-parameters
experiment_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

mkdir -p "$result_dir"

current_claim=$(kubectl -n "$namespace" get vm "$vm_name" \
  -o jsonpath='{.spec.template.spec.volumes[?(@.name=="datadisk")].persistentVolumeClaim.claimName}')
case "$current_claim" in
  *-source) next_claim=${current_claim%-source}-target ;;
  *-target) next_claim=${current_claim%-target}-source ;;
  *) echo "unexpected current claim: $current_claim" >&2; exit 1 ;;
esac

before_node=$(kubectl -n "$namespace" get vmi "$vm_name" -o jsonpath='{.status.nodeName}')
before_uid=$(kubectl -n "$namespace" get vmi "$vm_name" -o jsonpath='{.metadata.uid}')
existing_vmims=$(kubectl -n "$namespace" get vmim \
  -l "kubevirt.io/volume-update-migration=$vm_name" \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')
start_epoch=$(date +%s)

cat >"$result_dir/request.txt" <<EOF
vm=$vm_name
profile=$profile
current_claim=$current_claim
next_claim=$next_claim
before_node=$before_node
before_uid=$before_uid
start_epoch=$start_epoch
EOF

# MigrationPolicy 按 VMI label 匹配。VM template 保留标签，当前 VMI 同步打标，
# 避免迁移控制器在 template label 传播前读取到旧策略。
kubectl -n "$namespace" patch vm "$vm_name" --type=merge \
  -p "{\"spec\":{\"template\":{\"metadata\":{\"labels\":{\"migration.kubevirt.io/profile\":\"$profile\"}}}}}"
kubectl -n "$namespace" label vmi "$vm_name" --overwrite \
  "migration.kubevirt.io/profile=$profile"

kubectl -n "$namespace" patch vm "$vm_name" --type=json \
  -p "[{\"op\":\"replace\",\"path\":\"/spec/template/spec/volumes/1/persistentVolumeClaim/claimName\",\"value\":\"$next_claim\"}]"

vmim_name=""
for _ in $(seq 1 120); do
  while read -r candidate; do
    [[ -z "$candidate" ]] && continue
    if ! grep -Fxq "$candidate" <<<"$existing_vmims"; then
      vmim_name=$candidate
    fi
  done < <(kubectl -n "$namespace" get vmim \
    -l "kubevirt.io/volume-update-migration=$vm_name" \
    --sort-by=.metadata.creationTimestamp \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)
  if [[ -n "$vmim_name" ]]; then
    break
  fi
  sleep 1
done
[[ -n "$vmim_name" ]]

echo "vmim=$vmim_name" | tee -a "$result_dir/request.txt"
printf 'timestamp\tphase\tmode\tnode\tpolicy\n' >"$result_dir/timeline.tsv"

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
after_node=$(kubectl -n "$namespace" get vmi "$vm_name" -o jsonpath='{.status.nodeName}')
cat >>"$result_dir/request.txt" <<EOF
phase=$phase
after_node=$after_node
end_epoch=$end_epoch
duration_seconds=$((end_epoch - start_epoch))
EOF

"$experiment_dir/collect-migration.sh" "$vm_name" "$result_dir"

[[ "$phase" == "Succeeded" ]]
