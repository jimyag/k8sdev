#!/usr/bin/env python3
"""在专用 kind 集群验证维护预算、API 移除和 v1.35.1→v1.35.2 升级。"""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "article-upgrade/evidence"
os.environ["KUBECONFIG"] = str(ROOT / "tmp/article-upgrade/kubeconfig")
os.environ["TMPDIR"] = str(ROOT / "tmp/article-upgrade")
KUBECTL = str(ROOT / "tmp/article-tools/kubectl")
CONTEXT = "kind-article-upgrade"


def run(args, check=True, input=None, timeout=300):
    result = subprocess.run(args, text=True, input=input, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"{args}:\n{result.stdout}\n{result.stderr}")
    return result


def k(*args, **kwargs):
    return run([KUBECTL, "--context", CONTEXT, *args], **kwargs)


def save(name, value):
    (EVIDENCE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def wait_for(description, check, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(1)
    raise TimeoutError(description)


def pods():
    return json.loads(k("get", "pods", "-n", "article-upgrade", "-l", "app=upgrade-web", "-o", "json").stdout)["items"]


def ready(items, count):
    return len(items) == count and all(
        any(c["type"] == "Ready" and c["status"] == "True" for c in p.get("status", {}).get("conditions", []))
        for p in items
    )


assert run(["hostname"]).stdout.strip() == "zj"
nodes = json.loads(k("get", "nodes", "-o", "json").stdout)["items"]
assert {n["metadata"]["name"] for n in nodes} == {
    "article-upgrade-control-plane", "article-upgrade-worker", "article-upgrade-worker2"
}
assert all(n["status"]["nodeInfo"]["kubeletVersion"] == "v1.35.1" for n in nodes)
save("before-version.json", json.loads(k("version", "-o", "json").stdout))
k("apply", "-f", str(ROOT / "article-upgrade/workload.yaml"))
wait_for("单副本未就绪", lambda: ready(pods(), 1))
original = pods()[0]
node = original["spec"]["nodeName"]
assert node in {"article-upgrade-worker", "article-upgrade-worker2"}
blocked = k("drain", node, "--ignore-daemonsets", "--timeout=15s", check=False, timeout=30)
assert blocked.returncode != 0
assert "disruption budget" in (blocked.stdout + blocked.stderr).lower()
assert any(p["metadata"]["uid"] == original["metadata"]["uid"] for p in pods())
save("drain-blocked.json", {"node": node, "returncode": blocked.returncode,
                            "stdout": blocked.stdout, "stderr": blocked.stderr})
k("uncordon", node)
k("scale", "deployment/web", "-n", "article-upgrade", "--replicas=2")
wait_for("两副本未就绪", lambda: ready(pods(), 2))
before_drain = [{"uid": p["metadata"]["uid"], "node": p["spec"]["nodeName"]} for p in pods()]
assert len({p["node"] for p in before_drain}) == 2
k("drain", node, "--ignore-daemonsets", "--timeout=180s")
wait_for("维护后替代副本未就绪", lambda: ready(pods(), 2))
after_drain = [{"uid": p["metadata"]["uid"], "node": p["spec"]["nodeName"]} for p in pods()]
assert all(p["node"] != node for p in after_drain)
save("drain-recovered.json", {"before": before_drain, "after": after_drain})
k("uncordon", node)

# 直接访问旧端点，避免把客户端映射失败误认为服务端存储失败。
legacy = k("get", "--raw", "/apis/extensions/v1beta1/deployments", check=False)
assert legacy.returncode != 0 and "NotFound" in legacy.stderr
save("removed-api.json", {"returncode": legacy.returncode, "stderr": legacy.stderr,
                           "apps_v1": k("get", "--raw", "/apis/apps/v1").returncode})

cp = "article-upgrade-control-plane"
binary_root = ROOT / "tmp/article-upgrade/bin"
kernel_config = Path("/boot") / f"config-{os.uname().release}"
assert kernel_config.is_file(), "kind 节点预检需要读取与宿主实际内核匹配的配置"
run(["docker", "cp", str(kernel_config), f"{cp}:{kernel_config}"])
for name in ["kubeadm", "kubelet", "kubectl"]:
    run(["docker", "cp", str(binary_root / name), f"{cp}:/usr/local/bin/{name}.article"])
run(["docker", "exec", cp, "install", "-m", "0755", "/usr/local/bin/kubeadm.article", "/usr/bin/kubeadm"])
plan = run(["docker", "exec", cp, "kubeadm", "upgrade", "plan", "v1.35.2"], timeout=300)
(EVIDENCE / "upgrade-plan.txt").write_text((plan.stdout + plan.stderr).rstrip() + "\n")
apply = run(["docker", "exec", cp, "kubeadm", "upgrade", "apply", "v1.35.2", "--yes",
             "--etcd-upgrade=false", "--certificate-renewal=false"], timeout=600)
(EVIDENCE / "upgrade-apply.txt").write_text(apply.stdout + apply.stderr)
wait_for("API 未升级到 v1.35.2", lambda: (
    (result := k("version", "-o", "json", check=False)).returncode == 0
    and json.loads(result.stdout)["serverVersion"]["gitVersion"] == "v1.35.2"
))
save("control-plane-upgraded.json", json.loads(k("get", "nodes", "-o", "json").stdout))
for node in [cp, "article-upgrade-worker", "article-upgrade-worker2"]:
    k("drain", node, "--ignore-daemonsets", "--timeout=180s")
    if node != cp:
        run(["docker", "cp", str(kernel_config), f"{node}:{kernel_config}"])
        for name in ["kubeadm", "kubelet", "kubectl"]:
            run(["docker", "cp", str(binary_root / name), f"{node}:/usr/local/bin/{name}.article"])
        run(["docker", "exec", node, "install", "-m", "0755", "/usr/local/bin/kubeadm.article", "/usr/bin/kubeadm"])
        run(["docker", "exec", node, "kubeadm", "upgrade", "node"], timeout=300)
    run(["docker", "exec", node, "systemctl", "stop", "kubelet"])
    run(["docker", "exec", node, "install", "-m", "0755", "/usr/local/bin/kubelet.article", "/usr/bin/kubelet"])
    run(["docker", "exec", node, "install", "-m", "0755", "/usr/local/bin/kubectl.article", "/usr/bin/kubectl"])
    run(["docker", "exec", node, "systemctl", "start", "kubelet"])
    wait_for(f"{node} 的 kubelet 未升级", lambda: (
        (result := k("get", "node", node, "-o", "json", check=False)).returncode == 0
        and (obj := json.loads(result.stdout))["status"]["nodeInfo"]["kubeletVersion"] == "v1.35.2"
        and any(c["type"] == "Ready" and c["status"] == "True" for c in obj["status"]["conditions"])
    ))
    k("uncordon", node)
k("rollout", "status", "daemonset/kube-proxy", "-n", "kube-system", "--timeout=180s")
wait_for("升级后副本未恢复", lambda: ready(pods(), 2))
save("after-version.json", json.loads(k("version", "-o", "json").stdout))
save("after-nodes.json", json.loads(k("get", "nodes", "-o", "json").stdout))
print("PASS: PDB 阻塞与恢复、旧 API 拒绝、控制面及三节点补丁升级")
