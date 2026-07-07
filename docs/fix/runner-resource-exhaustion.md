<!-- Canonical: https://getpatchrail.com/fix/runner-resource-exhaustion -->

# Runner resource exhaustion — exit code 137 / OOMKilled

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/runner-resource-exhaustion](https://getpatchrail.com/fix/runner-resource-exhaustion)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
Process completed with exit code 137
OOMKilled
JavaScript heap out of memory
No space left on device
signal: killed
```

## What actually happened

The runner — not your program — hit a hard resource ceiling. Exit code 137 is the giveaway: it means the process received SIGKILL (128 + 9), which on Linux almost always means the kernel OOM killer fired. ENOSPC and "No space left on device" are the disk-side equivalents, frequently caused by accumulated Docker layers, package caches, or test artifacts on long-lived runners. The trap: the visible error is often downstream — a test "mysteriously failed" because the process it depended on was silently killed.

## Fix it

1. Search the log for 137, signal: killed, or OOMKilled before the first test failure. If present, stop debugging the test.
2. Rerun while measuring: wrap the heavy step in /usr/bin/time -v (peak RSS) and print df -h before and after.
3. Reduce peak usage first: lower test parallelism (pytest -n2, jest --maxWorkers=2), cap heap (NODE_OPTIONS=--max-old-space-size=4096), split the build into stages.
4. Free disk: prune Docker (docker system prune -af), delete caches you don't restore, clean /tmp between steps.
5. Only then consider a bigger runner class — it's the most expensive fix and hides growth, it doesn't stop it.

## Prevent it

- Add a step that prints df -h and available memory at job start. When exhaustion happens again you'll have a baseline in the log instead of a mystery.

---

Classify a red build locally with the `patchrail` CLI:

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
