"""Verify authentication and namespace/subresource authorization on the isolated cluster."""
import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
evidence = root / "evidence"
evidence.mkdir(exist_ok=True)
ns = "article-rbac"
k = [os.environ.get("KUBECTL", str(Path.home() / ".local/bin/kubectl"))]
results = {}


def call(args, obj=None, expected=None, prefix=None):
    p = subprocess.run((prefix or k) + args, input=json.dumps(obj) if obj is not None else None,
                       text=True, capture_output=True)
    if expected is None:
        assert p.returncode == 0, p.stderr
    else:
        assert p.returncode != 0 and expected in p.stderr, p.stderr or p.stdout
    return p.stdout if p.returncode == 0 else p.stderr or p.stdout


def create(kind, name, **fields):
    obj = {"apiVersion": "v1", "kind": kind, "metadata": {"name": name, "namespace": ns}, **fields}
    if kind in ("Role", "RoleBinding"):
        obj["apiVersion"] = "rbac.authorization.k8s.io/v1"
    return call(["create", "-f", "-"], obj)


assert os.environ.get("KUBECONFIG"), "set an explicit isolated KUBECONFIG"
assert call(["config", "current-context"]).strip() == "kind-article-api", "wrong cluster context"
call(["create", "namespace", ns])
call(["create", "namespace", ns + "-other"])
create("ServiceAccount", "reader")
create("Pod", "demo", spec={"containers": [{"name": "main", "image": "registry.k8s.io/pause:3.10.1"}]})
create("Role", "reader", rules=[{"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list"]}])
create("RoleBinding", "reader", roleRef={"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "reader"},
       subjects=[{"kind": "ServiceAccount", "name": "reader", "namespace": ns}])
config = json.loads(call(["config", "view", "--minify", "--raw", "-o", "json"]))
token = call(["-n", ns, "create", "token", "reader", "--duration=10m"]).strip()
config["users"] = [{"name": "reader", "user": {"token": token}}]
config["contexts"][0]["context"]["user"] = "reader"
scratch = root.parent / "tmp/article-api"
scratch.mkdir(parents=True, exist_ok=True)
cfg = scratch / "reader-config.json"
cfg.write_text(json.dumps(config))
cfg.chmod(0o600)
user = k + ["--kubeconfig", str(cfg)]
try:
    results["read_pod"] = json.loads(call(["-n", ns, "get", "pod", "demo", "-o", "json"], prefix=user))["metadata"]["name"]
    results["log_forbidden"] = call(["-n", ns, "get", "--raw", f"/api/v1/namespaces/{ns}/pods/demo/log"], expected="Forbidden", prefix=user)
    results["patch_forbidden"] = call(["-n", ns, "patch", "pod", "demo", "--type=merge", "-p", '{"metadata":{"labels":{"test":"x"}}}'], expected="Forbidden", prefix=user)
    results["other_namespace_forbidden"] = call(["-n", ns + "-other", "get", "pods"], expected="Forbidden", prefix=user)
    results["can_get_logs_before"] = call(["auth", "can-i", "get", "pods", "--subresource=log", "-n", ns], expected="", prefix=user).strip()
    call(["-n", ns, "patch", "role", "reader", "--type=json", "-p", '[{"op":"add","path":"/rules/-","value":{"apiGroups":[""],"resources":["pods/log"],"verbs":["get"]}}]'])
    results["can_get_logs_after"] = call(["auth", "can-i", "get", "pods", "--subresource=log", "-n", ns], prefix=user).strip()
    config["users"][0]["user"]["token"] = "not-a-valid-token"
    cfg.write_text(json.dumps(config))
    results["invalid_token"] = call(["-n", ns, "get", "pods"], expected="Unauthorized", prefix=user)
    (evidence / "result.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    (evidence / "version.json").write_text(call(["version", "-o", "json"]))
    print(json.dumps(results, ensure_ascii=False))
finally:
    cfg.unlink(missing_ok=True)
