<!-- Canonical: https://getpatchrail.com/fix/go-lint -->

# Go lint (golangci-lint) — (errcheck) / (govet) / (staticcheck)

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/go-lint](https://getpatchrail.com/fix/go-lint)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
main.go:12:6: Error return value is not checked (errcheck)
app.go:8:2: this value of err is never used (ineffassign)
util.go:30:1: exported function should have comment (revive)
(staticcheck)
(govet)
```

## What actually happened

golangci-lint aggregates many linters; each finding ends with the source linter in parentheses — file.go:12:6: ... (errcheck) — and that suffix is your triage key. The ones that are nearly always real bugs: (errcheck) — an ignored error return (the canonical Go landmine); (govet) — suspicious constructs like misformatted struct tags or copied locks; (staticcheck) correctness checks. The ones that are style: (gofmt), (revive), (gosimple). (ineffassign) and (unused) sit in between — often refactor residue, occasionally a sign that logic got disconnected.

## Fix it

1. Reproduce at CI's golangci-lint version — finding sets change a lot between releases; a version mismatch means you're fixing a different report.
2. Sort findings by linter. Fix errcheck/govet/staticcheck as bugs: handle the error, don't _ = it away unless ignoring is genuinely correct (then say why in a comment).
3. gofmt findings: just run gofmt -w / golangci-lint run --fix.
4. False positives: //nolint:lintername // reason at the line — the reason is mandatory in spirit; a bare nolint is a future "why is this here."
5. Rerun golangci-lint run ./... locally before pushing.

## Prevent it

- Pin the golangci-lint version in CI (and in the project Makefile so local matches), upgrade it deliberately.

---

**Get all 31 failure classes + the offline classifier.** The complete *CI Failure Triage Patterns* pack ($19) covers every class with downloadable step-by-step playbooks, and pairs with the `patchrail` CLI that classifies a red build locally: [patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=go-lint)

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
