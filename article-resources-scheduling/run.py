#!/usr/bin/env python3
"""在 article-resources 集群验证行为；异常或超时以非零状态退出。"""
import json
import os
import subprocess
import time
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)
K = [os.environ["KUBECTL"], "--kubeconfig", os.environ["KUBECONFIG"]]
def k(*args):
    return subprocess.check_output(K + list(args), text=True)
assert k("config", "current-context").strip() == "kind-article-resources", "拒绝在其他 context 执行"
def pod(name):
    return json.loads(k("get", "pod", name, "-n", NS, "-o", "json"))
def wait(check, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(1)
    raise TimeoutError("条件在指定时间内未满足")
def save(data):
    Path("results.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

NS = "article-scheduling"
k("apply", "-f", "classes.yaml")
node = json.loads(k("get", "node", "article-resources-control-plane", "-o", "json"))
cpu = node["status"]["allocatable"]["cpu"]
millis = int(cpu[:-1]) if cpu.endswith("m") else int(cpu) * 1000
request = millis * 3 // 4
def create(name, priority, selector=None):
    spec = {"priorityClassName": priority, "terminationGracePeriodSeconds": 0,
            "containers": [{"name": "idle", "image": "python:3.12-alpine", "imagePullPolicy": "IfNotPresent",
            "command": ["python", "-c", "import time; time.sleep(3600)"],
            "resources": {"requests": {"cpu": str(request) + "m", "memory": "32Mi"}, "limits": {"memory": "64Mi"}}}]}
    if selector:
        spec["nodeSelector"] = selector
    manifest = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "namespace": NS}, "spec": spec}
    subprocess.run(K + ["apply", "-f", "-"], input=json.dumps(manifest), text=True, check=True, capture_output=True)
create("low", "article-low")
k("wait", "--for=condition=Ready", "pod/low", "-n", NS, "--timeout=180s")
low_uid = pod("low")["metadata"]["uid"]
create("impossible", "article-high", {"article.example/absent": "true"})
def unschedulable():
    p = pod("impossible")
    return p if any(c.get("reason") == "Unschedulable" for c in p["status"].get("conditions", [])) else None
p = wait(unschedulable)
impossible = p["status"]["conditions"]
assert pod("low")["metadata"]["uid"] == low_uid
assert not pod("low")["metadata"].get("deletionTimestamp")
create("high", "article-high")
k("wait", "--for=condition=Ready", "pod/high", "-n", NS, "--timeout=180s")
events = json.loads(k("get", "events", "-n", NS, "-o", "json"))["items"]
preempted = [e["message"] for e in events if e["reason"] == "Preempted" and e["involvedObject"]["uid"] == low_uid]
assert preempted, events
assert pod("impossible")["status"]["phase"] == "Pending"
save({"allocatableCPU": cpu, "requestMillicoresEach": request, "lowUID": low_uid,
      "preemptedEvents": preempted, "highNode": pod("high")["spec"]["nodeName"],
      "impossibleConditions": impossible})
