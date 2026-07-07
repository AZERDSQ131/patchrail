<!-- Canonical: https://getpatchrail.com/fix -->

# CI Failure Triage — fix index

A red build usually fails for one of a small number of reasons. Find the class that matches the error in your log, and follow the narrow fix for it. Each page lists the literal log signatures, what actually happened, and a step-by-step playbook.

Canonical, formatted versions live at **[getpatchrail.com/fix](https://getpatchrail.com/fix)**.

| Failure class | Top signature |
| --- | --- |
| [Runner resource exhaustion](runner-resource-exhaustion.md) | `Process completed with exit code 137` |
| [Transient network failures](network-transient-failure.md) | `getaddrinfo EAI_AGAIN` |
| [Job timeouts and cancellations](ci-job-timeout.md) | `has exceeded the maximum execution time of 360 minutes` |
| [Python dependency resolution](python-dependency-resolution.md) | `Could not find a version that satisfies the requirement` |
| [Coverage threshold failures](code-coverage-threshold.md) | `Required test coverage of 80% not reached` |
| [Python type checking](python-type-check.md) | `Found 12 errors in 4 files` |
| [Python lint and formatting](python-lint.md) | `F401 imported but unused` |
| [Python test failures](python-test-failure.md) | `FAILED tests/test_x.py::test_name` |
| [Node package installation](node-dependency-install.md) | `npm ci can only install packages when your package.json and package-lock.json` |
| [TypeScript type checking](typescript-typecheck.md) | `error TS2339: Property 'x' does not exist on type` |
| [JavaScript and TypeScript lint](javascript-lint.md) | `error  'x' is defined but never used  no-unused-vars` |
| [Broken workflow wiring](github-actions-workflow.md) | `Invalid workflow file` |
| [Artifact and cache failures](artifact-or-cache-failure.md) | `No files were found with the provided path` |
| [Publish and release conflicts](release-publish-failure.md) | `You cannot publish over the previously published versions` |
| [Checkout, clone, submodule, and LFS failures](git-checkout-failure.md) | `fatal: Authentication failed` |
| [Merge and rebase conflicts](git-merge-conflict.md) | `Automatic merge failed; fix conflicts and then commit the result` |
| [Missing secrets and insufficient permissions](secrets-or-permissions-failure.md) | `Error: Input required and not supplied` |
| [Security scan failures](security-scan-failure.md) | `found 3 high severity vulnerabilities` |
| [.NET build failures](dotnet-build-failure.md) | `error NU1605: Detected package downgrade` |
| [Java build failures](java-build-failure.md) | `Unsupported class file major version 65` |
| [Docker image build failures](docker-build-failure.md) | `failed to solve` |
| [C/C++ native build failures](cpp-build-failure.md) | `fatal error: foo.h: No such file or directory` |
| [Browser end-to-end test failures](browser-test-failure.md) | `Executable doesn't exist at /ms-playwright/chromium` |
| [Rust test failures](rust-test-failure.md) | `error[E0308]: mismatched types` |
| [Ruby Bundler failures](ruby-bundle-failure.md) | `Bundler could not find compatible versions for gem` |
| [PHP Composer failures](php-composer-failure.md) | `Your requirements could not be resolved to an installable set of packages` |
| [Go test failures](go-test-failure.md) | `--- FAIL: TestName` |
| [Node test runner failures](node-test-failure.md) | `Tests:       2 failed, 18 passed` |
| [Rust lint (clippy)](rust-lint.md) | `error: this `if` has identical blocks` |
| [Go lint (golangci-lint)](go-lint.md) | `main.go:12:6: Error return value is not checked (errcheck)` |
| [Terraform and IaC failures](terraform-iac-failure.md) | `Error acquiring the state lock` |

