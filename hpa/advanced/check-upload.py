#!/usr/bin/env python3
"""用一次性 Docker 容器验证上传 API 与计数语义；先通过 setup.sh 构建镜像。"""

import argparse
import datetime
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, timeout=60).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # 随机分配本机端口；无论断言成功与否，都移除这个临时容器。
    container = docker("run", "-d", "--rm", "-p", "127.0.0.1::8080", "hpa-advanced:v1")
    evidence = {
        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "checks": [],
    }
    try:
        port = docker("port", container, "8080/tcp").rsplit(":", 1)[1]
        base = "http://127.0.0.1:" + port

        def request(path, body=None):
            req = urllib.request.Request(base + path, data=body)
            try:
                with urllib.request.urlopen(req, timeout=15) as response:
                    return response.status, response.read().decode()
            except urllib.error.HTTPError as error:
                return error.code, error.read().decode()

        # 有上限地等待应用监听，避免用固定延迟代替就绪判断。
        for _ in range(50):
            try:
                if request("/healthz")[0] == 200:
                    break
            except urllib.error.URLError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("application did not become ready")

        for name, body, status in [
            ("method", None, 405),
            ("one_mib", b"x" * 1048576, 200),
            ("half_mib", b"x" * 524288, 200),
            ("oversized", b"x" * (8388608 + 1), 400),
        ]:
            actual, response = request("/upload", body)
            evidence["checks"].append(
                {"case": name, "status": actual, "response": response}
            )
            assert actual == status, evidence["checks"][-1]
        # 探针、抓取和拒绝请求都不应增加业务完成计数；两个成功请求共 1.5 MiB。
        status, metrics = request("/metrics")
        evidence["metrics"] = metrics
        assert status == 200
        assert "demo_http_requests_total 2\n" in metrics
        assert "demo_processed_bytes_total 1572864\n" in metrics
        evidence["result"] = "PASS"
    except Exception as error:
        evidence.update(result="FAIL", error=str(error))
        raise
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2) + "\n")
        docker("rm", "-f", container)
    print("PASS", args.output)


if __name__ == "__main__":
    main()
