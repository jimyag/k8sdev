"""在专用 kind 集群比较资源身份；所有断言都来自 API 或节点运行状态。"""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "pod-lifecycle-source/evidence"
OUT.mkdir(exist_ok=True)
os.environ["KUBECONFIG"] = str(ROOT / "tmp/pod-lifecycle/kubeconfig")
NS = "lifecycle-lab"
NODE = "pod-lifecycle-worker"
timeline = []


def command(*args):
    return subprocess.check_output(args, text=True)


def kubectl(*args):
    return command("kubectl", "-n", NS, *args)


def get(resource, name=None):
    return json.loads(kubectl("get", resource, *([name] if name else []), "-o", "json"))


def save(name, data):
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def wait(fn, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(0.5)
    raise TimeoutError(f"Condition did not become true: {fn}")


def ready(p):
    return any(c["type"] == "Ready" and c["status"] == "True" for c in p["status"].get("conditions", []))


def active_pod():
    pods = [p for p in get("pods")["items"] if p["metadata"].get("labels", {}).get("app") == "lifecycle"
            and not p["metadata"].get("deletionTimestamp") and ready(p)]
    return pods[0] if len(pods) == 1 else None


def app_status(p):
    return next(c for c in p["status"]["containerStatuses"] if c["name"] == "app")


def cri(*args):
    return json.loads(command("docker", "exec", NODE, "crictl", *args))


def sandbox(p):
    return next(s for s in cri("pods", "-o", "json")["items"]
                if s["metadata"]["uid"] == p["metadata"]["uid"] and s["state"] == "SANDBOX_READY")


def snapshot(stage, p):
    uid = p["metadata"]["uid"]
    sid = sandbox(p)["id"]
    cid = app_status(p)["containerID"].split("://", 1)[1]
    container = cri("inspect", cid)
    pod_sandbox = cri("inspectp", sid)
    save(f"{stage}-pod", p)
    save(f"{stage}-container", container)
    save(f"{stage}-sandbox", pod_sandbox)
    save(f"{stage}-endpoints", get("endpointslices"))
    save(f"{stage}-pvc", get("pvc"))
    save(f"{stage}-pv", get("pv"))
    pid = container["info"]["pid"]
    shell = f"""set -eu
printf 'namespaces\\n'
ls -l /proc/{pid}/ns/
printf 'cgroup\\n'
cat /proc/{pid}/cgroup
cg=$(cut -d: -f3 /proc/{pid}/cgroup)
for f in cpu.max cpu.weight memory.max pids.max; do
  printf '%s=' "$f"
  cat "/sys/fs/cgroup$cg/$f"
done
printf 'network\\n'
nsenter -t {pid} -n ip -j address
printf 'pod-directory\\n'
find /var/lib/kubelet/pods/{uid} -maxdepth 3 -type d
printf 'mounts\\n'
cat /proc/{pid}/mountinfo
"""
    (OUT / f"{stage}-node.txt").write_text(command("docker", "exec", NODE, "sh", "-c", shell))
    row = {"stage": stage, "time": time.time(), "pod": p["metadata"]["name"], "uid": uid,
           "sandbox": sid, "container": cid, "restartCount": app_status(p)["restartCount"],
           "podIP": p["status"].get("podIP"), "pid": pid,
           "initContainers": [{"name": c["name"], "containerID": c.get("containerID"),
                               "restartCount": c["restartCount"]} for c in p["status"].get("initContainerStatuses", [])]}
    timeline.append(row)
    save("timeline", timeline)
    return row


def exec_app(p, *args):
    return kubectl("exec", p["metadata"]["name"], "-c", "app", "--", *args)


def wait_http(name):
    # Ready 的 API 快照可能短暂落后于容器 ID；确认新进程已执行完初始化。
    wait(lambda: subprocess.run(["kubectl", "-n", NS, "exec", name, "-c", "app", "--", "python", "-c",
                                "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=2)"],
                               capture_output=True).returncode == 0)


def endpoint_ready(uid, expected):
    endpoints = [e for s in get("endpointslices")["items"] for e in s.get("endpoints", [])
                 if e.get("targetRef", {}).get("uid") == uid]
    return endpoints and all(e["conditions"].get("ready") == expected for e in endpoints)


def collect_logs():
    for node in ("pod-lifecycle-control-plane", NODE):
        logs = command("docker", "exec", node, "journalctl", "-u", "kubelet", "--no-pager", "-o", "short-iso-precise")
        lines = [line for line in logs.splitlines() if "LIFECYCLE " in line]
        (OUT / f"{node}-trace.log").write_text("\n".join(lines) + "\n")
    for component in ("kube-apiserver", "kube-scheduler", "kube-controller-manager"):
        logs = command("kubectl", "-n", "kube-system", "logs", f"{component}-pod-lifecycle-control-plane", "--timestamps")
        (OUT / f"{component}-trace.log").write_text("\n".join(line for line in logs.splitlines() if "LIFECYCLE " in line) + "\n")
    save("events", get("events"))


def run():
    kubectl("apply", "-f", str(ROOT / "pod-lifecycle-source/workload.yaml"))
    p = wait(active_pod)
    name, uid = p["metadata"]["name"], p["metadata"]["uid"]
    wait(lambda: endpoint_ready(uid, True))
    initial = snapshot("01-created", p)
    exec_app(p, "sh", "-c", "echo retained > /work/marker; echo retained > /memory/marker; echo persistent > /data/user-marker")

    # readiness 只影响流量资格，不更换容器。
    exec_app(p, "rm", "/work/ready")
    wait(lambda: not ready(get("pod", name)))
    wait(lambda: endpoint_ready(uid, False))
    unready = snapshot("02-unready", get("pod", name))
    assert unready["container"] == initial["container"]
    exec_app(p, "touch", "/work/ready")
    wait(lambda: ready(get("pod", name)))

    # 进程崩溃：等待同一 UID 的容器 ID 变化，不能只等待 Ready。
    # 容器 PID namespace 的 PID 1 受到信号保护，从祖先 namespace 注入崩溃。
    command("docker", "exec", NODE, "kill", "-KILL", str(unready["pid"]))
    wait(lambda: ready(get("pod", name)) and app_status(get("pod", name))["containerID"].split("://", 1)[1] != initial["container"])
    wait_http(name)
    crashed = snapshot("03-crash-restarted", get("pod", name))
    assert crashed["uid"] == uid and crashed["sandbox"] == initial["sandbox"]
    assert crashed["restartCount"] > initial["restartCount"]
    assert crashed["initContainers"] == initial["initContainers"]

    # liveness 失败应触发 preStop/StopContainer，而 readiness 失败不触发。
    exec_app(p, "rm", "/work/live")
    wait(lambda: ready(get("pod", name)) and app_status(get("pod", name))["restartCount"] > crashed["restartCount"])
    wait_http(name)
    probed = snapshot("04-liveness-restarted", get("pod", name))
    assert probed["sandbox"] == initial["sandbox"]
    assert exec_app(p, "cat", "/work/marker", "/memory/marker", "/data/user-marker") == "retained\nretained\npersistent\n"

    exec_app(p, "sh", "-c", "kill -USR1 1")
    wait(lambda: ready(get("pod", name)) and app_status(get("pod", name))["containerID"].split("://", 1)[1] != probed["container"])
    wait_http(name)
    all_restarted = snapshot("04b-all-containers-restarted", get("pod", name))
    assert all_restarted["uid"] == uid and all_restarted["sandbox"] == initial["sandbox"]
    assert all_restarted["initContainers"][0]["containerID"] != probed["initContainers"][0]["containerID"]
    assert all_restarted["initContainers"][1]["containerID"] != probed["initContainers"][1]["containerID"]
    assert exec_app(p, "cat", "/work/marker", "/memory/marker") == "retained\nretained\n"

    # sandbox 故障：Pod UID 保留，sandbox 与容器重新创建。
    command("docker", "exec", NODE, "crictl", "stopp", all_restarted["sandbox"])
    def sandbox_recovered():
        current = get("pod", name)
        items = cri("pods", "-o", "json")["items"]
        return ready(current) and any(s["metadata"]["uid"] == uid and s["state"] == "SANDBOX_READY"
                                      and s["id"] != all_restarted["sandbox"] for s in items) and app_status(current)["containerID"].split("://", 1)[1] != all_restarted["container"]
    wait(sandbox_recovered)
    wait_http(name)
    recovered = snapshot("05-sandbox-recreated", get("pod", name))
    assert recovered["uid"] == uid and recovered["sandbox"] != probed["sandbox"]
    assert exec_app(p, "cat", "/work/marker", "/memory/marker") == "retained\nretained\n"

    # Finalizer 延长 API 对象的可观察窗口；它不阻止 kubelet 停止容器。
    kubectl("patch", "pod", name, "--type=merge", "-p", '{"metadata":{"finalizers":["lab.example.com/observe"]}}')
    kubectl("delete", "pod", name, "--wait=false")
    wait(lambda: get("pod", name)["metadata"].get("deletionTimestamp"))
    wait(lambda: endpoint_ready(uid, False))
    save("06-deleting-pod", get("pod", name))
    save("06-deleting-endpoints", get("endpointslices"))
    new_pod = wait(active_pod)
    assert new_pod["metadata"]["uid"] != uid
    new = snapshot("07-controller-recreated", new_pod)
    assert exec_app(new_pod, "cat", "/data/user-marker") == "persistent\n"
    assert exec_app(new_pod, "sh", "-c", "test ! -e /work/marker && test ! -e /memory/marker && echo cleared").strip() == "cleared"
    wait(lambda: get("pod", name)["status"].get("phase") in ("Succeeded", "Failed"))
    save("08-finalizer-held-pod", get("pod", name))
    kubectl("patch", "pod", name, "--type=merge", "-p", '{"metadata":{"finalizers":null}}')
    kubectl("wait", "--for=delete", "pod/" + name, "--timeout=180s")
    wait(lambda: subprocess.run(["docker", "exec", NODE, "test", "!", "-d", f"/var/lib/kubelet/pods/{uid}"], capture_output=True).returncode == 0)

    kubectl("scale", "deployment", "app", "--replicas=0")
    kubectl("wait", "--for=delete", "pod", "-l", "app=lifecycle", "--timeout=180s")
    wait(lambda: subprocess.run(["docker", "exec", NODE, "test", "!", "-d", f"/var/lib/kubelet/pods/{new['uid']}"], capture_output=True).returncode == 0)
    save("09-after-pod-deletion", get("deployment,replicaset,service,endpointslice,pvc,configmap,serviceaccount"))
    save("09-runtime-sandboxes", cri("pods", "-o", "json"))
    save("09-runtime-containers", cri("ps", "-a", "-o", "json"))
    kubectl("apply", "-f", str(ROOT / "pod-lifecycle-source/terminal-pods.yaml"))
    wait(lambda: get("pod", "completed")["status"].get("phase") == "Succeeded")
    wait(lambda: get("pod", "failed")["status"].get("phase") == "Failed")
    for name in ("completed", "failed"):
        terminal = get("pod", name)
        assert terminal["status"]["containerStatuses"][0]["restartCount"] == 0
        save(f"10-{name}", terminal)
    save("version", json.loads(command("kubectl", "version", "-o", "json")))
    save("result", {"passed": True, "stages": len(timeline), "oldUID": uid, "newUID": new["uid"],
                    "checks": ["readiness does not restart", "crash restart keeps sandbox", "liveness restart keeps volumes",
                               "sandbox recreation keeps UID and emptyDir", "controller replacement changes UID",
                               "replacement clears emptyDir and retains PVC data", "finalizer holds API object after process exit",
                               "Pod directories removed", "referenced objects survive Pod deletion"]})


if __name__ == "__main__":
    try:
        run()
    finally:
        collect_logs()
