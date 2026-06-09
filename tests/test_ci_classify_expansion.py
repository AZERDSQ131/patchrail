from __future__ import annotations

import json
import subprocess
import sys
import unittest

from patchrail.ci.classify import classify_ci_log, redact_ci_log


class NodeTestFailureClassification(unittest.TestCase):
    def test_jest_run_classifies_as_node_test_failure(self) -> None:
        log = (
            "Run npm test\n"
            "> demo@1.0.0 test\n"
            "> jest --ci --coverage=false\n"
            " FAIL  src/utils/math.test.ts\n"
            "  math > adds numbers\n"
            "    Expected: 4\n"
            "    Received: 5\n"
            "      expect(received).toEqual(expected)\n"
            "Tests:       1 failed, 12 passed, 13 total\n"
            "Test Suites: 1 failed, 4 passed, 5 total\n"
        )
        result = classify_ci_log(log)
        self.assertEqual(result["failure_class"], "node_test_failure")
        self.assertEqual(result["requirements"]["external_model_required"], False)
        self.assertIn("jest", result["reproduction_command"])

    def test_vitest_run_classifies_as_node_test_failure(self) -> None:
        log = (
            "Run npx vitest run\n"
            " FAIL  test/parser.spec.ts > parser > handles empty input\n"
            "AssertionError: expected undefined to equal []\n"
            " ❯ test/parser.spec.ts:14:22\n"
            "Tests:  2 failed, 40 passed\n"
        )
        result = classify_ci_log(log)
        self.assertEqual(result["failure_class"], "node_test_failure")

    def test_pure_jest_log_wins_over_browser_test_failure(self) -> None:
        log = (
            "Run npx jest\n"
            " FAIL  src/checkout/cart.test.tsx\n"
            "  ● cart > totals items > sums prices\n"
            "    Expected: 30\n"
            "    Received: 25\n"
            "Tests:       2 failed, 18 passed, 20 total\n"
            "Test Suites: 1 failed, 6 passed, 7 total\n"
        )
        self.assertEqual(classify_ci_log(log)["failure_class"], "node_test_failure")

    def test_playwright_log_stays_browser_test_failure_not_node_test(self) -> None:
        log = (
            "Run npx playwright test\n"
            "Running 12 tests using 4 workers\n"
            "  1) [chromium] login.spec.ts:8:5 › login flow\n"
            "    Error: Timeout 30000ms exceeded.\n"
            "    locator('#submit')\n"
            "    browserType.launch: Executable doesn't exist\n"
        )
        self.assertEqual(classify_ci_log(log)["failure_class"], "browser_test_failure")


class NodeDependencyInstallClassification(unittest.TestCase):
    def test_npm_eresolve_classifies_as_node_dependency_install(self) -> None:
        log = (
            "Run npm ci\n"
            "npm error code ERESOLVE\n"
            "npm error ERESOLVE unable to resolve dependency tree\n"
            "npm error While resolving: demo@1.0.0\n"
            "npm error Could not resolve dependency:\n"
            "npm error Fix the upstream dependency conflict, or retry this command with --force\n"
        )
        result = classify_ci_log(log)
        self.assertEqual(result["failure_class"], "node_dependency_install")
        self.assertIn("lockfile", result["minimal_repair_strategy"])

    def test_registry_404_classifies_as_node_dependency_install(self) -> None:
        log = (
            "Run npm install\n"
            "npm error code E404\n"
            "npm error 404 Not Found - GET https://registry.npmjs.org/@acme%2fnope\n"
            "npm error 404  '@acme/nope@1.0.0' is not in this registry.\n"
        )
        self.assertEqual(classify_ci_log(log)["failure_class"], "node_dependency_install")

    def test_yarn_classic_unexpected_error_is_node_dependency_install(self) -> None:
        log = (
            "Run yarn install --frozen-lockfile\n"
            "yarn install v1.22.19\n"
            'error An unexpected error occurred: couldn\'t find package "left-pad@^2.0.0".\n'
            "info Visit https://yarnpkg.com/en/docs/cli/install for documentation.\n"
        )
        self.assertEqual(classify_ci_log(log)["failure_class"], "node_dependency_install")

    def test_npm_eresolve_wins_over_node_test_failure_signal(self) -> None:
        log = (
            "Run npm ci && npm test\n"
            "npm error code ERESOLVE\n"
            "npm error ERESOLVE unable to resolve dependency tree\n"
            "npm error Could not resolve dependency:\n"
            "npm error Conflicting peer dependency: react@18.2.0\n"
            "npm error Fix the upstream dependency conflict, or retry with --force\n"
            "(the jest test step never ran)\n"
        )
        self.assertEqual(classify_ci_log(log)["failure_class"], "node_dependency_install")


class RustLintClassification(unittest.TestCase):
    def test_clippy_run_classifies_as_rust_lint(self) -> None:
        log = (
            "Run cargo clippy --all-targets --all-features -- -D warnings\n"
            "warning: clippy::needless_return\n"
            "error[clippy::needless_return]: unneeded `return` statement\n"
            "  --> src/lib.rs:12:5\n"
            "help: remove `return`\n"
            "error: could not compile due to clippy warnings\n"
        )
        result = classify_ci_log(log)
        self.assertEqual(result["failure_class"], "rust_lint")
        self.assertIn("clippy", result["reproduction_command"])

    def test_clippy_log_wins_over_rust_test_failure(self) -> None:
        log = (
            "Run cargo clippy --workspace -- -D warnings\n"
            "warning: clippy::redundant_clone\n"
            "error[clippy::redundant_clone]: redundant clone\n"
            "  --> src/handler.rs:30:9\n"
            "error: could not compile due to clippy warnings\n"
        )
        self.assertEqual(classify_ci_log(log)["failure_class"], "rust_lint")


class GoLintClassification(unittest.TestCase):
    def test_golangci_lint_run_classifies_as_go_lint(self) -> None:
        log = (
            "Run golangci-lint run ./...\n"
            "internal/server/handler.go:42:6: func unusedHelper is unused (unused)\n"
            "internal/server/handler.go:51:2: ineffectual assignment to err (ineffassign)\n"
            "internal/server/handler.go:60:9: error return value not checked (errcheck)\n"
        )
        result = classify_ci_log(log)
        self.assertEqual(result["failure_class"], "go_lint")
        self.assertIn("golangci-lint", result["reproduction_command"])

    def test_golangci_lint_log_wins_over_go_test_failure(self) -> None:
        log = (
            "Run golangci-lint run ./...\n"
            "internal/api/router.go:18:2: ineffectual assignment to ctx (ineffassign)\n"
            "internal/api/router.go:25:6: func mountRoutes is unused (unused)\n"
            "internal/api/router.go:31:9: error return value not checked (errcheck)\n"
        )
        self.assertEqual(classify_ci_log(log)["failure_class"], "go_lint")

    def test_pytest_log_mentioning_ruff_stays_python_test_failure(self) -> None:
        log = (
            "Run python -m pytest -q\n"
            "============================= test session starts =============================\n"
            "(we also run ruff check in a separate lint job)\n"
            "FAILED tests/test_app.py::test_ok - AssertionError: 1 != 2\n"
            "=========================== 1 failed, 30 passed ===========================\n"
        )
        self.assertEqual(classify_ci_log(log)["failure_class"], "python_test_failure")


class TypescriptTypecheckClassification(unittest.TestCase):
    def test_tsc_run_classifies_as_typescript_typecheck(self) -> None:
        log = (
            "Run npm run typecheck\n"
            "> tsc --noEmit\n"
            "src/api.ts:14:7 - error TS2339: Property 'user' does not exist on type 'Session'.\n"
            "src/api.ts:22:3 - error TS2769: No overload matches this call.\n"
            "src/api.ts:30:5 - error TS2531: Object is possibly 'null'.\n"
            "src/api.ts:40:9 - error TS2345: Argument of type 'number' "
            "is not assignable to parameter of type 'string'.\n"
            "tsc exited with code 2\n"
        )
        result = classify_ci_log(log)
        self.assertEqual(result["failure_class"], "typescript_typecheck")
        self.assertIn("typecheck", result["minimal_repair_strategy"])

    def test_ts_node_compile_error_classifies_as_typescript_typecheck(self) -> None:
        log = (
            "Run npm start\n"
            "TSError: ⨯ Unable to compile TypeScript:\n"
            "src/index.ts:5:18 - error TS2304: Cannot find name 'process'.\n"
            "Property 'env' does not exist on type 'unknown'.\n"
            "Type checking failed\n"
        )
        self.assertEqual(classify_ci_log(log)["failure_class"], "typescript_typecheck")

    def test_tsc_log_wins_over_javascript_lint(self) -> None:
        log = (
            "Run npm run typecheck\n"
            "> tsc --noEmit\n"
            "src/store.ts:12:5 - error TS2322: Type 'string' is not assignable to type 'number'.\n"
            "src/store.ts:18:9 - error TS2339: Property 'id' does not exist on type 'State'.\n"
            "src/store.ts:24:3 - error TS2769: No overload matches this call.\n"
            "(a separate eslint job runs prettier and no-unused-vars checks)\n"
        )
        self.assertEqual(classify_ci_log(log)["failure_class"], "typescript_typecheck")

    def test_pure_mypy_log_does_not_fall_into_python_test_failure(self) -> None:
        log = (
            "Run mypy .\n"
            'src/app.py:14: error: Incompatible return value type (got "str", '
            'expected "int")  [return-value]\n'
            'src/app.py:20: error: Argument 1 to "f" has incompatible type "int"; '
            'expected "str"  [arg-type]\n'
            "Found 2 errors in 1 file (checked 30 source files)\n"
        )
        result = classify_ci_log(log)
        self.assertNotEqual(result["failure_class"], "python_test_failure")
        self.assertEqual(result["failure_class"], "python_type_check")


class RedactionExpansion(unittest.TestCase):
    def test_url_credentials_redacted_in_git_clone_with_token(self) -> None:
        token = "ghp_" + "abcdefghijklmnopqrstuvwxyz123456"
        log = (
            "fatal: unable to access "
            f"https://x-access-token:{token}@github.com/acme/repo.git/: "
            "The requested URL returned error: 403\n"
        )
        result = redact_ci_log(log)
        self.assertIn("https://<credentials>@github.com/acme/repo.git/", result["text"])
        self.assertNotIn("x-access-token:", result["text"])
        self.assertNotIn(token, result["text"])
        self.assertEqual(result["redactions"].get("url_credentials"), 1)

    def test_url_credentials_redacted_in_postgres_dsn(self) -> None:
        log = (
            "sqlalchemy.exc.OperationalError: could not connect to "
            "postgres://dbuser:s3cr3tPass@db.internal:5432/appdb\n"
        )
        result = redact_ci_log(log)
        self.assertIn("postgres://<credentials>@db.internal:5432/appdb", result["text"])
        self.assertNotIn("dbuser:s3cr3tPass", result["text"])
        self.assertEqual(result["redactions"].get("url_credentials"), 1)

    def test_sendgrid_api_key_redacted_and_counted(self) -> None:
        key = "SG.aBcDeFgHiJkLmNoPqRsT12.uVwXyZ0123456789AbCdEfGhIjKlMnOpQrStUvWx"
        log = f"Error sending mail: rejected {key} not authorized\n"
        result = redact_ci_log(log)
        self.assertIn("<sendgrid-api-key>", result["text"])
        self.assertNotIn(key, result["text"])
        self.assertEqual(result["redactions"].get("sendgrid_api_key"), 1)

    def test_telegram_bot_token_redacted_and_counted(self) -> None:
        token = "123456789:AAH9xZ_qWeRtYuIoPaSdFgHjKlZxCvBnMqp"
        log = f"requests.exceptions.HTTPError: bot {token} failed with 401\n"
        result = redact_ci_log(log)
        self.assertIn("<telegram-bot-token>", result["text"])
        self.assertNotIn(token, result["text"])
        self.assertEqual(result["redactions"].get("telegram_bot_token"), 1)


class SchemaContractExpansion(unittest.TestCase):
    def test_schema_command_lists_new_failure_classes(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "patchrail", "schema", "ci-result"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        schema = json.loads(proc.stdout)
        enum = schema["properties"]["failure_class"]["enum"]
        self.assertIn("node_test_failure", enum)
        self.assertIn("node_dependency_install", enum)
        self.assertIn("rust_lint", enum)
        self.assertIn("go_lint", enum)
        self.assertIn("typescript_typecheck", enum)
        self.assertNotIn("node_dependency_failure", enum)
        self.assertNotIn("lint_failure", enum)
        self.assertNotIn("typecheck_failure", enum)


if __name__ == "__main__":
    unittest.main()
