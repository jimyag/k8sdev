"""可选绘图：uv run --with matplotlib python plot.py；只读取已保存证据，不访问集群。"""

import datetime
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

root = Path(__file__).resolve().parent
queue = json.loads((root / "evidence/queue-audit.json").read_text())
rows = [
    json.loads(line)
    for line in max((root / "evidence").glob("real-*.jsonl")).read_text().splitlines()
]


# 将审计中的 ISO 时间转换为秒，保留各批次独立的计时起点。
def stamp(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


# 上图展示逐任务 ACK，下图展示约 5 秒采样一次的 Ready 副本数。
fig, axes = plt.subplots(
    2, 1, figsize=(9, 6), sharex=True, gridspec_kw={"height_ratios": [2, 1]}
)
# 本次审计中任务 1～80 是单副本基线，81～160 是相同大小的 HPA 批次。
for lo, hi, label, color in [
    (1, 80, "Fixed: 1 consumer", "#4069a8"),
    (81, 160, "HPA: 1–4 consumers", "#d26732"),
]:
    events = [e for e in queue["events"] if lo <= e["id"] <= hi]
    start = min(stamp(e["time"]) for e in events if e["kind"] == "enqueue")
    completed = sorted(stamp(e["time"]) - start for e in events if e["kind"] == "ack")
    axes[0].step(
        [0] + completed,
        list(range(81)),
        where="post",
        label=f"{label} ({completed[-1]:.2f}s)",
        color=color,
        linewidth=2,
    )
    if lo == 81:
        points = [
            (stamp(r["time"]) - start, r["deployment"].get("readyReplicas", 0))
            for r in rows
            if r.get("stage") == "real-hpa-batch"
            and r.get("deployment")
            and 0 <= stamp(r["time"]) - start <= completed[-1]
        ]
        axes[1].step(
            [0] + [t for t, n in points] + [completed[-1]],
            [1] + [n for t, n in points] + [points[-1][1]],
            where="post",
            color=color,
            label="HPA Ready pods (5s samples)",
            linewidth=2,
        )
axes[1].plot(
    [0, 80.36], [1, 1], color="#4069a8", linestyle="--", label="Fixed Ready pods"
)
axes[0].set_ylabel("Completed tasks")
axes[1].set_ylabel("Ready pods")
axes[1].set_xlabel("Seconds since enqueue (80 tasks × 1 second each)")
axes[1].set_yticks([1, 2, 3, 4])
for ax in axes:
    ax.grid(alpha=0.2)
    ax.legend(loc="best", frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
(root / "figures").mkdir(exist_ok=True)
# 输出 SVG 供文章引用，不把插值或理论吞吐当成实测数据。
fig.savefig(root / "figures/queue-comparison.svg", metadata={"Date": None})
