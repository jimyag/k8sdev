#!/usr/bin/env bash
set -euo pipefail

cluster_name="${KIND_CLUSTER_NAME:-custom-resource-lab}"
image="custom-resource-controller:dev"
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "${script_dir}/.." && pwd)
export KUBECONFIG="${KUBECONFIG:-${TMPDIR:-/tmp}/${cluster_name}/kubeconfig}"

if kind get clusters | grep -Fxq "${cluster_name}"; then
  kind delete cluster --name "${cluster_name}"
fi

kind create cluster --name "${cluster_name}"
docker build -t "${image}" -f "${script_dir}/Dockerfile" "${repo_dir}"
kind load docker-image "${image}" --name "${cluster_name}"

kubectl apply -f "${script_dir}/deploy/crd.yaml"
kubectl wait --for=condition=Established crd/webapps.apps.demo.example.com --timeout=60s
kubectl apply -f "${script_dir}/deploy/namespace.yaml"
kubectl apply -f "${script_dir}/deploy/rbac.yaml"
kubectl apply -f "${script_dir}/deploy/deployment.yaml"
kubectl -n custom-resource-demo rollout status deployment/webapp-controller --timeout=120s
kubectl apply -f "${script_dir}/deploy/sample.yaml"
kubectl -n custom-resource-demo wait --for=condition=available deployment/hello --timeout=180s

echo "kind context: kind-${cluster_name}"
echo "kubeconfig: ${KUBECONFIG}"
