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

NS = "article-memory"
k("apply", "-f", "pods.yaml")
p = wait(lambda: (p if (p := pod("memory-oom"))["status"].get("phase") == "Failed" else None))
state = p["status"]["containerStatuses"][0]["state"]["terminated"]
assert state["reason"] == "OOMKilled", state
assert state["exitCode"] == 137, state
save({"version": json.loads(k("version", "-o", "json"))["serverVersion"],
      "uid": p["metadata"]["uid"], "qosClass": p["status"]["qosClass"], "terminated": state,
      "logs": k("logs", "memory-oom", "-n", NS)})
