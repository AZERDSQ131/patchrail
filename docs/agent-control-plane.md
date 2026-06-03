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

## Safety boundary

- Network is not required.
- GitHub credentials are not required.
- External model calls are not required.
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
