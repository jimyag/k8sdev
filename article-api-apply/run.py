"""Verify ownership conflict, independent fields, omission and forced transfer."""
import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
(root / "evidence").mkdir(exist_ok=True)
k = [os.environ.get("KUBECTL", str(Path.home() / ".local/bin/kubectl"))]
ns = "article-apply"
results = {}


def call(args, obj=None, conflict=False):
    p = subprocess.run(k + args, input=json.dumps(obj) if obj is not None else None, text=True, capture_output=True)
    if conflict:
        assert p.returncode != 0 and "conflict" in p.stderr.lower(), p.stderr
        return p.stderr
    assert p.returncode == 0, p.stderr
    return p.stdout


def apply(manager, data, force=False, conflict=False):
    obj = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "shared", "namespace": ns}, "data": data}
    return call(["apply", "--server-side", "--field-manager=" + manager, *(["--force-conflicts"] if force else []), "-f", "-"], obj, conflict)


def state():
    obj = json.loads(call(["-n", ns, "get", "cm", "shared", "-o", "json", "--show-managed-fields"]))
    return {"data": obj["data"], "managedFields": obj["metadata"]["managedFields"]}


assert os.environ.get("KUBECONFIG"), "set an explicit isolated KUBECONFIG"
assert call(["config", "current-context"]).strip() == "kind-article-api", "wrong cluster context"
call(["create", "namespace", ns])
apply("team-a", {"color": "blue", "obsolete": "remove-me"})
results["conflict"] = apply("team-b", {"color": "red"}, conflict=True)
apply("team-b", {"owner": "team-b"})
results["independent"] = state()
apply("team-a", {"color": "blue"})
results["omitted"] = state()
assert "obsolete" not in results["omitted"]["data"]
assert results["omitted"]["data"]["owner"] == "team-b"
apply("team-b", {"color": "red", "owner": "team-b"}, force=True)
results["forced"] = state()
assert results["forced"]["data"]["color"] == "red"
results["old_owner_conflict"] = apply("team-a", {"color": "blue"}, conflict=True)
call(["-n", ns, "patch", "cm", "shared", "--type=merge", "--field-manager=operator", "-p", '{"data":{"color":"green"}}'])
results["ordinary_patch"] = state()
assert results["ordinary_patch"]["data"]["color"] == "green"
(root / "evidence/result.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
(root / "evidence/version.json").write_text(call(["version", "-o", "json"]))
print(json.dumps({name: value if isinstance(value, str) else value["data"] for name, value in results.items()}, ensure_ascii=False))
