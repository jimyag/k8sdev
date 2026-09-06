#!/usr/bin/env bash
set -euo pipefail
: "${HAMI_LAB_DIR:?Set HAMI_LAB_DIR to the directory created by setup.sh}"
export KUBECONFIG="$HAMI_LAB_DIR/kubeconfig"
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
kubectl --context kind-hami-test get namespace hami-tests >/dev/null
if [[ -d "$HAMI_LAB_DIR/evidence/matrix" ]]; then
  echo 'Existing test evidence found. Back it up and remove the prior test result directories before rerunning.' >&2
  exit 1
fi
python3 run-tests.py
python3 run-extra-tests.py
python3 run-final-tests.py
python3 run-advanced-tests.py
python3 cuda-control.py
python3 - <<'PY'
import json, os, pathlib, sys
root = pathlib.Path(os.environ['HAMI_LAB_DIR']) / 'evidence'
rows = []
for group in ['matrix', 'extra', 'final', 'advanced']:
    rows.extend(json.loads((root / group / 'results.json').read_text()))
(root / 'results-all.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
for r in rows:
    print(r['status'], r['case'])
failed = [r for r in rows if r['status'] != 'PASS']
print(f'{len(rows)} checks, {len(rows)-len(failed)} passed, {len(failed)} failed')
sys.exit(bool(failed))
PY
