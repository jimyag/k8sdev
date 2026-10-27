import json
import os
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "evidence"
CTX = "kind-article-image"
NS = "article-image"
KUBECTL = os.environ.get("KUBECTL", "kubectl")
KIND = os.environ.get("KIND", "kind")


def command(args, data=None, check=True, timeout=300, env=None):
    result = subprocess.run(
        args,
        input=data,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )
    if check and result.returncode:
        raise RuntimeError(f"{args}: {result.stderr}\n{result.stdout}")
    return result


def k(*args, data=None, check=True, timeout=300):
    return command(
        [KUBECTL, "--context", CTX, *args],
        data=data,
        check=check,
        timeout=timeout,
    )


def wait(fn, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(2)
    raise TimeoutError(f"condition did not converge in {timeout}s")


def save(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    )
    print(f"{name}: {json.dumps(value, ensure_ascii=False)[:1200]}", flush=True)


def pod(name, image, command_args):
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "labels": {"app": name}},
        "spec": {
            "containers": [
                {
                    "name": "app",
                    "image": image,
                    "imagePullPolicy": "Always",
                    "command": command_args,
                }
            ]
        },
    }


def apply_obj(obj):
    save("input-" + obj["metadata"]["name"], obj)
    k("apply", "-n", NS, "-f", "-", data=json.dumps(obj))


def get(kind, name):
    return json.loads(k("get", kind, name, "-n", NS, "-o", "json").stdout)


def node_name():
    return json.loads(k("get", "nodes", "-o", "json").stdout)["items"][0]["metadata"][
        "name"
    ]


def node_stats(name):
    raw = k(
        "get",
        "--raw",
        f"/api/v1/nodes/{name}/proxy/stats/summary",
    ).stdout
    return json.loads(raw)


def crictl_images(node):
    container = "article-image-control-plane"
    result = command(["docker", "exec", container, "crictl", "images", "-o", "json"])
    return json.loads(result.stdout)


def image_present(images, tag):
    return any(
        tag in image.get("repoTags", []) or tag in image.get("repoDigests", [])
        for image in images.get("images", [])
    )


OUT.mkdir(parents=True, exist_ok=True)
supported = json.loads(k("get", "nodes", node_name(), "-o", "json").stdout)
version = json.loads(k("version", "-o", "json").stdout)
save("version", version)

k("delete", "namespace", NS, "--ignore-not-found", "--wait=true")
k("create", "namespace", NS)

pulled = pod(
    "pull-ok",
    "alpine:3.20",
    ["sh", "-c", "sleep 3600"],
)
apply_obj(pulled)
k("wait", "-n", NS, "--for=condition=Ready", "pod/pull-ok", "--timeout=240s")

failed = pod(
    "pull-fail",
    "example.invalid/kubernetes-image-does-not-exist:never",
    ["true"],
)
apply_obj(failed)


def pull_failed():
    current = get("pod", "pull-fail")
    for status in current.get("status", {}).get("containerStatuses", []):
        waiting = status.get("state", {}).get("waiting", {})
        if waiting.get("reason") == "ImagePullBackOff":
            return waiting
    return None


pull_waiting = wait(pull_failed, timeout=240)
save(
    "pull-failure",
    {
        "pod": get("pod", "pull-fail"),
        "events": json.loads(k("get", "events", "-n", NS, "-o", "json").stdout),
    },
)

node = node_name()
before = crictl_images(node)
save("images-before", before)
assert image_present(before, "docker.io/library/alpine:3.20") or image_present(
    before, "alpine:3.20"
)

stats = node_stats(node)
image_fs = stats["node"]["runtime"]["imageFs"]
capacity = int(image_fs["capacityBytes"])
used = int(image_fs["usedBytes"])
required = max(512 * 1024 * 1024, capacity // 100 - used + 256 * 1024 * 1024)
required = ((required + 63 * 1024 * 1024) // (64 * 1024 * 1024)) * 64 * 1024 * 1024
if required > 6 * 1024 * 1024 * 1024:
    raise RuntimeError(
        f"ImageFS 太大，需要构造 {required} 字节未使用镜像；请调整实验盘容量"
    )

build_dir = ROOT / "tmp" / "article-image" / "unused-image"
build_dir.mkdir(parents=True, exist_ok=True)
blob = build_dir / "blob"
with blob.open("wb") as stream:
    remaining = required
    chunk = os.urandom(1024 * 1024)
    while remaining:
        size = min(len(chunk), remaining)
        stream.write(chunk[:size])
        remaining -= size
(build_dir / "Dockerfile").write_text("FROM scratch\nCOPY blob /blob\n")
command(
    [
        "docker",
        "build",
        "--platform",
        "linux/amd64",
        "-t",
        "article-unused:1",
        str(build_dir),
    ],
    timeout=900,
    env={**os.environ, "DOCKER_DEFAULT_PLATFORM": "linux/amd64"},
)
command(
    [KIND, "load", "docker-image", "article-unused:1", "--name", "article-image"],
    timeout=900,
)
image_id = json.loads(
    command(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            "{{json .Id}}",
            "article-unused:1",
        ]
    ).stdout
)
loaded = crictl_images(node)
save("images-loaded", loaded)
if not any(image.get("id") == image_id for image in loaded.get("images", [])):
    raise AssertionError(f"未在节点找到镜像 ID {image_id}")

# 重启 kubelet 会立即执行一次镜像回收，不必等待默认的 5 分钟周期。
command(["docker", "exec", "article-image-control-plane", "systemctl", "restart", "kubelet"])


def gc_evaluated():
    logs = command(
        [
            "docker",
            "exec",
            "article-image-control-plane",
            "journalctl",
            "-u",
            "kubelet",
            "-n",
            "400",
            "--no-pager",
        ]
    ).stdout
    lines = [
        line
        for line in logs.splitlines()
        if "Image garbage collection" in line
        or "Disk usage on image filesystem is over the high threshold" in line
        or "Removing image to free bytes" in line
        or "Insufficient free disk space" in line
        or ("failed multiple times in a row" in line and "freed " in line)
    ]
    if any("Disk usage on image filesystem" in line for line in lines):
        return lines
    return None


gc_lines = wait(gc_evaluated, timeout=180)
after = crictl_images(node)
save("images-after", after)
save("kubelet-gc-lines", gc_lines)

in_use_retained = image_present(
    after, "docker.io/library/alpine:3.20"
) or image_present(after, "alpine:3.20")
if not in_use_retained:
    raise AssertionError("正在被容器使用的 alpine 镜像被错误回收")

low_threshold_reached = any("Image garbage collection succeeded" in line for line in gc_lines)
save(
    "result",
    {
        "image_pull_backoff": pull_waiting,
        "image_fs_capacity_bytes": capacity,
        "image_fs_used_bytes": used,
        "unused_image_bytes": required,
        "image_gc_evaluated": True,
        "low_threshold_reached": low_threshold_reached,
        "partial_unused_image_eviction_observed": any(
            "image_gc_manager.go:528" in line for line in gc_lines
        ),
        "in_use_image_retained": True,
        "node_images": after,
        "node_summary": supported,
    },
)

k("delete", "namespace", NS, "--wait=true")
print("PASS", flush=True)
