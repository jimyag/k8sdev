import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "article-next-common"))

from lab import Lab, k, wait  # noqa: E402


def apply_global(obj):
    lab.save("input-" + obj["kind"].lower() + "-" + obj["metadata"]["name"], obj)
    k("apply", "-f", "-", data=json.dumps(obj))


def storage_class(name, allow):
    return {
        "apiVersion": "storage.k8s.io/v1",
        "kind": "StorageClass",
        "metadata": {"name": name},
        "provisioner": "hostpath.csi.k8s.io",
        "reclaimPolicy": "Delete",
        "volumeBindingMode": "Immediate",
        "allowVolumeExpansion": allow,
    }


def pvc(name, sc, size):
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {"name": name},
        "spec": {
            "storageClassName": sc,
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": size}},
        },
    }


def consumer(name, claim, node):
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "labels": {"app": name}},
        "spec": {
            "terminationGracePeriodSeconds": 1,
            "nodeSelector": {"kubernetes.io/hostname": node},
            "containers": [
                {
                    "name": "app",
                    "image": "alpine:3.20",
                    "imagePullPolicy": "IfNotPresent",
                    "command": ["sh", "-c", "sleep 3600"],
                    "volumeMounts": [{"name": "data", "mountPath": "/data"}],
                }
            ],
            "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": claim}}],
        },
    }


lab = Lab("pvc-expansion")

driver = json.loads(
    k("get", "pod", "csi-hostpathplugin-0", "-o", "json").stdout
)
node = driver["spec"]["nodeName"]
lab.save(
    "driver",
    {
        "pod": driver["metadata"]["name"],
        "node": node,
        "images": [item["image"] for item in driver["spec"]["containers"]],
    },
)

apply_global(storage_class("article-expand", True))
apply_global(storage_class("article-no-expand", False))

lab.apply(pvc("expand", "article-expand", "64Mi"))
wait(lambda: lab.get("pvc", "expand")["status"]["phase"] == "Bound", timeout=180)
before_pvc = lab.get("pvc", "expand")
before_pv = lab.get("pv", before_pvc["spec"]["volumeName"])
lab.save("before", {"pvc": before_pvc, "pv": before_pv})

lab.apply(consumer("writer", "expand", node))
lab.ready("writer", timeout="240s")
lab.exec("writer", "sh", "-c", "printf persistent >/data/proof")

patch = lab.patch(
    "pvc",
    "expand",
    {"spec": {"resources": {"requests": {"storage": "128Mi"}}}},
)
if patch.returncode:
    raise RuntimeError(f"PVC 扩容请求失败: {patch.stderr}")


def resize_pending():
    current = lab.get("pvc", "expand")
    conditions = current.get("status", {}).get("conditions", [])
    pending = any(
        item.get("type") == "FileSystemResizePending" and item.get("status") == "True"
        for item in conditions
    )
    allocated = (
        current.get("status", {}).get("allocatedResources", {}).get("storage")
    )
    if pending and allocated == "128Mi":
        return current
    return None


pending_pvc = wait(resize_pending, timeout=180)
lab.save(
    "controller-expanded",
    {
        "pvc": pending_pvc,
        "pv": lab.get("pv", pending_pvc["spec"]["volumeName"]),
    },
)

k("delete", "pod", "writer", "-n", lab.ns, "--wait=true")
lab.apply(consumer("writer", "expand", node))
lab.ready("writer", timeout="240s")


def expanded():
    current = lab.get("pvc", "expand")
    if current.get("status", {}).get("capacity", {}).get("storage") == "128Mi":
        return current
    return None


after_pvc = wait(expanded, timeout=240)
after_pv = lab.get("pv", after_pvc["spec"]["volumeName"])
df = lab.exec("writer", "df", "-h", "/data").stdout
if lab.exec("writer", "cat", "/data/proof").stdout != "persistent":
    raise AssertionError("扩容后原有数据不可读")
lab.save(
    "after-expand",
    {
        "pvc": after_pvc,
        "pv": after_pv,
        "df": df,
        "data": "persistent",
        "events": lab.events(),
    },
)

shrink = lab.patch(
    "pvc",
    "expand",
    {"spec": {"resources": {"requests": {"storage": "64Mi"}}}},
    check=False,
)
if shrink.returncode == 0:
    raise AssertionError("PVC 缩容请求没有被拒绝")
lab.save(
    "shrink-rejected",
    {"exit_code": shrink.returncode, "stderr": shrink.stderr.strip()},
)

lab.apply(pvc("no-expand", "article-no-expand", "64Mi"))
wait(lambda: lab.get("pvc", "no-expand")["status"]["phase"] == "Bound", timeout=180)
no_expand = lab.patch(
    "pvc",
    "no-expand",
    {"spec": {"resources": {"requests": {"storage": "128Mi"}}}},
    check=False,
)
if no_expand.returncode == 0:
    raise AssertionError("未允许扩容的 StorageClass 没有拒绝修改")
lab.save(
    "storageclass-disallowed",
    {
        "exit_code": no_expand.returncode,
        "stderr": no_expand.stderr.strip(),
        "pvc": lab.get("pvc", "no-expand"),
    },
)

# 状态完成后再取一次日志，避免只看控制器阶段、漏掉节点扩容调用。
driver_log = k(
    "logs",
    "csi-hostpathplugin-0",
    "-c",
    "hostpath",
    "-n",
    "default",
    "--tail=1200",
).stdout
resizer_log = k(
    "logs",
    "csi-hostpathplugin-0",
    "-c",
    "csi-resizer",
    "-n",
    "default",
    "--tail=1200",
).stdout
volume_handle = after_pv["spec"]["csi"]["volumeHandle"]
expanded_calls = [
    line
    for line in driver_log.splitlines()
    if "ExpandVolume" in line and volume_handle in line
]
resize_lines = [
    line
    for line in resizer_log.splitlines()
    if f'"key":"{lab.ns}/expand"' in line
    and (
        "ControllerExpandVolume" in line
        or "file system resize" in line.lower()
        or "Resize volume succeeded" in line
    )
]
if not expanded_calls:
    raise AssertionError("CSI 驱动日志没有 ControllerExpandVolume 或 NodeExpandVolume")
lab.save(
    "csi-log",
    {
        "driver_expand_lines": expanded_calls,
        "resizer_lines": resize_lines,
    },
)

lab.save(
    "result",
    {
        "initial_capacity": "64Mi",
        "expanded_capacity": "128Mi",
        "data_preserved": True,
        "shrink_rejected": True,
        "storageclass_without_expansion_rejected": True,
        "hostpath_df": df.strip(),
        "hostpath_capacity_is_metadata_only": True,
    },
)

k("delete", "namespace", lab.ns, "--wait=true")
k("delete", "storageclass", "article-expand", "article-no-expand", "--wait=true")
print("PASS", flush=True)
