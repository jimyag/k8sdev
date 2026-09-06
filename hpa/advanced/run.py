#!/usr/bin/env python3
"""顺序执行有超时上限的 kind 实验；先运行 setup.sh，只依赖 Python 标准库。"""

import argparse
import contextlib
import datetime
import json
import os
import pathlib
import socket
import subprocess
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
K = ["kubectl", "--context", "kind-hpa-lab", "-n", "hpa-demo"]
STAGE = ""
OUT = None
PROXY_PORT = int(os.environ.get("HPA_PROXY_PORT", "18082"))


# 统一限定实验 context 与命名空间，收集错误并限制单条 kubectl 命令的执行时间。
def k(*args, check=True):
    r = subprocess.run(
        K + list(args), text=True, capture_output=True, timeout=210, check=False
    )
    if check and r.returncode:
        raise RuntimeError(r.stderr)
    return r.stdout


# 读取 Kubernetes 对象的原始 JSON，避免依赖人类可读表格的列宽或单位。
def get(kind, name):
    return json.loads(k("get", kind, name, "-o", "json"))


# 从脚本目录读取清单，迁移目录后仍保持各场景的相对路径有效。
def apply(name):
    k("apply", "-f", str(ROOT / name))


# 用 JSON 合并补丁修改当前场景所需字段。
def patch(kind, name, value):
    k("patch", kind, name, "--type=merge", "-p", json.dumps(value))


# 调整实验 Deployment 的副本数，用于基线或故障注入。
def scale(name, n):
    k("scale", "deployment", name, "--replicas=" + str(n))


# 保留 API 的成功数据或原始错误，区分无数据与数值为零。
def raw(path):
    try:
        return json.loads(k("get", "--raw", path))
    except RuntimeError as e:
        return {"error": str(e)}


# 读取 queue Service 上的总量指标，尚未除以 worker 副本数。
def metric():
    return raw(
        "/apis/custom.metrics.k8s.io/v1beta1/namespaces/hpa-demo/services/queue/queue_depth"
    )


# 统一使用 UTC 时间记录，便于对齐 Kubernetes 状态和应用日志。
def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# 逐行追加证据，进程中途失败时仍保留已经完成的观测。
def emit(row):
    row = {"time": now(), "stage": STAGE, **row}
    with OUT.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return row


# 记录每个阶段的起点，后续样本沿用该阶段名称。
def stage(name):
    global STAGE
    STAGE = name
    print(now(), name, flush=True)
    emit({"action": "start"})


# 借助本地 kubectl proxy 访问 Service，避免 Pod 重建后端口转发失效。
def http(port, path, post=False):
    service = {18080: "queue:8080", 18081: "broker:8080", 19090: "prometheus:9090"}[
        port
    ]
    req = urllib.request.Request(
        "http://127.0.0.1:"
        + str(PROXY_PORT)
        + "/api/v1/namespaces/hpa-demo/services/"
        + service
        + "/proxy"
        + path,
        method="POST" if post else "GET",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        b = r.read().decode()
        try:
            return json.loads(b)
        except ValueError:
            return b


# 人工设置基础实验的队列总量，并记录实际响应。
def gauge(n):
    emit(
        {
            "action": "set_gauge",
            "value": n,
            "response": http(18080, "/set?value=" + str(n), True),
        }
    )


# 同时保存 HPA 建议、Deployment 实际状态和 Pod 条件，避免只看期望副本数。
def snapshot(target="worker", broker=False):
    h = get("hpa", target) if target else {}
    d = get("deployment", target) if target else {}
    pods = (
        json.loads(k("get", "pods", "-l", "app=" + str(target), "-o", "json"))["items"]
        if target
        else []
    )
    row = {
        "target": target,
        "hpaSpec": h.get("spec"),
        "hpa": h.get("status"),
        "requested": d.get("spec", {}).get("replicas"),
        "deployment": d.get("status"),
        "pods": [
            {
                "name": p["metadata"]["name"],
                "deletionTimestamp": p["metadata"].get("deletionTimestamp"),
                "phase": p["status"]["phase"],
                "conditions": p["status"].get("conditions", []),
                "containers": p["status"].get("containerStatuses", []),
            }
            for p in pods
        ],
    }
    if broker:
        b = http(18081, "/stats")
        row["queue"] = {
            x: b[x] for x in ["accepted", "pending", "inflight", "completed", "retries"]
        }
    return emit(row)


# 按状态条件轮询；到达上限仍未满足时失败，不把固定睡眠当作成功。
def wait_for(predicate, target="worker", timeout=240, broker=False):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        r = snapshot(target, broker)
        if predicate(r):
            return r
        time.sleep(5)
    raise RuntimeError("Timeout: " + STAGE)


# 要求期望数、实际数和 Ready 数一致，且没有仍在终止的 Pod。
def steady(n, target="worker", timeout=240, broker=False):
    return wait_for(
        lambda r: (
            r["requested"] == n
            and r["deployment"].get("readyReplicas", 0) == n
            and r["deployment"].get("replicas", 0) == n
            and r["deployment"].get("terminatingReplicas", 0) == 0
            and r["hpa"].get("desiredReplicas") == n
            and any(
                c["type"] == "ScalingActive" and c["status"] == "True"
                for c in r["hpa"].get("conditions", [])
            )
        ),
        target,
        timeout,
        broker,
    )


# 在指定时段持续采样，用于验证稳定窗口或故障期间副本是否保持。
def hold(seconds, target="worker", broker=False):
    end = time.monotonic() + seconds
    rows = []
    while time.monotonic() < end:
        rows.append(snapshot(target, broker))
        time.sleep(5)
    return rows


# 等待 Deployment 发布完成，给恢复流程一个明确的就绪检查点。
def ready(name):
    k("rollout", "status", "deployment/" + name, "--timeout=180s")


# 恢复单队列指标并等待缩回 1，避免上一场景的配置影响下一场景。
def reset_worker():
    apply("../lab/hpa-queue.yaml")
    gauge(0)
    steady(1)


# 逐级升降模拟队列，并比较短暂低值与持续低值的缩容结果。
def steps():
    stage("steps-reset")
    reset_worker()
    for q, n in [(15, 2), (25, 3), (35, 4), (25, 3), (15, 2), (5, 1)]:
        stage("steps-q" + str(q) + "-to" + str(n))
        gauge(q)
        steady(n)
    stage("stabilization-high")
    gauge(35)
    steady(4)
    patch(
        "hpa",
        "worker",
        {"spec": {"behavior": {"scaleDown": {"stabilizationWindowSeconds": 60}}}},
    )
    stage("stabilization-low-pulse")
    gauge(0)
    rows = hold(25)
    assert all(r["requested"] == 4 for r in rows)
    stage("stabilization-high-again")
    gauge(35)
    hold(20)
    stage("stabilization-final-low")
    gauge(0)
    steady(1)


# 对比固定 Pod 数和百分比限速；方向切换前清除近期变化的影响。
def policies():
    for policy in ["pods", "percent"]:
        stage("policy-" + policy + "-reset")
        reset_worker()
        apply("hpa-policy-" + policy + ".yaml")
        hold(35)  # 等待前一轮副本变化离开 30 秒策略窗口。
        stage("policy-" + policy + "-up")
        gauge(35)
        steady(4)
        hold(35)
        stage("policy-" + policy + "-down")
        gauge(0)
        steady(1)


@contextlib.contextmanager
# 启动仅供本实验使用的本地 API 代理，并在正常结束或异常时清理进程。
def forwards():
    proc = subprocess.Popen(
        K + ["proxy", "--port=" + str(PROXY_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            if proc.poll() is not None:
                raise RuntimeError("kubectl proxy failed")
            try:
                with socket.create_connection(("127.0.0.1", PROXY_PORT), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("kubectl proxy timeout")
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


# 以下场景分别验证实际任务、安全退出、多指标和失败边界。
# 比较固定单副本与 HPA 的真实任务消费，再验证持续入队及在途任务缩容。
def real():
    stage("real-fixed-baseline")
    k("delete", "hpa", "consumer", "--ignore-not-found")
    scale("consumer", 1)
    ready("consumer")
    before = http(18081, "/stats")
    assert before["pending"] == before["inflight"] == 0
    if before["accepted"] != 0:
        raise RuntimeError(
            "real requires a fresh broker; restart broker after verifying the previous run has drained"
        )
    emit(
        {
            "action": "enqueue",
            "count": 80,
            "duration_ms": 1000,
            "response": http(18081, "/enqueue?n=80&duration_ms=1000", True),
        }
    )
    end = time.monotonic() + 180
    while time.monotonic() < end:
        b = http(18081, "/stats")
        emit(
            {
                "queue": {
                    x: b[x]
                    for x in ["accepted", "pending", "inflight", "completed", "retries"]
                }
            }
        )
        if b["completed"] == before["completed"] + 80:
            break
        time.sleep(5)
    else:
        raise RuntimeError("fixed consumer did not drain")
    stage("real-hpa-batch")
    apply("hpa-consumer.yaml")
    steady(1, "consumer", broker=True)
    emit(
        {
            "action": "enqueue",
            "count": 80,
            "duration_ms": 1000,
            "response": http(18081, "/enqueue?n=80&duration_ms=1000", True),
        }
    )
    wait_for(
        lambda r: r["requested"] > 1 and r["deployment"].get("readyReplicas", 0) > 1,
        "consumer",
        broker=True,
    )
    wait_for(
        lambda r: r["queue"]["pending"] == r["queue"]["inflight"] == 0,
        "consumer",
        broker=True,
    )
    steady(1, "consumer", broker=True)
    stage("real-continuous-producer")
    # 每秒提交一个任务，每个任务占用一个 worker 两秒，单副本会逐渐积压。
    start = time.monotonic()
    next_at = start
    count = 0
    while time.monotonic() - start < 60:
        http(18081, "/enqueue?n=1&duration_ms=2000", True)
        count += 1
        if count % 5 == 0:
            snapshot("consumer", True)
        next_at += 1
        time.sleep(max(0, next_at - time.monotonic()))
    emit({"action": "producer_stopped", "count": count})
    wait_for(
        lambda r: r["queue"]["pending"] == r["queue"]["inflight"] == 0,
        "consumer",
        broker=True,
    )
    steady(1, "consumer", broker=True)
    stage("graceful-prepare-four")
    patch("hpa", "consumer", {"spec": {"minReplicas": 4}})
    steady(4, "consumer", broker=True)
    names = k(
        "get", "pods", "-l", "app=consumer", "-o", "jsonpath={.items[*].metadata.name}"
    ).split()
    logs = []
    try:
        for name in names:
            f = (OUT.parent / (name + ".log")).open("w")
            proc = subprocess.Popen(
                K + ["logs", "-f", name, "--timestamps=true"],
                stdout=f,
                stderr=subprocess.STDOUT,
            )
            logs.append((proc, f))
        emit(
            {
                "action": "enqueue_long_tasks",
                "response": http(18081, "/enqueue?n=4&duration_ms=60000", True),
            }
        )
        wait_for(lambda r: r["queue"]["inflight"] == 4, "consumer", broker=True)
        stage("graceful-hpa-downscale")
        patch(
            "hpa",
            "consumer",
            {
                "spec": {
                    "minReplicas": 1,
                    "behavior": {"scaleDown": {"stabilizationWindowSeconds": 0}},
                }
            },
        )
        wait_for(
            lambda r: (
                r["requested"] == 1 and any(p["deletionTimestamp"] for p in r["pods"])
            ),
            "consumer",
            broker=True,
        )
        wait_for(
            lambda r: r["queue"]["pending"] == r["queue"]["inflight"] == 0,
            "consumer",
            broker=True,
        )
        steady(1, "consumer", broker=True)
    finally:
        for proc, f in logs:
            proc.terminate()
            proc.wait(timeout=5)
            f.close()
    b = http(18081, "/stats")
    (OUT.parent / "queue-audit.json").write_text(json.dumps(b, indent=2) + "\n")
    assert b["completed"] == b["accepted"] and b["retries"] == 0
    assert all(t["done"] and t["attempts"] == 1 for t in b["tasks"])
    assert not [e for e in b["events"] if e["kind"] == "rejected_ack"]
    emit({"result": "tasks_all_completed_once", "accepted": b["accepted"]})


# 让 CPU 和队列给出不同建议，并验证部分指标失败时扩容与缩容的区别。
def multi():
    stage("multi-reset")
    reset_worker()
    apply("hpa-multi.yaml")
    gauge(35)
    steady(4)
    stage("multi-cpu-low-queue-high")
    hold(25)
    gauge(0)
    scale("adapter-prometheus-adapter", 0)
    try:
        stage("multi-cpu-low-metric-failed")
        wait_for(
            lambda r: any(
                c["type"] == "ScalingActive" and c["status"] == "False"
                for c in r["hpa"].get("conditions", [])
            )
        )
        emit({"customAPI": metric()})
        rows = hold(45)
        assert all(r["requested"] == 4 for r in rows)
    finally:
        scale("adapter-prometheus-adapter", 1)
        ready("adapter-prometheus-adapter")
    stage("multi-recover-down")
    steady(1)
    scale("adapter-prometheus-adapter", 0)
    try:
        stage("multi-cpu-high-metric-failed")
        emit({"customAPI": metric()})
        apply("../lab/load.yaml")
        steady(4)
        unavailable = metric()
        emit({"customAPI": unavailable})
        assert "error" in unavailable
    finally:
        k("delete", "deployment", "load", "--ignore-not-found")
        scale("adapter-prometheus-adapter", 1)
        ready("adapter-prometheus-adapter")
    stage("multi-all-low")
    gauge(0)
    steady(1)
    stage("multi-cpu-high-queue-zero")
    apply("../lab/load.yaml")
    try:
        steady(4)
        emit({"customAPI": metric()})
    finally:
        k("delete", "deployment", "load", "--ignore-not-found")
    stage("multi-final-down")
    steady(1)


# 依次停用 exporter、Prometheus 和 Adapter，每轮恢复后再进行下一轮故障。
def failures():
    stage("failures-reset")
    reset_worker()
    gauge(35)
    steady(4)
    for component in ["queue", "prometheus", "adapter-prometheus-adapter"]:
        stage("failure-" + component)
        scale(component, 0)
        try:
            for _ in range(8):
                emit(
                    {
                        "customAPI": metric(),
                        "prometheusQuery": raw(
                            "/api/v1/namespaces/hpa-demo/services/prometheus:9090/proxy/api/v1/query?query=demo_queue_depth"
                        ),
                    }
                )
                snapshot()
                time.sleep(5)
            r = snapshot()
            assert r["requested"] == 4
            assert any(
                c["type"] == "ScalingActive" and c["status"] == "False"
                for c in r["hpa"].get("conditions", [])
            )
        finally:
            scale(component, 1)
            ready(component)
        stage("failure-" + component + "-recover")
        gauge(35)
        steady(4)
    stage("real-zero")
    gauge(0)
    steady(1)


# 用独立目标制造资源不足，再给 web 注入慢启动；不改变节点配置。
def scheduling():
    stage("pending-prepare")
    reset_worker()
    gauge(35)
    # 创建独立目标并请求无法满足的 CPU 数量，不修改节点或其他工作负载。
    d = get("deployment", "web")
    for field in [
        "uid",
        "resourceVersion",
        "generation",
        "creationTimestamp",
        "managedFields",
        "annotations",
    ]:
        d["metadata"].pop(field, None)
    d.pop("status", None)
    d["metadata"]["name"] = "blocked"
    d["spec"]["replicas"] = 1
    d["spec"]["selector"]["matchLabels"] = {"app": "blocked"}
    d["spec"]["template"]["metadata"] = {"labels": {"app": "blocked"}}
    c = d["spec"]["template"]["spec"]["containers"][0]
    c["resources"]["requests"]["cpu"] = "1000"
    c["resources"]["limits"]["cpu"] = "1000"
    subprocess.run(
        K + ["apply", "-f", "-"],
        input=json.dumps(d),
        text=True,
        check=True,
        capture_output=True,
    )
    h = get("hpa", "worker")
    h = {
        "apiVersion": "autoscaling/v2",
        "kind": "HorizontalPodAutoscaler",
        "metadata": {"name": "blocked", "namespace": "hpa-demo"},
        "spec": h["spec"],
    }
    h["spec"]["scaleTargetRef"]["name"] = "blocked"
    subprocess.run(
        K + ["apply", "-f", "-"],
        input=json.dumps(h),
        text=True,
        check=True,
        capture_output=True,
    )
    stage("pending-desired-four")
    wait_for(
        lambda r: (
            r["requested"] == 4
            and len(r["pods"]) == 4
            and all(p["phase"] == "Pending" for p in r["pods"])
        ),
        "blocked",
    )
    emit(
        {
            "events": json.loads(
                k(
                    "get",
                    "events",
                    "--field-selector",
                    "reason=FailedScheduling",
                    "-o",
                    "json",
                )
            )
        }
    )
    k("delete", "hpa", "blocked")
    k("delete", "deployment", "blocked")
    stage("slow-start-prepare")
    k("delete", "hpa", "web", "--ignore-not-found")
    scale("web", 1)
    patch(
        "deployment",
        "web",
        {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            dict(
                                name="web",
                                image="hpa-advanced:v1",
                                args=["http"],
                                ports=[dict(containerPort=8080, name="http")],
                                env=[dict(name="READY_DELAY_SECONDS", value="60")],
                                resources=dict(
                                    requests=dict(cpu="100m", memory="32Mi"),
                                    limits=dict(cpu="500m", memory="128Mi"),
                                ),
                                readinessProbe=dict(
                                    httpGet=dict(path="/healthz", port=8080),
                                    periodSeconds=2,
                                ),
                            )
                        ]
                    }
                }
            }
        },
    )
    ready("web")
    h["metadata"]["name"] = "web"
    h["spec"]["scaleTargetRef"]["name"] = "web"
    subprocess.run(
        K + ["apply", "-f", "-"],
        input=json.dumps(h),
        text=True,
        check=True,
        capture_output=True,
    )
    stage("slow-start-desired-four")
    wait_for(
        lambda r: r["requested"] == 4 and r["deployment"].get("readyReplicas", 0) < 4,
        "web",
    )
    steady(4, "web")
    stage("slow-start-down")
    gauge(0)
    steady(1, "web")
    k("delete", "hpa", "web")
    k("set", "env", "deployment/web", "READY_DELAY_SECONDS-")
    apply("workloads.yaml")
    ready("web")


# 用每 Pod 请求速率扩缩 web，同时核对原始 API 与总请求速率。
def pods():
    stage("pods-reset")
    apply("hpa-pods.yaml")
    steady(1, "web")
    stage("pods-rate-up")
    apply("load-http.yaml")
    try:
        wait_for(
            lambda r: (
                r["requested"] >= 3 and r["deployment"].get("readyReplicas", 0) >= 3
            ),
            "web",
        )
        rows = hold(60, "web")
        assert (
            rows[-1]["requested"] == 4
            and rows[-1]["deployment"].get("readyReplicas") == 4
        )
        emit(
            {
                "customAPI": raw(
                    "/apis/custom.metrics.k8s.io/v1beta1/namespaces/hpa-demo/pods/*/http_requests_per_second?labelSelector=app%3Dweb"
                )
            }
        )
        emit(
            {
                "rateQuery": raw(
                    "/api/v1/namespaces/hpa-demo/services/prometheus:9090/proxy/api/v1/query?query=sum(rate(demo_http_requests_total%5B30s%5D))"
                )
            }
        )
    finally:
        k("delete", "deployment", "http-load", "--ignore-not-found")
    stage("pods-rate-down")
    steady(1, "web")


# 命令行一次只执行一个场景；全部断言满足才记录 PASS，失败保留证据并非零退出。
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "case",
        choices=[
            "steps",
            "policies",
            "real",
            "multi",
            "failures",
            "scheduling",
            "pods",
        ],
    )
    parser.add_argument("--output", type=pathlib.Path, default=ROOT / "evidence")
    args = parser.parse_args()
    if not os.environ.get("KUBECONFIG"):
        raise SystemExit("Set dedicated KUBECONFIG first")
    args.output.mkdir(parents=True, exist_ok=True)
    OUT = args.output / (
        args.case
        + "-"
        + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".jsonl"
    )
    with forwards():
        try:
            globals()[args.case]()
            emit({"result": "PASS"})
            print("PASS", args.case, OUT, flush=True)
        except Exception as e:
            emit({"result": "FAIL", "error": str(e)})
            raise
