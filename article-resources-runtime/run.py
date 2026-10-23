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

NS = "article-runtime"
k("apply", "-f", "pods.yaml")
k("wait", "--for=condition=Ready", "pod/runtime-pair", "-n", NS, "--timeout=180s")
before = pod("runtime-pair")
uid = before["metadata"]["uid"]
statuses = {x["name"]: x for x in before["status"]["containerStatuses"]}
def netns(container):
    return k("exec", "-n", NS, "runtime-pair", "-c", container, "--", "readlink", "/proc/self/ns/net").strip()
namespaces = {c: netns(c) for c in ("server", "peer")}
assert namespaces["server"] == namespaces["peer"], namespaces
response = k("exec", "-n", NS, "runtime-pair", "-c", "peer", "--", "python", "-c",
             "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080').status)").strip()
assert response == "200", response
def sandboxes():
    raw = subprocess.check_output(["docker", "exec", "article-resources-control-plane", "crictl", "pods", "-o", "json"], text=True)
    return {x["metadata"]["name"]: x["id"] for x in json.loads(raw)["items"] if x["metadata"]["namespace"] == NS and x["state"] == "SANDBOX_READY"}
before_sandbox = sandboxes()
stop = subprocess.run(K + ["exec", "-n", NS, "runtime-pair", "-c", "server", "--", "python", "-c", "import os,signal; os.kill(1,signal.SIGINT)"], capture_output=True, text=True)
assert stop.returncode in (0, 137), stop.stderr
def restarted():
    p = pod("runtime-pair")
    status = next(x for x in p["status"]["containerStatuses"] if x["name"] == "server")
    return p if status["restartCount"] > statuses["server"]["restartCount"] and status.get("ready") else None
after = wait(restarted)
after_status = {x["name"]: x for x in after["status"]["containerStatuses"]}
assert after["metadata"]["uid"] == uid
assert statuses["peer"]["containerID"] == after_status["peer"]["containerID"]
after_sandbox = sandboxes()
assert before_sandbox["runtime-pair"] == after_sandbox["runtime-pair"]
bad = wait(lambda: (p if (p := pod("runtime-bad-command"))["status"].get("containerStatuses", [{}])[0].get("state", {}).get("waiting", {}).get("reason") in ("RunContainerError", "CrashLoopBackOff") else None))
assert "runtime-bad-command" in sandboxes()
events = json.loads(k("get", "events", "-n", NS, "--field-selector", "involvedObject.name=runtime-bad-command", "-o", "json"))["items"]
errors = [e["message"] for e in events if e["involvedObject"]["uid"] == bad["metadata"]["uid"] and e["reason"] == "Failed" and "/does-not-exist" in e["message"]]
assert errors, events
save({"uid": uid, "netns": namespaces, "localhostHTTP": response,
      "sandboxBefore": before_sandbox, "sandboxAfter": after_sandbox,
      "serverContainerBefore": statuses["server"]["containerID"], "serverContainerAfter": after_status["server"]["containerID"],
      "peerContainerUnchanged": True, "serverRestartCount": after_status["server"]["restartCount"],
      "badCommandWaiting": bad["status"]["containerStatuses"][0]["state"]["waiting"], "badCommandErrors": errors})
