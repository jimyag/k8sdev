"""Scope a real TLS AdmissionReview server to experimental ConfigMaps."""
import base64
import json
import os
from pathlib import Path
import subprocess
import time

root = Path(__file__).resolve().parent
(root / "evidence").mkdir(exist_ok=True)
scratch = root.parent / "tmp/article-api/tls"
scratch.mkdir(parents=True, exist_ok=True)
k = [os.environ.get("KUBECTL", str(Path.home() / ".local/bin/kubectl"))]
ns = "article-admission"
results = {}


def call(args, obj=None, error=None):
    p = subprocess.run(k + args, input=json.dumps(obj) if obj is not None else None, text=True, capture_output=True)
    if error:
        assert p.returncode != 0 and error.lower() in p.stderr.lower(), p.stderr
        return p.stderr
    assert p.returncode == 0, p.stderr
    return p.stdout


def create(name, deny=False, error=None, namespace=ns):
    return call(["create", "-f", "-"], {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"namespace": namespace, "name": name}, "data": {"deny": str(deny).lower()}}, error)


def policy(kind, path, failure="Fail"):
    return {"apiVersion": "admissionregistration.k8s.io/v1", "kind": kind,
            "metadata": {"name": "article-" + path}, "webhooks": [{
                "name": path + ".article.example", "admissionReviewVersions": ["v1"], "sideEffects": "None",
                "failurePolicy": failure, "timeoutSeconds": 1,
                "namespaceSelector": {"matchLabels": {"article-admission": "enabled"}},
                "clientConfig": {"url": f"https://{gateway}:{port}/{path}", "caBundle": ca},
                "rules": [{"operations": ["CREATE"], "apiGroups": [""], "apiVersions": ["v1"], "resources": ["configmaps"]}]}]}


assert os.environ.get("KUBECONFIG"), "set an explicit isolated KUBECONFIG"
assert call(["config", "current-context"]).strip() == "kind-article-api", "wrong cluster context"
gateway = subprocess.check_output(["docker", "inspect", "article-api-control-plane", "--format", '{{(index .NetworkSettings.Networks "kind").IPAddress}}'], text=True).strip()
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=article-webhook", "-addext", f"subjectAltName=IP:{gateway}", "-keyout", str(scratch / "server.key"), "-out", str(scratch / "server.crt")], check=True, capture_output=True)
port = 19443
subprocess.run(["docker", "run", "--detach", "--rm", "--name", "article-api-webhook", "--network", "container:article-api-control-plane", "-v", f"{root}:/work:ro", "-v", f"{scratch}:/tls:ro", "python:3.12-alpine", "python", "-u", "/work/webhook.py"], check=True, capture_output=True)
deadline = time.monotonic() + 30
while True:
    ready = subprocess.run(["docker", "exec", "article-api-webhook", "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 19443), timeout=1).close()"], capture_output=True)
    if ready.returncode == 0:
        break
    assert time.monotonic() < deadline, ready.stderr.decode()
ca = base64.b64encode((scratch / "server.crt").read_bytes()).decode()
call(["create", "namespace", ns])
call(["label", "namespace", ns, "article-admission=enabled"])
mutate = policy("MutatingWebhookConfiguration", "mutate")
validate = policy("ValidatingWebhookConfiguration", "validate")
try:
    call(["create", "-f", "-"], mutate)
    call(["create", "-f", "-"], validate)
    # Discovery propagation is checked by observing the actual mutation, not a fixed sleep.
    deadline = time.monotonic() + 30
    for i in range(300):
        name = "ready-" + str(i)
        create(name)
        obj = json.loads(call(["-n", ns, "get", "cm", name, "-o", "json"]))
        if obj["metadata"].get("annotations", {}).get("article.example/mutated") == "yes":
            results["mutated"] = obj["metadata"]["annotations"]
            break
        assert time.monotonic() < deadline, "webhook configuration did not propagate"
    else:
        raise AssertionError("mutation not observed")
    results["explicit_deny"] = create("denied", deny=True, error="article policy denied")
    call(["patch", "validatingwebhookconfiguration", "article-validate", "--type=json", "-p", '[{"op":"replace","path":"/webhooks/0/failurePolicy","value":"Ignore"}]'])
    deadline = time.monotonic() + 30
    while True:
        p = subprocess.run(k + ["-n", ns, "create", "configmap", "timeout-ignore"], text=True, capture_output=True)
        if p.returncode == 0:
            results["timeout_ignore"] = p.stdout.strip()
            break
        assert "deadline exceeded" in p.stderr and time.monotonic() < deadline, p.stderr
    # An Ignore call failure must never turn an explicit allowed:false into acceptance.
    results["deny_with_ignore"] = create("still-denied", deny=True, error="article policy denied")
    call(["patch", "validatingwebhookconfiguration", "article-validate", "--type=json", "-p", '[{"op":"replace","path":"/webhooks/0/failurePolicy","value":"Fail"}]'])
    results["timeout_fail"] = create("timeout-fail", error="deadline exceeded")
    call(["delete", "mutatingwebhookconfiguration", "article-mutate"])
    results["webhook_requests"] = subprocess.check_output(["docker", "logs", "article-api-webhook"], text=True)
    subprocess.run(["docker", "stop", "article-api-webhook"], check=True, capture_output=True)
    results["unavailable_fail"] = create("unavailable-fail", error="failed calling webhook")
    results["unmatched_namespace"] = create("unmatched", namespace="default").strip()
    validate["webhooks"][0]["failurePolicy"] = "Ignore"
    call(["apply", "-f", "-"], validate)
    # Test the admission result until the changed failure policy is observed.
    deadline = time.monotonic() + 30
    while True:
        p = subprocess.run(k + ["-n", ns, "create", "configmap", "unavailable-ignore"], text=True, capture_output=True)
        if p.returncode == 0:
            results["unavailable_ignore"] = p.stdout.strip()
            break
        assert "failed calling webhook" in p.stderr and time.monotonic() < deadline, p.stderr
    # Pod Security Admission enforces a separate built-in policy on Pods.
    call(["create", "namespace", "article-psa"])
    call(["label", "namespace", "article-psa", "pod-security.kubernetes.io/enforce=restricted", "pod-security.kubernetes.io/enforce-version=v1.35"])
    results["psa_reject"] = call(["-n", "article-psa", "run", "privileged", "--image=registry.k8s.io/pause:3.10.1", "--privileged=true"], error="violates PodSecurity")
    safe = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "compliant", "namespace": "article-psa"}, "spec": {"securityContext": {"runAsNonRoot": True, "runAsUser": 65532, "seccompProfile": {"type": "RuntimeDefault"}}, "containers": [{"name": "main", "image": "registry.k8s.io/pause:3.10.1", "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}}}]}}
    results["psa_allow"] = call(["create", "-f", "-"], safe).strip()
    (root / "evidence/result.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    (root / "evidence/version.json").write_text(call(["version", "-o", "json"]))
    print(json.dumps(results, ensure_ascii=False))
finally:
    call(["delete", "mutatingwebhookconfiguration", "article-mutate", "--ignore-not-found"])
    call(["delete", "validatingwebhookconfiguration", "article-validate", "--ignore-not-found"])
    subprocess.run(["docker", "rm", "-f", "article-api-webhook"], capture_output=True)
    for f in ("server.key", "server.crt"):
        (scratch / f).unlink(missing_ok=True)
