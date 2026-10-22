import json
import subprocess
from run import ROOT, OUT, NODE, kubectl, get, save, wait, ready, cri, collect_logs


def run():
    previous = json.loads((OUT / "timeline.json").read_text())
    uids = {row["uid"] for row in previous}
    # 容器与 sandbox 的回收由后台 GC 推进，不能在 API DELETE 返回时就断言完成。
    def runtime_removed():
        sandboxes = cri("pods", "-o", "json")["items"]
        containers = cri("ps", "-a", "-o", "json")["containers"]
        return not any(s["metadata"]["uid"] in uids for s in sandboxes) and not any(
            c.get("labels", {}).get("io.kubernetes.pod.uid") in uids for c in containers)
    wait(runtime_removed, timeout=300)
    save("11-runtime-after-gc", {"sandboxes": cri("pods", "-o", "json"), "containers": cri("ps", "-a", "-o", "json")})
    cleanup = []
    for row in previous:
        inspection = json.loads((OUT / f"{row['stage']}-sandbox.json").read_text())
        network_paths = [ns["path"] for ns in inspection["info"]["runtimeSpec"]["linux"]["namespaces"]
                         if ns["type"] == "network"]
        cgroup = inspection["info"]["runtimeSpec"]["linux"]["cgroupsPath"]
        for path in network_paths:
            result = subprocess.run(["docker", "exec", NODE, "test", "!", "-e", path], capture_output=True)
            assert result.returncode == 0, path
        # systemd cgroup 中 UID 的连字符被改成下划线，检查整个 Pod 层级。
        match = row["uid"].replace("-", "_")
        paths = subprocess.check_output(["docker", "exec", NODE, "find", "/sys/fs/cgroup", "-type", "d", "-name", f"*{match}*"], text=True)
        assert not paths.strip(), paths
        cleanup.append({"uid": row["uid"], "sandbox": row["sandbox"], "formerNetns": network_paths,
                        "formerCgroup": cgroup, "netnsRemoved": True, "podCgroupRemoved": True})
    save("11-resource-cleanup", cleanup)

    kubectl("apply", "-f", str(ROOT / "pod-lifecycle-source/failure-paths.yaml"))
    wait(lambda: any(c["type"] == "PodScheduled" and c["status"] == "False"
                     for c in get("pod", "unscheduled")["status"].get("conditions", [])))
    pending = get("pod", "unscheduled")
    assert not pending["spec"].get("nodeName")
    save("12-unscheduled", pending)
    wait(lambda: get("pod", "mount-blocked")["spec"].get("nodeName"))
    blocked = get("pod", "mount-blocked")
    uid = blocked["metadata"]["uid"]
    wait(lambda: any(e.get("reason") == "FailedMount" and e["involvedObject"]["uid"] == uid for e in get("events")["items"]))
    assert not any(s["metadata"]["uid"] == uid for s in cri("pods", "-o", "json")["items"])
    save("13-mount-blocked", get("pod", "mount-blocked"))
    kubectl("create", "configmap", "supplied-later", "--from-literal=value=ready")
    wait(lambda: ready(get("pod", "mount-blocked")))
    mounted = get("pod", "mount-blocked")
    assert mounted["metadata"]["uid"] == uid
    save("14-mount-recovered", mounted)

    def oom_recovered():
        p = get("pod", "memory-limit")
        statuses = p["status"].get("containerStatuses", [])
        return ready(p) and statuses and statuses[0]["restartCount"] > 0
    wait(oom_recovered)
    oom = get("pod", "memory-limit")
    assert oom["status"]["containerStatuses"][0]["lastState"]["terminated"]["reason"] == "OOMKilled"
    save("15-oom-recovered", oom)
    save("failure-paths-result", {"passed": True, "checks": ["runtime GC", "netns removal", "Pod cgroup removal",
         "unschedulable before node assignment", "mount failure before sandbox creation", "same UID recovers after ConfigMap creation",
         "OOMKilled triggers OnFailure restart"]})


try:
    run()
finally:
    collect_logs()
