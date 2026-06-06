# Agent Control Plane

PatchRail's agent control plane is an experimental local queue for reviewable
maintainer work. It is designed to turn reports, release tasks, and future
agent proposals into auditable work items before any write action happens.

The queue is local-first:

- storage is SQLite on the maintainer's machine;
- new work items start with `approval_state=pending`;
- approving an item records a maintainer decision but does not execute a write
  action;
- proposal records link a work item to a reviewable patch plan before handoff;
- export is JSON or JSONL for audit, handoff, or demos;
- audit events are local, append-only SQLite records for queue add, approve,
  reject, skip, proposal, and export decisions;
- an optional HTTP API binds to `127.0.0.1` by default for local dashboards,
  demos, and handoffs;
- no command posts comments, opens pull requests, contacts third-party repos,
  claims funding, or calls an external model.

## Quickstart

Create a local queue:

```bash
patchrail queue init
```

Check the local control-plane status:

```bash
patchrail queue status --format markdown
```

The status command summarizes work item counts, proposal counts, pending human
decisions, audit-event counts, the latest local audit event, and the safety
boundary. It is intended for maintainer handoffs and release evidence: approval
records are visible, but write actions, network access, billing, and external
models remain off by default.

The local HTTP API exposes the same `patchrail.queue_status.v1` payload at
`GET /status`, so CLI handoffs and local dashboards use one shared status
contract.

Add a work item from a local pilot pack:

```bash
patchrail ci pilot-pack \
  --log examples/ci-triage/dependency-failure.log \
  --out-dir patchrail-pilot-pack

patchrail queue add \
  --from-pilot-pack patchrail-pilot-pack
```

The pilot-pack importer reads `pilot-manifest.json`, validates that the raw log
was not copied, loads `patchrail-result.json`, and stores references to the
redacted log and Markdown report in the local work item payload.

You can also add a work item from a standalone CI result:

```bash
patchrail ci classify \
  --log examples/ci-triage/dependency-failure.log \
  --format json \
  --out patchrail-ci-result.json

patchrail queue add \
  --from-ci-result patchrail-ci-result.json
```

Manual work items are still supported:

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

Create a local proposal record for maintainer review:

```bash
patchrail queue proposal add \
  --item-id prq_example \
  --title "Pin compatible dependency range" \
  --summary "Adjust dependency constraints and re-run the affected CI matrix." \
  --patch-plan "1. Reproduce the failure.
2. Update dependency bounds.
3. Re-run the failing CI matrix." \
  --risk-level low
```

Inspect and approve the proposal:

```bash
patchrail queue proposal show prp_example --format markdown
patchrail queue proposal approve prp_example --note "Plan reviewed locally."
```

Reject a proposal that skips review or attempts a write action too early:

```bash
patchrail queue proposal reject prp_risky --note "Rejected: automatic PRs stay gated."
```

Record a maintainer decision:

```bash
patchrail queue approve prq_example --note "Reviewed local evidence."
patchrail queue reject prq_example --note "Needs a smaller reproduction."
patchrail queue skip prq_example --reason "Retired by current maintainer policy."
```

`patchrail queue skip` is for work that should remain visible but must not be
processed, such as retired workflows or out-of-scope automation. It marks the
item `status=skipped`, keeps `approval_state=rejected`, records the reason in
`decision_note`, and appends a `work_item_skipped` audit event. It does not
delete historical data or execute any action.

Export the local audit trail:

```bash
patchrail queue export --format jsonl > patchrail-queue.jsonl
patchrail queue audit --format jsonl > patchrail-audit-events.jsonl
patchrail queue policy-scan --format markdown
patchrail queue review --format markdown
patchrail queue audit-summary --format markdown
patchrail queue gate-report --format markdown
patchrail queue bundle --format markdown > patchrail-queue-bundle.md
```

`patchrail queue policy-scan` is a read-only pre-handoff brake. It scans local
work items and proposals for blocked automation signals such as automatic pull
requests, automatic issue comments, outbound contact, payout/claim language,
KYC/payment gates, package publishing, external application submission, or
other external write actions. It exits non-zero while
matching records remain active and recommends rejecting or skipping those
records before handoff. Reading the scan records no audit event, permits no
execution, redacts absolute local paths, and preserves historical queue data.

`patchrail queue review` is the compact maintainer inbox. It groups pending,
approved, and rejected work items and proposals without exporting full payloads,
patch plans, or audit history. Work items include only compact review metadata
and payload key names, so a maintainer can decide what needs attention before
opening the fuller item, proposal, gate report, or bundle. Its
`handoff_checklist` gives reviewers the next local commands to run: approve,
reject, or skip pending work items; approve or reject pending proposals; or,
when no decisions remain, run `policy-scan`, `gate-report`, and `bundle` for
the final read-only handoff packet. The command is read-only, redacts absolute
local paths, records no audit event, permits no execution, and exits non-zero
while pending work items or proposals remain.

`patchrail queue audit-summary` turns the append-only audit trail into a
release-checkable gate summary. By default it expects the full local demo
sequence: work item creation, proposal creation, proposal approval, proposal
rejection, work item approval, work item rejection, and queue export. It exits
successfully only when the required events are present. The command is read-only
against the local SQLite queue: it does not create a new audit event, execute a
proposal, open a pull request, post a comment, or contact a repository.

`patchrail queue gate-report` is the short reviewer-facing readiness check. It
combines queue status and audit-summary coverage without exporting the full
work items, proposals, or audit events. It reports pending decisions, missing
required events, decision counts, reviewer actions, and the safety boundary. It
is read-only, records no audit event, permits no execution, and exits non-zero
until all required local gate events are present and no decisions remain
pending.

`patchrail queue bundle` emits a read-only handoff packet from the same SQLite
database. The bundle includes queue status, audit-summary gate coverage, work
items, proposals, audit events, safety requirements, a reviewer checklist, and
remaining gate gaps in one JSON or Markdown artifact. The reviewer checklist
summarizes whether the handoff is ready, whether human gates are complete, how
many decisions remain pending, and what sections a maintainer should inspect
before acting on the local evidence. It redacts absolute local paths in the
emitted bundle and leaves the original SQLite records unchanged. Reading the
bundle does not add an audit event, execute a proposal, open a pull request,
post a comment, or contact a repository.

The runnable demo in
[`examples/local-agent-queue`](../examples/local-agent-queue/README.md) writes
`.patchrail-demo/gate-report.json`, `.patchrail-demo/gate-report.md`,
`.patchrail-demo/bundle.json`, and `.patchrail-demo/bundle.md`. Its stable
summary records `gate_report_status=ready_for_reviewer_handoff`,
`gate_report_pending_decisions=0`, `gate_report_execution_allowed=false`,
`bundle_status=ready_for_handoff`,
`bundle_is_read_only=true`, `bundle_records_audit_event=false`, and
`bundle_local_paths_redacted=true`. The Markdown bundle starts with a reviewer
checklist for the local CI evidence, proposal decisions, audit summary, and
safety fields, so reviewers can inspect the handoff without starting a server
or granting GitHub write permission.

From a source checkout, the installed CLI can generate and validate the same
local demo artifacts in one command:

```bash
patchrail evidence control-plane-demo \
  --out-dir .patchrail-demo \
  --force \
  --format markdown \
  --out .patchrail-demo/demo-run.md
```

The command fails closed if the checked-in demo cannot exercise the local human
approval, risky-proposal rejection, audit-summary, gate-report, and bundle
contracts. It writes `.patchrail-demo/summary.json` plus the reviewer handoff
artifacts, then validates the summary with
`patchrail evidence control-plane` before reporting `local_demo_ready`.

For reviewers who want the value signal without installing anything first, the
same stable Markdown transcript is checked in at
[`examples/control-plane-demo/demo-output.md`](../examples/control-plane-demo/demo-output.md).
It shows the SQLite queue handoff, completed human gates, read-only bundle, and
no-network/no-write safety flags in under 30 lines.

Run the local-only HTTP API:

```bash
patchrail serve --host 127.0.0.1 --port 8765 --db .patchrail/queue.sqlite
```

Example local API calls:

```bash
curl -sS http://127.0.0.1:8765/health
curl -sS http://127.0.0.1:8765/status
curl -sS http://127.0.0.1:8765/work-items
curl -sS http://127.0.0.1:8765/proposals
curl -sS http://127.0.0.1:8765/audit-events
```

See [`docs/api-reference.md`](api-reference.md) for the endpoint contract,
request fields, filters, and approval boundary.

Create and approve local records through the API:

```bash
curl -sS -X POST http://127.0.0.1:8765/work-items \
  -H 'Content-Type: application/json' \
  -d '{"kind":"ci_failure","title":"Review failed dependency install","source":"local-demo"}'

curl -sS -X POST http://127.0.0.1:8765/work-items/prq_example/approve \
  -H 'Content-Type: application/json' \
  -d '{"note":"Maintainer reviewed the local evidence."}'
```

For a complete local demo that starts from a CI report and ends with an
approved queue export, see
[`examples/local-agent-queue`](../examples/local-agent-queue/README.md).
The demo includes `run_demo.py`, which produces a stable `summary.json`
contract for release evidence and CI checks.

Audit that demo as local Agent Control Plane evidence:

```bash
patchrail evidence control-plane --format markdown
```

The command reads the checked-in demo summary, verifies the required queue
events and artifacts, and reports whether the human approval and rejection gates
were exercised. It does not use network access, billing, external models,
GitHub write permission, or repository write actions.

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

Proposal decisions are equally bounded. `patchrail queue proposal approve`
records that a maintainer accepted a local patch plan for handoff.
`patchrail queue proposal reject` records that a plan was declined, for example
because it tried to skip review or automate a write action. Neither decision
executes the plan or authorizes repository writes.

That boundary is the product value: maintainers can structure work for coding
agents while keeping write actions explicit, reviewable, and human-approved.

## Current Scope

The current queue is enough for local demos and release evidence:

- initialize SQLite;
- add work items manually or from `patchrail.ci_result.v1` JSON;
- list and show items;
- approve, reject, or skip items while preserving the audit trail;
- add, list, show, approve, and reject local proposal records;
- run a local HTTP API for `health`, `status`, work items, proposals,
  approval decisions, and audit events;
- export work items;
- export audit events for item creation, proposals, maintainer decisions, and
  handoffs;
- summarize local audit events into a release-checkable human-gate report;
- emit a short read-only gate report for reviewer handoff readiness;
- emit a read-only queue bundle for maintainer handoff and release evidence.
