<!-- Canonical: https://getpatchrail.com/fix/browser-test-failure -->

# Browser end-to-end test failures — Executable doesn't exist / Timeout exceeded

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/browser-test-failure](https://getpatchrail.com/fix/browser-test-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
Executable doesn't exist at /ms-playwright/chromium
browserType.launch: 
Timeout 30000ms exceeded
browser exited unexpectedly
CypressError
```

## What actually happened

E2E failures split into environment and test problems. Environment: "Executable doesn't exist" / "browserType.launch" errors mean the browser binary isn't installed in CI — for Playwright the classic miss is running npm ci but never npx playwright install --with-deps; "browser exited unexpectedly" is usually missing system libraries (headless Chrome needs a long list) or sandbox/SHM issues in containers. Test problems: "Timeout ...ms exceeded" on a locator(...) means the element never reached the expected state — either the app actually broke, the selector drifted from the DOM, or the test is racing the app (asserting before a network response settles).

## Fix it

1. Environment first: if the browser didn't launch, nothing else in the log matters. Add npx playwright install --with-deps (or the Cypress image) to CI and rerun.
2. For locator timeouts, get artifacts before theorizing: Playwright traces (--trace on), screenshots and videos on failure. The trace shows the DOM at timeout — the answer is usually visible.
3. Distinguish "element never appeared" (app or selector issue) from "element appeared then detached" (re-render race). The trace timeline tells you which.
4. Fix races with web-first assertions that auto-wait (await expect(locator).toBeVisible()), never waitForTimeout(3000) — fixed sleeps are why the suite is flaky and slow.
5. Selector drift: prefer role/test-id selectors (getByRole, data-testid) over CSS paths coupled to layout.

## Prevent it

- Run E2E against deterministic backends (seeded data, mocked third parties). Most "flaky E2E" is actually nondeterministic test data, not the browser.

---

**Get all 31 failure classes + the offline classifier.** The complete *CI Failure Triage Patterns* pack ($19) covers every class with downloadable step-by-step playbooks, and pairs with the `patchrail` CLI that classifies a red build locally: [patchrail.gumroad.com/l/ci-failure-triage](https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=github&utm_campaign=browser-test-failure)

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
