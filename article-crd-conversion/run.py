import base64
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "article-next-common"))

from lab import Lab, k, wait  # noqa: E402


TLS_DIR = ROOT / "tmp" / "article-next" / "crd-tls"
WEBHOOK_DIR = Path(__file__).resolve().parent
GROUP = "example.jimyag.com"
CRD_NAME = "widgets.example.jimyag.com"


def command(args, data=None, check=True):
    result = subprocess.run(args, input=data, text=True, capture_output=True)
    if check and result.returncode:
        raise RuntimeError(f"{args}: {result.stderr}\n{result.stdout}")
    return result


def apply_global(obj):
    lab.save("input-" + obj["kind"].lower() + "-" + obj["metadata"]["name"], obj)
    k("apply", "-f", "-", data=json.dumps(obj))


def make_tls(namespace):
    TLS_DIR.mkdir(parents=True, exist_ok=True)
    ca_key = TLS_DIR / "ca.key"
    ca_crt = TLS_DIR / "ca.crt"
    server_key = TLS_DIR / "server.key"
    server_csr = TLS_DIR / "server.csr"
    server_crt = TLS_DIR / "server.crt"
    ext = TLS_DIR / "server.ext"
    command(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_crt),
            "-subj",
            "/CN=article-crd-ca",
            "-days",
            "2",
        ]
    )
    command(
        [
            "openssl",
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(server_key),
            "-out",
            str(server_csr),
            "-subj",
            f"/CN=widget-webhook.{namespace}.svc",
        ]
    )
    ext.write_text(f"subjectAltName=DNS:widget-webhook.{namespace}.svc\n")
    command(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(server_csr),
            "-CA",
            str(ca_crt),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(server_crt),
            "-days",
            "2",
            "-extfile",
            str(ext),
        ]
    )
    return ca_crt, server_crt, server_key


def condition(obj, kind):
    for item in obj.get("status", {}).get("conditions", []):
        if item.get("type") == kind and item.get("status") == "True":
            return item
    return None


k("delete", "crd", CRD_NAME, "--ignore-not-found", "--wait=true")
lab = Lab("crd-conversion")
ca, cert, key = make_tls(lab.ns)
k(
    "delete",
    "secret",
    "widget-webhook-tls",
    "-n",
    lab.ns,
    "--ignore-not-found",
)
k(
    "delete",
    "configmap",
    "webhook-code",
    "-n",
    lab.ns,
    "--ignore-not-found",
)
k(
    "create",
    "secret",
    "tls",
    "widget-webhook-tls",
    "-n",
    lab.ns,
    f"--cert={cert}",
    f"--key={key}",
)
k(
    "create",
    "configmap",
    "webhook-code",
    "-n",
    lab.ns,
    f"--from-file=webhook.py={WEBHOOK_DIR / 'webhook.py'}",
)

deployment = {
    "apiVersion": "apps/v1",
    "kind": "Deployment",
    "metadata": {"name": "widget-webhook"},
    "spec": {
        "replicas": 1,
        "selector": {"matchLabels": {"app": "widget-webhook"}},
        "template": {
            "metadata": {"labels": {"app": "widget-webhook"}},
            "spec": {
                "containers": [
                    {
                        "name": "webhook",
                        "image": "python:3.12-alpine",
                        "imagePullPolicy": "IfNotPresent",
                        "command": ["python", "/app/webhook.py"],
                        "ports": [{"name": "https", "containerPort": 8443}],
                        "readinessProbe": {
                            "httpGet": {
                                "path": "/healthz",
                                "port": "https",
                                "scheme": "HTTPS",
                            },
                            "periodSeconds": 2,
                        },
                        "volumeMounts": [
                            {"name": "code", "mountPath": "/app"},
                            {"name": "tls", "mountPath": "/tls", "readOnly": True},
                        ],
                    }
                ],
                "volumes": [
                    {"name": "code", "configMap": {"name": "webhook-code"}},
                    {"name": "tls", "secret": {"secretName": "widget-webhook-tls"}},
                ],
            },
        },
    },
}
lab.apply(deployment)
k(
    "rollout",
    "status",
    "deployment/widget-webhook",
    "-n",
    lab.ns,
    "--timeout=240s",
)

service = {
    "apiVersion": "v1",
    "kind": "Service",
    "metadata": {"name": "widget-webhook"},
    "spec": {
        "selector": {"app": "widget-webhook"},
        "ports": [
            {
                "name": "https",
                "port": 443,
                "targetPort": "https",
            }
        ],
    },
}
lab.apply(service)

ca_bundle = base64.b64encode(ca.read_bytes()).decode()
schema_v1alpha1 = {
    "openAPIV3Schema": {
        "type": "object",
        "properties": {
            "spec": {
                "type": "object",
                "required": ["label"],
                "properties": {
                    "label": {"type": "string"},
                    "replicas": {"type": "integer", "minimum": 1},
                },
            },
            "status": {"type": "object", "x-kubernetes-preserve-unknown-fields": True},
        },
    }
}
schema_v1beta1 = {
    "openAPIV3Schema": {
        "type": "object",
        "properties": {
            "spec": {
                "type": "object",
                "required": ["displayName"],
                "properties": {
                    "displayName": {"type": "string"},
                    "replicas": {"type": "integer", "minimum": 1},
                },
            },
            "status": {"type": "object", "x-kubernetes-preserve-unknown-fields": True},
        },
    }
}
crd = {
    "apiVersion": "apiextensions.k8s.io/v1",
    "kind": "CustomResourceDefinition",
    "metadata": {"name": CRD_NAME},
    "spec": {
        "group": GROUP,
        "scope": "Namespaced",
        "names": {
            "plural": "widgets",
            "singular": "widget",
            "kind": "Widget",
        },
        "conversion": {
            "strategy": "Webhook",
            "webhook": {
                "conversionReviewVersions": ["v1"],
                "clientConfig": {
                    "service": {
                        "namespace": lab.ns,
                        "name": "widget-webhook",
                        "path": "/convert",
                        "port": 443,
                    },
                    "caBundle": ca_bundle,
                },
            },
        },
        "versions": [
            {
                "name": "v1alpha1",
                "served": True,
                "storage": True,
                "schema": schema_v1alpha1,
                "subresources": {"status": {}},
            },
            {
                "name": "v1beta1",
                "served": True,
                "storage": False,
                "schema": schema_v1beta1,
                "subresources": {"status": {}},
            },
        ],
    },
}
apply_global(crd)


def established():
    current = json.loads(k("get", "crd", CRD_NAME, "-o", "json").stdout)
    return current if condition(current, "Established") else None


wait(established, timeout=180)

resource = {
    "apiVersion": f"{GROUP}/v1alpha1",
    "kind": "Widget",
    "metadata": {"name": "sample"},
    "spec": {"label": "alpha", "replicas": 3, "unknown": "pruned"},
}
lab.save("input-widget-sample", resource)
k(
    "apply",
    "--validate=false",
    "-n",
    lab.ns,
    "-f",
    "-",
    data=json.dumps(resource),
)


def resource_exists(version):
    result = k(
        "get",
        f"widgets.{version}.{GROUP}",
        "sample",
        "-n",
        lab.ns,
        "-o",
        "json",
        check=False,
    )
    if result.returncode:
        return None
    return json.loads(result.stdout)


v1alpha1 = wait(lambda: resource_exists("v1alpha1"), timeout=60)
v1beta1 = wait(lambda: resource_exists("v1beta1"), timeout=60)
if v1alpha1["spec"].get("unknown") == "pruned":
    raise AssertionError("未知字段没有被 pruning")
if v1beta1["spec"] != {"displayName": "alpha", "replicas": 3}:
    raise AssertionError(f"Conversion Webhook 返回了错误对象: {v1beta1['spec']}")
lab.save(
    "converted-read",
    {
        "v1alpha1": v1alpha1,
        "v1beta1": v1beta1,
        "crd": json.loads(k("get", "crd", CRD_NAME, "-o", "json").stdout),
    },
)

patch = [
    {"op": "replace", "path": "/spec/versions/0/storage", "value": False},
    {"op": "replace", "path": "/spec/versions/1/storage", "value": True},
]
k(
    "patch",
    "crd",
    CRD_NAME,
    "--type=json",
    "-p",
    json.dumps(patch),
)


def storage_is_beta():
    current = json.loads(k("get", "crd", CRD_NAME, "-o", "json").stdout)
    stored = current.get("status", {}).get("storedVersions", [])
    return current if "v1beta1" in stored else None


after_switch = wait(storage_is_beta, timeout=120)
lab.save("storage-version-switched", after_switch)

k(
    "patch",
    f"widgets.v1beta1.{GROUP}",
    "sample",
    "-n",
    lab.ns,
    "--type=merge",
    "-p",
    json.dumps(
        {"metadata": {"annotations": {"example.jimyag.com/written-via": "v1beta1"}}}
    ),
)
rewritten = wait(lambda: resource_exists("v1beta1"), timeout=60)
lab.save(
    "written-via-beta",
    {
        "object": rewritten,
        "crd": json.loads(k("get", "crd", CRD_NAME, "-o", "json").stdout),
    },
)

k(
    "patch",
    "crd",
    CRD_NAME,
    "--type=json",
    "-p",
    json.dumps(
        [
            {"op": "replace", "path": "/spec/versions/0/served", "value": False},
        ]
    ),
)


def alpha_unserved():
    result = k(
        "get",
        f"widgets.v1alpha1.{GROUP}",
        "sample",
        "-n",
        lab.ns,
        "-o",
        "json",
        check=False,
    )
    return result if result.returncode else None


unserved = wait(alpha_unserved, timeout=90)
beta_after = resource_exists("v1beta1")
if not beta_after:
    raise AssertionError("停止服务 v1alpha1 后 v1beta1 无法读取对象")
lab.save(
    "old-version-unserved",
    {
        "v1alpha1_error": unserved.stderr.strip(),
        "v1beta1": beta_after,
        "crd": json.loads(k("get", "crd", CRD_NAME, "-o", "json").stdout),
    },
)

lab.save(
    "webhook-log",
    k("logs", "deployment/widget-webhook", "-n", lab.ns, "--tail=100").stdout,
)
lab.save(
    "result",
    {
        "conversion_webhook": True,
        "pruned_unknown_field": True,
        "storage_version_has_v1beta1": True,
        "old_version_unserved": True,
    },
)

k("delete", "crd", CRD_NAME, "--wait=true")
k("delete", "namespace", lab.ns, "--wait=true")
print("PASS", flush=True)
