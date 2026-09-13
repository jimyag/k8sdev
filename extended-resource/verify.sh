#!/usr/bin/env bash
set -euo pipefail

cluster_name="${KIND_CLUSTER_NAME:-extended-resource-lab}"
export KUBECONFIG="${KUBECONFIG:-${TMPDIR:-/tmp}/${cluster_name}/kubeconfig}"
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

kubectl get nodes -o wide
kubectl get nodes -o custom-columns=NAME:.metadata.name,FPGA:.status.allocatable.example\\.com/fpga
kubectl -n kube-system get pods -l app.kubernetes.io/name=fpga-device-plugin -o wide
kubectl apply -f "${script_dir}/deploy/workload.yaml"
kubectl apply -f "${script_dir}/deploy/workload-second.yaml"
kubectl wait --for=jsonpath='{.status.phase}'=Running pod/fpga-consumer --timeout=120s
kubectl wait --for=jsonpath='{.status.phase}'=Running pod/fpga-consumer-second --timeout=120s
kubectl get pods -o wide
kubectl describe node "$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')" | sed -n '/Allocatable:/,/System Info:/p'
kubectl logs pod/fpga-consumer -c consumer
kubectl logs pod/fpga-consumer-second -c consumer
