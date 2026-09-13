#!/usr/bin/env bash
set -euo pipefail

cluster_name="${KIND_CLUSTER_NAME:-extended-resource-lab}"
node_image="${KIND_NODE_IMAGE:-kindest/node:v1.35.0}"
image="extended-resource-device-plugin:dev"
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export KUBECONFIG="${KUBECONFIG:-${TMPDIR:-/tmp}/${cluster_name}/kubeconfig}"
plugin_binary="${script_dir}/.device-plugin"
trap 'rm -f "${plugin_binary}"' EXIT

if kind get clusters | grep -Fxq "${cluster_name}"; then
  kind delete cluster --name "${cluster_name}"
fi

kind create cluster --name "${cluster_name}" --image "${node_image}"
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -o "${plugin_binary}" "${script_dir}"
docker build -t "${image}" -f "${script_dir}/Dockerfile" "${script_dir}"
kind load docker-image "${image}" --name "${cluster_name}"
kind load docker-image alpine:3.22 --name "${cluster_name}"
kubectl apply -f "${script_dir}/deploy/daemonset.yaml"
kubectl -n kube-system rollout status daemonset/fpga-device-plugin --timeout=120s

echo "kind context: kind-${cluster_name}"
echo "kubeconfig: ${KUBECONFIG}"
