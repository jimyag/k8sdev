#!/usr/bin/env bash
set -euo pipefail

export KUBECONFIG=${KV_MIGRATION_KUBECONFIG:-${TMPDIR:-/tmp}/kv-migration-params.kubeconfig}

if (($# != 2)); then
  echo "usage: $0 <kubevirt-merge-patch> <result-directory>" >&2
  exit 2
fi

patch_file=$1
result_dir=$2
namespace=migration-parameters
vms=(migration-aux1 migration-aux2)
mkdir -p "$result_dir"

kubectl -n kubevirt patch kubevirt kubevirt --type=merge --patch-file "$patch_file"
kubectl -n kubevirt get kubevirt kubevirt \
  -o jsonpath='{.spec.configuration.migrations}' >"$result_dir/migration-config.json"

before_names=$(kubectl -n "$namespace" get vmim \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')

for vm_name in "${vms[@]}"; do
  kubectl -n "$namespace" patch vm "$vm_name" --type=merge \
    -p '{"spec":{"template":{"metadata":{"labels":{"migration.kubevirt.io/profile":"bandwidth-high"}}}}}'
  kubectl -n "$namespace" label vmi "$vm_name" --overwrite \
    migration.kubevirt.io/profile=bandwidth-high
done

for vm_name in "${vms[@]}"; do
  current_claim=$(kubectl -n "$namespace" get vm "$vm_name" \
    -o jsonpath='{.spec.template.spec.volumes[?(@.name=="datadisk")].persistentVolumeClaim.claimName}')
  case "$current_claim" in
    *-source) next_claim=${current_claim%-source}-target ;;
    *-target) next_claim=${current_claim%-target}-source ;;
    *) echo "unexpected current claim for $vm_name: $current_claim" >&2; exit 1 ;;
  esac
  kubectl -n "$namespace" patch vm "$vm_name" --type=json \
    -p "[{\"op\":\"replace\",\"path\":\"/spec/template/spec/volumes/1/persistentVolumeClaim/claimName\",\"value\":\"$next_claim\"}]" &
done
wait

mapfile -t vmims < <(
  for _ in $(seq 1 120); do
    kubectl -n "$namespace" get vmim \
      -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' |
      while read -r candidate; do
        [[ -z "$candidate" ]] && continue
        if ! grep -Fxq "$candidate" <<<"$before_names"; then
          echo "$candidate"
        fi
      done | sort -u
    sleep 1
  done | awk '!seen[$0]++ {print; if (++count == 2) exit}'
)

if ((${#vmims[@]} != 2)); then
  echo "expected two new migrations, got ${#vmims[@]}" >&2
  exit 1
fi

printf 'timestamp\tvmim\tphase\tvmi\n' >"$result_dir/timeline.tsv"
deadline=$((SECONDS + 900))
while ((SECONDS < deadline)); do
  terminal=0
  for vmim_name in "${vmims[@]}"; do
    phase=$(kubectl -n "$namespace" get vmim "$vmim_name" -o jsonpath='{.status.phase}')
    vmi=$(kubectl -n "$namespace" get vmim "$vmim_name" -o jsonpath='{.spec.vmiName}')
    printf '%s\t%s\t%s\t%s\n' "$(date -Ins)" "$vmim_name" "$phase" "$vmi" \
      >>"$result_dir/timeline.tsv"
    case "$phase" in Succeeded|Failed) terminal=$((terminal + 1)) ;; esac
  done
  ((terminal == 2)) && break
  sleep 2
done

kubectl -n "$namespace" get vmim "${vmims[@]}" -o yaml >"$result_dir/vmims.yaml"
awk -F '\t' 'NR > 1 {count[$1] += ($3 == "Running")} END {for (t in count) if (count[t] > max) max=count[t]; print "max_running=" max}' \
  "$result_dir/timeline.tsv" >"$result_dir/summary.txt"

grep -q $'\tFailed\t' "$result_dir/timeline.tsv" && exit 1
