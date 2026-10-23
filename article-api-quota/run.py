"""Verify defaulting, per-container bounds, quota and admission/scheduling separation."""
import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
(root / "evidence").mkdir(exist_ok=True)
k = [os.environ.get("KUBECTL", str(Path.home() / ".local/bin/kubectl"))]
ns = "article-quota"
results = {}


def call(args, obj=None, error=None):
    p = subprocess.run(k + args, input=json.dumps(obj) if obj is not None else None, text=True, capture_output=True)
    if error:
        assert p.returncode != 0 and error in p.stderr, p.stderr
        return p.stderr
    assert p.returncode == 0, p.stderr
    return p.stdout


def pod(name, resources=None):
    container = {"name": "main", "image": "registry.k8s.io/pause:3.10.1"}
    if resources is not None:
        container["resources"] = resources
    return {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "namespace": ns}, "spec": {"containers": [container]}}


assert os.environ.get("KUBECONFIG"), "set an explicit isolated KUBECONFIG"
assert call(["config", "current-context"]).strip() == "kind-article-api", "wrong cluster context"
call(["create", "namespace", ns])
call(["-n", ns, "create", "-f", str(root / "policy.yaml")])
call(["create", "-f", "-"], pod("defaulted"))
results["defaulted_resources"] = json.loads(call(["-n", ns, "get", "pod", "defaulted", "-o", "json"]))["spec"]["containers"][0]["resources"]
assert results["defaulted_resources"] == {"requests": {"cpu": "100m", "memory": "32Mi"}, "limits": {"cpu": "200m", "memory": "64Mi"}}
results["max_rejection"] = call(["create", "-f", "-"], pod("too-large", {"requests": {"cpu": "100m", "memory": "32Mi"}, "limits": {"cpu": "2", "memory": "64Mi"}}), error="maximum cpu usage")
call(["create", "-f", "-"], pod("second"))
results["quota_rejection"] = call(["create", "-f", "-"], pod("third"), error="exceeded quota")
results["quota"] = json.loads(call(["-n", ns, "get", "quota", "budget", "-o", "json"]))["status"]
# A different namespace demonstrates schedulability without the per-container maximum.
ns = "article-quota-capacity"
call(["create", "namespace", ns])
call(["-n", ns, "create", "quota", "generous", "--hard=requests.cpu=20000,pods=10"])
call(["create", "-f", "-"], pod("no-node-fits", {"requests": {"cpu": "10000"}}))
call(["-n", ns, "wait", "pod/no-node-fits", "--for=jsonpath={.status.conditions[0].reason}=Unschedulable", "--timeout=60s"])
obj = json.loads(call(["-n", ns, "get", "pod", "no-node-fits", "-o", "json"]))
results["capacity_pod"] = {"phase": obj["status"]["phase"], "conditions": obj["status"]["conditions"]}
assert obj["status"]["phase"] == "Pending" and not obj["spec"].get("nodeName")
(root / "evidence/result.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
(root / "evidence/version.json").write_text(call(["version", "-o", "json"]))
print(json.dumps(results, ensure_ascii=False))
