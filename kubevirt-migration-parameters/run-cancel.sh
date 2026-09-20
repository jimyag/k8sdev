#!/usr/bin/env bash
set -euo pipefail

export KUBECONFIG=${KV_MIGRATION_KUBECONFIG:-${TMPDIR:-/tmp}/kv-migration-params.kubeconfig}

result_dir=${1:-results/14-cancel}
namespace=migration-parameters
vm_name=migration-main
mkdir -p "$result_dir"

original_claim=$(kubectl -n "$namespace" get vm "$vm_name" \
  -o jsonpath='{.spec.template.spec.volumes[?(@.name=="datadisk")].persistentVolumeClaim.claimName}')
case "$original_claim" in
  *-source) target_claim=${original_claim%-source}-target ;;
  *-target) target_claim=${original_claim%-target}-source ;;
  *) echo "unexpected current claim: $original_claim" >&2; exit 1 ;;
esac

existing_vmims=$(kubectl -n "$namespace" get vmim \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')
kubectl -n "$namespace" patch vm "$vm_name" --type=merge \
  -p '{"spec":{"template":{"metadata":{"labels":{"migration.kubevirt.io/profile":"bandwidth-low"}}}}}'
kubectl -n "$namespace" label vmi "$vm_name" --overwrite \
  migration.kubevirt.io/profile=bandwidth-low
kubectl -n "$namespace" patch vm "$vm_name" --type=json \
  -p "[{\"op\":\"replace\",\"path\":\"/spec/template/spec/volumes/1/persistentVolumeClaim/claimName\",\"value\":\"$target_claim\"}]"

vmim_name=""
for _ in $(seq 1 120); do
  while read -r candidate; do
    [[ -z "$candidate" ]] && continue
    if ! grep -Fxq "$candidate" <<<"$existing_vmims"; then
      vmim_name=$candidate
    fi
  done < <(kubectl -n "$namespace" get vmim --sort-by=.metadata.creationTimestamp \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')
  [[ -n "$vmim_name" ]] && break
  sleep 1
done
[[ -n "$vmim_name" ]]

kubectl -n "$namespace" wait --for=jsonpath='{.status.phase}'=Running \
  "vmim/$vmim_name" --timeout=120s
kubectl -n "$namespace" get vmim "$vmim_name" -o yaml >"$result_dir/before-cancel.yaml"

# VolumeMigration 的取消动作是把 VM 卷集合精确恢复成迁移前的值。
kubectl -n "$namespace" patch vm "$vm_name" --type=json \
  -p "[{\"op\":\"replace\",\"path\":\"/spec/template/spec/volumes/1/persistentVolumeClaim/claimName\",\"value\":\"$original_claim\"}]"

for _ in $(seq 1 120); do
  phase=$(kubectl -n "$namespace" get vmim "$vmim_name" -o jsonpath='{.status.phase}' 2>/dev/null || echo Deleted)
  case "$phase" in Failed|Deleted) break ;; esac
  sleep 1
done

cat >"$result_dir/summary.txt" <<EOF
vmim=$vmim_name
phase=$phase
original_claim=$original_claim
final_claim=$(kubectl -n "$namespace" get vm "$vm_name" -o jsonpath='{.spec.template.spec.volumes[?(@.name=="datadisk")].persistentVolumeClaim.claimName}')
node=$(kubectl -n "$namespace" get vmi "$vm_name" -o jsonpath='{.status.nodeName}')
EOF
