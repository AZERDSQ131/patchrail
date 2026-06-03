# Reviewable Automation Workflows

PatchRail is designed to make automation workflows reviewable instead of opaque.
The public v0.1 classifier is local and deterministic, and its output can be
used as evidence for later human-reviewed repair work.

Recommended workflow:

1. Run `patchrail ci explain` on a failed CI log.
2. Review the root cause, evidence, and suggested action.
3. Add a proposed local work item with `patchrail queue add`.
4. Approve or reject the item after a maintainer reviews the evidence.
5. Ask for a minimal patch only after the failure is understood and approved.
6. Keep repository write actions behind human approval.
7. Attach before/after test output to any pull request.

Example:

```bash
patchrail ci classify --log failed.log --format json --out patchrail-result.json
patchrail queue add \
  --kind ci_failure \
  --title "Repair failed dependency install" \
  --source failed.log \
  --payload-file patchrail-result.json
patchrail queue approve 1 --note "Evidence reviewed by maintainer"
patchrail queue export --format jsonl
```

The queue is intentionally local-first. It stores work items in SQLite, records
audit events, and does not perform repository writes. A later repair workflow can
consume approved items, but PatchRail keeps the approval boundary explicit.

Repository-specific agent instructions should follow [AGENTS.md](../AGENTS.md).
