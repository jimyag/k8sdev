#!/usr/bin/env bash
set -euo pipefail

cluster_name="kv-migration-params"
experiment_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
kubeconfig_path=${KV_MIGRATION_KUBECONFIG:-${TMPDIR:-/tmp}/kv-migration-params.kubeconfig}
kubevirt_version=${KUBEVIRT_VERSION:-v1.9.0}

mkdir -p "$(dirname "$kubeconfig_path")"

if kind get clusters | grep -Fxq "$cluster_name"; then
  echo "cluster $cluster_name already exists" >&2
  exit 1
fi

kind create cluster \
  --config "$experiment_dir/00-kind.yaml" \
  --kubeconfig "$kubeconfig_path" \
  --wait 180s

export KUBECONFIG="$kubeconfig_path"

# local PV 要求目录预先存在于对应 Kind worker 容器中。
docker exec "${cluster_name}-worker" mkdir -p \
  /var/local/kubevirt-migration/main-source \
  /var/local/kubevirt-migration/aux1-source \
  /var/local/kubevirt-migration/aux2-source
docker exec "${cluster_name}-worker2" mkdir -p \
  /var/local/kubevirt-migration/main-target \
  /var/local/kubevirt-migration/aux1-target \
  /var/local/kubevirt-migration/aux2-target

kubectl apply -f "https://github.com/kubevirt/kubevirt/releases/download/${kubevirt_version}/kubevirt-operator.yaml"
kubectl apply -f "https://github.com/kubevirt/kubevirt/releases/download/${kubevirt_version}/kubevirt-cr.yaml"
kubectl -n kubevirt wait kubevirt/kubevirt --for=condition=Available --timeout=20m

kubectl -n kubevirt patch kubevirt kubevirt \
  --type=merge --patch-file "$experiment_dir/01-kubevirt-config.yaml"
kubectl -n kubevirt wait kubevirt/kubevirt --for=condition=Available --timeout=10m

kubectl apply -f "$experiment_dir/02-storage.yaml"
kubectl apply -f "$experiment_dir/03-policies.yaml"
kubectl apply -f "$experiment_dir/04-vms.yaml"

kubectl -n migration-parameters wait \
  vmi/migration-main vmi/migration-aux1 vmi/migration-aux2 \
  --for=condition=Ready --timeout=15m

kubectl get nodes -o wide
kubectl -n migration-parameters get vm,vmi,pvc -o wide
