#!/usr/bin/env bash
set -euo pipefail

cluster=svc-iptables
context=kind-svc-iptables
namespace=service-ops
image=python:3.13.7-alpine3.22

kind load docker-image "$image" --name "$cluster"
kubectl --context "$context" apply -f 01-dns-drain.yaml
kubectl --context "$context" -n "$namespace" rollout status \
  deployment/echo-server --timeout=120s
kubectl --context "$context" -n "$namespace" wait \
  --for=condition=Ready pod/client --timeout=120s

echo '===== DNS and discovery ====='
kubectl --context "$context" -n "$namespace" get service,endpointslice -o wide
echo '-- client resolv.conf --'
kubectl --context "$context" -n "$namespace" exec client -- cat /etc/resolv.conf
echo '-- resolver results --'
kubectl --context "$context" -n "$namespace" exec client -- python -c '
import socket
for name in (
    "echo-server",
    "echo-server.service-ops.svc.cluster.local",
    "echo-server.service-ops.svc.cluster.local.",
    "echo-headless",
    "empty-service",
):
    try:
        addresses = sorted({
            row[4][0]
            for row in socket.getaddrinfo(name, 80, socket.AF_INET, socket.SOCK_STREAM)
        })
        print(f"{name} -> {addresses}")
    except Exception as error:
        print(f"{name} -> {type(error).__name__}: {error}")
'

echo '===== failure injection ====='
kubectl --context "$context" -n "$namespace" exec client -- python -c '
from urllib.request import urlopen
for name in ("echo-server", "empty-service", "wrong-port"):
    try:
        body = urlopen(f"http://{name}/hostname", timeout=2).read().decode()
        print(f"{name}: success body={body}")
    except Exception as error:
        print(f"{name}: {type(error).__name__}: {error}")
'

echo '===== terminating Endpoint and in-flight request ====='
target=$(kubectl --context "$context" -n "$namespace" exec client -- python -c \
  'from urllib.request import urlopen; print(urlopen("http://echo-server/hostname").read().decode())')
echo "session-affinity target=$target"

slow_output=$(mktemp /tmp/service-drain-slow.XXXXXX)
kubectl --context "$context" -n "$namespace" exec client -- python -c \
  'from urllib.request import urlopen; print(urlopen("http://echo-server/slow?seconds=6", timeout=15).read().decode())' \
  >"$slow_output" 2>&1 &
slow_pid=$!
sleep 1
kubectl --context "$context" -n "$namespace" delete pod "$target" --wait=false

for _ in $(seq 1 30); do
  terminating=$(kubectl --context "$context" -n "$namespace" get endpointslice \
    -l kubernetes.io/service-name=echo-server \
    -o jsonpath="{range .items[*].endpoints[?(@.targetRef.name=='$target')]}pod={.targetRef.name} ready={.conditions.ready} serving={.conditions.serving} terminating={.conditions.terminating}{'\\n'}{end}")
  if [[ "$terminating" == *'terminating=true'* ]]; then
    echo "$terminating"
    break
  fi
  sleep 0.2
done

echo '-- new connections while old Pod terminates --'
kubectl --context "$context" -n "$namespace" exec client -- python -c '
from urllib.request import urlopen
for _ in range(6):
    print(urlopen("http://echo-server/hostname", timeout=2).read().decode())
'

wait "$slow_pid"
echo '-- in-flight request result --'
cat "$slow_output"
rm -f "$slow_output"

echo '-- terminating Pod application log --'
kubectl --context "$context" -n "$namespace" logs "$target" --tail=50 |
  grep -E 'slow-|GET /slow' || true

echo '-- replacement ready; old Pod may still be in grace period --'
kubectl --context "$context" -n "$namespace" rollout status \
  deployment/echo-server --timeout=120s
kubectl --context "$context" -n "$namespace" get pod,endpointslice -o wide

echo '-- old Pod deleted; final endpoints --'
kubectl --context "$context" -n "$namespace" wait \
  --for=delete "pod/$target" --timeout=30s
kubectl --context "$context" -n "$namespace" get pod,endpointslice -o wide
