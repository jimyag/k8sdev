#!/usr/bin/env bash
set -euo pipefail

cluster_name="${KIND_CLUSTER_NAME:-extended-resource-lab}"
node_image="${KIND_NODE_IMAGE:-kindest/node:v1.35.0}"
image="extended-resource-device-plugin:dev"
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "${script_dir}/.." && pwd)
export KUBECONFIG="${KUBECONFIG:-${TMPDIR:-/tmp}/${cluster_name}/kubeconfig}"

if kind get clusters | grep -Fxq "${cluster_name}"; then
  kind delete cluster --name "${cluster_name}"
fi

kind create cluster --name "${cluster_name}" --image "${node_image}"
docker build -t "${image}" -f "${script_dir}/Dockerfile" "${repo_dir}"
kind load docker-image "${image}" --name "${cluster_name}"
kubectl apply -f "${script_dir}/deploy/daemonset.yaml"
kubectl -n kube-system rollout status daemonset/fpga-device-plugin --timeout=120s

echo "kind context: kind-${cluster_name}"
echo "kubeconfig: ${KUBECONFIG}"
