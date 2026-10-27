"""article-next 实验共用的 kubectl 调用、条件等待和证据记录。"""

import json
import os
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parent.parent
CONTEXT = os.environ.get("ARTICLE_CONTEXT", "kind-article-next")


def command(args, data=None, check=True, timeout=300):
    result = subprocess.run(
        args,
        input=data,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if check and result.returncode:
        raise RuntimeError(f"{args}: {result.stderr}\n{result.stdout}")
    return result


def k(*args, data=None, check=True, timeout=300):
    kubectl = os.environ.get("KUBECTL", "kubectl")
    return command(
        [kubectl, "--context", CONTEXT, *args],
        data=data,
        check=check,
        timeout=timeout,
    )


def wait(fn, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(2)
    raise TimeoutError(f"condition did not converge in {timeout}s")


class Lab:
    def __init__(self, topic):
        self.ns = "article-" + topic
        self.out = ROOT / ("article-" + topic) / "evidence"
        self.out.mkdir(parents=True, exist_ok=True)
        if not os.environ.get("KUBECONFIG"):
            raise RuntimeError("请显式设置本实验 KUBECONFIG")
        nodes = json.loads(k("get", "nodes", "-o", "json").stdout)["items"]
        if not any(node["metadata"]["name"].startswith("article-next-") for node in nodes):
            raise RuntimeError("当前 context 不是 article-next 实验集群")
        k("delete", "namespace", self.ns, "--ignore-not-found", "--wait=true")
        k("create", "namespace", self.ns)
        self.save("version", json.loads(k("version", "-o", "json").stdout))

    def save(self, name, value):
        path = self.out / (name + ".json")
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        print(f"{name}: {json.dumps(value, ensure_ascii=False)[:1200]}", flush=True)

    def apply(self, obj):
        self.save("input-" + obj["kind"].lower() + "-" + obj["metadata"]["name"], obj)
        return k("apply", "-n", self.ns, "-f", "-", data=json.dumps(obj))

    def get(self, kind, name=None):
        args = ["get", kind]
        if name:
            args.append(name)
        return json.loads(k(*args, "-n", self.ns, "-o", "json").stdout)

    def patch(self, kind, name, value, check=True):
        return k(
            "patch",
            kind,
            name,
            "-n",
            self.ns,
            "--type=merge",
            "-p",
            json.dumps(value),
            check=check,
        )

    def ready(self, name, timeout="180s"):
        k("wait", "-n", self.ns, "--for=condition=Ready", "pod/" + name, "--timeout=" + timeout)

    def exec(self, name, *args, check=True):
        return k("exec", "-n", self.ns, name, "--", *args, check=check)

    def events(self):
        return self.get("events")
