<!-- Canonical: https://getpatchrail.com/fix/ci-job-timeout -->

# Job timeouts and cancellations — exceeded the maximum execution time

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/ci-job-timeout](https://getpatchrail.com/fix/ci-job-timeout)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
has exceeded the maximum execution time of 360 minutes
The operation was canceled
Too long with no output
ERROR: Job failed: execution took longer than
ran longer than the maximum time of 60 minutes
```

## What actually happened

Three distinct causes share these signatures, and telling them apart matters: a real time limit ("exceeded the maximum execution time") — the job is genuinely too slow, or it hung; matrix fail-fast cancellation ("The operation was canceled" on a job that was passing) — a sibling matrix job failed and CI killed the rest, so your job was innocent; output stall ("Too long with no output") — the process is alive but silent, usually a hung subprocess or a prompt waiting for input that will never come.

## Fix it

1. Check whether this job failed or was canceled because a sibling failed. If sibling: triage the sibling, ignore this log.
2. If it's a real timeout, compare this run's step durations against the last green run. A step that went from 4 to 40 minutes is a hang, not slowness — look for an interactive prompt, a deadlock, or an unbounded retry loop inside it.
3. If it's genuinely slow: cache dependencies, split the job, or parallelize the slowest step.
4. Raise timeout-minutes only deliberately, with a comment saying why. A raised limit without a reason is a future 60-minute hang.

## Prevent it

- Set explicit timeout-minutes per job at a value just above normal duration (e.g. p95 × 2). The default (360 minutes on GitHub Actions) means a hang costs you six hours of runner time before anyone notices.

---

**Get all 31 failure classes + the offline classifier.** The complete *CI Failure Triage Patterns* pack ($19) covers every class with downloadable step-by-step playbooks, and pairs with the `patchrail` CLI that classifies a red build locally: [patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=ci-job-timeout)

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
