#!/usr/bin/env bash
set -euo pipefail

cluster_name="${KIND_CLUSTER_NAME:-custom-resource-lab}"
export KUBECONFIG="${KUBECONFIG:-${TMPDIR:-/tmp}/${cluster_name}/kubeconfig}"
namespace=custom-resource-demo

kubectl config current-context
kubectl api-resources --api-group=apps.demo.example.com
kubectl -n "${namespace}" get webapp hello
kubectl -n "${namespace}" get webapp hello -o yaml
kubectl -n "${namespace}" get deployment,service,pods -l app.kubernetes.io/instance=hello -o wide
kubectl -n "${namespace}" logs deployment/webapp-controller --tail=30
