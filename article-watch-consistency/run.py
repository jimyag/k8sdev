import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "article-next-common"))

from lab import Lab, k  # noqa: E402


PROXY_PORT = 18081
BASE = f"http://127.0.0.1:{PROXY_PORT}"


def get_json(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as response:
        return json.load(response)


def pod(name):
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "labels": {"app": name}},
        "spec": {
            "terminationGracePeriodSeconds": 1,
            "containers": [
                {
                    "name": "app",
                    "image": "alpine:3.20",
                    "imagePullPolicy": "IfNotPresent",
                    "command": ["sh", "-c", "sleep 3600"],
                }
            ],
        },
    }


def compact_etcd_and_restart_apiserver():
    cluster_list = get_json("/api/v1/namespaces")
    old_rv = cluster_list["metadata"]["resourceVersion"]
    etcd_pods = json.loads(
        k(
            "get",
            "pods",
            "-n",
            "kube-system",
            "-l",
            "component=etcd",
            "-o",
            "json",
        ).stdout
    )["items"]
    if len(etcd_pods) != 1:
        raise AssertionError(f"期望一个 etcd Pod，实际 {len(etcd_pods)}")
    etcd_name = etcd_pods[0]["metadata"]["name"]
    k(
        "exec",
        "-n",
        "kube-system",
        etcd_name,
        "--",
        "etcdctl",
        "--endpoints=https://127.0.0.1:2379",
        "--cacert=/etc/kubernetes/pki/etcd/ca.crt",
        "--cert=/etc/kubernetes/pki/etcd/server.crt",
        "--key=/etc/kubernetes/pki/etcd/server.key",
        "compact",
        old_rv,
    )

    container = "article-next-control-plane"
    apiserver_id = subprocess.run(
        [
            "docker",
            "exec",
            container,
            "crictl",
            "ps",
            "--name",
            "kube-apiserver",
            "-q",
        ],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    if not apiserver_id:
        raise AssertionError("没有找到 kube-apiserver 容器")
    subprocess.run(
        ["docker", "exec", container, "crictl", "stop", apiserver_id],
        capture_output=True,
        check=True,
    )
    kubectl_bin = os.environ.get("KUBECTL", "kubectl")
    for _ in range(120):
        ready = subprocess.run(
            [kubectl_bin, "--context", "kind-article-next", "get", "--raw", "/readyz"],
            text=True,
            capture_output=True,
        )
        if ready.returncode == 0:
            return old_rv
        time.sleep(1)
    raise TimeoutError("kube-apiserver 重启后没有恢复 Ready")


lab = Lab("watch-consistency")
kubectl = os.environ.get("KUBECTL", "kubectl")
proxy = subprocess.Popen(
    [
        kubectl,
        "--context",
        "kind-article-next",
        "proxy",
        f"--port={PROXY_PORT}",
        "--address=127.0.0.1",
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

try:
    for _ in range(30):
        try:
            get_json("/version")
            break
        except Exception:
            time.sleep(0.5)
    else:
        raise RuntimeError("kubectl proxy 未就绪")

    expired_rv = compact_etcd_and_restart_apiserver()
    for _ in range(60):
        try:
            get_json("/version")
            break
        except Exception:
            time.sleep(0.5)
    else:
        raise RuntimeError("API Server 重启后 proxy 无法访问")

    old_path = (
        f"/api/v1/namespaces/{lab.ns}/pods"
        f"?watch=1&resourceVersion={expired_rv}&timeoutSeconds=10"
    )
    old_status = None
    try:
        with urllib.request.urlopen(BASE + old_path, timeout=15) as response:
            line = response.readline().decode()
            old_status = {"http_status": response.status, "first_event": line.strip()}
    except urllib.error.HTTPError as error:
        old_status = {
            "http_status": error.code,
            "body": json.loads(error.read().decode()),
        }
    if not old_status or (
        old_status.get("http_status") != 410
        and '"code":410' not in old_status.get("first_event", "")
    ):
        raise AssertionError(f"旧 resourceVersion 没有返回 410: {old_status}")
    lab.save(
        "expired-watch",
        {
            "etcd_compacted_revision": expired_rv,
            "apiserver_restarted": True,
            "watch": old_status,
        },
    )

    lab.apply(pod("before"))
    lab.ready("before")
    current = get_json(f"/api/v1/namespaces/{lab.ns}/pods")
    list_rv = current["metadata"]["resourceVersion"]
    if not list_rv:
        raise AssertionError("List 响应没有 resourceVersion")
    lab.save(
        "list",
        {
            "resourceVersion": list_rv,
            "pods": [item["metadata"]["name"] for item in current["items"]],
        },
    )

    watch_path = (
        f"/api/v1/namespaces/{lab.ns}/pods"
        f"?watch=1&resourceVersion={list_rv}&timeoutSeconds=30"
    )
    with urllib.request.urlopen(BASE + watch_path, timeout=40) as response:
        lab.apply(pod("after"))
        events = []
        last_rv = list_rv
        while True:
            line = response.readline()
            if not line:
                raise AssertionError("watch 在收到 after Pod 前结束")
            event = json.loads(line)
            events.append(event)
            obj = event.get("object", {})
            last_rv = obj.get("metadata", {}).get("resourceVersion", last_rv)
            if (
                event.get("type") == "ADDED"
                and obj.get("metadata", {}).get("name") == "after"
            ):
                break
    lab.save(
        "watch-after-create",
        {
            "startResourceVersion": list_rv,
            "lastResourceVersion": last_rv,
            "events": events,
        },
    )

    reconnect_path = (
        f"/api/v1/namespaces/{lab.ns}/pods"
        f"?watch=1&resourceVersion={last_rv}&timeoutSeconds=30"
    )
    with urllib.request.urlopen(BASE + reconnect_path, timeout=40) as response:
        k("delete", "pod", "after", "-n", lab.ns, "--wait=false")
        events = []
        while True:
            line = response.readline()
            if not line:
                raise AssertionError("watch 在收到删除事件前结束")
            event = json.loads(line)
            events.append(event)
            obj = event.get("object", {})
            if (
                event.get("type") == "DELETED"
                and obj.get("metadata", {}).get("name") == "after"
            ):
                break
    lab.save(
        "watch-reconnect-delete",
        {
            "startResourceVersion": last_rv,
            "events": events,
        },
    )

    lab.save(
        "result",
        {
            "old_resource_version_status": 410,
            "list_resource_version": list_rv,
            "watch_reconnect_observed_delete": True,
            "relisted": True,
        },
    )
finally:
    proxy.terminate()
    try:
        proxy.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proxy.kill()

k("delete", "namespace", lab.ns, "--wait=true")
print("PASS", flush=True)
