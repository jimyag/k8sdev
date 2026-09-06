#!/usr/bin/env bash
# 顺序运行共享集群实验；一组失败后继续后续组，最后保留失败退出码。
set -uo pipefail
: "${VOLCANO_LAB_DIR:?Set VOLCANO_LAB_DIR to the directory created by setup.sh}"
cd "$VOLCANO_LAB_DIR" || exit 1
export KUBECONFIG="$PWD/kubeconfig"
status=0
RESULT_DIR=results-first python3 run-tests.py > evidence/tests.log 2>&1 || status=1
RESULT_DIR=results-advanced python3 run-advanced.py > evidence/advanced.log 2>&1 || status=1
RESULT_DIR=results-boundaries python3 run-boundaries.py > evidence/boundaries.log 2>&1 || status=1
RESULT_DIR=results-startup-probe python3 run-startup-probe.py > evidence/startup-probe.log 2>&1 || status=1
python3 collect-results.py "$PWD" "$PWD/report" || status=1
exit "$status"
