# Local Agent Control Plane Demo

This demo turns a local CI report into a reviewable queue item, records a human
approval decision, and exports the local audit trail. It does not create pull
requests, post comments, contact repositories, call external models, require
billing, or use network access.

Run it from the repository root:

```bash
mkdir -p .patchrail-demo

patchrail ci explain \
  --log examples/ci-triage/dependency-failure.log \
  --format markdown \
  --out .patchrail-demo/ci-report.md

patchrail ci classify \
  --log examples/ci-triage/dependency-failure.log \
  --format json \
  --out .patchrail-demo/ci-result.json

patchrail queue --db .patchrail-demo/queue.sqlite init \
  --out .patchrail-demo/init.json

patchrail queue --db .patchrail-demo/queue.sqlite add \
  --from-ci-result .patchrail-demo/ci-result.json \
  --payload-json '{"markdown_report": ".patchrail-demo/ci-report.md"}' \
  --out .patchrail-demo/item.json

ITEM_ID=$(python3 -c 'import json; print(json.load(open(".patchrail-demo/item.json"))["id"])')

patchrail queue --db .patchrail-demo/queue.sqlite show "$ITEM_ID" \
  --format markdown \
  --out .patchrail-demo/item.md

patchrail queue --db .patchrail-demo/queue.sqlite approve "$ITEM_ID" \
  --note "Maintainer reviewed the local CI evidence." \
  --out .patchrail-demo/approved.json

patchrail queue --db .patchrail-demo/queue.sqlite export \
  --format jsonl \
  --out .patchrail-demo/queue.jsonl
```

Expected local artifacts:

- `.patchrail-demo/ci-report.md`: the local CI explanation.
- `.patchrail-demo/ci-result.json`: the machine-readable CI result.
- `.patchrail-demo/item.json`: the pending work item.
- `.patchrail-demo/item.md`: a human-readable queue item.
- `.patchrail-demo/approved.json`: the approval decision.
- `.patchrail-demo/queue.jsonl`: the exported audit trail.

Check the safety boundary:

```bash
python3 - <<'PY'
import json
from pathlib import Path

item = json.loads(Path(".patchrail-demo/approved.json").read_text())
assert item["approval_state"] == "approved"
assert item["write_actions_allowed"] is False
assert item["payload"]["failure_class"] == "python_dependency_resolution"
assert item["payload"]["ci_result"]["schema_version"] == "patchrail.ci_result.v1"
PY
```

Approval means a maintainer reviewed the local evidence. It does not grant
GitHub write permissions, open a pull request, post a comment, or execute any
agent action.
