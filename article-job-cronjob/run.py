import json
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "article-next-common"))

from lab import Lab, k, wait  # noqa: E402


IMAGE = "alpine:3.20"


def labels(name):
    return {"app": name}


def job(name, command, **spec):
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "labels": labels(name)},
        "spec": {
            "template": {
                "metadata": {"labels": labels(name)},
                "spec": {
                    "restartPolicy": "Never",
                    "containers": [
                        {
                            "name": "task",
                            "image": IMAGE,
                            "imagePullPolicy": "IfNotPresent",
                            "command": ["sh", "-c", command],
                        }
                    ],
                },
            },
            **spec,
        },
    }


def condition(obj, kind):
    for item in obj.get("status", {}).get("conditions", []):
        if item.get("type") == kind and item.get("status") == "True":
            return item
    return None


def job_pods(name):
    pods = json.loads(k("get", "pods", "-n", lab.ns, "-o", "json").stdout)["items"]
    return [
        pod
        for pod in pods
        if pod["metadata"].get("labels", {}).get("job-name") == name
    ]


lab = Lab("job-cronjob")

indexed = job(
    "indexed",
    'echo "completion=${JOB_COMPLETION_INDEX}"; sleep 1',
    completions=4,
    parallelism=2,
    completionMode="Indexed",
    backoffLimit=0,
)
lab.apply(indexed)
wait(lambda: condition(lab.get("job", "indexed"), "Complete"), timeout=240)
indexed_pods = job_pods("indexed")
indices = sorted(
    int(pod["metadata"].get("annotations", {}).get("batch.kubernetes.io/job-completion-index"))
    for pod in indexed_pods
)
if indices != [0, 1, 2, 3]:
    raise AssertionError(f"Indexed Job 的索引不完整: {indices}")
lab.save(
    "indexed-job",
    {
        "job": lab.get("job", "indexed"),
        "pod_names": [pod["metadata"]["name"] for pod in indexed_pods],
        "completion_indices": indices,
    },
)

policy_job = job(
    "policy-fail",
    "exit 42",
    backoffLimit=3,
    podFailurePolicy={
        "rules": [
            {
                "action": "FailJob",
                "onExitCodes": {
                    "containerName": "task",
                    "operator": "In",
                    "values": [42],
                },
            }
        ]
    },
)
lab.apply(policy_job)
wait(lambda: condition(lab.get("job", "policy-fail"), "Failed"), timeout=180)
policy_pods = job_pods("policy-fail")
if len(policy_pods) != 1:
    raise AssertionError(f"FailJob 规则后仍创建了 {len(policy_pods)} 个 Pod")
lab.save(
    "pod-failure-policy",
    {
        "job": lab.get("job", "policy-fail"),
        "pod_count": len(policy_pods),
        "pods": policy_pods,
    },
)

backoff = job("backoff-limit", "exit 1", backoffLimit=1)
lab.apply(backoff)
wait(lambda: condition(lab.get("job", "backoff-limit"), "Failed"), timeout=240)
backoff_pods = job_pods("backoff-limit")
if len(backoff_pods) != 2:
    raise AssertionError(f"backoffLimit=1 时期望 2 个 Pod，实际 {len(backoff_pods)}")
lab.save(
    "backoff-limit",
    {
        "job": lab.get("job", "backoff-limit"),
        "pod_count": len(backoff_pods),
        "pods": backoff_pods,
    },
)

cronjob = {
    "apiVersion": "batch/v1",
    "kind": "CronJob",
    "metadata": {"name": "forbid-overlap"},
    "spec": {
        "schedule": "*/1 * * * *",
        "concurrencyPolicy": "Forbid",
        "successfulJobsHistoryLimit": 2,
        "failedJobsHistoryLimit": 1,
        "jobTemplate": {
            "spec": {
                "template": {
                    "metadata": {"labels": labels("forbid-overlap")},
                    "spec": {
                        "restartPolicy": "Never",
                        "containers": [
                            {
                                "name": "task",
                                "image": IMAGE,
                                "imagePullPolicy": "IfNotPresent",
                                "command": ["sh", "-c", "sleep 75"],
                            }
                        ],
                    },
                }
            }
        },
    },
}
lab.apply(cronjob)


def cron_jobs():
    jobs = lab.get("jobs")["items"]
    return [item for item in jobs if item["metadata"]["name"].startswith("forbid-overlap-")]


first_jobs = wait(lambda: cron_jobs() or None, timeout=150)
if len(first_jobs) != 1:
    raise AssertionError(f"首次调度后期望 1 个 Job，实际 {len(first_jobs)}")
first_name = first_jobs[0]["metadata"]["name"]

# 下一个调度点到来时，上一个 Job 仍在运行；Forbid 不应再创建 Job。
time.sleep(75)
overlap = cron_jobs()
if len(overlap) != 1 or overlap[0]["metadata"]["name"] != first_name:
    raise AssertionError(
        "Forbid 未阻止重叠: "
        + json.dumps([item["metadata"]["name"] for item in overlap], ensure_ascii=False)
    )
lab.save(
    "cronjob-forbid",
    {
        "cronjob": lab.get("cronjob", "forbid-overlap"),
        "job_names": [item["metadata"]["name"] for item in overlap],
        "active_job": overlap[0],
    },
)

lab.save(
    "result",
    {
        "indexed_completion_indices": indices,
        "pod_failure_policy_pod_count": len(policy_pods),
        "backoff_limit_pod_count": len(backoff_pods),
        "cronjob_forbid_overlap": True,
    },
)

k("delete", "namespace", lab.ns, "--wait=true")
print("PASS", flush=True)
