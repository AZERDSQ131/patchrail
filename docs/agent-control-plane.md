# Agent Control Plane

PatchRail's agent control plane is an experimental local queue for reviewable
maintainer work. It is designed to turn reports, release tasks, and future
agent proposals into auditable work items before any write action happens.

The queue is local-first:

- storage is SQLite on the maintainer's machine;
- new work items start with `approval_state=pending`;
- approving an item records a maintainer decision but does not execute a write
  action;
- export is JSON or JSONL for audit, handoff, or demos;
- no command posts comments, opens pull requests, contacts third-party repos,
  claims funding, or calls an external model.

## Quickstart

Create a local queue:

```bash
patchrail queue init
```

Add a work item from a CI report:

```bash
patchrail queue add \
  --kind ci_failure \
  --title "Investigate failing dependency install" \
  --source patchrail-ci-report.md \
  --payload-json '{"report": "patchrail-ci-report.md"}'
```

List pending items:

```bash
patchrail queue list --approval-state pending
```

Inspect one item:

```bash
patchrail queue show prq_example --format markdown
```

Record a maintainer decision:

```bash
patchrail queue approve prq_example --note "Reviewed local evidence."
patchrail queue reject prq_example --note "Needs a smaller reproduction."
```

Export the local audit trail:

```bash
patchrail queue export --format jsonl > patchrail-queue.jsonl
```

For a complete local demo that starts from a CI report and ends with an
approved queue export, see
[`examples/local-agent-queue`](../examples/local-agent-queue/README.md).

## Custom Database Path

By default PatchRail stores the queue in `.patchrail/queue.sqlite` in the current
checkout. Use `--db` to keep a queue next to a demo, release, or test fixture:

```bash
patchrail queue --db /tmp/patchrail-demo.sqlite init
patchrail queue --db /tmp/patchrail-demo.sqlite list --format json
```

## Approval Boundary

Approval state is deliberately separate from execution. `patchrail queue approve`
means a maintainer reviewed the local item. It does not grant GitHub write
permissions, push commits, open a pull request, post a comment, or contact
anyone.

That boundary is the product value: maintainers can structure work for coding
agents while keeping write actions explicit, reviewable, and human-approved.

## Current Scope

The current queue is enough for local demos and release evidence:

- initialize SQLite;
- add work items;
- list and show items;
- approve or reject items;
- export work items.

Future work will add richer audit events, CI-report imports, and an end-to-end
demo importer that links `patchrail ci explain` to a queued repair proposal.
