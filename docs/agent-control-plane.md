# Agent Control Plane

PatchRail's control plane is a local queue for reviewable maintainer work. It is
designed for coding-agent workflows where the maintainer wants evidence,
approval gates, and an audit trail before any write action happens.

The alpha CLI stores state in SQLite:

```bash
patchrail queue init
patchrail queue add \
  --kind ci_failure \
  --title "Triage dependency install failure" \
  --source failed.log \
  --payload-file patchrail-result.json
patchrail queue list
patchrail queue show 1
patchrail queue approve 1 --note "Maintainer reviewed evidence"
patchrail queue export --format jsonl
```

To bridge CI Janitor into the queue, classify a log and convert the JSON result
into a proposed local work item:

```bash
patchrail ci classify --log failed.log --format json --out patchrail-result.json
patchrail queue from-ci-result \
  --result patchrail-result.json \
  --source failed.log \
  --priority 10
```

It can also run as a loopback-only HTTP control plane for local dashboards,
agent supervisors, or shell scripts:

```bash
patchrail serve --host 127.0.0.1 --port 8765
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/work-items
curl -X POST http://127.0.0.1:8765/work-items/1/approve \
  -H 'Content-Type: application/json' \
  -d '{"note":"Maintainer reviewed evidence"}'
curl http://127.0.0.1:8765/audit-log
```

## Safety boundary

- Network is not required.
- GitHub credentials are not required.
- External model calls are not required.
- The HTTP server binds to `127.0.0.1` by default.
- Work items start as `proposed`.
- Write actions remain outside the queue and require human approval.
- Every proposal and approval decision is recorded in the audit log.

## Statuses

| Status | Meaning |
| --- | --- |
| `proposed` | Evidence exists, but no maintainer approval has been recorded. |
| `approved` | A maintainer approved the item for a later workflow. |
| `rejected` | A maintainer rejected the item or marked it unsafe/not useful. |
| `done` | Reserved for future repair/release workflows after verification. |

The control plane is the bridge between CI Janitor reports and future repair
workflows. PatchRail should generate evidence first, queue a proposed item
second, and only let a human-approved workflow produce repository changes.

## HTTP endpoints

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/health` | `GET` | Local liveness and safety requirements. |
| `/status` | `GET` | Queue counts, audit count, version, and DB path. |
| `/work-items` | `GET` | List queue items. Supports `?status=proposed`. |
| `/work-items/<id>` | `GET` | Show one work item. |
| `/work-items/<id>/approve` | `POST` | Record human approval with optional JSON `note`. |
| `/work-items/<id>/reject` | `POST` | Record human rejection with optional JSON `note`. |
| `/audit-log` | `GET` | Export audit events as JSON. |

The HTTP API does not create pull requests, post comments, contact maintainers,
or call models. It records local evidence and human decisions so later workflows
can prove what was approved.
