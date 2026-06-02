# Reviewable Automation Workflows

PatchRail is designed to make automation workflows reviewable instead of opaque.
The public v0.1 classifier is local and deterministic, and its output can be
used as evidence for later human-reviewed repair work.

Recommended workflow:

1. Run `patchrail ci explain` on a failed CI log.
2. Review the root cause, evidence, and suggested action.
3. Ask for a minimal patch only after the failure is understood.
4. Keep repository write actions behind human approval.
5. Attach before/after test output to any pull request.

The bundled [GitHub Actions CI triage workflow](github-action.md) follows the
same boundary: it uploads local PatchRail reports as artifacts and does not
comment, open pull requests, push commits, or call external models.

Repository-specific agent instructions should follow [AGENTS.md](../AGENTS.md).
