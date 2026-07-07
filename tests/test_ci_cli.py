from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import patchrail.cli as cli_module
from patchrail.ci.classify import RULES
from patchrail.cli import (
    _FIX_GUIDE_SLUGS,
    _ci_triage_action_url,
    _ci_triage_pack_url,
    _ci_triage_sample_url,
    _fix_guide_url,
    main,
)


class PatchRailCITests(unittest.TestCase):
    def test_ci_adoption_event_reviews_workflow_signal_without_counting_adoption(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "v1",
                        "action_repository": "patchrail/ci-triage-action",
                        "adoption_key": "ci-triage:action:ci-triage-action:python-lint",
                        "adoption_event_id": "ci-triage-run:buyer/repo:123:test:python-lint",
                        "failure_class": "python_lint",
                        "failure_slug": "python-lint",
                        "confidence": "0.88",
                        "redacted_categories": 2,
                        "artifact_name": "patchrail-ci-triage-python-lint",
                        "json_result": "ci-result.json",
                        "markdown_report": "ci-report.md",
                        "workflow_repository": "buyer/repo",
                        "workflow_run_id": "123",
                        "workflow_run_url": "https://github.com/buyer/repo/actions/runs/123",
                        "workflow_run_host": "github.com",
                        "workflow_name": "CI",
                        "workflow_job": "test",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["schema_version"], "patchrail.ci_triage_adoption_event_review.v1")
        self.assertEqual(payload["signal_kind"], "workflow_run")
        self.assertEqual(payload["workflow_repository"], "buyer/repo")
        self.assertEqual(payload["github_issue"], "patchrail/patchrail#69")
        self.assertTrue(payload["triage_artifacts_present"])
        self.assertTrue(payload["strict_evidence_ready_for_permission_request"])
        self.assertEqual(payload["missing_strict_evidence"], [])
        self.assertIn("explicit permission", payload["safe_next_step"])
        self.assertFalse(payload["counts_as_external_adoption"])
        self.assertIn("--require-workflow-context", payload["strict_verification_command"])
        self.assertIn("--require-triage-artifacts", payload["strict_verification_command"])
        self.assertIsNotNone(payload["permission_request_copy_brief"])
        copy_brief = payload["permission_request_copy_brief"]
        assert copy_brief is not None
        self.assertEqual(copy_brief["schema"], "copy_brief.external_permission_request.v1")
        self.assertEqual(copy_brief["prohibited_fields"], ["body", "draft", "email_body"])
        self.assertEqual(copy_brief["payload"]["type"], "external_permission_request")
        self.assertEqual(copy_brief["payload"]["lead"], "buyer/repo")
        self.assertFalse(copy_brief["payload"]["external_body_allowed"])
        self.assertFalse(copy_brief["payload"]["payment_route_allowed_now"])
        self.assertNotIn("body", copy_brief["payload"])
        self.assertNotIn("draft", copy_brief["payload"])
        self.assertNotIn("email_body", copy_brief["payload"])
        self.assertIn(
            "public_adoption_claim_without_maintainer_permission",
            payload["blocked_actions"],
        )

    def test_ci_adoption_event_writes_permission_copy_brief_without_external_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            brief_path = Path(tmpdir) / "requests" / "permission.json"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "v1",
                        "action_repository": "patchrail/ci-triage-action",
                        "adoption_key": "ci-triage:action:ci-triage-action:python-lint",
                        "adoption_event_id": "ci-triage-run:buyer/repo:123:test:python-lint",
                        "failure_class": "python_lint",
                        "failure_slug": "python-lint",
                        "confidence": "0.88",
                        "json_result": "ci-result.json",
                        "markdown_report": "ci-report.md",
                        "workflow_repository": "buyer/repo",
                        "workflow_run_id": "123",
                        "workflow_run_url": "https://github.com/buyer/repo/actions/runs/123",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--write-copy-brief",
                        str(brief_path),
                        "--format",
                        "json",
                    ]
                )
            copy_brief_payload = json.loads(brief_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["copy_brief_write"]["status"], "written")
        self.assertFalse(payload["copy_brief_write"]["prohibited_fields_present"])
        self.assertEqual(copy_brief_payload["type"], "external_permission_request")
        self.assertEqual(copy_brief_payload["channel"], "maintainer_permission")
        self.assertEqual(copy_brief_payload["lead"], "buyer/repo")
        self.assertIn(
            "https://github.com/buyer/repo/actions/runs/123", copy_brief_payload["key_facts"][2]
        )
        self.assertTrue(
            any(
                fact.startswith("Strict verification command: patchrail ci adoption-event ")
                for fact in copy_brief_payload["key_facts"]
            )
        )
        self.assertFalse(copy_brief_payload["external_body_allowed"])
        self.assertFalse(copy_brief_payload["payment_route_allowed_now"])
        self.assertNotIn("body", copy_brief_payload)
        self.assertNotIn("draft", copy_brief_payload)
        self.assertNotIn("email_body", copy_brief_payload)

    def test_ci_adoption_event_writes_permission_copy_brief_to_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            requests_dir = Path(tmpdir) / "requests"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "v1",
                        "action_repository": "patchrail/ci-triage-action",
                        "adoption_key": "ci-triage:action:ci-triage-action:python-lint",
                        "adoption_event_id": "ci-triage-run:buyer/repo:123:test:python-lint",
                        "failure_class": "python_lint",
                        "failure_slug": "python-lint",
                        "confidence": "0.88",
                        "json_result": "ci-result.json",
                        "markdown_report": "ci-report.md",
                        "workflow_repository": "buyer/repo",
                        "workflow_run_id": "123",
                        "workflow_run_url": "https://github.com/buyer/repo/actions/runs/123",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--write-copy-brief-dir",
                        str(requests_dir),
                        "--format",
                        "json",
                    ]
                )
            written_files = list(requests_dir.glob("*.json"))
            copy_brief_payload = json.loads(written_files[0].read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(written_files), 1)
            self.assertRegex(
                written_files[0].name,
                r"^\d{8}T\d{6}Z-ci-triage-adoption-permission-buyer-repo-run-123\.json$",
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["copy_brief_write"]["status"], "written")
            self.assertTrue(payload["copy_brief_write"]["auto_named"])
            self.assertEqual(payload["copy_brief_write"]["directory"], str(requests_dir))
            self.assertEqual(payload["copy_brief_write"]["path"], str(written_files[0]))
            self.assertEqual(copy_brief_payload["type"], "external_permission_request")
            self.assertNotIn("body", copy_brief_payload)
            self.assertNotIn("draft", copy_brief_payload)
            self.assertNotIn("email_body", copy_brief_payload)

    def test_ci_adoption_event_rejects_copy_brief_path_and_directory_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "v1",
                        "action_repository": "patchrail/ci-triage-action",
                        "adoption_key": "ci-triage:action:ci-triage-action:python-lint",
                        "adoption_event_id": "ci-triage-run:buyer/repo:123:test:python-lint",
                        "failure_class": "python_lint",
                        "failure_slug": "python-lint",
                        "json_result": "ci-result.json",
                        "markdown_report": "ci-report.md",
                        "workflow_repository": "buyer/repo",
                        "workflow_run_id": "123",
                        "workflow_run_url": "https://github.com/buyer/repo/actions/runs/123",
                    }
                ),
                encoding="utf-8",
            )

            stderr = StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--write-copy-brief",
                        str(Path(tmpdir) / "permission.json"),
                        "--write-copy-brief-dir",
                        str(Path(tmpdir) / "requests"),
                    ]
                )

        self.assertEqual(exit_code, 2)
        self.assertIn("not both", stderr.getvalue())

    def test_ci_adoption_event_require_workflow_context_accepts_real_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "v1",
                        "action_repository": "patchrail/ci-triage-action",
                        "adoption_key": "ci-triage:action:ci-triage-action:python-lint",
                        "adoption_event_id": "ci-triage-run:buyer/repo:123:test:python-lint",
                        "failure_class": "python_lint",
                        "failure_slug": "python-lint",
                        "workflow_repository": "buyer/repo",
                        "workflow_run_id": "123",
                        "workflow_run_url": "https://github.com/buyer/repo/actions/runs/123",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--require-workflow-context",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["signal_kind"], "workflow_run")
        self.assertEqual(
            payload["workflow_run_url"], "https://github.com/buyer/repo/actions/runs/123"
        )

    def test_ci_adoption_event_rejects_mismatched_workflow_run_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "v1",
                        "action_repository": "patchrail/ci-triage-action",
                        "adoption_key": "ci-triage:action:ci-triage-action:python-lint",
                        "adoption_event_id": "ci-triage-run:buyer/repo:123:test:python-lint",
                        "failure_class": "python_lint",
                        "failure_slug": "python-lint",
                        "workflow_repository": "buyer/repo",
                        "workflow_run_id": "123",
                        "workflow_run_url": "https://github.com/other/repo/actions/runs/999",
                    }
                ),
                encoding="utf-8",
            )

            stderr = StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--require-workflow-context",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("workflow_run_url must match", stderr.getvalue())

    def test_ci_adoption_event_rejects_insecure_workflow_run_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "v1",
                        "action_repository": "patchrail/ci-triage-action",
                        "adoption_key": "ci-triage:action:ci-triage-action:python-lint",
                        "adoption_event_id": "ci-triage-run:buyer/repo:123:test:python-lint",
                        "failure_class": "python_lint",
                        "failure_slug": "python-lint",
                        "workflow_repository": "buyer/repo",
                        "workflow_run_id": "123",
                        "workflow_run_url": "http://github.com/buyer/repo/actions/runs/123",
                    }
                ),
                encoding="utf-8",
            )

            stderr = StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--require-workflow-context",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("workflow_run_url must match", stderr.getvalue())

    def test_ci_adoption_event_rejects_malformed_workflow_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "v1",
                        "action_repository": "patchrail/ci-triage-action",
                        "adoption_key": "ci-triage:action:ci-triage-action:python-lint",
                        "adoption_event_id": "ci-triage-run:buyer/repo/extra:123:test:python-lint",
                        "failure_class": "python_lint",
                        "failure_slug": "python-lint",
                        "workflow_repository": "buyer/repo/extra",
                        "workflow_run_id": "123",
                        "workflow_run_url": "https://github.com/buyer/repo/extra/actions/runs/123",
                    }
                ),
                encoding="utf-8",
            )

            stderr = StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--require-workflow-context",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("workflow_repository must be an owner/repo pair", stderr.getvalue())

    def test_ci_adoption_event_rejects_non_numeric_workflow_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "v1",
                        "action_repository": "patchrail/ci-triage-action",
                        "adoption_key": "ci-triage:action:ci-triage-action:python-lint",
                        "adoption_event_id": "ci-triage-run:buyer/repo:not-a-run:test:python-lint",
                        "failure_class": "python_lint",
                        "failure_slug": "python-lint",
                        "workflow_repository": "buyer/repo",
                        "workflow_run_id": "not-a-run",
                        "workflow_run_url": "https://github.com/buyer/repo/actions/runs/not-a-run",
                    }
                ),
                encoding="utf-8",
            )

            stderr = StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--require-workflow-context",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("workflow_run_id must be numeric", stderr.getvalue())

    def test_ci_adoption_event_rejects_mismatched_workflow_run_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "v1",
                        "action_repository": "patchrail/ci-triage-action",
                        "adoption_key": "ci-triage:action:ci-triage-action:python-lint",
                        "adoption_event_id": "ci-triage-run:buyer/repo:123:test:python-lint",
                        "failure_class": "python_lint",
                        "failure_slug": "python-lint",
                        "workflow_repository": "buyer/repo",
                        "workflow_run_id": "123",
                        "workflow_run_url": (
                            "https://github.enterprise.test/buyer/repo/actions/runs/123"
                        ),
                        "workflow_run_host": "github.com",
                    }
                ),
                encoding="utf-8",
            )

            stderr = StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--require-workflow-context",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("workflow_run_host must match", stderr.getvalue())

    def test_ci_adoption_event_require_canonical_action_rejects_fork(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "v1",
                        "action_repository": "buyer/ci-triage-action-fork",
                        "adoption_key": "ci-triage:action:ci-triage-action:python-lint",
                        "adoption_event_id": "ci-triage-run:buyer/repo:123:test:python-lint",
                        "failure_class": "python_lint",
                        "failure_slug": "python-lint",
                        "workflow_repository": "buyer/repo",
                        "workflow_run_id": "123",
                        "workflow_run_url": "https://github.com/buyer/repo/actions/runs/123",
                    }
                ),
                encoding="utf-8",
            )

            stderr = StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--require-workflow-context",
                        "--require-canonical-action",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("--require-canonical-action", stderr.getvalue())

    def test_ci_adoption_event_require_published_action_ref_accepts_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "v1",
                        "action_repository": "patchrail/ci-triage-action",
                        "adoption_key": "ci-triage:action:ci-triage-action:python-lint",
                        "adoption_event_id": "ci-triage-run:buyer/repo:123:test:python-lint",
                        "failure_class": "python_lint",
                        "failure_slug": "python-lint",
                        "workflow_repository": "buyer/repo",
                        "workflow_run_id": "123",
                        "workflow_run_url": "https://github.com/buyer/repo/actions/runs/123",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--require-workflow-context",
                        "--require-canonical-action",
                        "--require-published-action-ref",
                        "--require-external-workflow-repository",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["action_ref"], "v1")
        self.assertTrue(payload["published_action_ref_match"])
        self.assertTrue(payload["public_github_run_match"])
        self.assertEqual(payload["workflow_repository_owner"], "buyer")
        self.assertTrue(payload["external_workflow_repository_match"])
        self.assertFalse(payload["strict_evidence_ready_for_permission_request"])
        self.assertEqual(payload["missing_strict_evidence"], ["triage_artifacts"])

    def test_ci_adoption_event_require_public_github_run_rejects_enterprise_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "v1",
                        "action_repository": "patchrail/ci-triage-action",
                        "adoption_key": "ci-triage:action:ci-triage-action:python-lint",
                        "adoption_event_id": "ci-triage-run:buyer/repo:123:test:python-lint",
                        "failure_class": "python_lint",
                        "failure_slug": "python-lint",
                        "workflow_repository": "buyer/repo",
                        "workflow_run_id": "123",
                        "workflow_run_url": (
                            "https://github.enterprise.test/buyer/repo/actions/runs/123"
                        ),
                    }
                ),
                encoding="utf-8",
            )

            stderr = StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--require-workflow-context",
                        "--require-canonical-action",
                        "--require-published-action-ref",
                        "--require-public-github-run",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("--require-public-github-run", stderr.getvalue())

    def test_ci_adoption_event_require_external_repository_rejects_patchrail_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "v1",
                        "action_repository": "patchrail/ci-triage-action",
                        "adoption_key": "ci-triage:action:ci-triage-action:python-lint",
                        "adoption_event_id": (
                            "ci-triage-run:patchrail/patchrail:123:test:python-lint"
                        ),
                        "failure_class": "python_lint",
                        "failure_slug": "python-lint",
                        "json_result": "ci-result.json",
                        "markdown_report": "ci-report.md",
                        "workflow_repository": "patchrail/patchrail",
                        "workflow_run_id": "123",
                        "workflow_run_url": (
                            "https://github.com/patchrail/patchrail/actions/runs/123"
                        ),
                    }
                ),
                encoding="utf-8",
            )

            stderr = StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--require-workflow-context",
                        "--require-canonical-action",
                        "--require-published-action-ref",
                        "--require-public-github-run",
                        "--require-external-workflow-repository",
                        "--require-triage-artifacts",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("--require-external-workflow-repository", stderr.getvalue())

    def test_ci_adoption_event_require_triage_artifacts_rejects_missing_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "v1",
                        "action_repository": "patchrail/ci-triage-action",
                        "adoption_key": "ci-triage:action:ci-triage-action:python-lint",
                        "adoption_event_id": "ci-triage-run:buyer/repo:123:test:python-lint",
                        "failure_class": "python_lint",
                        "failure_slug": "python-lint",
                        "workflow_repository": "buyer/repo",
                        "workflow_run_id": "123",
                        "workflow_run_url": "https://github.com/buyer/repo/actions/runs/123",
                    }
                ),
                encoding="utf-8",
            )

            stderr = StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--require-workflow-context",
                        "--require-canonical-action",
                        "--require-published-action-ref",
                        "--require-public-github-run",
                        "--require-triage-artifacts",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("--require-triage-artifacts", stderr.getvalue())

    def test_ci_adoption_event_require_published_action_ref_rejects_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "local",
                        "action_repository": "patchrail/ci-triage-action",
                        "adoption_key": "ci-triage:action:ci-triage-action:python-lint",
                        "adoption_event_id": "ci-triage-run:buyer/repo:123:test:python-lint",
                        "failure_class": "python_lint",
                        "failure_slug": "python-lint",
                        "workflow_repository": "buyer/repo",
                        "workflow_run_id": "123",
                        "workflow_run_url": "https://github.com/buyer/repo/actions/runs/123",
                    }
                ),
                encoding="utf-8",
            )

            stderr = StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--require-workflow-context",
                        "--require-canonical-action",
                        "--require-published-action-ref",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("--require-published-action-ref", stderr.getvalue())

    def test_ci_adoption_event_marks_local_signal_as_non_adoption(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "local",
                        "action_repository": "patchrail/ci-triage-action",
                        "adoption_key": "ci-triage:cli:index:pre-commit-hook-failure",
                        "adoption_event_id": "ci-triage:cli:index:pre-commit-hook-failure",
                        "failure_class": "pre_commit_hook_failure",
                        "failure_slug": "pre-commit-hook-failure",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--format",
                        "markdown",
                    ]
                )

        self.assertEqual(exit_code, 0)
        markdown = stdout.getvalue()
        self.assertIn("- Signal: `local_or_sample_signal`", markdown)
        self.assertIn("- Counts as external adoption: `False`", markdown)
        self.assertIn("- Strict evidence ready for permission request: `False`", markdown)
        self.assertIn("- `workflow_context`", markdown)
        self.assertIn("Use this as local action smoke evidence only", markdown)

    def test_ci_adoption_event_require_workflow_context_rejects_local_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "adoption-event.json"
            event_path.write_text(
                json.dumps(
                    {
                        "schema_version": "patchrail.ci_triage_adoption_event.v1",
                        "product": "ci-triage-action",
                        "action_ref": "local",
                        "action_repository": "patchrail/ci-triage-action",
                        "adoption_key": "ci-triage:cli:index:pre-commit-hook-failure",
                        "adoption_event_id": "ci-triage:cli:index:pre-commit-hook-failure",
                        "failure_class": "pre_commit_hook_failure",
                        "failure_slug": "pre-commit-hook-failure",
                    }
                ),
                encoding="utf-8",
            )

            stderr = StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "ci",
                        "adoption-event",
                        "--event",
                        str(event_path),
                        "--require-workflow-context",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("--require-workflow-context", stderr.getvalue())

    def test_distribution_sku1_gate_reports_traffic_gap_from_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            (posted / "x.json").write_text(
                json.dumps(
                    {
                        "channel": "x",
                        "status": "posted",
                        "url": "https://x.com/pablito3_3/status/1",
                        "item_id": "1",
                        "ts_posted": "2026-06-19T07:38:47Z",
                    }
                ),
                encoding="utf-8",
            )
            (posted / "show-hn.json").write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "blocked",
                        "reason": "browser route unavailable",
                        "copy_file": "products/gumroad/distribution/posts/show-hn.md",
                    }
                ),
                encoding="utf-8",
            )
            (posted / "devto.json").write_text(
                json.dumps(
                    {
                        "channel": "devto",
                        "status": "blocked",
                        "reason": "copywriter unavailable; no approved local copy file",
                        "ts_posted": "2026-06-24T09:34:00Z",
                    }
                ),
                encoding="utf-8",
            )
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "covered_channels": ["devto", "show-hn", "x"],
                        "social_post_blocked_total": 2,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "uncovered": [],
                        "blocked": [
                            {
                                "channel": "show-hn",
                                "reason": "Chrome route missing extension",
                                "receipt": str(posted / "show-hn.json"),
                                "path": "opportunity-desk/outbox/requests/show-hn.json",
                                "copy_file": "products/gumroad/distribution/posts/show-hn.md",
                                "ts_blocked": "2026-06-25T07:40:05Z",
                            },
                            {
                                "channel": "devto",
                                "reason": "copywriter unavailable; no approved local copy file",
                                "receipt": str(posted / "devto.json"),
                                "path": "opportunity-desk/outbox/requests/devto.json",
                                "ts_blocked": "2026-06-24T09:34:00Z",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--stalled-after-days",
                        "1",
                        "--paid-click-cpc-usd",
                        "0.50",
                        "--ad-cap-usd",
                        "75",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["schema_version"], "patchrail.distribution_gate.v1")
        self.assertEqual(payload["conversion_consumer"], "SKU #1 CI Triage $19")
        self.assertEqual(payload["conversion_kpi"], "visits_and_sales_before_2026-06-30")
        self.assertIn("utm_source=github_marketplace", payload["conversion_url"])
        self.assertEqual(payload["traffic_gap"], 275)
        self.assertEqual(
            payload["traffic_pressure"],
            {
                "traffic_gap": 275,
                "days_to_gate": 5,
                "required_daily_traffic": 55.0,
                "status": "traffic_gap_before_gate",
            },
        )
        self.assertEqual(
            payload["paid_traffic_plan"],
            {
                "ad_cap_usd": 75.0,
                "ad_spend_reported_usd": 0.0,
                "ad_spend_committed_usd": 0.0,
                "ad_spend_over_cap_usd": 0.0,
                "ad_remaining_usd": 75.0,
                "paid_click_cpc_usd": 0.5,
                "traffic_gap": 275,
                "budget_for_gap_usd": 137.5,
                "cap_click_capacity": 150,
                "cap_covers_gap": False,
                "remaining_organic_gap_after_cap": 125,
                "recommendation": "organic_distribution_required_before_or_alongside_ads",
                "preflight_required": True,
                "preflight_blocked_reason": "",
            },
        )

        self.assertEqual(
            payload["traffic_execution_plan"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "deadline": "2026-06-30",
                "paid_click_target": 50,
                "paid_budget_usd": 25.0,
                "ad_boost_max_usd": 25.0,
                "ad_boost_click_capacity": 50,
                "organic_click_target": 225,
                "daily_organic_click_target": 45.0,
                "recommended_channel": "devto",
                "measurement_event": "sku1_visits_and_sales_delta",
            },
        )
        self.assertEqual(
            payload["channel_conversion_plan"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "channel": "devto",
                "url": (
                    "https://patchrail.gumroad.com/l/ci-failure-triage"
                    "?utm_source=devto&utm_campaign=sku1-organic-distribution"
                ),
                "measurement_command": (
                    "jq '.traffic_delivered_total,.gumroad_sales_total,.gumroad_gross_usd' "
                    "~/.patchrail/run/patchrail_supervisor_last.json"
                ),
                "ready_to_publish": False,
                "next_action": "copywriter_required",
            },
        )
        self.assertEqual(
            payload["channel_measurement_urls"],
            [
                {
                    "channel": "devto",
                    "owner": "copywriter",
                    "source": "blocked",
                    "next_action": "copywriter_required",
                    "url": (
                        "https://patchrail.gumroad.com/l/ci-failure-triage"
                        "?utm_source=devto&utm_campaign=sku1-organic-distribution"
                    ),
                    "measurement_event": "sku1_visits_and_sales_delta",
                },
                {
                    "channel": "show-hn",
                    "owner": "pablo",
                    "source": "blocked",
                    "next_action": "browser_extension_setup_required",
                    "url": (
                        "https://patchrail.gumroad.com/l/ci-failure-triage"
                        "?utm_source=show-hn&utm_campaign=sku1-organic-distribution"
                    ),
                    "measurement_event": "sku1_visits_and_sales_delta",
                },
            ],
        )
        self.assertEqual(
            payload["measurement_packet"]["url_check_commands"][:2],
            [
                {
                    "source": "organic",
                    "channel": "devto",
                    "command": (
                        "curl -fsSL -o /dev/null -w '%{http_code} %{url_effective}\\n' "
                        "'https://patchrail.gumroad.com/l/ci-failure-triage?"
                        "utm_source=devto&utm_campaign=sku1-organic-distribution'"
                    ),
                    "success_criteria": "curl_exit_0",
                },
                {
                    "source": "organic",
                    "channel": "show-hn",
                    "command": (
                        "curl -fsSL -o /dev/null -w '%{http_code} %{url_effective}\\n' "
                        "'https://patchrail.gumroad.com/l/ci-failure-triage?"
                        "utm_source=show-hn&utm_campaign=sku1-organic-distribution'"
                    ),
                    "success_criteria": "curl_exit_0",
                },
            ],
        )
        self.assertEqual(
            payload["measurement_packet"]["next_check"],
            "measure_traffic_delta_again_before_next_distribution_action",
        )
        self.assertEqual(
            payload["measurement_packet"]["next_measurement_target"],
            {
                "traffic_delta_target": 55,
                "next_traffic_checkpoint": 80,
                "sales_delta_target": 1,
                "pivot_gate_condition": "traffic_delivered>=300 and sales_total==0",
            },
        )
        self.assertEqual(
            payload["measurement_packet"]["pivot_gate_snapshot"],
            {
                "armed": False,
                "traffic_target_met": False,
                "traffic_remaining_to_decision": 275,
                "sales_required_to_clear_gate": 1,
                "outcome": "traffic_sample_incomplete",
            },
        )
        self.assertEqual(
            payload["pivot_decision"],
            {
                "schema_version": "patchrail.sku1_pivot_decision.v1",
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "as_of": "2026-06-25",
                "gate_date": "2026-06-30",
                "status": "continue_distribution",
                "decision": "keep_driving_measured_traffic",
                "next_action": "ship_measurable_distribution_or_guarded_paid_boost",
                "reason": "traffic_sample_incomplete",
                "inputs": {
                    "traffic_delivered": 25,
                    "traffic_target": 300,
                    "traffic_gap": 275,
                    "traffic_target_met": False,
                    "sales_total": 0,
                    "gross_usd": 0.0,
                    "gate_armed": False,
                    "days_to_gate": 5,
                },
            },
        )
        self.assertEqual(
            payload["execution_checklist"],
            [
                {
                    "name": "paid_ads_preflight",
                    "required": True,
                    "owner": "worker",
                    "amount_usd": 25.0,
                    "platform": "sku1-traffic-boost",
                    "command": (
                        "python3 opportunity-desk/scripts/ad_spend_guard.py preflight "
                        "--amount 25.00 --platform sku1-traffic-boost "
                        "--campaign ci-triage-sku1-gate"
                    ),
                    "halt_flag": "~/.patchrail/run/AD_SPEND_HALT.flag",
                },
                {
                    "name": "organic_distribution",
                    "required": True,
                    "owner": "copywriter",
                    "channel": "devto",
                    "target_clicks": 225,
                    "daily_target_clicks": 45.0,
                    "next_action": "copywriter_required",
                },
                {
                    "name": "measure_gate",
                    "required": True,
                    "owner": "worker",
                    "event": "sku1_visits_and_sales_delta",
                    "command": (
                        "jq '.traffic_delivered_total,.gumroad_sales_total,.gumroad_gross_usd' "
                        "~/.patchrail/run/patchrail_supervisor_last.json"
                    ),
                },
            ],
        )
        self.assertEqual(
            payload["publish_post_commands"],
            {
                "channel": "devto",
                "health_command": "python3 opportunity-desk/scripts/publish_post.py health --json",
                "claim_command": (
                    "python3 opportunity-desk/scripts/publish_post.py claim "
                    "--channel devto --copy-file <copywriter-approved-copy-file>"
                ),
                "record_command": (
                    "python3 opportunity-desk/scripts/publish_post.py record "
                    "--channel devto --url <submission_url>"
                ),
                "block_command": (
                    "python3 opportunity-desk/scripts/publish_post.py block "
                    "--channel devto --reason <concrete_blocker>"
                ),
            },
        )
        self.assertEqual(
            payload["channel_execution_packet"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "required": True,
                "deadline": "2026-06-30",
                "channel": "devto",
                "owner": "copywriter",
                "source": "blocked",
                "next_action": "copywriter_required",
                "safe_next_step": (
                    "copywriter must create approved copy_file; "
                    "worker must not draft external prose"
                ),
                "url": (
                    "https://patchrail.gumroad.com/l/ci-failure-triage"
                    "?utm_source=devto&utm_campaign=sku1-organic-distribution"
                ),
                "ready_to_publish": False,
                "copywriter_required": True,
                "copy_file": "",
                "organic_click_target": 225,
                "daily_organic_click_target": 45.0,
                "measurement_event": "sku1_visits_and_sales_delta",
                "measurement_command": (
                    "jq '.traffic_delivered_total,.gumroad_sales_total,.gumroad_gross_usd' "
                    "~/.patchrail/run/patchrail_supervisor_last.json"
                ),
                "claim_command": (
                    "python3 opportunity-desk/scripts/publish_post.py claim "
                    "--channel devto --copy-file <copywriter-approved-copy-file>"
                ),
                "record_command": (
                    "python3 opportunity-desk/scripts/publish_post.py record "
                    "--channel devto --url <submission_url>"
                ),
                "block_command": (
                    "python3 opportunity-desk/scripts/publish_post.py block "
                    "--channel devto --reason <concrete_blocker>"
                ),
                "copy_brief_request": {
                    "write_path": (
                        "opportunity-desk/outbox/requests/<timestamp>-sku1-devto-social-post.json"
                    ),
                    "schema": "copy_brief.social_post.v1",
                    "prohibited_fields": ["body", "draft", "email_body"],
                    "payload": {
                        "type": "social_post",
                        "channel": "devto",
                        "lead": "SKU #1 CI Triage $19",
                        "goal": (
                            "Create approved PatchRail social copy for devto that drives "
                            "measured visits to SKU #1 before 2026-06-30."
                        ),
                        "key_facts": [
                            "Product: SKU #1 CI Triage $19.",
                            "KPI: visits_and_sales_before_2026-06-30.",
                            (
                                "Channel URL with UTM: "
                                "https://patchrail.gumroad.com/l/ci-failure-triage"
                                "?utm_source=devto&utm_campaign=sku1-organic-distribution."
                            ),
                            "Organic click target: 225.",
                            "Daily organic target: 45.0.",
                            "Source: blocked.",
                            "Reason: copywriter unavailable; no approved local copy file.",
                        ],
                        "tone": "Concise, practical, maintainer-safe, no hype.",
                        "constraints": [
                            (
                                "Copywriter authors final external prose; worker does not draft "
                                "publishable text."
                            ),
                            "Brand-only: PatchRail.",
                            (
                                "No internal model/tool names, no payout or sales guarantees, "
                                "no calls or Calendly."
                            ),
                            "Use the provided UTM URL exactly for measurement.",
                        ],
                        "urgency": "normal",
                        "thread_ref": (
                            "distribution sku1-gate channel=devto; "
                            "kpi=visits_and_sales_before_2026-06-30; "
                            "url=https://patchrail.gumroad.com/l/ci-failure-triage"
                            "?utm_source=devto&utm_campaign=sku1-organic-distribution"
                        ),
                    },
                },
            },
        )
        self.assertEqual(
            payload["copywriter_handoff"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "required": True,
                "pending_count": 1,
                "next_channel": "devto",
                "next_brief": "opportunity-desk/outbox/requests/devto.json",
                "pending": [
                    {
                        "channel": "devto",
                        "brief": "opportunity-desk/outbox/requests/devto.json",
                        "blocked_days": 1,
                        "reason": "copywriter unavailable; no approved local copy file",
                        "next_action": "copywriter_required",
                        "safe_next_step": (
                            "copywriter must create approved copy_file; "
                            "worker must not draft external prose"
                        ),
                        "claim_after_copy_command": (
                            "python3 opportunity-desk/scripts/publish_post.py claim "
                            "--channel devto --copy-file <copywriter-approved-copy-file>"
                        ),
                    }
                ],
            },
        )
        self.assertEqual(
            payload["browser_extension_handoff"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "required": True,
                "owner": "pablo",
                "pending_count": 1,
                "pending_channels": ["show-hn"],
                "claimable_after_setup_count": 1,
                "next_channel": "show-hn",
                "next_verify_command": (
                    "python3 opportunity-desk/scripts/publish_post.py blockers --owner pablo --json --exit-zero"
                ),
                "next_claim_after_setup_command": (
                    "python3 opportunity-desk/scripts/publish_post.py claim --channel show-hn "
                    "--copy-file products/gumroad/distribution/posts/show-hn.md"
                ),
                "next_verify_after_claim_command": (
                    "python3 opportunity-desk/scripts/publish_post.py blockers --owner pablo --json --exit-zero"
                ),
                "claim_after_setup_commands": [
                    (
                        "python3 opportunity-desk/scripts/publish_post.py claim --channel show-hn "
                        "--copy-file products/gumroad/distribution/posts/show-hn.md"
                    )
                ],
                "verify_after_claim_commands": [
                    "python3 opportunity-desk/scripts/publish_post.py blockers --owner pablo --json --exit-zero"
                ],
                "checklist": [
                    "Open chrome://extensions in the selected logged-in Chrome profile.",
                    "Enable or install the approved Chrome publishing extension for that profile.",
                    "Do not bypass login, 2FA, CAPTCHA, profile, or account controls.",
                    (
                        "After setup, run the claim-after-setup command for the channel if "
                        "copy_file exists, then rerun the verify-after-claim command."
                    ),
                ],
                "pending": [
                    {
                        "channel": "show-hn",
                        "owner": "pablo",
                        "blocked_days": 0,
                        "reason": "Chrome route missing extension",
                        "copy_file": "products/gumroad/distribution/posts/show-hn.md",
                        "safe_next_step": (
                            "enable/install the approved Chrome publishing extension in the selected "
                            "logged-in Chrome profile for show-hn; worker must not bypass "
                            "profile/login controls"
                        ),
                        "verify_command": (
                            "python3 opportunity-desk/scripts/publish_post.py blockers "
                            "--owner pablo --json --exit-zero"
                        ),
                        "claim_after_setup_command": (
                            "python3 opportunity-desk/scripts/publish_post.py claim "
                            "--channel show-hn --copy-file "
                            "products/gumroad/distribution/posts/show-hn.md"
                        ),
                        "verify_after_claim_command": (
                            "python3 opportunity-desk/scripts/publish_post.py blockers "
                            "--owner pablo --json --exit-zero"
                        ),
                    }
                ],
            },
        )
        self.assertEqual(payload["posted_channels"], ["x"])
        self.assertEqual(payload["blocked_channels"], ["devto", "show-hn"])
        self.assertEqual(payload["publish_health"]["blocked_total"], 2)
        self.assertEqual(payload["publish_health"]["blocked"][0]["channel"], "show-hn")
        self.assertEqual(payload["publish_health"]["uncovered_channels"], [])
        self.assertEqual(payload["blocker_owner_counts"], {"copywriter": 1, "pablo": 1})
        self.assertEqual(
            [
                (item["channel"], item["owner"], item["next_action"])
                for item in payload["blocker_plan"]
            ],
            [
                ("devto", "copywriter", "copywriter_required"),
                ("show-hn", "pablo", "browser_extension_setup_required"),
            ],
        )
        self.assertIn(
            "worker must not draft external prose", payload["blocker_plan"][0]["safe_next_step"]
        )
        self.assertIn("worker must not bypass", payload["blocker_plan"][1]["safe_next_step"])
        self.assertEqual(
            [
                (item["channel"], item["owner"], item["next_action"])
                for item in payload["blocker_queue"]
            ],
            [
                ("devto", "copywriter", "copywriter_required"),
                ("show-hn", "pablo", "browser_extension_setup_required"),
            ],
        )
        self.assertEqual(payload["blocker_queue"][0]["blocked_at"], "2026-06-24T09:34:00Z")
        self.assertEqual(payload["blocker_queue"][0]["blocked_days"], 1)
        self.assertEqual(payload["blocker_queue"][1]["blocked_days"], 0)
        self.assertEqual(payload["oldest_blocked_days"], 1)
        self.assertEqual(payload["oldest_blocker"]["channel"], "devto")
        self.assertEqual(
            payload["recommended_channel"],
            {
                "channel": "devto",
                "source": "blocked",
                "owner": "copywriter",
                "next_action": "copywriter_required",
                "safe_next_step": "copywriter must create approved copy_file; worker must not draft external prose",
                "reason": "copywriter unavailable; no approved local copy file",
                "blocked_at": "2026-06-24T09:34:00Z",
                "blocked_days": 1,
                "estimated_visits": 25,
            },
        )
        self.assertEqual(
            payload["traffic_priority_queue"],
            [
                {
                    "channel": "show-hn",
                    "owner": "pablo",
                    "next_action": "browser_extension_setup_required",
                    "estimated_visits": 120,
                    "safe_next_step": "enable/install the approved Chrome publishing extension in the selected logged-in Chrome profile for show-hn; worker must not bypass profile/login controls",
                    "source": "blocked",
                },
                {
                    "channel": "devto",
                    "owner": "copywriter",
                    "next_action": "copywriter_required",
                    "estimated_visits": 25,
                    "safe_next_step": "copywriter must create approved copy_file; worker must not draft external prose",
                    "source": "blocked",
                },
            ],
        )
        self.assertEqual(
            payload["owner_next_actions"],
            [
                {
                    "owner": "copywriter",
                    "channel": "devto",
                    "pending_channels": ["devto"],
                    "pending_count": 1,
                    "next_action": "copywriter_required",
                    "safe_next_step": "copywriter must create approved copy_file; worker must not draft external prose",
                    "source": "blocked",
                    "oldest_blocked_days": 1,
                    "estimated_visits": 25,
                },
                {
                    "owner": "pablo",
                    "channel": "show-hn",
                    "pending_channels": ["show-hn"],
                    "pending_count": 1,
                    "next_action": "browser_extension_setup_required",
                    "safe_next_step": "enable/install the approved Chrome publishing extension in the selected logged-in Chrome profile for show-hn; worker must not bypass profile/login controls",
                    "source": "blocked",
                    "oldest_blocked_days": 0,
                    "estimated_visits": 120,
                },
            ],
        )
        self.assertEqual(payload["next_action"], "unblock_distribution_channels")
        self.assertEqual(payload["channel_closeout_plan"]["required"], False)
        self.assertEqual(payload["channel_closeout_plan"]["all_channels_covered"], False)
        self.assertEqual(payload["channel_closeout_plan"]["next_action"], "copywriter_required")
        self.assertEqual(
            payload["channel_closeout_plan"]["safe_next_step"],
            "copywriter must create approved copy_file; worker must not draft external prose",
        )
        self.assertFalse(payload["requirements"]["network_required"])
        self.assertEqual(payload["stalled_after_days"], 1)
        self.assertEqual(payload["stalled_owner_counts"], {"copywriter": 1})
        self.assertEqual(
            [
                (item["channel"], item["owner"], item["blocked_days"])
                for item in payload["stalled_blockers"]
            ],
            [("devto", "copywriter", 1)],
        )
        self.assertEqual(
            payload["stalled_handoff"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "required": True,
                "pending_count": 1,
                "next_owner": "copywriter",
                "next_channel": "devto",
                "next_blocked_days": 1,
                "next_brief": "opportunity-desk/outbox/requests/devto.json",
                "next_unblock_command": (
                    "python3 opportunity-desk/scripts/publish_post.py claim "
                    "--channel devto --copy-file <copywriter-approved-copy-file>"
                ),
                "pending": [
                    {
                        "channel": "devto",
                        "owner": "copywriter",
                        "blocked_days": 1,
                        "brief": "opportunity-desk/outbox/requests/devto.json",
                        "reason": "copywriter unavailable; no approved local copy file",
                        "safe_next_step": (
                            "copywriter must create approved copy_file; "
                            "worker must not draft external prose"
                        ),
                        "unblock_command": (
                            "python3 opportunity-desk/scripts/publish_post.py claim "
                            "--channel devto --copy-file <copywriter-approved-copy-file>"
                        ),
                    }
                ],
            },
        )
        self.assertEqual(payload["stalled_handoff_owner"], "copywriter")
        self.assertEqual(
            payload["receipt_audit"],
            {
                "total_receipts": 3,
                "unique_channels": 3,
                "duplicate_channel_total": 0,
                "duplicate_channels": [],
                "measurement_risk": "none",
                "cleanup_plan": {
                    "required": False,
                    "items": [],
                    "safe_next_action": "",
                },
            },
        )
        self.assertEqual(
            payload["adoption_evidence_packet"]["schema_version"], "patchrail.adoption_evidence.v1"
        )
        self.assertEqual(
            payload["adoption_evidence_packet"]["github_issue"], "patchrail/patchrail#69"
        )
        self.assertEqual(
            payload["adoption_evidence_packet"]["evidence_status"], "distribution_signal_only"
        )
        self.assertFalse(payload["adoption_evidence_packet"]["qualifies_as_adoption"])
        self.assertEqual(
            payload["adoption_evidence_packet"]["metric_snapshot"],
            {
                "traffic_delivered": 25,
                "traffic_target": 300,
                "traffic_gap": 275,
                "traffic_target_met": False,
                "sales_total": 0,
                "gross_usd": 0.0,
                "posted_channel_total": 1,
            },
        )
        self.assertEqual(
            payload["adoption_evidence_packet"]["distribution_signal_breakdown"],
            {
                "receipt_status_counts": {
                    "blocked": 2,
                    "posted": 1,
                },
                "blocker_owner_counts": {
                    "copywriter": 1,
                    "pablo": 1,
                },
                "measurement_url_total": 2,
                "posted_channel_total": 1,
                "receipt_measurement_risk": "none",
                "clean_receipt_measurement": True,
            },
        )
        self.assertIn(
            "do not count distribution traffic as adoption",
            payload["adoption_evidence_packet"]["safe_next_step"],
        )

    def test_distribution_adoption_evidence_subcommand_emits_issue_69_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            (posted / "x.json").write_text(
                json.dumps(
                    {
                        "channel": "x",
                        "status": "posted",
                        "url": "https://x.com/pablito3_3/status/1",
                        "item_id": "1",
                        "ts_posted": "2026-06-19T07:38:47Z",
                    }
                ),
                encoding="utf-8",
            )
            (posted / "show-hn.json").write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "blocked",
                        "reason": "Chrome route missing extension",
                        "copy_file": "products/gumroad/distribution/posts/show-hn.md",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "adoption-evidence",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["schema_version"], "patchrail.adoption_evidence.v1")
        self.assertEqual(payload["github_issue"], "patchrail/patchrail#69")
        self.assertEqual(payload["evidence_status"], "distribution_signal_only")
        self.assertFalse(payload["qualifies_as_adoption"])
        self.assertEqual(payload["metric_snapshot"]["traffic_delivered"], 25)
        self.assertEqual(payload["metric_snapshot"]["posted_channel_total"], 1)
        self.assertEqual(payload["receipt_measurement_risk"], "none")
        self.assertEqual(
            payload["evidence_closeout"],
            {
                "can_update_issue_69_as_adoption": False,
                "can_update_issue_69_as_conversion_evidence": False,
                "can_update_issue_69_as_distribution_evidence": True,
                "adoption_blocker": "no_paid_sale",
                "required_next_evidence": "measured_traffic_delta_or_sale",
                "next_measurement_command": (
                    "jq '.traffic_delivered_total,.pivot_gate_armed,.pivot_gate_fires,"
                    ".gumroad_sales_total,.gumroad_gross_usd,.replies_detected,"
                    ".ad_spend_committed_usd,.ad_cap_usd' "
                    "~/.patchrail/run/patchrail_supervisor_last.json"
                ),
            },
        )
        self.assertEqual(
            payload["external_adoption_gate"],
            {
                "ready": False,
                "counts_as_external_adoption": False,
                "issue_69_close_ready": False,
                "blocker": "no_paid_sale",
                "conversion_signal_recordable": False,
                "required_evidence": [
                    "paid_sale_receipt",
                    "fulfilled_customer_outcome",
                    "explicit_public_permission",
                ],
                "blocked_public_claims": [
                    "external_adopter_count",
                    "public_customer_or_repository_name",
                    "issue_69_closure",
                ],
            },
        )
        self.assertEqual(
            payload["issue_69_close_readiness"],
            {
                "ready": False,
                "missing_evidence": ["paid_sale_receipt"],
                "missing_evidence_count": 1,
                "next_action": "drive_or_measure_sku1_conversion_until_paid_sale",
                "next_executable_step": {
                    "action": "browser_extension_setup_required",
                    "owner": "pablo",
                    "channel": "show-hn",
                    "required": True,
                    "command": "",
                    "blocked_reason": "",
                    "measurement_event": "sku1_visits_and_sales_delta",
                },
                "traffic_gap_to_pivot_sample": 275,
                "can_record_distribution_evidence": True,
            },
        )

    def test_distribution_adoption_evidence_marks_paid_conversion_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            (posted / "show-hn.json").write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "posted",
                        "url": "https://news.ycombinator.com/item?id=123",
                        "item_id": "123",
                        "ts_posted": "2026-07-01T14:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "adoption-evidence",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "74",
                        "--sales-total",
                        "1",
                        "--gross-usd",
                        "19",
                        "--as-of",
                        "2026-07-07",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["evidence_status"], "paid_conversion_signal")
        self.assertTrue(payload["qualifies_as_adoption"])
        self.assertEqual(payload["evidence_closeout"]["adoption_blocker"], "")
        self.assertEqual(
            payload["evidence_closeout"]["required_next_evidence"],
            "sale_receipt_and_fulfillment_snapshot",
        )
        self.assertFalse(payload["evidence_closeout"]["can_update_issue_69_as_adoption"])
        self.assertTrue(payload["evidence_closeout"]["can_update_issue_69_as_conversion_evidence"])
        self.assertEqual(
            payload["external_adoption_gate"]["blocker"],
            "missing_fulfillment_snapshot_and_public_permission",
        )
        self.assertFalse(payload["external_adoption_gate"]["ready"])
        self.assertFalse(payload["external_adoption_gate"]["counts_as_external_adoption"])
        self.assertFalse(payload["external_adoption_gate"]["issue_69_close_ready"])
        self.assertTrue(payload["external_adoption_gate"]["conversion_signal_recordable"])
        self.assertEqual(
            payload["issue_69_close_readiness"],
            {
                "ready": False,
                "missing_evidence": [
                    "fulfilled_customer_outcome",
                    "explicit_public_permission",
                ],
                "missing_evidence_count": 2,
                "next_action": "prepare_fulfillment_snapshot_and_request_public_permission",
                "next_executable_step": {
                    "action": "prepare_fulfillment_snapshot",
                    "owner": "worker",
                    "channel": "",
                    "required": True,
                    "command": "",
                    "blocked_reason": "",
                    "measurement_event": "sku1_paid_sale_fulfillment_evidence",
                },
                "traffic_gap_to_pivot_sample": 226,
                "can_record_distribution_evidence": True,
            },
        )
        self.assertIn(
            "explicit_public_permission",
            payload["external_adoption_gate"]["required_evidence"],
        )
        self.assertIn(
            "issue_69_closure",
            payload["external_adoption_gate"]["blocked_public_claims"],
        )
        self.assertIn("permission-safe evidence", payload["safe_next_step"])
        assertions = {item["name"]: item["met"] for item in payload["evidence_assertions"]}
        self.assertTrue(assertions["paid_sale"])
        self.assertTrue(assertions["gross_revenue_positive"])
        self.assertFalse(assertions["traffic_target"])

    def test_distribution_adoption_evidence_subcommand_has_text_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "adoption-evidence",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "300",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-07-01",
                        "--format",
                        "text",
                    ]
                )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("schema_version: patchrail.adoption_evidence.v1\n", output)
        self.assertIn("evidence_status: traffic_target_met_no_sales\n", output)
        self.assertIn("qualifies_as_adoption: False\n", output)
        self.assertIn("traffic: 300/300\n", output)
        self.assertIn("external_adoption_ready: False\n", output)
        self.assertIn("issue_69_close_ready: False\n", output)
        self.assertIn("external_adoption_blocker: no_paid_sale\n", output)
        self.assertIn("issue_69_missing_evidence: paid_sale_receipt\n", output)
        self.assertIn(
            "issue_69_next_action: drive_or_measure_sku1_conversion_until_paid_sale\n",
            output,
        )
        self.assertIn("issue_69_next_executable_action: measure_existing_distribution\n", output)
        self.assertIn("issue_69_next_executable_owner: worker\n", output)
        self.assertIn("adoption_blocker: no_paid_sale\n", output)
        self.assertIn("required_next_evidence: pivot_decision_snapshot\n", output)
        self.assertIn("next_measurement_command: jq '.traffic_delivered_total", output)
        self.assertIn("safe_next_step: Do not record this as adoption", output)

    def test_distribution_sku1_gate_measurement_format_reports_pivot_and_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            (posted / "show-hn.json").write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "blocked",
                        "reason": "Chrome route missing extension",
                        "copy_file": "products/gumroad/distribution/posts/show-hn.md",
                        "ts_blocked": "2026-07-01T07:11:52Z",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "5",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-07-01",
                        "--format",
                        "measurement",
                    ]
                )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("consumer: SKU #1 CI Triage $19\n", output)
        self.assertIn("traffic: 5/300\n", output)
        self.assertIn("traffic_gap: 295\n", output)
        self.assertIn(
            "next_check: measure_traffic_delta_again_before_next_distribution_action\n", output
        )
        self.assertIn("next_traffic_checkpoint: 300\n", output)
        self.assertIn("pivot_status: inconclusive_insufficient_traffic\n", output)
        self.assertIn("pivot_decision: do_not_pivot_on_underpowered_sample\n", output)
        self.assertIn("pivot_gate_armed: True\n", output)
        self.assertIn("pivot_gate_fires: False\n", output)
        self.assertIn("paid_boost_executable: False\n", output)
        self.assertIn("measurement_command: jq ", output)
        self.assertIn("measurement_url_total: ", output)
        self.assertIn(
            "measurement_url: organic/show-hn/pablo/browser_extension_setup_required "
            "https://patchrail.gumroad.com/l/ci-failure-triage"
            "?utm_source=show-hn&utm_campaign=sku1-organic-distribution",
            output,
        )

    def test_distribution_sku1_gate_runway_format_reports_traffic_pressure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            (posted / "show-hn.json").write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "blocked",
                        "reason": "Chrome route missing extension",
                        "copy_file": "products/gumroad/distribution/posts/show-hn.md",
                        "ts_blocked": "2026-07-01T07:11:52Z",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "5",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-07-01",
                        "--format",
                        "runway",
                    ]
                )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("consumer: SKU #1 CI Triage $19\n", output)
        self.assertIn("traffic: 5/300\n", output)
        self.assertIn("traffic_gap: 295\n", output)
        self.assertIn("traffic_status: traffic_gap_after_gate\n", output)
        self.assertIn("required_daily_traffic: 295.0\n", output)
        self.assertIn("organic_status: pending_channels_not_enough\n", output)
        self.assertIn(
            "organic_next_action: unblock_channels_then_add_new_distribution_or_guarded_paid_boost\n",
            output,
        )
        self.assertIn("pending_channel_estimated_visits: 120\n", output)
        self.assertIn("traffic_gap_after_pending_channels: 175\n", output)
        self.assertIn("paid_cap_click_capacity: 100\n", output)
        self.assertIn("traffic_gap_after_pending_and_paid_cap: 75\n", output)
        self.assertIn("paid_click_capacity: 100\n", output)
        self.assertIn("remaining_organic_gap_after_cap: 195\n", output)
        self.assertIn(
            "paid_recommendation: organic_distribution_required_before_or_alongside_ads\n",
            output,
        )
        self.assertIn("paid_boost_required: False\n", output)
        self.assertIn("paid_boost_executable: False\n", output)
        self.assertIn("paid_boost_blocked_reason: none\n", output)
        self.assertIn("pivot_status: inconclusive_insufficient_traffic\n", output)
        self.assertIn("pivot_decision: do_not_pivot_on_underpowered_sample\n", output)
        self.assertIn("pending_channels:\n", output)
        self.assertIn("- channel: show-hn\n", output)

    def test_distribution_sku1_gate_reports_duplicate_channel_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            (posted / "devto-first.json").write_text(
                json.dumps(
                    {
                        "channel": "devto",
                        "status": "posted",
                        "url": "https://dev.to/patchrail/first",
                        "ts_posted": "2026-06-24T09:34:00Z",
                    }
                ),
                encoding="utf-8",
            )
            (posted / "devto-second.json").write_text(
                json.dumps(
                    {
                        "channel": "devto",
                        "status": "blocked",
                        "reason": "Chrome route missing extension",
                        "ts_blocked": "2026-06-25T09:34:00Z",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "17",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-27",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["receipt_audit"]["total_receipts"], 2)
        self.assertEqual(payload["receipt_audit"]["unique_channels"], 1)
        self.assertEqual(payload["receipt_audit"]["duplicate_channel_total"], 1)
        self.assertEqual(payload["receipt_audit"]["measurement_risk"], "duplicate_channel_receipts")
        self.assertEqual(
            payload["receipt_audit"]["duplicate_channels"],
            [
                {
                    "channel": "devto",
                    "receipt_count": 2,
                    "statuses": ["blocked", "posted"],
                    "paths": [
                        str(posted / "devto-first.json"),
                        str(posted / "devto-second.json"),
                    ],
                    "urls": ["https://dev.to/patchrail/first"],
                    "measurement_risk": "duplicate_channel_receipts",
                }
            ],
        )
        self.assertEqual(
            payload["receipt_audit"]["cleanup_plan"],
            {
                "required": True,
                "items": [
                    {
                        "channel": "devto",
                        "keep_path": str(posted / "devto-first.json"),
                        "archive_paths": [str(posted / "devto-second.json")],
                        "reason": (
                            "keep posted receipt when present, else latest blocked/claimed receipt"
                        ),
                    }
                ],
                "safe_next_action": (
                    "archive duplicate receipt files after confirming no publication is in flight"
                ),
            },
        )

    def test_distribution_receipt_cleanup_accepts_json_and_text_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            (posted / "show-hn-claimed.json").write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "claimed",
                        "copy_file": "products/gumroad/distribution/posts/show-hn-approved.md",
                        "ts_claimed": "2026-06-29T07:19:07Z",
                    }
                ),
                encoding="utf-8",
            )
            (posted / "show-hn-blocked.json").write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "blocked",
                        "reason": "browser route unavailable",
                        "copy_file": "products/gumroad/distribution/posts/show-hn-approved.md",
                        "ts_blocked": "2026-06-29T07:20:16Z",
                    }
                ),
                encoding="utf-8",
            )

            json_stdout = StringIO()
            with redirect_stdout(json_stdout):
                json_exit_code = main(
                    [
                        "distribution",
                        "receipt-cleanup",
                        "--posted-dir",
                        str(posted),
                        "--format",
                        "json",
                    ]
                )

            text_stdout = StringIO()
            with redirect_stdout(text_stdout):
                text_exit_code = main(
                    [
                        "distribution",
                        "receipt-cleanup",
                        "--posted-dir",
                        str(posted),
                        "--format",
                        "text",
                    ]
                )

        self.assertEqual(json_exit_code, 0)
        payload = json.loads(json_stdout.getvalue())
        self.assertEqual(payload["schema_version"], "patchrail.distribution_receipt_cleanup.v1")
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["duplicate_channel_total"], 1)
        self.assertEqual(payload["action_total"], 1)
        self.assertEqual(payload["actions"][0]["channel"], "show-hn")
        self.assertEqual(text_exit_code, 0)
        self.assertIn("Status: ok", text_stdout.getvalue())
        self.assertIn("Mode: dry_run", text_stdout.getvalue())
        self.assertIn("Duplicate channels: 1", text_stdout.getvalue())
        self.assertIn("- show-hn:", text_stdout.getvalue())

    def test_distribution_sku1_gate_reports_pivot_decision_cases(self) -> None:
        cases = [
            {
                "traffic": "42",
                "sales": "1",
                "gross": "19.00",
                "as_of": "2026-06-29",
                "status": "validated_by_sale",
                "decision": "keep_offer",
                "next_action": "record_paid_sale_and_prepare_fulfillment_snapshot",
                "reason": "sales_total_positive",
                "gate_armed": False,
            },
            {
                "traffic": "300",
                "sales": "0",
                "gross": "0",
                "as_of": "2026-06-30",
                "status": "pivot_required_no_sales",
                "decision": "pivot_offer",
                "next_action": "director_pivot_review",
                "reason": "gate_date_reached_with_target_traffic_and_zero_sales",
                "gate_armed": True,
            },
            {
                "traffic": "9",
                "sales": "0",
                "gross": "0",
                "as_of": "2026-06-30",
                "status": "inconclusive_insufficient_traffic",
                "decision": "do_not_pivot_on_underpowered_sample",
                "next_action": "ship_or_measure_more_distribution_before_pivot",
                "reason": "gate_date_reached_without_traffic_target",
                "gate_armed": True,
            },
        ]

        for case in cases:
            with self.subTest(case=case["status"]):
                with tempfile.TemporaryDirectory() as tmpdir:
                    posted = Path(tmpdir) / "posted"
                    posted.mkdir()

                    stdout = StringIO()
                    with redirect_stdout(stdout):
                        exit_code = main(
                            [
                                "distribution",
                                "sku1-gate",
                                "--posted-dir",
                                str(posted),
                                "--traffic-delivered",
                                case["traffic"],
                                "--sales-total",
                                case["sales"],
                                "--gross-usd",
                                case["gross"],
                                "--as-of",
                                case["as_of"],
                                "--format",
                                "json",
                            ]
                        )

                self.assertEqual(exit_code, 0)
                decision = json.loads(stdout.getvalue())["pivot_decision"]
                self.assertEqual(decision["status"], case["status"])
                self.assertEqual(decision["decision"], case["decision"])
                self.assertEqual(decision["next_action"], case["next_action"])
                self.assertEqual(decision["reason"], case["reason"])
                self.assertEqual(decision["inputs"]["gate_armed"], case["gate_armed"])
                self.assertEqual(decision["inputs"]["traffic_delivered"], int(case["traffic"]))
                self.assertEqual(decision["inputs"]["sales_total"], int(case["sales"]))

    def test_distribution_sku1_gate_reports_organic_runway_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            for channel in ("x", "reddit-sideproject"):
                posted.joinpath(f"{channel}-posted.json").write_text(
                    json.dumps(
                        {
                            "channel": channel,
                            "status": "posted",
                            "url": f"https://example.com/{channel}",
                            "ts_posted": "2026-06-25T10:00:00+00:00",
                        }
                    ),
                    encoding="utf-8",
                )
            for channel in ("show-hn", "linkedin", "devto", "hashnode"):
                posted.joinpath(f"{channel}-blocked.json").write_text(
                    json.dumps(
                        {
                            "channel": channel,
                            "status": "blocked",
                            "reason": "approved Chrome publishing extension missing installed=false",
                            "ts_blocked": "2026-06-25T10:00:00+00:00",
                        }
                    ),
                    encoding="utf-8",
                )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "9",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-29",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        runway = payload["organic_runway"]
        self.assertEqual(runway["schema_version"], "patchrail.sku1_organic_runway.v1")
        self.assertEqual(runway["status"], "pending_channels_not_enough")
        self.assertEqual(runway["traffic_gap"], 291)
        self.assertEqual(runway["pending_channel_total"], 4)
        self.assertEqual(runway["published_channel_total"], 2)
        self.assertEqual(runway["pending_channel_estimated_visits"], 205)
        self.assertEqual(runway["published_channel_estimated_visits"], 40)
        self.assertEqual(runway["traffic_gap_after_pending_channels"], 86)
        self.assertEqual(runway["paid_cap_click_capacity"], 100)
        self.assertEqual(runway["traffic_gap_after_pending_and_paid_cap"], 0)
        self.assertEqual(
            runway["next_action"],
            "unblock_channels_then_add_new_distribution_or_guarded_paid_boost",
        )
        self.assertEqual(
            [item["channel"] for item in runway["pending_channels"]],
            ["devto", "hashnode", "linkedin", "show-hn"],
        )
        self.assertEqual(payload["next_action"], "unblock_distribution_channels")

    def test_distribution_sku1_gate_does_not_request_ad_proof_before_paid_boost_required(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            posted.joinpath("show-hn-blocked.json").write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "blocked",
                        "reason": "browser route unavailable",
                        "copy_file": "products/gumroad/distribution/posts/show-hn-approved.md",
                        "ts_blocked": "2026-06-29T07:20:16Z",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "5",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-30",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertEqual(payload["next_action"], "unblock_distribution_channels")
        self.assertEqual(payload["channel_closeout_plan"]["next_action"], "browser_route_required")
        self.assertFalse(packet["required"])
        self.assertFalse(packet["eligibility_required"])
        self.assertFalse(packet["eligibility_handoff"]["required"])
        self.assertEqual(packet["amount_usd"], 0.0)
        self.assertEqual(packet["preflight_command"], "")
        self.assertEqual(packet["commit_command_template"], "")
        self.assertEqual(
            packet["safe_next_step"], payload["channel_closeout_plan"]["safe_next_step"]
        )

    def test_distribution_receipt_cleanup_dry_run_reports_archives_without_moving(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            keep = posted / "devto-first.json"
            duplicate = posted / "devto-second.json"
            keep.write_text(
                json.dumps(
                    {
                        "channel": "devto",
                        "status": "posted",
                        "url": "https://dev.to/patchrail/first",
                        "ts_posted": "2026-06-24T09:34:00Z",
                    }
                ),
                encoding="utf-8",
            )
            duplicate.write_text(
                json.dumps(
                    {
                        "channel": "devto",
                        "status": "blocked",
                        "reason": "Chrome route missing extension",
                        "ts_blocked": "2026-06-25T09:34:00Z",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "receipt-cleanup",
                        "--posted-dir",
                        str(posted),
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["mode"], "dry_run")
            self.assertTrue(payload["required"])
            self.assertEqual(payload["duplicate_channel_total"], 1)
            self.assertEqual(payload["action_total"], 1)
            self.assertTrue(keep.exists())
            self.assertTrue(duplicate.exists())
            self.assertFalse((posted / ".archive" / duplicate.name).exists())

    def test_distribution_receipt_cleanup_apply_archives_duplicate_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            keep = posted / "devto-first.json"
            duplicate = posted / "devto-second.json"
            keep.write_text(
                json.dumps(
                    {
                        "channel": "devto",
                        "status": "posted",
                        "url": "https://dev.to/patchrail/first",
                        "ts_posted": "2026-06-24T09:34:00Z",
                    }
                ),
                encoding="utf-8",
            )
            duplicate.write_text(
                json.dumps(
                    {
                        "channel": "devto",
                        "status": "blocked",
                        "reason": "Chrome route missing extension",
                        "ts_blocked": "2026-06-25T09:34:00Z",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "receipt-cleanup",
                        "--posted-dir",
                        str(posted),
                        "--apply",
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            archived = posted / ".archive" / duplicate.name
            self.assertEqual(payload["mode"], "apply")
            self.assertEqual(payload["action_total"], 1)
            self.assertEqual(payload["errors"], [])
            self.assertTrue(keep.exists())
            self.assertFalse(duplicate.exists())
            self.assertTrue(archived.exists())
            self.assertEqual(payload["actions"][0]["keep_path"], str(keep))
            self.assertEqual(
                payload["actions"][0]["archived_paths"],
                [{"source": str(duplicate), "destination": str(archived)}],
            )

    def test_distribution_sku1_gate_gives_pablo_claim_command_for_stalled_extension_blocker(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            copy_file = "products/gumroad/distribution/posts/show-hn-approved.md"
            receipt = posted / "show-hn.json"
            receipt.write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "blocked",
                        "reason": "approved Chrome publishing extension missing in selected Chrome profile",
                        "copy_file": copy_file,
                        "ts_blocked": "2026-06-25T07:40:05Z",
                    }
                ),
                encoding="utf-8",
            )
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "covered_channels": ["show-hn"],
                        "social_post_blocked_total": 1,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "uncovered": [],
                        "blocked": [
                            {
                                "channel": "show-hn",
                                "reason": "approved Chrome publishing extension missing in selected Chrome profile",
                                "receipt": str(receipt),
                                "path": "opportunity-desk/outbox/sent/show-hn.json",
                                "copy_file": copy_file,
                                "ts_blocked": "2026-06-25T07:40:05Z",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-26",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["stalled_handoff_owner"], "pablo")
        self.assertEqual(payload["stalled_handoff"]["next_channel"], "show-hn")
        self.assertEqual(
            payload["stalled_handoff"]["next_unblock_command"],
            (
                "python3 opportunity-desk/scripts/publish_post.py claim "
                "--channel show-hn --copy-file "
                "products/gumroad/distribution/posts/show-hn-approved.md"
            ),
        )
        self.assertEqual(
            payload["stalled_handoff"]["pending"][0]["unblock_command"],
            payload["stalled_handoff"]["next_unblock_command"],
        )
        self.assertEqual(
            payload["pablo_handoff_packet"],
            {
                "required": True,
                "owner": "pablo",
                "type": "browser_extension_setup",
                "approval_required": False,
                "reason": "browser_extension_setup_required",
                "pending_count": 1,
                "pending_channels": ["show-hn"],
                "next_channel": "show-hn",
                "commands": {
                    "verify_before_claim": (
                        "python3 opportunity-desk/scripts/publish_post.py blockers "
                        "--owner pablo --json --exit-zero"
                    ),
                    "claim_after_setup": (
                        "python3 opportunity-desk/scripts/publish_post.py claim "
                        "--channel show-hn --copy-file "
                        "products/gumroad/distribution/posts/show-hn-approved.md"
                    ),
                    "verify_after_claim": (
                        "python3 opportunity-desk/scripts/publish_post.py blockers "
                        "--owner pablo --json --exit-zero"
                    ),
                },
                "checklist": payload["browser_extension_handoff"]["checklist"],
                "stop_conditions": ["login_required", "captcha_or_2fa_required"],
            },
        )

    def test_distribution_sku1_gate_recommends_uncovered_channel_when_no_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "covered_channels": ["x"],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 2,
                        "social_post_stale_claims_total": 0,
                        "uncovered": [{"channel": "linkedin"}, "devto"],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                    ]
                )

        self.assertEqual(exit_code, 0)
        text = stdout.getvalue()
        self.assertIn("Recommended channel: devto (claim_uncovered_distribution_channel)", text)
        self.assertIn(
            "Publish commands: health=python3 opportunity-desk/scripts/publish_post.py health --json; "
            "claim=python3 opportunity-desk/scripts/publish_post.py claim --channel devto "
            "--copy-file <copywriter-approved-copy-file>; "
            "record=python3 opportunity-desk/scripts/publish_post.py record --channel devto "
            "--url <submission_url>",
            text,
        )
        self.assertIn(
            "Traffic pressure: traffic_gap_before_gate, days_to_gate=5, "
            "required_daily_traffic=55.0",
            text,
        )
        self.assertIn(
            "Traffic execution: paid_clicks=33, paid_budget=$24.75, "
            "organic_clicks=242, daily_organic=48.4, channel=devto",
            text,
        )
        self.assertIn(
            "Channel conversion: devto "
            "url=https://patchrail.gumroad.com/l/ci-failure-triage"
            "?utm_source=devto&utm_campaign=sku1-organic-distribution ready=True",
            text,
        )
        self.assertIn(
            "Channel measurement URLs: "
            "devto=https://patchrail.gumroad.com/l/ci-failure-triage"
            "?utm_source=devto&utm_campaign=sku1-organic-distribution",
            text,
        )
        self.assertIn(
            "Execution checklist: paid_ads_preflight=worker, organic_distribution=worker, "
            "measure_gate=worker",
            text,
        )
        self.assertIn(
            "Owner next actions: worker=devto/claim_uncovered_distribution_channel (1 channel)",
            text,
        )
        self.assertIn("Copywriter handoff: none", text)
        self.assertIn("Stalled blockers: none", text)
        self.assertIn("Stalled handoff: none", text)
        self.assertIn("Next action: claim_uncovered_distribution_channel", text)

    def test_distribution_sku1_gate_reports_compact_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            (posted / "show-hn.json").write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "blocked",
                        "reason": "Chrome route missing extension",
                        "copy_file": "products/gumroad/distribution/posts/show-hn.md",
                        "ts_blocked": "2026-06-30T09:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "covered_channels": ["show-hn"],
                        "social_post_blocked_total": 1,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [
                            {
                                "channel": "show-hn",
                                "reason": "Chrome route missing extension",
                                "receipt": str(posted / "show-hn.json"),
                                "copy_file": "products/gumroad/distribution/posts/show-hn.md",
                                "ts_blocked": "2026-06-30T09:00:00Z",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "5",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-07-01",
                        "--ad-spend-committed-usd",
                        "12.5",
                        "--format",
                        "compact",
                    ]
                )

        self.assertEqual(exit_code, 0)
        compact = stdout.getvalue()
        self.assertEqual(
            compact,
            "\n".join(
                [
                    (
                        "owner_next_actions: "
                        "pablo=show-hn/browser_extension_setup_required (1; 120 visits)"
                    ),
                    (
                        "owner_action_queue: "
                        "pablo=show-hn/browser_extension_setup_required "
                        "(1; command=python3 opportunity-desk/scripts/publish_post.py "
                        "blockers --owner pablo --json --exit-zero)"
                    ),
                    ("traffic_priority: show-hn=120 visits/pablo/browser_extension_setup_required"),
                    "blocked_channels: show-hn",
                    "traffic_gap: 295",
                    "next_traffic_checkpoint: 300",
                    "traffic_delta_target: 295",
                    "sales_delta_target: 1",
                    (
                        "measurement_command: jq "
                        "'.traffic_delivered_total,.gumroad_sales_total,.gumroad_gross_usd' "
                        "~/.patchrail/run/patchrail_supervisor_last.json"
                    ),
                    "ad_spend_committed_usd: 12.50",
                    "ad_cap_usd: 75.00",
                    "pivot_gate_armed: True",
                    "pivot_gate_fires: False",
                    ("execution_handoff: pablo/show-hn/browser_extension_setup_required"),
                    (
                        "execution_command: python3 "
                        "opportunity-desk/scripts/publish_post.py blockers --owner pablo --json --exit-zero"
                    ),
                    "worker_actionable: False",
                    "worker_actionable_reason: pablo_handoff_required",
                    "turn_result_hint: waiting - pablo_handoff_required",
                    "next_action: unblock_distribution_channels",
                    "browser_extension_handoff: show-hn (1 pending)",
                    (
                        "browser_verify_command: python3 "
                        "opportunity-desk/scripts/publish_post.py blockers --owner pablo --json --exit-zero"
                    ),
                    (
                        "browser_claim_after_setup_command: python3 "
                        "opportunity-desk/scripts/publish_post.py claim --channel show-hn "
                        "--copy-file products/gumroad/distribution/posts/show-hn.md"
                    ),
                    (
                        "browser_verify_after_claim_command: python3 "
                        "opportunity-desk/scripts/publish_post.py blockers --owner pablo --json --exit-zero"
                    ),
                    "",
                ]
            ),
        )
        self.assertNotIn("Measurement packet:", compact)

    def test_distribution_sku1_gate_reports_blockers_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            copy_file = "products/gumroad/distribution/posts/show-hn.md"
            receipt = posted / "show-hn.json"
            receipt.write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "blocked",
                        "reason": "Chrome route missing extension",
                        "copy_file": copy_file,
                        "ts_blocked": "2026-06-30T09:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "covered_channels": ["show-hn"],
                        "social_post_blocked_total": 1,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [
                            {
                                "channel": "show-hn",
                                "reason": "Chrome route missing extension",
                                "receipt": str(receipt),
                                "copy_file": copy_file,
                                "ts_blocked": "2026-06-30T09:00:00Z",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "5",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-07-01",
                        "--format",
                        "blockers",
                    ]
                )

        self.assertEqual(exit_code, 0)
        blockers = stdout.getvalue()
        self.assertIn("blockers_total: 1", blockers)
        self.assertIn("owner_counts: pablo=1", blockers)
        self.assertIn("blocked_channels: show-hn", blockers)
        self.assertIn("execution_handoff: pablo/show-hn/browser_extension_setup_required", blockers)
        self.assertIn(
            "execution_command: python3 opportunity-desk/scripts/publish_post.py "
            "blockers --owner pablo --json --exit-zero",
            blockers,
        )
        self.assertIn("- channel: show-hn", blockers)
        self.assertIn("  owner: pablo", blockers)
        self.assertIn("  action: browser_extension_setup_required", blockers)
        self.assertIn(f"  receipt: {receipt}", blockers)
        self.assertIn(f"  copy_file: {copy_file}", blockers)
        self.assertIn("  reason: Chrome route missing extension", blockers)
        self.assertIn(
            "  safe_next_step: enable/install the approved Chrome publishing extension in the selected "
            "logged-in Chrome profile for show-hn; worker must not bypass profile/login controls",
            blockers,
        )
        self.assertNotIn("Measurement packet:", blockers)

    def test_distribution_sku1_gate_reports_handoff_for_blocked_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            copy_file = "products/gumroad/distribution/posts/show-hn.md"
            receipt = posted / "show-hn.json"
            receipt.write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "blocked",
                        "reason": "Chrome route missing extension",
                        "copy_file": copy_file,
                        "ts_blocked": "2026-06-30T09:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "covered_channels": ["show-hn"],
                        "social_post_blocked_total": 1,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [
                            {
                                "channel": "show-hn",
                                "reason": "Chrome route missing extension",
                                "receipt": str(receipt),
                                "copy_file": copy_file,
                                "ts_blocked": "2026-06-30T09:00:00Z",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "5",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-07-01",
                        "--format",
                        "handoff",
                    ]
                )

        self.assertEqual(exit_code, 0)
        handoff = stdout.getvalue()
        self.assertIn("consumer: SKU #1 CI Triage $19", handoff)
        self.assertIn("next_action: browser_extension_setup_required", handoff)
        self.assertIn("owner: pablo", handoff)
        self.assertIn("channel: show-hn", handoff)
        self.assertIn("traffic: 5/300", handoff)
        self.assertIn(
            "command: python3 opportunity-desk/scripts/publish_post.py blockers --owner pablo --json --exit-zero",
            handoff,
        )
        self.assertIn("owner_action_queue:", handoff)
        self.assertIn("  channel: show-hn", handoff)
        self.assertIn("  action: browser_extension_setup_required", handoff)
        self.assertIn("stalled_handoff: pablo/show-hn/1d (1 pending)", handoff)
        self.assertIn(
            "stalled_unblock_command: python3 "
            "opportunity-desk/scripts/publish_post.py claim --channel show-hn "
            "--copy-file products/gumroad/distribution/posts/show-hn.md",
            handoff,
        )
        self.assertIn("browser_extension_handoff: show-hn (1 pending)", handoff)
        self.assertIn(
            "browser_claim_after_setup_command: python3 "
            "opportunity-desk/scripts/publish_post.py claim --channel show-hn "
            "--copy-file products/gumroad/distribution/posts/show-hn.md",
            handoff,
        )
        self.assertIn(
            "browser_verify_after_claim_command: python3 "
            "opportunity-desk/scripts/publish_post.py blockers --owner pablo --json --exit-zero",
            handoff,
        )
        self.assertNotIn("Measurement packet:", handoff)

    def test_distribution_sku1_gate_handoff_reports_claimable_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "covered_channels": ["x"],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 1,
                        "social_post_stale_claims_total": 0,
                        "uncovered": [{"channel": "devto"}],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "handoff",
                    ]
                )

        self.assertEqual(exit_code, 0)
        handoff = stdout.getvalue()
        self.assertIn("next_action: claim_uncovered_distribution_channel", handoff)
        self.assertIn("owner: worker", handoff)
        self.assertIn("channel: devto", handoff)
        self.assertIn(
            "command: python3 opportunity-desk/scripts/publish_post.py claim "
            "--channel devto --copy-file <copywriter-approved-copy-file>",
            handoff,
        )
        self.assertIn("stop_conditions: login_required, captcha_or_2fa_required", handoff)
        self.assertIn("owner_action_queue:", handoff)
        self.assertIn("  channel: devto", handoff)
        self.assertNotIn("Measurement packet:", handoff)

    def test_distribution_sku1_gate_next_reports_single_blocked_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            copy_file = "products/gumroad/distribution/posts/show-hn.md"
            receipt = posted / "show-hn.json"
            receipt.write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "blocked",
                        "reason": "Chrome route missing extension",
                        "copy_file": copy_file,
                        "ts_blocked": "2026-06-30T09:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "5",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-07-01",
                        "--format",
                        "next",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            stdout.getvalue(),
            "\n".join(
                [
                    "next_action: browser_extension_setup_required",
                    "owner: pablo",
                    "channel: show-hn",
                    (
                        "conversion_url: https://patchrail.gumroad.com/l/ci-failure-triage?"
                        "utm_source=show-hn&utm_campaign=sku1-organic-distribution"
                    ),
                    (
                        "measurement_url: https://patchrail.gumroad.com/l/ci-failure-triage?"
                        "utm_source=show-hn&utm_campaign=sku1-organic-distribution"
                    ),
                    (
                        "command: python3 opportunity-desk/scripts/publish_post.py blockers "
                        "--owner pablo --json --exit-zero"
                    ),
                    (
                        "verify_command: python3 opportunity-desk/scripts/publish_post.py "
                        "blockers --owner pablo --json --exit-zero"
                    ),
                    "worker_actionable: False",
                    "worker_actionable_reason: pablo_handoff_required",
                    (
                        "safe_next_step: Enable/install the browser extension in the logged-in "
                        "profile, then claim the channel if copy is available."
                    ),
                    "stop_conditions: login_required, captcha_or_2fa_required",
                    "traffic_gap: 295",
                    "next_measurement: checkpoint=300, traffic_delta=295, sales_delta=1",
                    "browser_pending_count: 1",
                    "browser_pending_channels: show-hn",
                    "pablo_handoff_type: browser_extension_setup",
                    "pablo_handoff_required: True",
                    "pablo_handoff_next_channel: show-hn",
                    (
                        "browser_claim_after_setup_command: "
                        "python3 opportunity-desk/scripts/publish_post.py claim "
                        "--channel show-hn --copy-file "
                        "products/gumroad/distribution/posts/show-hn.md"
                    ),
                    (
                        "browser_verify_after_claim_command: "
                        "python3 opportunity-desk/scripts/publish_post.py blockers "
                        "--owner pablo --json --exit-zero"
                    ),
                    "",
                ]
            ),
        )

    def test_distribution_sku1_gate_next_prioritizes_highest_traffic_blocked_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            for channel in ("linkedin", "devto", "hashnode", "show-hn"):
                posted.joinpath(f"{channel}.json").write_text(
                    json.dumps(
                        {
                            "channel": channel,
                            "status": "blocked",
                            "reason": "Chrome route missing extension",
                            "copy_file": f"products/gumroad/distribution/posts/{channel}.md",
                            "ts_blocked": "2026-06-25T09:00:00Z",
                        }
                    ),
                    encoding="utf-8",
                )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "2",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-07-04",
                        "--format",
                        "next",
                    ]
                )

            json_stdout = StringIO()
            with redirect_stdout(json_stdout):
                json_exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "2",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-07-04",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        next_step = stdout.getvalue()
        self.assertIn("channel: show-hn\n", next_step)
        self.assertIn(
            "measurement_url: https://patchrail.gumroad.com/l/ci-failure-triage?"
            "utm_source=show-hn&utm_campaign=sku1-organic-distribution\n",
            next_step,
        )
        self.assertIn(
            "safe_next_step: Enable/install the browser extension in the logged-in profile, "
            "then claim the channel if copy is available.\n",
            next_step,
        )

        self.assertEqual(json_exit_code, 0)
        payload = json.loads(json_stdout.getvalue())
        self.assertEqual(payload["recommended_channel"]["channel"], "show-hn")
        self.assertEqual(payload["channel_conversion_plan"]["channel"], "show-hn")
        self.assertEqual(
            payload["channel_conversion_plan"]["url"],
            "https://patchrail.gumroad.com/l/ci-failure-triage"
            "?utm_source=show-hn&utm_campaign=sku1-organic-distribution",
        )

    def test_distribution_sku1_gate_receipt_summarizes_blocked_worker_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            copy_file = "products/gumroad/distribution/posts/show-hn.md"
            (posted / "show-hn.json").write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "blocked",
                        "reason": "Chrome route missing extension",
                        "copy_file": copy_file,
                        "ts_blocked": "2026-06-30T09:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "5",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-07-01",
                        "--ad-spend-committed-usd",
                        "12.5",
                        "--format",
                        "receipt",
                    ]
                )

        self.assertEqual(exit_code, 0)
        receipt = stdout.getvalue()
        self.assertIn("receipt_status: blocked_handoff", receipt)
        self.assertIn("consumer: SKU #1 CI Triage $19", receipt)
        self.assertIn("traffic: 5/300", receipt)
        self.assertIn("sales_total: 0", receipt)
        self.assertIn("gross_usd: 0.00", receipt)
        self.assertIn("ad_spend_committed_usd: 12.50", receipt)
        self.assertIn("next_action: browser_extension_setup_required", receipt)
        self.assertIn("owner: pablo", receipt)
        self.assertIn("channel: show-hn", receipt)
        self.assertIn("worker_actionable: False", receipt)
        self.assertIn("worker_actionable_reason: pablo_handoff_required", receipt)
        self.assertIn("blocked_channels: show-hn", receipt)
        self.assertIn("blocker_owners: pablo=1", receipt)
        self.assertIn(
            "owner_action_queue: pablo=show-hn/browser_extension_setup_required (1)", receipt
        )
        self.assertIn(
            "command: python3 opportunity-desk/scripts/publish_post.py blockers "
            "--owner pablo --json --exit-zero",
            receipt,
        )
        self.assertIn(
            "safe_next_step: Enable/install the browser extension in the logged-in profile",
            receipt,
        )
        self.assertNotIn("Measurement packet:", receipt)

    def test_distribution_sku1_gate_next_reports_claimable_channel_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "covered_channels": ["x"],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 1,
                        "social_post_stale_claims_total": 0,
                        "uncovered": [{"channel": "devto"}],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "next",
                    ]
                )

        self.assertEqual(exit_code, 0)
        next_step = stdout.getvalue()
        self.assertIn("next_action: claim_uncovered_distribution_channel", next_step)
        self.assertIn("owner: worker", next_step)
        self.assertIn("channel: devto", next_step)
        self.assertIn(
            "conversion_url: https://patchrail.gumroad.com/l/ci-failure-triage?"
            "utm_source=devto&utm_campaign=sku1-organic-distribution",
            next_step,
        )
        self.assertIn(
            "measurement_url: https://patchrail.gumroad.com/l/ci-failure-triage?"
            "utm_source=devto&utm_campaign=sku1-organic-distribution",
            next_step,
        )
        self.assertIn(
            "command: python3 opportunity-desk/scripts/publish_post.py claim --channel devto "
            "--copy-file <copywriter-approved-copy-file>",
            next_step,
        )
        self.assertIn("worker_actionable: True", next_step)
        self.assertIn("worker_actionable_reason: worker_command_ready", next_step)
        self.assertIn("traffic_gap: 275", next_step)
        self.assertNotIn("owner_action_queue:", next_step)
        self.assertNotIn("Measurement packet:", next_step)

    def test_distribution_sku1_gate_require_worker_actionable_blocks_pablo_handoff(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            receipt = posted / "show-hn.json"
            copy_file = "products/gumroad/distribution/posts/show-hn-approved.md"
            receipt.write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "blocked",
                        "reason": "Chrome route missing extension",
                        "copy_file": copy_file,
                        "ts_blocked": "2026-06-30T09:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "5",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-07-01",
                        "--format",
                        "next",
                        "--require-worker-actionable",
                    ]
                )

        self.assertEqual(exit_code, 2)
        next_step = stdout.getvalue()
        self.assertIn("worker_actionable: False", next_step)
        self.assertIn("worker_actionable_reason: pablo_handoff_required", next_step)
        self.assertIn("browser_pending_count: 1", next_step)
        self.assertIn("browser_pending_channels: show-hn", next_step)
        self.assertIn("pablo_handoff_type: browser_extension_setup", next_step)
        self.assertIn("pablo_handoff_required: True", next_step)
        self.assertIn("pablo_handoff_next_channel: show-hn", next_step)
        self.assertIn(
            "browser_claim_after_setup_command: "
            "python3 opportunity-desk/scripts/publish_post.py claim --channel show-hn "
            f"--copy-file {copy_file}",
            next_step,
        )
        self.assertIn(
            "browser_verify_after_claim_command: "
            "python3 opportunity-desk/scripts/publish_post.py blockers "
            "--owner pablo --json --exit-zero",
            next_step,
        )

    def test_distribution_sku1_gate_default_workspace_commands_work_from_product_cwd(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            product_cwd = root / "product/patchrail"
            posted = root / "products/gumroad/distribution/posted"
            script = root / "opportunity-desk/scripts/publish_post.py"
            copy_file = root / "products/gumroad/distribution/posts/show-hn-approved.md"
            product_cwd.mkdir(parents=True)
            posted.mkdir(parents=True)
            script.parent.mkdir(parents=True)
            script.write_text("# placeholder\n", encoding="utf-8")
            copy_file.parent.mkdir(parents=True)
            copy_file.write_text("approved copy\n", encoding="utf-8")
            (posted / "show-hn.json").write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "blocked",
                        "reason": "Chrome route missing extension",
                        "copy_file": "products/gumroad/distribution/posts/show-hn-approved.md",
                        "ts_blocked": "2026-06-30T09:00:00Z",
                    }
                ),
                encoding="utf-8",
            )

            old_cwd = Path.cwd()
            stdout = StringIO()
            try:
                os.chdir(product_cwd)
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "distribution",
                            "sku1-gate",
                            "--traffic-delivered",
                            "5",
                            "--sales-total",
                            "0",
                            "--gross-usd",
                            "0",
                            "--as-of",
                            "2026-07-01",
                            "--format",
                            "next",
                            "--require-worker-actionable",
                        ]
                    )
            finally:
                os.chdir(old_cwd)

        self.assertEqual(exit_code, 2)
        next_step = stdout.getvalue()
        self.assertIn(
            "command: python3 ../../opportunity-desk/scripts/publish_post.py blockers "
            "--owner pablo --json --exit-zero",
            next_step,
        )
        self.assertIn(
            "browser_claim_after_setup_command: "
            "python3 ../../opportunity-desk/scripts/publish_post.py claim --channel show-hn "
            "--copy-file ../../products/gumroad/distribution/posts/show-hn-approved.md",
            next_step,
        )

    def test_distribution_sku1_gate_require_worker_actionable_passes_worker_handoff(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "covered_channels": ["x"],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 1,
                        "social_post_stale_claims_total": 0,
                        "uncovered": [{"channel": "devto"}],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "next",
                        "--require-worker-actionable",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("worker_actionable: True", stdout.getvalue())
        self.assertIn("worker_actionable_reason: worker_command_ready", stdout.getvalue())

    def test_distribution_sku1_gate_compact_reports_next_channel_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "covered_channels": ["x"],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 2,
                        "social_post_stale_claims_total": 0,
                        "uncovered": [{"channel": "linkedin"}, "devto"],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "compact",
                    ]
                )

        self.assertEqual(exit_code, 0)
        compact = stdout.getvalue()
        self.assertIn(
            (
                "owner_next_actions: "
                "worker=devto/claim_uncovered_distribution_channel (1; 25 visits)"
            ),
            compact,
        )
        self.assertIn(
            "traffic_priority: devto=25 visits/worker/claim_uncovered_distribution_channel",
            compact,
        )
        self.assertIn("next_action: claim_uncovered_distribution_channel", compact)
        self.assertIn("next_traffic_checkpoint: 80", compact)
        self.assertIn("traffic_delta_target: 55", compact)
        self.assertIn("sales_delta_target: 1", compact)
        self.assertIn(
            "measurement_command: jq "
            "'.traffic_delivered_total,.gumroad_sales_total,.gumroad_gross_usd' "
            "~/.patchrail/run/patchrail_supervisor_last.json",
            compact,
        )
        self.assertIn("channel: devto", compact)
        self.assertIn(
            "url: https://patchrail.gumroad.com/l/ci-failure-triage"
            "?utm_source=devto&utm_campaign=sku1-organic-distribution",
            compact,
        )
        self.assertIn("ready_to_publish: True", compact)
        self.assertIn("copywriter_required: False", compact)
        self.assertIn(
            "claim_command: python3 opportunity-desk/scripts/publish_post.py claim "
            "--channel devto --copy-file <copywriter-approved-copy-file>",
            compact,
        )
        self.assertIn(
            "record_command: python3 opportunity-desk/scripts/publish_post.py record "
            "--channel devto --url <submission_url>",
            compact,
        )
        self.assertIn(
            "block_command: python3 opportunity-desk/scripts/publish_post.py block "
            "--channel devto --reason <concrete_blocker>",
            compact,
        )
        self.assertNotIn("Measurement packet:", compact)

    def test_distribution_sku1_gate_subtracts_committed_ad_spend_from_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": ["reddit-sideproject", "x"],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 1,
                        "social_post_stale_claims_total": 0,
                        "uncovered": [{"channel": "devto"}],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--paid-click-cpc-usd",
                        "0.75",
                        "--ad-cap-usd",
                        "75",
                        "--ad-spend-committed-usd",
                        "50",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["paid_traffic_plan"]["ad_cap_usd"], 75.0)
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_reported_usd"], 50.0)
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_committed_usd"], 50.0)
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_over_cap_usd"], 0.0)
        self.assertEqual(payload["paid_traffic_plan"]["ad_remaining_usd"], 25.0)
        self.assertEqual(payload["paid_traffic_plan"]["cap_click_capacity"], 33)
        self.assertEqual(payload["traffic_execution_plan"]["paid_click_target"], 33)
        self.assertEqual(payload["traffic_execution_plan"]["paid_budget_usd"], 24.75)
        self.assertIn("--amount 24.75", payload["execution_checklist"][0]["command"])

    def test_distribution_sku1_gate_reads_committed_ad_spend_from_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": ["reddit-sideproject", "x"],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 1,
                        "social_post_stale_claims_total": 0,
                        "uncovered": [{"channel": "devto"}],
                    }
                ),
                encoding="utf-8",
            )
            ledger = Path(tmpdir) / "ledger.jsonl"
            ledger.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "status": "committed",
                                "kind": "charge",
                                "amount_usd": "12.34",
                            }
                        ),
                        json.dumps(
                            {
                                "status": "refused",
                                "kind": "charge",
                                "amount_usd": "99.00",
                            }
                        ),
                        json.dumps(
                            {
                                "status": "committed",
                                "kind": "preauth",
                                "amount_usd": "5.00",
                            }
                        ),
                        json.dumps(
                            {
                                "status": "committed",
                                "kind": "refund",
                                "amount_usd": "2.00",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--paid-click-cpc-usd",
                        "0.75",
                        "--ad-cap-usd",
                        "75",
                        "--ad-spend-committed-usd",
                        "50",
                        "--ad-spend-ledger",
                        str(ledger),
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload["ad_spend_source"],
            {
                "source": "ledger",
                "ledger_path": str(ledger),
                "committed_usd": 15.34,
                "line_count": 4,
                "committed_lines": 3,
                "ignored_lines": 1,
            },
        )
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_committed_usd"], 15.34)
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_reported_usd"], 15.34)
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_over_cap_usd"], 0.0)
        self.assertEqual(payload["paid_traffic_plan"]["ad_remaining_usd"], 59.66)
        self.assertEqual(payload["traffic_execution_plan"]["paid_click_target"], 33)
        self.assertEqual(payload["traffic_execution_plan"]["paid_budget_usd"], 24.75)
        self.assertIn("--amount 24.75", payload["execution_checklist"][0]["command"])

    def test_distribution_sku1_gate_reads_committed_ad_spend_from_guard_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            ledger = Path(tmpdir) / "patchrail_ad_spend.json"
            ledger.write_text(
                json.dumps(
                    {
                        "ad_cap_usd": 75.0,
                        "ad_charges": 0,
                        "ad_spend_committed_usd": 12.5,
                        "ad_spend_remaining_usd": 62.5,
                        "by_platform": {},
                        "halted": False,
                        "source": "ad_spend_guard",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--paid-click-cpc-usd",
                        "0.75",
                        "--ad-cap-usd",
                        "75",
                        "--ad-spend-ledger",
                        str(ledger),
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload["ad_spend_source"],
            {
                "source": "ad_spend_guard",
                "ledger_path": str(ledger),
                "committed_usd": 12.5,
                "line_count": 1,
                "committed_lines": 1,
                "ignored_lines": 0,
                "snapshot_format": "json_object",
            },
        )
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_committed_usd"], 12.5)
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_reported_usd"], 12.5)
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_over_cap_usd"], 0.0)
        self.assertEqual(payload["paid_traffic_plan"]["ad_remaining_usd"], 62.5)
        self.assertEqual(payload["measurement_packet"]["ad_remaining_usd"], 62.5)

    def test_distribution_sku1_gate_reads_metrics_from_supervisor_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            supervisor = Path(tmpdir) / "patchrail_supervisor_last.json"
            supervisor.write_text(
                json.dumps(
                    {
                        "traffic_delivered_total": 9,
                        "gumroad_sales_total": 0,
                        "gumroad_gross_usd": 0.0,
                        "ad_spend_committed_usd": 12.5,
                        "ad_cap_usd": 75.0,
                        "pivot_gate_armed": False,
                        "pivot_gate_fires": False,
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--supervisor-snapshot",
                        str(supervisor),
                        "--as-of",
                        "2026-06-28",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["traffic_delivered"], 9)
        self.assertEqual(payload["traffic_delivered_total"], 9)
        self.assertEqual(payload["sales_total"], 0)
        self.assertEqual(payload["gross_usd"], 0.0)
        self.assertEqual(
            payload["metric_source"],
            {
                "traffic_delivered": "supervisor_snapshot",
                "sales_total": "supervisor_snapshot",
                "gross_usd": "supervisor_snapshot",
                "ad_spend_committed_usd": "supervisor_snapshot",
            },
        )
        self.assertEqual(
            payload["ad_spend_source"],
            {
                "source": "supervisor_snapshot",
                "ledger_path": str(supervisor),
                "committed_usd": 12.5,
                "line_count": 1,
                "committed_lines": 1,
                "ignored_lines": 0,
                "snapshot_format": "patchrail_supervisor_last",
            },
        )
        self.assertEqual(payload["supervisor_snapshot"]["metrics"]["traffic_delivered_total"], 9)
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_committed_usd"], 12.5)
        self.assertIn(str(supervisor), payload["measurement_packet"]["next_measurement_command"])
        self.assertIn(str(supervisor), payload["channel_closeout_plan"]["measurement_command"])
        self.assertNotIn(
            "~/.patchrail/run/patchrail_supervisor_last.json",
            payload["measurement_packet"]["next_measurement_command"],
        )

    def test_distribution_sku1_gate_uses_default_supervisor_snapshot_when_metrics_omitted(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            supervisor = Path(tmpdir) / "patchrail_supervisor_last.json"
            supervisor.write_text(
                json.dumps(
                    {
                        "traffic_delivered_total": 5,
                        "gumroad_sales_total": 0,
                        "gumroad_gross_usd": 0.0,
                        "ad_spend_committed_usd": 0.0,
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with (
                patch.object(
                    cli_module,
                    "_DEFAULT_DISTRIBUTION_SUPERVISOR_SNAPSHOT",
                    supervisor,
                ),
                redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["as_of"], date.today().isoformat())
        self.assertEqual(payload["traffic_delivered_total"], 5)
        self.assertEqual(
            payload["metric_source"],
            {
                "traffic_delivered": "supervisor_snapshot",
                "sales_total": "supervisor_snapshot",
                "gross_usd": "supervisor_snapshot",
                "ad_spend_committed_usd": "supervisor_snapshot",
            },
        )
        self.assertEqual(payload["supervisor_snapshot"]["path"], str(supervisor))

    def test_distribution_sku1_gate_discovers_workspace_posted_dir_when_omitted(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "hermes-revenue"
            product_cwd = workspace / "product" / "patchrail"
            posted = workspace / "products" / "gumroad" / "distribution" / "posted"
            posted.mkdir(parents=True)
            product_cwd.mkdir(parents=True)
            (posted / "show-hn.json").write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "blocked",
                        "reason": "Chrome route missing extension",
                        "copy_file": "products/gumroad/distribution/posts/show-hn.md",
                        "ts_blocked": "2026-07-01T07:11:52Z",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with (
                patch.object(cli_module.Path, "cwd", return_value=product_cwd),
                redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--traffic-delivered",
                        "5",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-07-01",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["posted_dir"], str(posted))
        self.assertEqual(payload["blocked_channels"], ["show-hn"])
        self.assertEqual(payload["worker_actionable_reason"], "pablo_handoff_required")

    def test_distribution_sku1_gate_manual_metrics_override_supervisor_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            supervisor = Path(tmpdir) / "patchrail_supervisor_last.json"
            supervisor.write_text(
                json.dumps(
                    {
                        "traffic_delivered_total": 9,
                        "gumroad_sales_total": 0,
                        "gumroad_gross_usd": 0.0,
                        "ad_spend_committed_usd": 5.0,
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--supervisor-snapshot",
                        str(supervisor),
                        "--traffic-delivered",
                        "11",
                        "--sales-total",
                        "1",
                        "--gross-usd",
                        "19.0",
                        "--ad-spend-committed-usd",
                        "7.5",
                        "--as-of",
                        "2026-06-28",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["traffic_delivered"], 11)
        self.assertEqual(payload["sales_total"], 1)
        self.assertEqual(payload["gross_usd"], 19.0)
        self.assertEqual(
            payload["metric_source"],
            {
                "traffic_delivered": "argument",
                "sales_total": "argument",
                "gross_usd": "argument",
                "ad_spend_committed_usd": "argument",
            },
        )
        self.assertEqual(
            payload["metric_warnings"],
            [
                {
                    "metric": "traffic_delivered",
                    "reason": "manual_metric_overrides_supervisor_snapshot",
                    "argument_value": 11,
                    "supervisor_snapshot_value": 9,
                    "snapshot_key": "traffic_delivered_total",
                },
                {
                    "metric": "sales_total",
                    "reason": "manual_metric_overrides_supervisor_snapshot",
                    "argument_value": 1,
                    "supervisor_snapshot_value": 0,
                    "snapshot_key": "gumroad_sales_total",
                },
                {
                    "metric": "gross_usd",
                    "reason": "manual_metric_overrides_supervisor_snapshot",
                    "argument_value": 19.0,
                    "supervisor_snapshot_value": 0.0,
                    "snapshot_key": "gumroad_gross_usd",
                },
                {
                    "metric": "ad_spend_committed_usd",
                    "reason": "manual_metric_overrides_supervisor_snapshot",
                    "argument_value": 7.5,
                    "supervisor_snapshot_value": 5.0,
                    "snapshot_key": "ad_spend_committed_usd",
                },
            ],
        )
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_committed_usd"], 7.5)

    def test_distribution_sku1_gate_exposes_ad_spend_over_cap_from_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            ledger = Path(tmpdir) / "ledger.jsonl"
            ledger.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "status": "committed",
                                "kind": "charge",
                                "amount_usd": "80.25",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--paid-click-cpc-usd",
                        "0.75",
                        "--ad-cap-usd",
                        "75",
                        "--ad-spend-ledger",
                        str(ledger),
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["ad_spend_source"]["committed_usd"], 80.25)
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_reported_usd"], 80.25)
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_committed_usd"], 75.0)
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_over_cap_usd"], 5.25)
        self.assertEqual(payload["paid_traffic_plan"]["ad_remaining_usd"], 0.0)
        self.assertEqual(
            payload["paid_traffic_plan"]["preflight_blocked_reason"], "ad_cap_exceeded"
        )
        self.assertEqual(
            payload["paid_ad_execution_packet"]["preflight_blocked_reason"], "ad_cap_exceeded"
        )
        self.assertEqual(payload["paid_ad_execution_packet"]["commit_command_template"], "")

    def test_distribution_sku1_gate_reports_exhausted_ad_cap_even_with_valid_proof(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "login_required": False,
                        "captured_at": "2026-06-25",
                        "proof_url": "https://ads.google.com/campaigns/ci-triage-sku1-gate",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--paid-click-cpc-usd",
                        "0.75",
                        "--ad-cap-usd",
                        "75",
                        "--ad-spend-committed-usd",
                        "75",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_reported_usd"], 75.0)
        self.assertEqual(payload["paid_traffic_plan"]["ad_spend_over_cap_usd"], 0.0)
        self.assertEqual(payload["paid_traffic_plan"]["ad_remaining_usd"], 0.0)
        self.assertEqual(payload["paid_traffic_plan"]["cap_click_capacity"], 0)
        self.assertEqual(
            payload["paid_traffic_plan"]["recommendation"],
            "ad_cap_exhausted_organic_distribution_required",
        )
        self.assertEqual(
            payload["paid_traffic_plan"]["preflight_blocked_reason"], "ad_cap_exhausted"
        )
        packet = payload["paid_ad_execution_packet"]
        self.assertFalse(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(packet["preflight_blocked_reason"], "ad_cap_exhausted")
        self.assertEqual(packet["commit_command_template"], "")

    def test_distribution_sku1_gate_unblocks_blocked_receipts_without_health_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            (posted / "devto.json").write_text(
                json.dumps(
                    {
                        "channel": "devto",
                        "status": "blocked",
                        "reason": "copywriter unavailable; no approved local copy file",
                        "ts_posted": "2026-06-24T09:34:00Z",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["next_action"], "unblock_distribution_channels")
        self.assertEqual(payload["blocker_queue"][0]["channel"], "devto")

    def test_distribution_sku1_gate_uses_health_to_clear_historical_blocked_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            (posted / "devto-old-block.json").write_text(
                json.dumps(
                    {
                        "channel": "devto",
                        "status": "blocked",
                        "reason": "copywriter unavailable; no approved local copy file for channel",
                        "ts_blocked": "2026-06-24T09:34:00Z",
                    }
                ),
                encoding="utf-8",
            )
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": ["devto"],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(payload["blocked_channels"], [])
        self.assertEqual(payload["blocker_plan"], [])
        self.assertEqual(payload["blocker_queue"], [])
        self.assertEqual(payload["receipt_status_counts"], {"blocked": 1})
        self.assertEqual(payload["publish_health"]["blocked_total"], 0)

    def test_distribution_sku1_gate_recommends_linkedin_expansion_after_base_channels(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["next_action"], "ship_more_distribution")
        self.assertEqual(
            payload["recommended_channel"],
            {
                "channel": "linkedin",
                "source": "expansion",
                "owner": "worker",
                "next_action": "create_social_post_brief",
                "safe_next_step": (
                    "create facts-only social_post brief for linkedin; "
                    "copywriter authors external prose before claim/publish"
                ),
                "reason": "traffic_gap_remaining_after_base_channels_covered",
                "estimated_visits": 45,
            },
        )
        self.assertEqual(payload["traffic_execution_plan"]["recommended_channel"], "linkedin")
        self.assertEqual(payload["channel_conversion_plan"]["channel"], "linkedin")
        self.assertEqual(
            payload["channel_conversion_plan"]["url"],
            "https://patchrail.gumroad.com/l/ci-failure-triage"
            "?utm_source=linkedin&utm_campaign=sku1-organic-distribution",
        )
        self.assertEqual(
            payload["channel_measurement_urls"],
            [
                {
                    "channel": "linkedin",
                    "owner": "worker",
                    "source": "expansion",
                    "next_action": "create_social_post_brief",
                    "url": (
                        "https://patchrail.gumroad.com/l/ci-failure-triage"
                        "?utm_source=linkedin&utm_campaign=sku1-organic-distribution"
                    ),
                    "measurement_event": "sku1_visits_and_sales_delta",
                }
            ],
        )
        self.assertEqual(
            payload["channel_execution_packet"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "required": True,
                "deadline": "2026-06-30",
                "channel": "linkedin",
                "owner": "worker",
                "source": "expansion",
                "next_action": "create_social_post_brief",
                "safe_next_step": (
                    "create facts-only social_post brief for linkedin; "
                    "copywriter authors external prose before claim/publish"
                ),
                "url": (
                    "https://patchrail.gumroad.com/l/ci-failure-triage"
                    "?utm_source=linkedin&utm_campaign=sku1-organic-distribution"
                ),
                "ready_to_publish": False,
                "copywriter_required": True,
                "copy_file": "",
                "organic_click_target": 239,
                "daily_organic_click_target": 47.8,
                "measurement_event": "sku1_visits_and_sales_delta",
                "measurement_command": (
                    "jq '.traffic_delivered_total,.gumroad_sales_total,.gumroad_gross_usd' "
                    "~/.patchrail/run/patchrail_supervisor_last.json"
                ),
                "claim_command": (
                    "python3 opportunity-desk/scripts/publish_post.py claim "
                    "--channel linkedin --copy-file <copywriter-approved-copy-file>"
                ),
                "record_command": (
                    "python3 opportunity-desk/scripts/publish_post.py record "
                    "--channel linkedin --url <submission_url>"
                ),
                "block_command": (
                    "python3 opportunity-desk/scripts/publish_post.py block "
                    "--channel linkedin --reason <concrete_blocker>"
                ),
                "copy_brief_request": {
                    "write_path": (
                        "opportunity-desk/outbox/requests/"
                        "<timestamp>-sku1-linkedin-social-post.json"
                    ),
                    "schema": "copy_brief.social_post.v1",
                    "prohibited_fields": ["body", "draft", "email_body"],
                    "payload": {
                        "type": "social_post",
                        "channel": "linkedin",
                        "lead": "SKU #1 CI Triage $19",
                        "goal": (
                            "Create approved PatchRail social copy for linkedin that drives "
                            "measured visits to SKU #1 before 2026-06-30."
                        ),
                        "key_facts": [
                            "Product: SKU #1 CI Triage $19.",
                            "KPI: visits_and_sales_before_2026-06-30.",
                            (
                                "Channel URL with UTM: "
                                "https://patchrail.gumroad.com/l/ci-failure-triage"
                                "?utm_source=linkedin&utm_campaign=sku1-organic-distribution."
                            ),
                            "Organic click target: 239.",
                            "Daily organic target: 47.8.",
                            "Source: expansion.",
                            "Reason: traffic_gap_remaining_after_base_channels_covered.",
                        ],
                        "tone": "Concise, practical, maintainer-safe, no hype.",
                        "constraints": [
                            (
                                "Copywriter authors final external prose; worker does not draft "
                                "publishable text."
                            ),
                            "Brand-only: PatchRail.",
                            (
                                "No internal model/tool names, no payout or sales guarantees, "
                                "no calls or Calendly."
                            ),
                            "Use the provided UTM URL exactly for measurement.",
                        ],
                        "urgency": "normal",
                        "thread_ref": (
                            "distribution sku1-gate channel=linkedin; "
                            "kpi=visits_and_sales_before_2026-06-30; "
                            "url=https://patchrail.gumroad.com/l/ci-failure-triage"
                            "?utm_source=linkedin&utm_campaign=sku1-organic-distribution"
                        ),
                    },
                },
            },
        )
        self.assertFalse(payload["channel_conversion_plan"]["ready_to_publish"])
        self.assertEqual(
            payload["owner_next_actions"],
            [
                {
                    "owner": "worker",
                    "channel": "linkedin",
                    "pending_channels": ["linkedin"],
                    "pending_count": 1,
                    "next_action": "create_social_post_brief",
                    "safe_next_step": (
                        "create facts-only social_post brief for linkedin; "
                        "copywriter authors external prose before claim/publish"
                    ),
                    "source": "expansion",
                    "oldest_blocked_days": None,
                    "estimated_visits": 45,
                }
            ],
        )
        self.assertEqual(
            payload["owner_action_queue"],
            [
                {
                    "owner": "worker",
                    "primary_channel": "linkedin",
                    "pending_channels": ["linkedin"],
                    "pending_count": 1,
                    "next_action": "create_social_post_brief",
                    "estimated_visits": 45,
                    "command": (
                        "python3 opportunity-desk/scripts/publish_post.py "
                        "blockers --owner worker --json --exit-zero"
                    ),
                    "safe_next_step": (
                        "create facts-only social_post brief for linkedin; "
                        "copywriter authors external prose before claim/publish"
                    ),
                }
            ],
        )

    def test_distribution_sku1_gate_recommends_claiming_approved_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            approved_copy_dir = Path(tmpdir) / "sent"
            approved_copy_dir.mkdir()
            copy_file = Path(tmpdir) / "linkedin.md"
            approved_copy_dir.joinpath("sku1-linkedin-social-post.json").write_text(
                json.dumps(
                    {
                        "type": "social_post",
                        "channel": "linkedin",
                        "copy_file": str(copy_file),
                        "thread_ref": (
                            "distribution sku1-gate channel=linkedin; "
                            "url=https://patchrail.gumroad.com/l/ci-failure-triage"
                            "?utm_source=linkedin&utm_campaign=sku1-organic-distribution"
                        ),
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--approved-copy-dir",
                        str(approved_copy_dir),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["next_action"], "claim_approved_copy")
        self.assertEqual(
            payload["recommended_channel"],
            {
                "channel": "linkedin",
                "source": "approved_copy",
                "owner": "worker_browser",
                "next_action": "claim_approved_copy",
                "safe_next_step": (
                    f"claim linkedin with approved copy_file={copy_file}, "
                    "publish once, then record receipt; login/2FA/CAPTCHA=STOP"
                ),
                "reason": "copywriter_approved_copy_pending_publication",
                "copy_file": str(copy_file),
                "copy_source": str(approved_copy_dir / "sku1-linkedin-social-post.json"),
                "estimated_visits": 45,
            },
        )
        self.assertTrue(payload["channel_conversion_plan"]["ready_to_publish"])
        self.assertFalse(payload["channel_execution_packet"]["copywriter_required"])
        self.assertEqual(payload["channel_execution_packet"]["copy_file"], str(copy_file))
        self.assertEqual(
            payload["publish_post_commands"]["claim_command"],
            "python3 opportunity-desk/scripts/publish_post.py claim "
            f"--channel linkedin --copy-file {copy_file}",
        )
        self.assertEqual(payload["approved_copy"][0]["channel"], "linkedin")

    def test_distribution_sku1_gate_unblocks_copywriter_receipt_with_approved_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            posted.joinpath("devto-20260624T093400Z.json").write_text(
                json.dumps(
                    {
                        "channel": "devto",
                        "status": "blocked",
                        "reason": "copywriter unavailable; no approved local copy file for channel",
                        "ts_blocked": "2026-06-24T09:34:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            approved_copy_dir = Path(tmpdir) / "sent"
            approved_copy_dir.mkdir()
            copy_file = Path(tmpdir) / "devto.md"
            approved_copy_dir.joinpath("sku1-devto-social-post.json").write_text(
                json.dumps(
                    {
                        "type": "social_post",
                        "channel": "devto",
                        "copy_file": str(copy_file),
                        "thread_ref": "distribution sku1-gate channel=devto",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--approved-copy-dir",
                        str(approved_copy_dir),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["recommended_channel"]["channel"], "devto")
        self.assertEqual(payload["recommended_channel"]["next_action"], "claim_approved_copy")
        self.assertEqual(payload["recommended_channel"]["owner"], "worker")
        self.assertEqual(payload["recommended_channel"]["copy_file"], str(copy_file))
        self.assertEqual(payload["blocker_owner_counts"], {"worker": 1})
        self.assertFalse(payload["channel_execution_packet"]["copywriter_required"])

    def test_distribution_sku1_gate_does_not_recommend_posted_expansion_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            posted.joinpath("linkedin.json").write_text(
                json.dumps(
                    {
                        "channel": "linkedin",
                        "status": "posted",
                        "url": "https://www.linkedin.com/feed/update/urn:li:activity:123",
                        "ts_posted": "2026-06-25T14:22:03Z",
                    }
                ),
                encoding="utf-8",
            )
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            approved_copy_dir = Path(tmpdir) / "sent"
            approved_copy_dir.mkdir()
            approved_copy_dir.joinpath("sku1-linkedin-social-post.json").write_text(
                json.dumps(
                    {
                        "type": "social_post",
                        "channel": "linkedin",
                        "copy_file": str(Path(tmpdir) / "linkedin.md"),
                        "thread_ref": "distribution sku1-gate channel=linkedin",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--approved-copy-dir",
                        str(approved_copy_dir),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertIsNone(payload["recommended_channel"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(payload["traffic_execution_plan"]["recommended_channel"], None)
        self.assertEqual(payload["covered_channel_plan"]["next_channel"], None)
        self.assertEqual(
            payload["channel_closeout_plan"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "required": True,
                "all_channels_covered": True,
                "covered_channels": 6,
                "total_channels": 6,
                "next_action": "preflight_guarded_ads_or_measure_gate",
                "safe_next_step": (
                    "Run the ad_spend_guard preflight before any paid boost; if no logged-in "
                    "eligible ad account is available, record measurement and wait for the next signal."
                ),
                "paid_preflight_command": (
                    "python3 opportunity-desk/scripts/ad_spend_guard.py preflight "
                    "--amount 24.75 --platform sku1-traffic-boost "
                    "--campaign ci-triage-sku1-gate"
                ),
                "measurement_command": (
                    "jq '.traffic_delivered_total,.gumroad_sales_total,.gumroad_gross_usd' "
                    "~/.patchrail/run/patchrail_supervisor_last.json"
                ),
            },
        )
        self.assertEqual(
            payload["paid_ad_execution_packet"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "required": True,
                "owner": "worker",
                "platform": "sku1-traffic-boost",
                "campaign": "ci-triage-sku1-gate",
                "amount_usd": 24.75,
                "ad_boost_max_usd": 25.0,
                "ad_boost_click_capacity": 33,
                "paid_click_target": 33,
                "url": (
                    "https://patchrail.gumroad.com/l/ci-failure-triage"
                    "?utm_source=guarded_paid_boost&utm_campaign=ci-triage-sku1-gate"
                ),
                "preflight_command": (
                    "python3 opportunity-desk/scripts/ad_spend_guard.py preflight "
                    "--amount 24.75 --platform sku1-traffic-boost "
                    "--campaign ci-triage-sku1-gate"
                ),
                "eligibility_required": True,
                "spend_executable": False,
                "preflight_blocked_reason": "",
                "blocker_code": "missing_logged_in_preexisting_ad_account_proof",
                "blocker_owner": "human",
                "ad_account_eligibility": {
                    "source": "not_provided",
                    "proof_path": "",
                    "platform": "sku1-traffic-boost",
                    "eligible": False,
                    "reason": "missing_logged_in_preexisting_ad_account_proof",
                    "required_fields": [
                        "platform",
                        "logged_in",
                        "preexisting_account",
                        "card_on_file",
                        "proof_url_or_evidence_path",
                    ],
                },
                "eligibility_handoff": {
                    "required": True,
                    "owner": "worker",
                    "proof_status": "not_provided",
                    "worker_can_collect_proof": True,
                    "human_gate_required": False,
                    "handoff_action": "collect_preexisting_ad_account_proof",
                    "platform": "sku1-traffic-boost",
                    "write_path": "runs/<timestamp>-sku1-ad-account-eligibility/proof.json",
                    "rerun_arg": "--ad-account-eligibility-file <proof.json>",
                    "proof_template": {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "login_required": False,
                        "captcha_or_2fa_required": False,
                        "new_account_required": False,
                        "card_setup_required": False,
                        "billing_or_identity_form_required": False,
                        "captured_at": "YYYY-MM-DD",
                        "proof_url": "<ad_manager_url_or_local_screenshot_path>",
                    },
                    "stop_conditions": [
                        "login_required",
                        "captcha_or_2fa_required",
                        "new_account_required",
                        "card_setup_required",
                        "billing_or_identity_form_required",
                    ],
                    "safe_next_step": (
                        "Create proof only from an already logged-in preexisting ad account with "
                        "a card already on file; otherwise leave spend non-executable."
                    ),
                },
                "commit_command_template": "",
                "fallback_action": "measure_gate_until_eligible_ad_account",
                "halt_flag": "~/.patchrail/run/AD_SPEND_HALT.flag",
                "measurement_command": (
                    "jq '.traffic_delivered_total,.gumroad_sales_total,.gumroad_gross_usd,"
                    ".ad_spend_committed_usd,.ad_cap_usd' "
                    "~/.patchrail/run/patchrail_supervisor_last.json"
                ),
                "safe_next_step": (
                    "Measure the gate until a logged-in preexisting ad account with card-on-file "
                    "is proven; do not create accounts, add cards, bypass login, or spend from "
                    "unproven eligibility."
                ),
            },
        )
        self.assertEqual(
            payload["measurement_packet"],
            {
                "consumer": "SKU #1 CI Triage $19",
                "kpi": "visits_and_sales_before_2026-06-30",
                "as_of": "2026-06-25",
                "gate_date": "2026-06-30",
                "traffic_delivered": 28,
                "traffic_target": 300,
                "traffic_gap": 272,
                "sales_total": 0,
                "gross_usd": 0.0,
                "days_to_gate": 5,
                "required_daily_traffic": 54.4,
                "ad_remaining_usd": 75.0,
                "paid_click_capacity": 100,
                "paid_boost_blocked_reason": "missing_logged_in_preexisting_ad_account_proof",
                "measurement_urls": [
                    {
                        "source": "paid",
                        "channel": "sku1-traffic-boost",
                        "owner": "worker",
                        "next_action": "preflight_guarded_ads_or_measure_gate",
                        "url": (
                            "https://patchrail.gumroad.com/l/ci-failure-triage"
                            "?utm_source=guarded_paid_boost"
                            "&utm_campaign=ci-triage-sku1-gate"
                        ),
                        "measurement_event": "sku1_paid_visits_and_sales_delta",
                    }
                ],
                "url_check_commands": [
                    {
                        "source": "paid",
                        "channel": "sku1-traffic-boost",
                        "command": (
                            "curl -fsSL -o /dev/null -w '%{http_code} %{url_effective}\\n' "
                            "'https://patchrail.gumroad.com/l/ci-failure-triage?"
                            "utm_source=guarded_paid_boost"
                            "&utm_campaign=ci-triage-sku1-gate'"
                        ),
                        "success_criteria": "curl_exit_0",
                    }
                ],
                "next_check": "measure_traffic_delta_again_before_next_distribution_action",
                "next_measurement_target": {
                    "traffic_delta_target": 55,
                    "next_traffic_checkpoint": 83,
                    "sales_delta_target": 1,
                    "pivot_gate_condition": "traffic_delivered>=300 and sales_total==0",
                },
                "pivot_gate_snapshot": {
                    "armed": False,
                    "traffic_target_met": False,
                    "traffic_remaining_to_decision": 272,
                    "sales_required_to_clear_gate": 1,
                    "outcome": "traffic_sample_incomplete",
                },
                "next_measurement_command": (
                    "jq '.traffic_delivered_total,.pivot_gate_armed,.pivot_gate_fires,"
                    ".gumroad_sales_total,.gumroad_gross_usd,.replies_detected,"
                    ".ad_spend_committed_usd,.ad_cap_usd' "
                    "~/.patchrail/run/patchrail_supervisor_last.json"
                ),
                "safe_next_step": (
                    "Measure visits and sales until SKU #1 reaches 300 visits before 2026-06-30, "
                    "or until a proven eligible ad account makes the guarded boost executable."
                ),
            },
        )
        self.assertIn("posted", payload["covered_channel_plan"]["status_counts"])
        self.assertEqual(
            [
                (item["channel"], item["status"], item["recommended"])
                for item in payload["covered_channel_plan"]["channels"]
                if item["channel"] == "linkedin"
            ],
            [("linkedin", "posted", False)],
        )

    def test_distribution_sku1_gate_marks_paid_boost_executable_with_eligibility_proof(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            posted.joinpath("linkedin.json").write_text(
                json.dumps(
                    {
                        "channel": "linkedin",
                        "status": "posted",
                        "url": "https://www.linkedin.com/posts/patchrail",
                    }
                ),
                encoding="utf-8",
            )
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "login_required": False,
                        "captured_at": "2026-06-25",
                        "proof_url": "https://ads.google.com/campaigns/ci-triage-sku1-gate",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["next_action"], "preflight_guarded_ads_or_measure_gate")
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertTrue(packet["spend_executable"])
        self.assertEqual(packet["blocker_code"], "")
        self.assertEqual(packet["blocker_owner"], "")
        self.assertEqual(packet["fallback_action"], "")
        self.assertEqual(
            packet["ad_account_eligibility"]["reason"], "eligible_preexisting_logged_in_account"
        )
        self.assertEqual(
            packet["ad_account_eligibility"]["evidence_ref"],
            "https://ads.google.com/campaigns/ci-triage-sku1-gate",
        )
        self.assertFalse(packet["eligibility_handoff"]["required"])
        self.assertIn("--amount 24.75", packet["commit_command_template"])

    def test_distribution_sku1_gate_allows_paid_boost_when_cap_covers_remaining_gap(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "login_required": False,
                        "captured_at": "2026-06-29",
                        "proof_url": "https://ads.google.com/campaigns/ci-triage-sku1-gate",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "275",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-29",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload["paid_traffic_plan"]["recommendation"],
            "paid_boost_can_cover_gap_if_preflight_passes",
        )
        self.assertEqual(payload["traffic_execution_plan"]["paid_click_target"], 25)
        self.assertEqual(payload["traffic_execution_plan"]["organic_click_target"], 0)
        self.assertEqual(payload["next_action"], "preflight_guarded_ads_or_measure_gate")
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertTrue(packet["spend_executable"])
        self.assertIn("--amount 18.75", packet["preflight_command"])
        self.assertIn("--amount 18.75", packet["commit_command_template"])

    def test_distribution_sku1_gate_requires_local_proof_path_linked_to_campaign(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            linked_evidence = Path(tmpdir) / "ci-triage-sku1-gate-screenshot.png"
            linked_evidence.write_bytes(b"fake screenshot bytes")
            generic_evidence = Path(tmpdir) / "screenshot.png"
            generic_evidence.write_bytes(b"fake screenshot bytes")
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"

            def run_gate(local_screenshot_path: str) -> dict[str, object]:
                eligibility_file.write_text(
                    json.dumps(
                        {
                            "platform": "sku1-traffic-boost",
                            "logged_in": True,
                            "preexisting_account": True,
                            "card_on_file": True,
                            "captured_at": "2026-06-25",
                            "local_screenshot_path": local_screenshot_path,
                        }
                    ),
                    encoding="utf-8",
                )
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "distribution",
                            "sku1-gate",
                            "--posted-dir",
                            str(posted),
                            "--publish-health-file",
                            str(health_file),
                            "--ad-account-eligibility-file",
                            str(eligibility_file),
                            "--traffic-delivered",
                            "28",
                            "--sales-total",
                            "0",
                            "--gross-usd",
                            "0",
                            "--as-of",
                            "2026-06-25",
                            "--format",
                            "json",
                        ]
                    )
                self.assertEqual(exit_code, 0)
                return json.loads(stdout.getvalue())

            linked_payload = run_gate(str(linked_evidence))
            linked_packet = linked_payload["paid_ad_execution_packet"]
            self.assertTrue(linked_packet["spend_executable"])
            self.assertEqual(linked_packet["ad_account_eligibility"]["evidence_status"], "present")

            generic_payload = run_gate(str(generic_evidence))
            generic_packet = generic_payload["paid_ad_execution_packet"]
            self.assertFalse(generic_packet["spend_executable"])
            self.assertEqual(generic_packet["blocker_code"], "eligibility_failed")
            self.assertEqual(generic_packet["blocker_owner"], "worker")
            self.assertEqual(
                generic_payload["next_action"], "measure_gate_until_eligible_ad_account"
            )
            self.assertEqual(
                generic_packet["ad_account_eligibility"]["evidence_status"],
                "unlinked_local_evidence_file",
            )
            self.assertEqual(
                generic_packet["ad_account_eligibility"]["missing_or_failed"],
                ["proof_url_or_evidence_path"],
            )

    def test_distribution_sku1_gate_rejects_paid_boost_when_proof_url_is_placeholder_domain(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "captured_at": "2026-06-25",
                        "proof_url": "https://ads.example.com/campaigns/ci-triage-sku1-gate",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(
            packet["ad_account_eligibility"]["evidence_status"],
            "placeholder_or_local_proof_url",
        )
        self.assertEqual(
            packet["ad_account_eligibility"]["missing_or_failed"],
            ["proof_url_or_evidence_path"],
        )
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_when_proof_url_is_not_ad_manager(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "captured_at": "2026-06-25",
                        "proof_url": "https://analytics.patchrail.com/campaigns/ci-triage-sku1-gate",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(
            packet["ad_account_eligibility"]["evidence_status"], "untrusted_ad_manager_url"
        )
        self.assertEqual(
            packet["ad_account_eligibility"]["missing_or_failed"],
            ["proof_url_or_evidence_path"],
        )
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_without_capture_date(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "proof_url": "https://ads.google.com/campaigns/ci-triage-sku1-gate",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(packet["ad_account_eligibility"]["capture_status"], "not_provided")
        self.assertEqual(packet["ad_account_eligibility"]["missing_or_failed"], ["fresh_capture"])
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_when_proof_is_stale(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "captured_at": "2026-06-10",
                        "proof_url": "https://ads.google.com/campaigns/ci-triage-sku1-gate",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(packet["ad_account_eligibility"]["capture_status"], "stale_capture")
        self.assertEqual(packet["ad_account_eligibility"]["capture_age_days"], 15)
        self.assertEqual(
            packet["ad_account_eligibility"]["missing_or_failed"],
            ["fresh_capture"],
        )
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_when_proof_url_contains_userinfo(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "captured_at": "2026-06-25",
                        "proof_url": "https://token@ads.google.com/campaigns/ci-triage-sku1-gate",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(
            packet["ad_account_eligibility"]["evidence_status"], "credentialed_proof_url"
        )
        self.assertEqual(
            packet["ad_account_eligibility"]["missing_or_failed"],
            ["proof_url_or_evidence_path"],
        )
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_when_proof_url_is_unlinked(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "captured_at": "2026-06-25",
                        "proof_url": "https://ads.google.com/campaigns/brand-awareness",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(packet["ad_account_eligibility"]["evidence_status"], "unlinked_proof_url")
        self.assertEqual(
            packet["ad_account_eligibility"]["missing_or_failed"],
            ["proof_url_or_evidence_path"],
        )
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_when_campaign_only_in_query(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "captured_at": "2026-06-25",
                        "proof_url": (
                            "https://ads.google.com/campaigns?utm_campaign=ci-triage-sku1-gate"
                        ),
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(packet["ad_account_eligibility"]["evidence_status"], "unlinked_proof_url")
        self.assertEqual(
            packet["ad_account_eligibility"]["missing_or_failed"],
            ["proof_url_or_evidence_path"],
        )
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_when_proof_has_multiple_evidence_refs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            local_evidence = Path(tmpdir) / "proof.png"
            local_evidence.write_bytes(b"fake screenshot bytes")
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "captured_at": "2026-06-25",
                        "proof_url": "https://ads.google.com/campaigns/ci-triage-sku1-gate",
                        "local_screenshot_path": str(local_evidence),
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(
            packet["ad_account_eligibility"]["evidence_status"], "ambiguous_evidence_fields"
        )
        self.assertEqual(
            packet["ad_account_eligibility"]["evidence_fields"],
            ["proof_url", "local_screenshot_path"],
        )
        self.assertEqual(
            packet["ad_account_eligibility"]["missing_or_failed"],
            ["proof_url_or_evidence_path"],
        )
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_when_proof_has_gated_stop_condition(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "billing_or_identity_form_required": True,
                        "captured_at": "2026-06-25",
                        "proof_url": "https://ads.google.com/campaigns/ci-triage-sku1-gate",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "gated_stop_condition_present")
        self.assertEqual(
            packet["ad_account_eligibility"]["stop_conditions_triggered"],
            ["billing_or_identity_form_required"],
        )
        self.assertEqual(
            packet["ad_account_eligibility"]["missing_or_failed"],
            ["no_gated_stop_conditions"],
        )
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])
        self.assertEqual(packet["eligibility_handoff"]["proof_status"], "provided")
        self.assertFalse(packet["eligibility_handoff"]["worker_can_collect_proof"])
        self.assertTrue(packet["eligibility_handoff"]["human_gate_required"])
        self.assertEqual(
            packet["eligibility_handoff"]["handoff_action"],
            "stop_for_human_ad_account_state",
        )

    def test_distribution_sku1_gate_rejects_paid_boost_when_stop_condition_uses_string_true(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "billing_or_identity_form_required": "true",
                        "captured_at": "2026-06-25",
                        "proof_url": "https://ads.google.com/campaigns/ci-triage-sku1-gate",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "gated_stop_condition_present")
        self.assertEqual(
            packet["ad_account_eligibility"]["stop_conditions_triggered"],
            ["billing_or_identity_form_required"],
        )
        self.assertEqual(
            packet["ad_account_eligibility"]["invalid_stop_condition_fields"],
            ["billing_or_identity_form_required"],
        )
        self.assertEqual(
            packet["ad_account_eligibility"]["missing_or_failed"],
            ["no_gated_stop_conditions"],
        )
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_when_proof_omits_platform(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "captured_at": "2026-06-25",
                        "proof_url": "https://ads.google.com/campaigns/ci-triage-sku1-gate",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(
            packet["ad_account_eligibility"]["expected_platform"], "sku1-traffic-boost"
        )
        self.assertEqual(packet["ad_account_eligibility"]["platform_status"], "missing")
        self.assertEqual(packet["ad_account_eligibility"]["missing_or_failed"], ["platform"])
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_when_proof_platform_differs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "brand-awareness-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "captured_at": "2026-06-25",
                        "proof_url": "https://ads.google.com/campaigns/ci-triage-sku1-gate",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(packet["ad_account_eligibility"]["platform"], "brand-awareness-boost")
        self.assertEqual(
            packet["ad_account_eligibility"]["expected_platform"], "sku1-traffic-boost"
        )
        self.assertEqual(packet["ad_account_eligibility"]["platform_status"], "mismatch")
        self.assertEqual(packet["ad_account_eligibility"]["missing_or_failed"], ["platform"])
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_when_proof_has_no_evidence_ref(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "captured_at": "2026-06-25",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(
            packet["ad_account_eligibility"]["missing_or_failed"],
            ["proof_url_or_evidence_path"],
        )
        self.assertEqual(packet["ad_account_eligibility"]["evidence_ref"], "")
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_when_proof_uses_string_booleans(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": "false",
                        "preexisting_account": "true",
                        "card_on_file": "true",
                        "login_required": "false",
                        "captured_at": "2026-06-25",
                        "proof_url": "https://ads.google.com/campaigns/ci-triage-sku1-gate",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(
            packet["ad_account_eligibility"]["missing_or_failed"],
            ["logged_in", "preexisting_account", "card_on_file", "no_gated_stop_conditions"],
        )
        self.assertEqual(
            packet["ad_account_eligibility"]["invalid_stop_condition_fields"],
            ["login_required"],
        )
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_when_proof_uses_template_placeholder(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "login_required": False,
                        "captcha_or_2fa_required": False,
                        "new_account_required": False,
                        "card_setup_required": False,
                        "billing_or_identity_form_required": False,
                        "captured_at": "2026-06-25",
                        "proof_url": "<ad_manager_url_or_local_screenshot_path>",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(packet["ad_account_eligibility"]["evidence_status"], "placeholder")
        self.assertEqual(
            packet["ad_account_eligibility"]["missing_or_failed"],
            ["proof_url_or_evidence_path"],
        )
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_when_proof_url_is_not_url(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "captured_at": "2026-06-25",
                        "proof_url": "ads.example.com/campaigns/ci-triage",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(packet["ad_account_eligibility"]["evidence_status"], "invalid_proof_url")
        self.assertEqual(packet["ad_account_eligibility"]["evidence_field"], "proof_url")
        self.assertEqual(
            packet["ad_account_eligibility"]["missing_or_failed"],
            ["proof_url_or_evidence_path"],
        )
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_when_proof_url_is_not_https(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "captured_at": "2026-06-25",
                        "proof_url": "http://ads.google.com/campaigns/ci-triage-sku1-gate",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(packet["ad_account_eligibility"]["evidence_status"], "invalid_proof_url")
        self.assertEqual(packet["ad_account_eligibility"]["evidence_field"], "proof_url")
        self.assertEqual(
            packet["ad_account_eligibility"]["missing_or_failed"],
            ["proof_url_or_evidence_path"],
        )
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_when_local_evidence_missing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "captured_at": "2026-06-25",
                        "local_screenshot_path": "missing-screenshot.png",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(
            packet["ad_account_eligibility"]["evidence_status"],
            "missing_local_evidence_file",
        )
        self.assertEqual(
            packet["ad_account_eligibility"]["evidence_field"], "local_screenshot_path"
        )
        self.assertEqual(
            packet["ad_account_eligibility"]["missing_or_failed"],
            ["proof_url_or_evidence_path"],
        )
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_when_local_evidence_empty(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            evidence_file = Path(tmpdir) / "screenshot.png"
            evidence_file.touch()
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "captured_at": "2026-06-25",
                        "local_screenshot_path": "screenshot.png",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(
            packet["ad_account_eligibility"]["evidence_status"],
            "empty_local_evidence_file",
        )
        self.assertEqual(
            packet["ad_account_eligibility"]["evidence_field"], "local_screenshot_path"
        )
        self.assertEqual(
            packet["ad_account_eligibility"]["missing_or_failed"],
            ["proof_url_or_evidence_path"],
        )
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_rejects_paid_boost_when_local_evidence_is_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "covered_channels": [
                            "devto",
                            "hashnode",
                            "linkedin",
                            "reddit-sideproject",
                            "show-hn",
                            "x",
                        ],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 0,
                        "social_post_stale_claims_total": 0,
                        "blocked": [],
                        "stale_claims": [],
                        "uncovered": [],
                    }
                ),
                encoding="utf-8",
            )
            evidence_dir = Path(tmpdir) / "screenshots"
            evidence_dir.mkdir()
            eligibility_file = Path(tmpdir) / "ad-account-eligibility.json"
            eligibility_file.write_text(
                json.dumps(
                    {
                        "platform": "sku1-traffic-boost",
                        "logged_in": True,
                        "preexisting_account": True,
                        "card_on_file": True,
                        "captured_at": "2026-06-25",
                        "local_screenshot_path": "screenshots",
                    }
                ),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--ad-account-eligibility-file",
                        str(eligibility_file),
                        "--traffic-delivered",
                        "28",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        packet = payload["paid_ad_execution_packet"]
        self.assertTrue(packet["required"])
        self.assertFalse(packet["spend_executable"])
        self.assertEqual(payload["next_action"], "measure_gate_until_eligible_ad_account")
        self.assertEqual(packet["ad_account_eligibility"]["reason"], "eligibility_failed")
        self.assertEqual(
            packet["ad_account_eligibility"]["evidence_status"],
            "invalid_local_evidence_file",
        )
        self.assertEqual(
            packet["ad_account_eligibility"]["evidence_field"], "local_screenshot_path"
        )
        self.assertEqual(
            packet["ad_account_eligibility"]["missing_or_failed"],
            ["proof_url_or_evidence_path"],
        )
        self.assertEqual(packet["commit_command_template"], "")
        self.assertTrue(packet["eligibility_handoff"]["required"])

    def test_distribution_sku1_gate_fires_only_after_target_and_gate_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "300",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-30",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["pivot_gate_armed"])
        self.assertTrue(payload["pivot_gate_fires"])
        self.assertEqual(payload["next_action"], "pivot_offer")
        self.assertEqual(payload["traffic_execution_plan"]["paid_click_target"], 0)
        self.assertEqual(payload["traffic_execution_plan"]["organic_click_target"], 0)
        self.assertEqual(
            payload["measurement_packet"]["next_check"],
            "snapshot_pivot_gate_with_sales_count",
        )
        self.assertEqual(
            payload["measurement_packet"]["pivot_gate_snapshot"],
            {
                "armed": True,
                "traffic_target_met": True,
                "traffic_remaining_to_decision": 0,
                "sales_required_to_clear_gate": 1,
                "outcome": "pivot_required_no_sales",
            },
        )

    def test_distribution_sku1_gate_does_not_pivot_on_unparseable_as_of(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "300",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "not-a-date",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["pivot_gate_armed"])
        self.assertFalse(payload["pivot_gate_fires"])
        self.assertEqual(payload["traffic_pressure"]["status"], "unknown_date")
        self.assertEqual(payload["pivot_decision"]["status"], "await_gate_date")
        self.assertEqual(
            payload["measurement_packet"]["pivot_gate_snapshot"]["outcome"],
            "await_sales_until_gate_date",
        )

    def test_distribution_sku1_gate_measurement_packet_records_sale_next_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "42",
                        "--sales-total",
                        "1",
                        "--gross-usd",
                        "19",
                        "--as-of",
                        "2026-06-29",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["next_action"], "fulfill_sale")
        self.assertEqual(
            payload["measurement_packet"]["next_check"],
            "record_paid_sale_and_prepare_fulfillment_snapshot",
        )
        self.assertEqual(
            payload["measurement_packet"]["pivot_gate_snapshot"],
            {
                "armed": False,
                "traffic_target_met": False,
                "traffic_remaining_to_decision": 258,
                "sales_required_to_clear_gate": 0,
                "outcome": "validated_by_sale",
            },
        )

    def test_distribution_sku1_gate_writes_social_copy_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "covered_channels": ["x"],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 1,
                        "social_post_stale_claims_total": 0,
                        "uncovered": [{"channel": "devto"}],
                    }
                ),
                encoding="utf-8",
            )
            brief_path = Path(tmpdir) / "requests" / "sku1-devto-social-post.json"

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                        "--write-copy-brief",
                        str(brief_path),
                    ]
                )
            brief = json.loads(brief_path.read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["copy_brief_write"]["status"], "written")
            self.assertEqual(payload["copy_brief_write"]["path"], str(brief_path))
            self.assertTrue(payload["copy_brief_write"]["forbidden_fields_absent"])
        self.assertEqual(brief["type"], "social_post")
        self.assertEqual(brief["channel"], "devto")
        self.assertEqual(brief["lead"], "SKU #1 CI Triage $19")
        self.assertIn("utm_source=devto", brief["thread_ref"])
        self.assertNotIn("body", brief)
        self.assertNotIn("draft", brief)
        self.assertNotIn("email_body", brief)

    def test_distribution_sku1_gate_does_not_overwrite_existing_social_copy_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            health_file = Path(tmpdir) / "publish-health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "covered_channels": ["x"],
                        "social_post_blocked_total": 0,
                        "social_post_uncovered_total": 1,
                        "social_post_stale_claims_total": 0,
                        "uncovered": [{"channel": "devto"}],
                    }
                ),
                encoding="utf-8",
            )
            brief_path = Path(tmpdir) / "requests" / "sku1-devto-social-post.json"
            brief_path.parent.mkdir()
            original = {"type": "social_post", "channel": "devto", "sentinel": "keep"}
            brief_path.write_text(json.dumps(original), encoding="utf-8")

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--publish-health-file",
                        str(health_file),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-25",
                        "--format",
                        "json",
                        "--write-copy-brief",
                        str(brief_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["copy_brief_write"]["status"], "already_exists")
            self.assertEqual(json.loads(brief_path.read_text(encoding="utf-8")), original)

    def test_distribution_sku1_gate_does_not_write_copy_brief_for_extension_blocker(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posted = Path(tmpdir) / "posted"
            posted.mkdir()
            copy_file = Path(tmpdir) / "devto.md"
            posted.joinpath("devto-blocked.json").write_text(
                json.dumps(
                    {
                        "channel": "devto",
                        "status": "blocked",
                        "copy_file": str(copy_file),
                        "reason": "approved Chrome publishing extension missing installed=false",
                        "ts_blocked": "2026-06-25T21:10:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            brief_path = Path(tmpdir) / "requests" / "sku1-devto-social-post.json"

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "distribution",
                        "sku1-gate",
                        "--posted-dir",
                        str(posted),
                        "--traffic-delivered",
                        "25",
                        "--sales-total",
                        "0",
                        "--gross-usd",
                        "0",
                        "--as-of",
                        "2026-06-26",
                        "--format",
                        "json",
                        "--write-copy-brief",
                        str(brief_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(
                payload["recommended_channel"]["next_action"], "browser_extension_setup_required"
            )
            self.assertEqual(
                payload["execution_handoff"],
                {
                    "consumer": "SKU #1 CI Triage $19",
                    "kpi": "visits_and_sales_before_2026-06-30",
                    "required": True,
                    "owner": "pablo",
                    "channel": "devto",
                    "next_action": "browser_extension_setup_required",
                    "command": (
                        "python3 opportunity-desk/scripts/publish_post.py blockers "
                        "--owner pablo --json --exit-zero"
                    ),
                    "verify_command": (
                        "python3 opportunity-desk/scripts/publish_post.py blockers "
                        "--owner pablo --json --exit-zero"
                    ),
                    "safe_next_step": (
                        "Enable/install the browser extension in the logged-in profile, then "
                        "claim the channel if copy is available."
                    ),
                    "stop_conditions": ["login_required", "captcha_or_2fa_required"],
                },
            )
            self.assertEqual(payload["channel_execution_packet"]["copy_file"], str(copy_file))
            covered_devto = next(
                row
                for row in payload["covered_channel_plan"]["channels"]
                if row["channel"] == "devto"
            )
            self.assertEqual(covered_devto["copy_file"], str(copy_file))
            self.assertEqual(payload["copy_brief_write"]["status"], "skipped")
            self.assertEqual(
                payload["copy_brief_write"]["reason"],
                "copy_brief_not_required_for_recommended_channel",
            )
            self.assertEqual(payload["copy_brief_write"]["copy_file"], str(copy_file))
            self.assertFalse(brief_path.exists())

    def test_ci_classify_emits_json_without_external_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "python -m pytest -q\nFAILED tests/test_app.py::test_ok - AssertionError\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["schema_version"], "patchrail.ci_result.v1")
            self.assertEqual(payload["failure_class"], "python_test_failure")
            self.assertEqual(payload["requirements"]["billing_required"], False)
            self.assertEqual(payload["requirements"]["external_model_required"], False)
            self.assertIn("pytest", payload["reproduction_command"])

    def test_ci_classify_detects_runner_memory_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run pytest -q\n"
                "collected 412 items\n"
                "##[error]The operation was canceled.\n"
                "Process completed with exit code 137.\n"
                "Container app was OOMKilled (exceeded memory limit).\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "runner_resource_exhaustion")
            self.assertEqual(payload["requirements"]["external_model_required"], False)
            self.assertIn("memory", payload["minimal_repair_strategy"])

    def test_ci_classify_detects_runner_disk_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "npm error code ENOSPC\n"
                "npm error syscall write\n"
                "npm error errno -28\n"
                "npm error nospc ENOSPC: No space left on device, write\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "runner_resource_exhaustion")
            self.assertIn("disk", payload["minimal_repair_strategy"])

    def test_ci_classify_detects_dns_network_transient_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run python -m pip install -r requirements.txt\n"
                "WARNING: Retrying after connection broken by 'NewConnectionError'\n"
                "Could not resolve host: pypi.org\n"
                "Temporary failure in name resolution\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "network_transient_failure")
            self.assertIn("retry", payload["minimal_repair_strategy"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_transient_registry_outage_wins_over_install_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "npm ERR! code E503\n"
                "npm ERR! 503 Service Unavailable - GET https://registry.npmjs.org/react\n"
                "npm ERR! Connection reset by peer\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "network_transient_failure")

    def test_ci_classify_detects_git_network_transient_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run actions/checkout@v4\n"
                "fatal: unable to access 'https://github.com/org/repo/': "
                "Failed to connect to github.com port 443: Connection timed out\n"
                "The remote end hung up unexpectedly\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "network_transient_failure")
            self.assertIn("re-run", payload["reproduction_command"])

    def test_ci_classify_detects_github_actions_job_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run python -m pytest -q\n"
                "The job running on runner GitHub Actions 12 has exceeded "
                "the maximum execution time of 360 minutes.\n"
                "##[error]The operation was canceled.\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "ci_job_timeout")
            self.assertIn("time limit", payload["reproduction_command"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_detects_gitlab_job_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Running with gitlab-runner 17.4.0\n"
                "ERROR: Job failed: execution took longer than 1h0m0s seconds\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "ci_job_timeout")

    def test_ci_classify_circleci_no_output_timeout_wins_over_network_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Too long with no output (exceeded 10m0s): context deadline exceeded\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "ci_job_timeout")

    def test_ci_classify_job_timeout_wins_over_passing_pytest_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "python -m pytest -q\n"
                "tests/test_app.py ........................                [ 64%]\n"
                "The job running on runner ubuntu-latest-8core has exceeded "
                "the maximum execution time of 90 minutes.\n"
                "##[error]The operation was canceled.\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "ci_job_timeout")

    def test_ci_classify_detects_pytest_coverage_threshold_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run pytest --cov=src --cov-fail-under=90\n"
                "======================== 412 passed in 18.44s ========================\n"
                "Required test coverage of 90% not reached. Total coverage: 86.71%\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "code_coverage_threshold")
            self.assertIn("coverage", payload["minimal_repair_strategy"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_coverage_gate_wins_over_passing_pytest_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "coverage report --fail-under=85\n"
                "Coverage failure: total of 82 is less than fail-under=85\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "code_coverage_threshold")

    def test_ci_classify_detects_jest_coverage_threshold_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                'Jest: "global" coverage threshold for statements (90%) not met: 84.21%\n'
                "Jest: Coverage for lines (88%) does not meet global threshold (90%)\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "code_coverage_threshold")

    def test_ci_classify_detects_mypy_type_check_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run mypy src\n"
                'src/app.py:42: error: Incompatible return value type (got "int", '
                'expected "str")  [return-value]\n'
                'src/app.py:88: error: Argument 1 to "run" has incompatible type '
                '"bytes"; expected "str"  [arg-type]\n'
                "Found 2 errors in 1 file (checked 24 source files)\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "python_type_check")
            self.assertGreaterEqual(payload["confidence"], 0.7)
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_detects_pyright_type_check_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run pyright\n"
                '/repo/src/app.py:17:9 - error: "value" is not assignable to declared '
                'type "int" (reportAssignmentType)\n'
                "3 errors, 0 warnings, 0 informations\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "python_type_check")

    def test_ci_classify_type_check_wins_over_passing_pytest_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run: pytest && mypy src\n"
                "============== 120 passed in 4.2s ==============\n"
                "src/app.py:10: error: Incompatible types in assignment  [assignment]\n"
                "Found 1 error in 1 file (checked 12 source files)\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "python_type_check")

    def test_ci_classify_detects_ruff_lint_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run ruff check .\n"
                "src/app.py:1:1: F401 [*] `os` imported but unused\n"
                "src/app.py:12:89: E501 Line too long (104 > 88)\n"
                "Found 2 errors.\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["failure_class"], "python_lint")
        self.assertGreaterEqual(payload["confidence"], 0.7)
        self.assertEqual(
            payload["guide_url"],
            "https://getpatchrail.com/fix/python-lint?utm_source=cli&utm_campaign=python-lint",
        )
        self.assertEqual(
            payload["pack_url"],
            "https://patchrail.gumroad.com/l/ci-failure-triage"
            "?utm_source=cli&utm_campaign=python-lint",
        )
        self.assertEqual(
            payload["sample_url"],
            "https://patchrail.gumroad.com/l/iwycg?utm_source=cli&utm_campaign=python-lint",
        )
        self.assertEqual(
            payload["action_url"],
            "https://github.com/patchrail/ci-triage-action?utm_source=cli&utm_campaign=python-lint",
        )

    def test_ci_classify_detects_black_format_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "Run black --check .\n"
                "would reformat src/app.py\n"
                "Oh no! 1 file would be reformatted, 23 files would be left unchanged.\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "python_lint")

    def test_schema_command_emits_ci_result_contract(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "patchrail", "schema", "ci-result"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        schema = json.loads(proc.stdout)
        self.assertEqual(schema["properties"]["schema_version"]["const"], "patchrail.ci_result.v1")
        self.assertIn("python_test_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("java_build_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("dotnet_build_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("docker_build_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("browser_test_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("security_scan_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("ruby_bundle_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("php_composer_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("runner_resource_exhaustion", schema["properties"]["failure_class"]["enum"])
        self.assertIn("network_transient_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("code_coverage_threshold", schema["properties"]["failure_class"]["enum"])
        self.assertIn("python_type_check", schema["properties"]["failure_class"]["enum"])
        self.assertIn("python_lint", schema["properties"]["failure_class"]["enum"])
        self.assertIn("ci_job_timeout", schema["properties"]["failure_class"]["enum"])
        self.assertIn("cpp_build_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("guide_url", schema["required"])
        self.assertIn("pack_url", schema["required"])
        self.assertIn("sample_url", schema["required"])
        self.assertIn("action_url", schema["required"])
        self.assertEqual(
            schema["properties"]["guide_url"]["pattern"],
            "^https://getpatchrail\\.com/fix",
        )
        self.assertEqual(
            schema["properties"]["pack_url"]["pattern"],
            "^https://patchrail\\.gumroad\\.com/l/ci-failure-triage",
        )
        self.assertEqual(
            schema["properties"]["sample_url"]["pattern"],
            "^https://patchrail\\.gumroad\\.com/l/iwycg",
        )
        self.assertEqual(
            schema["properties"]["action_url"]["pattern"],
            "^https://github\\.com/patchrail/ci-triage-action",
        )
        self.assertIn("node_test_failure", schema["properties"]["failure_class"]["enum"])
        self.assertIn("node_dependency_install", schema["properties"]["failure_class"]["enum"])
        self.assertIn("rust_lint", schema["properties"]["failure_class"]["enum"])
        self.assertIn("go_lint", schema["properties"]["failure_class"]["enum"])
        self.assertIn("typescript_typecheck", schema["properties"]["failure_class"]["enum"])
        self.assertEqual(
            schema["properties"]["requirements"]["properties"]["billing_required"]["const"], False
        )
        self.assertEqual(
            schema["properties"]["requirements"]["properties"]["external_model_required"]["const"],
            False,
        )

    def test_schema_command_emits_ci_benchmark_and_pilot_contracts(self) -> None:
        expected_versions = {
            "application-dossier": "patchrail.application_dossier.v1",
            "ci-benchmark": "patchrail.ci_benchmark.v1",
            "ci-fixture-check": "patchrail.ci_fixture_check.v1",
            "ci-pilot-summary": "patchrail.ci_pilot_summary.v1",
            "ci-pilot-metrics": "patchrail.ci_pilot_metrics.v1",
            "reviewer-quick-check-artifacts": "patchrail.reviewer_quick_check_artifacts.v1",
        }

        for schema_name, schema_version in expected_versions.items():
            with self.subTest(schema_name=schema_name):
                proc = subprocess.run(
                    [sys.executable, "-m", "patchrail", "schema", schema_name],
                    text=True,
                    capture_output=True,
                    check=False,
                )

                self.assertEqual(proc.returncode, 0, proc.stderr)
                schema = json.loads(proc.stdout)
                self.assertEqual(schema["properties"]["schema_version"]["const"], schema_version)
                if schema_name == "application-dossier":
                    submission = schema["properties"]["submission_policy"]["properties"]
                    safety = schema["properties"]["safety"]["properties"]
                    self.assertEqual(submission["maintainer_tap_required"]["const"], True)
                    self.assertEqual(submission["agent_may_submit"]["const"], False)
                    self.assertEqual(submission["no_placeholder_metrics"]["const"], True)
                    self.assertEqual(submission["no_money_goal"]["const"], True)
                    self.assertEqual(safety["local_first"]["const"], True)
                    self.assertEqual(safety["billing_required"]["const"], False)
                    self.assertEqual(safety["third_party_write_actions_allowed"]["const"], False)
                elif schema_name == "reviewer-quick-check-artifacts":
                    self.assertEqual(
                        schema["properties"]["generated_from"]["const"], "local_checkout"
                    )
                    self.assertEqual(schema["properties"]["network_required"]["const"], False)
                    self.assertEqual(schema["properties"]["write_action_required"]["const"], False)
                    self.assertEqual(
                        schema["properties"]["application_form_submission_performed"]["const"],
                        False,
                    )
                    artifacts = schema["properties"]["artifacts"]["items"]["enum"]
                    self.assertIn("README.md", artifacts)
                    self.assertIn("reviewer-quick-check.md", artifacts)
                    self.assertIn("application-dossier.json", artifacts)
                    self.assertIn("http-api-evidence.json", artifacts)
                    self.assertIn("http-api-evidence.md", artifacts)
                    self.assertIn("release-readiness.json", artifacts)
                    self.assertIn("release-readiness.md", artifacts)
                    self.assertIn("reviewer-quick-check-artifacts.schema.json", artifacts)
                else:
                    requirements = schema["properties"]["requirements"]["properties"]
                    self.assertEqual(requirements["billing_required"]["const"], False)
                    self.assertEqual(requirements["external_model_required"]["const"], False)
                    self.assertEqual(requirements["network_required"]["const"], False)
                    if "github_write_permission_required" in requirements:
                        self.assertEqual(
                            requirements["github_write_permission_required"]["const"], False
                        )

    def test_doctor_reports_local_first_requirements(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "patchrail", "doctor", "--format", "json"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schema_version"], "patchrail.doctor.v1")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["local_first"], True)
        self.assertEqual(payload["checks"]["ci_fixture_count"], 153)
        self.assertEqual(payload["checks"]["ci_result_schema_available"], True)
        self.assertEqual(payload["requirements"]["billing_required"], False)
        self.assertEqual(payload["requirements"]["external_model_required"], False)
        self.assertEqual(payload["requirements"]["network_required"], False)
        self.assertEqual(payload["requirements"]["github_write_permission_required"], False)

    def test_ci_benchmark_checks_fixture_expectations(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "ci",
                "benchmark",
                "examples/ci-triage",
                "--format",
                "json",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["schema_version"], "patchrail.ci_benchmark.v1")
        self.assertEqual(payload["total_cases"], 153)
        self.assertEqual(payload["passed"], 153)
        self.assertEqual(payload["failed"], 0)
        self.assertEqual(payload["accuracy"]["top_1"], 1.0)
        self.assertEqual(payload["coverage_gate"]["min_cases_per_class"], 0)
        self.assertEqual(payload["coverage_gate"]["passed"], True)
        self.assertEqual(payload["coverage_gate"]["failures"], [])
        self.assertEqual(payload["root"], "examples/ci-triage")
        self.assertEqual(
            payload["class_summary"],
            {
                "browser_test_failure": {"failed": 0, "passed": 5, "total_cases": 5},
                "dotnet_build_failure": {"failed": 0, "passed": 5, "total_cases": 5},
                "docker_build_failure": {"failed": 0, "passed": 5, "total_cases": 5},
                "github_actions_workflow": {"failed": 0, "passed": 10, "total_cases": 10},
                "go_test_failure": {"failed": 0, "passed": 10, "total_cases": 10},
                "java_build_failure": {"failed": 0, "passed": 5, "total_cases": 5},
                "javascript_lint": {"failed": 0, "passed": 11, "total_cases": 11},
                "node_dependency_install": {"failed": 0, "passed": 19, "total_cases": 19},
                "php_composer_failure": {"failed": 0, "passed": 5, "total_cases": 5},
                "python_dependency_resolution": {"failed": 0, "passed": 27, "total_cases": 27},
                "python_test_failure": {"failed": 0, "passed": 9, "total_cases": 9},
                "ruby_bundle_failure": {"failed": 0, "passed": 8, "total_cases": 8},
                "rust_test_failure": {"failed": 0, "passed": 10, "total_cases": 10},
                "security_scan_failure": {"failed": 0, "passed": 5, "total_cases": 5},
                "typescript_typecheck": {"failed": 0, "passed": 19, "total_cases": 19},
            },
        )
        actual_classes = {case["actual_failure_class"] for case in payload["cases"]}
        self.assertEqual(
            actual_classes,
            {
                "browser_test_failure",
                "dotnet_build_failure",
                "docker_build_failure",
                "github_actions_workflow",
                "go_test_failure",
                "java_build_failure",
                "javascript_lint",
                "node_dependency_install",
                "php_composer_failure",
                "python_dependency_resolution",
                "python_test_failure",
                "ruby_bundle_failure",
                "rust_test_failure",
                "security_scan_failure",
                "typescript_typecheck",
            },
        )
        self.assertEqual(payload["requirements"]["network_required"], False)

    def test_ci_benchmark_summary_only_omits_case_details(self) -> None:
        json_proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "ci",
                "benchmark",
                "examples/ci-triage",
                "--format",
                "json",
                "--summary-only",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(json_proc.returncode, 0, json_proc.stderr)
        payload = json.loads(json_proc.stdout)
        self.assertEqual(payload["schema_version"], "patchrail.ci_benchmark.v1")
        self.assertEqual(payload["total_cases"], 153)
        self.assertEqual(payload["passed"], 153)
        self.assertEqual(payload["failed"], 0)
        self.assertEqual(payload["accuracy"]["top_1"], 1.0)
        self.assertEqual(payload["coverage_gate"]["passed"], True)
        self.assertIn("class_summary", payload)
        self.assertIn("coverage_gate", payload)
        self.assertNotIn("cases", payload)

        markdown_proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "ci",
                "benchmark",
                "examples/ci-triage",
                "--format",
                "markdown",
                "--summary-only",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(markdown_proc.returncode, 0, markdown_proc.stderr)
        self.assertIn("# PatchRail CI Benchmark", markdown_proc.stdout)
        self.assertIn("- Total cases: `153`", markdown_proc.stdout)
        self.assertIn("- Coverage gate passed: `True`", markdown_proc.stdout)
        self.assertIn("## Class summary", markdown_proc.stdout)
        self.assertNotIn("## Cases", markdown_proc.stdout)

    def test_ci_benchmark_coverage_gate_can_require_depth_per_class(self) -> None:
        pass_proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "ci",
                "benchmark",
                "examples/ci-triage",
                "--format",
                "json",
                "--summary-only",
                "--min-cases-per-class",
                "5",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(pass_proc.returncode, 0, pass_proc.stderr)
        pass_payload = json.loads(pass_proc.stdout)
        self.assertEqual(pass_payload["coverage_gate"]["min_cases_per_class"], 5)
        self.assertEqual(pass_payload["coverage_gate"]["passed"], True)
        self.assertEqual(pass_payload["coverage_gate"]["failures"], [])

        fail_proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "ci",
                "benchmark",
                "examples/ci-triage",
                "--format",
                "json",
                "--summary-only",
                "--min-cases-per-class",
                "6",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(fail_proc.returncode, 1)
        fail_payload = json.loads(fail_proc.stdout)
        self.assertEqual(fail_payload["failed"], 0)
        self.assertEqual(fail_payload["coverage_gate"]["passed"], False)
        failing_classes = {
            failure["failure_class"]: failure
            for failure in fail_payload["coverage_gate"]["failures"]
        }
        self.assertEqual(failing_classes["browser_test_failure"]["total_cases"], 5)
        self.assertEqual(failing_classes["browser_test_failure"]["minimum_cases"], 6)

    def test_ci_benchmark_rejects_negative_coverage_gate(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "ci",
                "benchmark",
                "examples/ci-triage",
                "--min-cases-per-class",
                "-1",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 2)
        self.assertIn("--min-cases-per-class must be >= 0", proc.stderr)

    def test_ci_fixture_check_accepts_clean_fixture_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log = root / "python-test.log"
            log.write_text(
                "python -m pytest -q\nFAILED tests/test_app.py::test_ok - AssertionError\n",
                encoding="utf-8",
            )
            log.with_suffix(".expected.json").write_text(
                json.dumps({"failure_class": "python_test_failure", "minimum_confidence": 0.7}),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "fixture-check",
                    str(root),
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["schema_version"], "patchrail.ci_fixture_check.v1")
            self.assertEqual(payload["total_cases"], 1)
            self.assertEqual(payload["passed"], 1)
            self.assertEqual(payload["failed"], 0)
            self.assertEqual(payload["requirements"]["network_required"], False)
            self.assertEqual(payload["requirements"]["github_write_permission_required"], False)

    def test_ci_classify_detects_docker_build_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "docker.log"
            log.write_text(
                "docker buildx build --target runtime .\n"
                'ERROR: failed to solve: target stage "runtime" could not be found\n',
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, "-m", "patchrail", "ci", "classify", "--log", str(log)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failure_class"], "docker_build_failure")
            self.assertIn("docker build", payload["reproduction_command"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_detects_cmake_build_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "CMake Error at CMakeLists.txt:42 (find_package)\n"
                "ninja: build stopped: subcommand failed.\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "cpp_build_failure")
            self.assertIn("cmake --build", payload["reproduction_command"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_detects_gcc_link_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "app.o: in function `main': undefined reference to `foo::bar()'\n"
                "collect2: error: ld returned 1 exit status\n"
                "make: *** [app] Error 1\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "cpp_build_failure")

    def test_ci_classify_detects_clang_compile_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "src/widget.cpp:18:5: error: use of undeclared identifier 'widget'\n"
                "clang++: error: unable to execute command: linker command failed\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "cpp_build_failure")

    def test_ci_classify_cpp_header_failure_wins_over_docker_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "src/widget.cpp:3:10: fatal error: widget.h: No such file or directory\n"
                "make: *** [obj/widget.o] Error 1\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "classify", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["failure_class"], "cpp_build_failure")

    def test_ci_classify_detects_browser_test_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "playwright.log"
            log.write_text(
                "npx playwright test\n"
                "Error: browserType.launch: Executable doesn't exist at <cache>/chromium/chrome\n"
                "Please run npx playwright install\n",
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, "-m", "patchrail", "ci", "classify", "--log", str(log)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failure_class"], "browser_test_failure")
            self.assertIn("playwright", payload["reproduction_command"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_detects_java_build_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "java.log"
            log.write_text(
                "Run mvn -B test\n"
                "[ERROR] COMPILATION ERROR :\n"
                "[ERROR] cannot find symbol\n"
                "[ERROR] Failed to execute goal org.apache.maven.plugins:maven-compiler-plugin\n",
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, "-m", "patchrail", "ci", "classify", "--log", str(log)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failure_class"], "java_build_failure")
            self.assertIn("gradlew", payload["reproduction_command"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_detects_dotnet_build_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "dotnet.log"
            log.write_text(
                "Run dotnet restore src/App/App.csproj\n"
                "error NU1107: Version conflict detected for Microsoft.Extensions.Logging.\n"
                "Install/reference Microsoft.Extensions.Logging 8.0.0 directly to project.\n",
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, "-m", "patchrail", "ci", "classify", "--log", str(log)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failure_class"], "dotnet_build_failure")
            self.assertIn("dotnet restore", payload["reproduction_command"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_detects_ruby_bundle_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "ruby.log"
            log.write_text(
                "Run bundle install\n"
                'Bundler could not find compatible versions for gem "rack":\n'
                "  In Gemfile:\n"
                "    rails was resolved to 7.1.0, which depends on rack (~> 2.2)\n",
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, "-m", "patchrail", "ci", "classify", "--log", str(log)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failure_class"], "ruby_bundle_failure")
            self.assertIn("bundle install", payload["reproduction_command"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_classify_detects_php_composer_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "php.log"
            log.write_text(
                "Run composer install --no-interaction --prefer-dist\n"
                "Your requirements could not be resolved to an installable set of packages.\n"
                "Problem 1\n"
                "Root composer.json requires php ^8.3 but your php version (8.2.14) does not satisfy that requirement.\n",
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, "-m", "patchrail", "ci", "classify", "--log", str(log)],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failure_class"], "php_composer_failure")
            self.assertIn("composer install", payload["reproduction_command"])
            self.assertEqual(payload["requirements"]["external_model_required"], False)

    def test_ci_fixture_check_fails_for_missing_expected_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log = root / "missing-metadata.log"
            log.write_text("cargo test\nthread 'demo' panicked\n", encoding="utf-8")

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "fixture-check",
                    str(root),
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 1)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failed"], 1)
            self.assertIn("missing neighboring .expected.json file", payload["cases"][0]["issues"])

    def test_ci_fixture_check_fails_for_unredacted_sensitive_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log = root / "unredacted.log"
            log.write_text(
                "python -m pytest -q\n"
                "FAILED tests/test_app.py::test_ok - AssertionError\n"
                "Contact maintainer@example.com\n"
                "Path /Users/example/project\n",
                encoding="utf-8",
            )
            log.with_suffix(".expected.json").write_text(
                json.dumps({"failure_class": "python_test_failure", "minimum_confidence": 0.7}),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "fixture-check",
                    str(root),
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 1)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failed"], 1)
            self.assertIn("email", payload["cases"][0]["redactions"])
            self.assertIn("mac_home_path", payload["cases"][0]["redactions"])
            self.assertIn("possible unredacted sensitive data", payload["cases"][0]["issues"][0])

    def test_ci_fixture_check_flags_registry_tokens_and_windows_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log = root / "unredacted-windows.log"
            log.write_text(
                "npm audit\n"
                "1 critical severity vulnerability\n"
                "npm token npm_1234567890abcdefghijklmnopqrst\n"
                "Path C:\\Users\\runner\\work\\repo\n",
                encoding="utf-8",
            )
            log.with_suffix(".expected.json").write_text(
                json.dumps({"failure_class": "security_scan_failure", "minimum_confidence": 0.5}),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "fixture-check",
                    str(root),
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 1)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["failed"], 1)
            self.assertIn("npm_token", payload["cases"][0]["redactions"])
            self.assertIn("windows_home_path", payload["cases"][0]["redactions"])
            self.assertTrue(
                any(
                    "possible unredacted sensitive data" in issue
                    for issue in payload["cases"][0]["issues"]
                )
            )

    def test_ci_explain_defaults_to_markdown_and_states_safety_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "python -m pip install -r requirements.txt\n"
                "ERROR: Could not find a version that satisfies the requirement demo==99\n"
                "ResolutionImpossible\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "explain", "--log", str(log)])

            markdown = stdout.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("# PatchRail CI Report", markdown)
            self.assertIn("python_dependency_resolution", markdown)
            self.assertIn("did not create a pull request", markdown)
            self.assertIn("send data to an external service", markdown)

    def test_module_entrypoint_runs_public_cli(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "patchrail", "ci", "classify"],
            input="cargo test\nthread 'demo' panicked\n",
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["failure_class"], "rust_test_failure")
        self.assertEqual(
            payload["guide_url"],
            "https://getpatchrail.com/fix/rust-test-failure"
            "?utm_source=cli&utm_campaign=rust-test-failure",
        )
        self.assertEqual(
            payload["pack_url"],
            "https://patchrail.gumroad.com/l/ci-failure-triage"
            "?utm_source=cli&utm_campaign=rust-test-failure",
        )

    def test_ci_explain_redacts_secret_values_from_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            fake_github_token = "ghp_" + "abcdefghijklmnopqrstuvwxyz123456"
            log.write_text(
                "python -m pytest -q\n"
                "FAILED tests/test_app.py::test_ok - AssertionError\n"
                f"GITHUB_TOKEN={fake_github_token}\n"
                "Contact maintainer@example.com\n"
                "Path /Users/example/project\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "explain", "--redact", "--log", str(log)])

            markdown = stdout.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("## Redaction", markdown)
            self.assertIn("env_secret_assignment", markdown)
            self.assertIn("email", markdown)
            self.assertIn("mac_home_path", markdown)
            self.assertNotIn(fake_github_token, markdown)
            self.assertNotIn("maintainer@example.com", markdown)
            self.assertNotIn("/Users/example", markdown)

    def test_ci_pilot_pack_generates_local_redacted_consent_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log = root / "failed-ci.log"
            out_dir = root / "pilot-pack"
            fake_github_token = "ghp_" + "abcdefghijklmnopqrstuvwxyz123456"
            log.write_text(
                "python -m pip install -r requirements.txt\n"
                "ERROR: Could not find a version that satisfies the requirement demo==99\n"
                "ResolutionImpossible\n"
                f"GITHUB_TOKEN={fake_github_token}\n"
                "Contact maintainer@example.com\n"
                "Path /Users/example/project\n",
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-pack",
                    "--log",
                    str(log),
                    "--out-dir",
                    str(out_dir),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            summary = json.loads(proc.stdout)
            self.assertEqual(summary["schema_version"], "patchrail.ci_pilot_pack_result.v1")
            self.assertEqual(summary["requirements"]["network_required"], False)
            self.assertEqual(summary["requirements"]["github_write_permission_required"], False)
            self.assertIn("open_pull_request", summary["blocked_actions"])
            self.assertIn("contact_maintainer", summary["blocked_actions"])

            manifest = json.loads((out_dir / "pilot-manifest.json").read_text(encoding="utf-8"))
            result = json.loads((out_dir / "patchrail-result.json").read_text(encoding="utf-8"))
            redacted_log = (out_dir / "failed-ci.redacted.log").read_text(encoding="utf-8")
            report = (out_dir / "patchrail-report.md").read_text(encoding="utf-8")
            readme = (out_dir / "README.md").read_text(encoding="utf-8")

            self.assertEqual(manifest["schema_version"], "patchrail.ci_pilot_pack.v1")
            self.assertEqual(manifest["source"]["source_log_name"], "failed-ci.log")
            self.assertEqual(manifest["source"]["raw_log_copied"], False)
            self.assertEqual(
                manifest["classification"]["failure_class"], "python_dependency_resolution"
            )
            self.assertEqual(result["failure_class"], "python_dependency_resolution")
            self.assertEqual(
                result["guide_url"],
                "https://getpatchrail.com/fix/python-dependency-resolution"
                "?utm_source=cli&utm_campaign=python-dependency-resolution",
            )
            self.assertEqual(
                result["pack_url"],
                "https://patchrail.gumroad.com/l/ci-failure-triage"
                "?utm_source=cli&utm_campaign=python-dependency-resolution",
            )
            self.assertEqual(
                result["action_url"],
                "https://github.com/patchrail/ci-triage-action"
                "?utm_source=cli&utm_campaign=python-dependency-resolution",
            )
            self.assertEqual(
                manifest["consent_boundary"]["maintainer_review_required_before_sharing"], True
            )
            self.assertEqual(
                manifest["consent_boundary"]["repository_write_access_required"], False
            )
            self.assertEqual(manifest["requirements"]["external_model_required"], False)

            serialized = "\n".join([redacted_log, report, readme, json.dumps(manifest)])
            self.assertIn("python_dependency_resolution", serialized)
            self.assertIn("PatchRail did not copy the raw log", readme)
            self.assertIn("Share only after a maintainer reviews", readme)
            self.assertNotIn(fake_github_token, serialized)
            self.assertNotIn("maintainer@example.com", serialized)
            self.assertNotIn("/Users/example", serialized)
            self.assertIn("GITHUB_TOKEN=<redacted>", redacted_log)
            self.assertIn("<email>", redacted_log)
            self.assertIn("/Users/<user>/project", redacted_log)

    def test_ci_pilot_summary_defaults_to_private_repository_mention(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log = root / "failed-ci.log"
            out_dir = root / "pilot-pack"
            log.write_text(
                "python -m pip install -r requirements.txt\n"
                "ERROR: Could not find a version that satisfies the requirement demo==99\n"
                "ResolutionImpossible\n",
                encoding="utf-8",
            )
            pack_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-pack",
                    "--log",
                    str(log),
                    "--out-dir",
                    str(out_dir),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(pack_proc.returncode, 0, pack_proc.stderr)

            summary_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-summary",
                    "--pack",
                    str(out_dir),
                    "--repository",
                    "private-owner/private-repo",
                    "--ci-provider",
                    "GitHub Actions",
                    "--toolchain",
                    "Python",
                    "--classification-correct",
                    "yes",
                    "--maintainer-action-useful",
                    "yes",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(summary_proc.returncode, 0, summary_proc.stderr)
            self.assertIn("# PatchRail Consent-Only Pilot Summary", summary_proc.stdout)
            self.assertIn("Repository approved for public mention: `false`", summary_proc.stdout)
            self.assertIn("Repository: `not approved for public listing`", summary_proc.stdout)
            self.assertIn("Root cause: `python_dependency_resolution`", summary_proc.stdout)
            self.assertIn("Classification correct: `yes`", summary_proc.stdout)
            self.assertIn("Suggested maintainer action useful: `yes`", summary_proc.stdout)
            self.assertIn("PatchRail ran locally", summary_proc.stdout)
            self.assertIn("did not copy the raw log", summary_proc.stdout)
            self.assertNotIn("private-owner/private-repo", summary_proc.stdout)

    def test_ci_pilot_summary_json_includes_repository_only_when_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log = root / "failed-ci.log"
            out_dir = root / "pilot-pack"
            log.write_text(
                "cargo test\nthread 'tests::demo' panicked at src/lib.rs:7\n",
                encoding="utf-8",
            )
            pack_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-pack",
                    "--log",
                    str(log),
                    "--out-dir",
                    str(out_dir),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(pack_proc.returncode, 0, pack_proc.stderr)

            summary_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-summary",
                    "--pack",
                    str(out_dir / "pilot-manifest.json"),
                    "--repository",
                    "patchrail/example",
                    "--repository-mention-approved",
                    "yes",
                    "--ci-provider",
                    "GitHub Actions",
                    "--toolchain",
                    "Rust",
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(summary_proc.returncode, 0, summary_proc.stderr)
            payload = json.loads(summary_proc.stdout)
            self.assertEqual(payload["schema_version"], "patchrail.ci_pilot_summary.v1")
            self.assertEqual(payload["pilot_pack"]["manifest_path"], "pilot-manifest.json")
            self.assertEqual(payload["public_listing"]["repository_mention_approved"], True)
            self.assertEqual(payload["public_listing"]["repository"], "patchrail/example")
            self.assertEqual(payload["pilot_context"]["ci_provider"], "GitHub Actions")
            self.assertEqual(payload["pilot_context"]["toolchain"], "Rust")
            self.assertEqual(payload["classification"]["failure_class"], "rust_test_failure")
            self.assertEqual(payload["pilot_pack"]["raw_log_copied"], False)
            self.assertEqual(payload["requirements"]["network_required"], False)
            self.assertIn("open_pull_request", payload["blocked_actions"])
            self.assertNotIn("/Volumes/", summary_proc.stdout)
            self.assertNotIn("/Users/", summary_proc.stdout)
            self.assertNotIn("/home/", summary_proc.stdout)

    def test_ci_pilot_metrics_aggregates_public_and_private_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            first_log = root / "first.log"
            first_pack = root / "first-pack"
            first_summary = root / "first-summary.json"
            first_log.write_text(
                "python -m pytest -q\nFAILED tests/test_app.py::test_ok - AssertionError\n",
                encoding="utf-8",
            )
            first_pack_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-pack",
                    "--log",
                    str(first_log),
                    "--out-dir",
                    str(first_pack),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(first_pack_proc.returncode, 0, first_pack_proc.stderr)
            first_summary_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-summary",
                    "--pack",
                    str(first_pack),
                    "--classification-correct",
                    "yes",
                    "--maintainer-action-useful",
                    "yes",
                    "--format",
                    "json",
                    "--out",
                    str(first_summary),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(first_summary_proc.returncode, 0, first_summary_proc.stderr)

            second_log = root / "second.log"
            second_pack = root / "second-pack"
            second_summary = root / "second-summary.json"
            second_log.write_text(
                "cargo test\nthread 'tests::demo' panicked at src/lib.rs:7\n",
                encoding="utf-8",
            )
            second_pack_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-pack",
                    "--log",
                    str(second_log),
                    "--out-dir",
                    str(second_pack),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(second_pack_proc.returncode, 0, second_pack_proc.stderr)
            second_summary_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-summary",
                    "--pack",
                    str(second_pack),
                    "--repository",
                    "patchrail/example",
                    "--repository-mention-approved",
                    "yes",
                    "--classification-correct",
                    "no",
                    "--maintainer-action-useful",
                    "unknown",
                    "--format",
                    "json",
                    "--out",
                    str(second_summary),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(second_summary_proc.returncode, 0, second_summary_proc.stderr)

            metrics_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-metrics",
                    str(first_summary),
                    str(second_summary),
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(metrics_proc.returncode, 0, metrics_proc.stderr)
            payload = json.loads(metrics_proc.stdout)
            self.assertEqual(payload["schema_version"], "patchrail.ci_pilot_metrics.v1")
            self.assertEqual(payload["total_pilot_summaries"], 2)
            self.assertEqual(payload["public_repository_mentions"], 1)
            self.assertEqual(payload["private_or_unapproved_repository_mentions"], 1)
            self.assertEqual(payload["public_repositories"], ["patchrail/example"])
            self.assertEqual(payload["owned_repository_mentions"], 1)
            self.assertEqual(payload["external_repository_mentions"], 0)
            self.assertEqual(payload["owned_repositories"], ["patchrail/example"])
            self.assertEqual(payload["external_repositories"], [])
            self.assertEqual(payload["evidence_readiness"]["status"], "owned_repo_evidence_only")
            self.assertEqual(payload["evidence_readiness"]["external_adopters_countable"], 0)
            self.assertEqual(payload["evidence_readiness"]["owned_repo_evidence_countable"], 1)
            self.assertEqual(payload["evidence_readiness"]["private_feedback_count"], 1)
            self.assertEqual(payload["classification_correct"]["yes"], 1)
            self.assertEqual(payload["classification_correct"]["no"], 1)
            self.assertEqual(payload["maintainer_action_useful"]["yes"], 1)
            self.assertEqual(payload["maintainer_action_useful"]["unknown"], 1)
            self.assertEqual(payload["local_only_and_no_raw_log"], 2)
            self.assertEqual(payload["requirements"]["network_required"], False)

            markdown_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "pilot-metrics",
                    str(first_summary),
                    str(second_summary),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(markdown_proc.returncode, 0, markdown_proc.stderr)
            self.assertIn("# PatchRail Consent-Only Pilot Metrics", markdown_proc.stdout)
            self.assertIn("- Public repository mentions: `1`", markdown_proc.stdout)
            self.assertIn("- Owned-repo public mentions: `1`", markdown_proc.stdout)
            self.assertIn("- External public repository mentions: `0`", markdown_proc.stdout)
            self.assertIn("- Evidence readiness: `owned_repo_evidence_only`", markdown_proc.stdout)
            self.assertIn("- Countable external adopters: `0`", markdown_proc.stdout)
            self.assertIn("- `patchrail/example`", markdown_proc.stdout)
            self.assertIn("- None approved for external adopter listing.", markdown_proc.stdout)

    def test_redact_command_emits_redacted_text(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "patchrail", "redact"],
            input=(
                "TOKEN=secret-value\n"
                "Contact maintainer@example.com\n"
                "Path /home/runner/work\n"
                "Windows path C:\\Users\\runner\\work\\repo\n"
                "GitLab token glpat-1234567890abcdefghijkl\n"
                "PyPI token pypi-AgEIcHlwaS5vcmcCdGVzdC12YWx1ZQ\n"
                "npm token npm_1234567890abcdefghijklmnopqrst\n"
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("TOKEN=<redacted>", proc.stdout)
        self.assertIn("<email>", proc.stdout)
        self.assertIn("/home/<user>/work", proc.stdout)
        self.assertIn("C:/Users/<user>\\work\\repo", proc.stdout)
        self.assertIn("<gitlab-token>", proc.stdout)
        self.assertIn("<pypi-token>", proc.stdout)
        self.assertIn("<npm-token>", proc.stdout)
        self.assertNotIn("secret-value", proc.stdout)
        self.assertNotIn("maintainer@example.com", proc.stdout)
        self.assertNotIn("glpat-1234567890abcdefghijkl", proc.stdout)
        self.assertNotIn("pypi-AgEIcHlwaS5vcmcCdGVzdC12YWx1ZQ", proc.stdout)
        self.assertNotIn("npm_1234567890abcdefghijklmnopqrst", proc.stdout)

    def test_redact_command_handles_cloud_and_key_material(self) -> None:
        fake_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.s5b3Qd7n0pXcVm9wQ1aZ2k4L8tR6yU0o"
        fake_google_key = "AIza" + "b" * 35
        # Build at runtime so the recognizable token prefix never appears verbatim in source.
        fake_slack_token = "xox" + "b-123456789012-abcdefghijklmnop"
        private_key = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIBVAIBADANBgkqhkiG9w0BAQEFAASCAT4wggE6AgEAAkEA\n"
            "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKL\n"
            "-----END RSA PRIVATE KEY-----"
        )
        proc = subprocess.run(
            [sys.executable, "-m", "patchrail", "redact"],
            input=(
                f"Slack token {fake_slack_token}\n"
                f"Google key {fake_google_key}\n"
                "Google oauth ya29.A0ARrdaM-abcdefghijklmnopqrstuvwxyz0123\n"
                "HuggingFace hf_abcdefghijklmnopqrstuvwxyz0123\n"
                f"Auth header Authorization: Bearer {fake_jwt}\n"
                f"{private_key}\n"
            ),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("<slack-token>", proc.stdout)
        self.assertIn("<google-api-key>", proc.stdout)
        self.assertIn("<google-oauth-token>", proc.stdout)
        self.assertIn("<huggingface-token>", proc.stdout)
        self.assertIn("<jwt>", proc.stdout)
        self.assertIn("<private-key>", proc.stdout)
        self.assertNotIn(fake_slack_token, proc.stdout)
        self.assertNotIn(fake_google_key, proc.stdout)
        self.assertNotIn("ya29.A0ARrdaM", proc.stdout)
        self.assertNotIn("hf_abcdefghijklmnopqrstuvwxyz0123", proc.stdout)
        self.assertNotIn(fake_jwt, proc.stdout)
        self.assertNotIn("MIIBVAIBADANBgkqhkiG", proc.stdout)
        self.assertNotIn("BEGIN RSA PRIVATE KEY", proc.stdout)

    def test_unknown_log_is_not_repairable(self) -> None:
        result = json.loads(
            subprocess.run(
                [sys.executable, "-m", "patchrail", "ci", "classify"],
                input="build did not work\n",
                text=True,
                capture_output=True,
                check=True,
            ).stdout
        )

        self.assertEqual(result["failure_class"], "unknown")
        self.assertLess(result["confidence"], 0.5)
        self.assertIn("Do not auto-repair", result["minimal_repair_strategy"])
        self.assertEqual(result["guide_url"], "https://getpatchrail.com/fix?utm_source=cli")
        self.assertEqual(
            result["pack_url"],
            "https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=cli&utm_campaign=index",
        )
        self.assertEqual(
            result["sample_url"],
            "https://patchrail.gumroad.com/l/iwycg?utm_source=cli&utm_campaign=index",
        )
        self.assertEqual(
            result["action_url"],
            "https://github.com/patchrail/ci-triage-action?utm_source=cli&utm_campaign=index",
        )

    def test_ci_explain_prints_fix_guide_url_for_known_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log = Path(tmpdir) / "failed.log"
            log.write_text(
                "python -m pytest -q\nFAILED tests/test_app.py::test_ok - AssertionError\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["ci", "explain", "--log", str(log)])

            self.assertEqual(exit_code, 0)
            self.assertIn(
                "Guide: https://getpatchrail.com/fix/python-test-failure"
                "?utm_source=cli&utm_campaign=python-test-failure",
                stdout.getvalue(),
            )
            self.assertIn(
                "Pack: https://patchrail.gumroad.com/l/ci-failure-triage"
                "?utm_source=cli&utm_campaign=python-test-failure",
                stdout.getvalue(),
            )
            self.assertIn(
                "Free sample: https://patchrail.gumroad.com/l/iwycg"
                "?utm_source=cli&utm_campaign=python-test-failure",
                stdout.getvalue(),
            )
            self.assertIn(
                "Action: https://github.com/patchrail/ci-triage-action"
                "?utm_source=cli&utm_campaign=python-test-failure",
                stdout.getvalue(),
            )

    def test_ci_explain_links_index_for_unknown_class(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "patchrail", "ci", "explain"],
            input="build did not work\n",
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertIn("Guide: https://getpatchrail.com/fix?utm_source=cli", result.stdout)
        self.assertIn(
            "Pack: https://patchrail.gumroad.com/l/ci-failure-triage"
            "?utm_source=cli&utm_campaign=index",
            result.stdout,
        )
        self.assertIn(
            "Free sample: https://patchrail.gumroad.com/l/iwycg?utm_source=cli&utm_campaign=index",
            result.stdout,
        )
        self.assertIn(
            "Action: https://github.com/patchrail/ci-triage-action?utm_source=cli&utm_campaign=index",
            result.stdout,
        )
        self.assertNotIn("/fix/", result.stdout)

    def test_ci_share_links_emits_measurable_owned_surface_packet(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "ci",
                "share-links",
                "--failure-class",
                "python_test_failure",
                "--format",
                "json",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], "patchrail.ci_share_links.v1")
        self.assertEqual(payload["failure_class"], "python_test_failure")
        self.assertEqual(payload["failure_slug"], "python-test-failure")
        self.assertEqual(payload["measurement"]["utm_source"], "cli")
        self.assertEqual(payload["measurement"]["utm_campaign"], "python-test-failure")
        self.assertEqual(payload["measurement"]["revenue_surface"], "SKU #1 CI Triage $19")
        self.assertEqual(
            payload["links"]["fix_guide"],
            "https://getpatchrail.com/fix/python-test-failure"
            "?utm_source=cli&utm_campaign=python-test-failure",
        )
        self.assertEqual(
            payload["links"]["free_sample"],
            "https://patchrail.gumroad.com/l/iwycg?utm_source=cli&utm_campaign=python-test-failure",
        )
        self.assertEqual(
            payload["links"]["field_guide_pack"],
            "https://patchrail.gumroad.com/l/ci-failure-triage"
            "?utm_source=cli&utm_campaign=python-test-failure",
        )
        self.assertEqual(
            payload["links"]["github_action"],
            "https://github.com/patchrail/ci-triage-action"
            "?utm_source=cli&utm_campaign=python-test-failure",
        )
        self.assertTrue(payload["safety"]["local_only"])
        self.assertFalse(payload["safety"]["counts_as_external_adoption"])
        self.assertFalse(payload["safety"]["network_required"])

    def test_ci_share_links_classifies_stdin_when_failure_class_is_omitted(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "patchrail", "ci", "share-links", "--format", "text"],
            input="python -m pytest -q\nFAILED tests/test_app.py::test_ok - AssertionError\n",
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("failure_class: python_test_failure\n", result.stdout)
        self.assertIn(
            "free_sample: https://patchrail.gumroad.com/l/iwycg"
            "?utm_source=cli&utm_campaign=python-test-failure\n",
            result.stdout,
        )
        self.assertIn("counts_as_external_adoption: false\n", result.stdout)
        self.assertIn("network_required: false\n", result.stdout)

    def test_ci_share_links_accepts_owned_surface_attribution(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "ci",
                "share-links",
                "--failure-class",
                "python_test_failure",
                "--utm-source",
                "github release",
                "--utm-campaign",
                "ci sample v0.1.1",
                "--format",
                "json",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["measurement"]["utm_source"], "github release")
        self.assertEqual(payload["measurement"]["utm_campaign"], "ci sample v0.1.1")
        self.assertEqual(
            payload["links"]["fix_guide"],
            "https://getpatchrail.com/fix/python-test-failure"
            "?utm_source=github%20release&utm_campaign=ci%20sample%20v0.1.1",
        )
        self.assertEqual(
            payload["links"]["field_guide_pack"],
            "https://patchrail.gumroad.com/l/ci-failure-triage"
            "?utm_source=github%20release&utm_campaign=ci%20sample%20v0.1.1",
        )
        self.assertIn(
            "github%20release",
            payload["share_packet"]["bullets"][0],
        )

    def test_ci_share_links_can_size_an_organic_channel_packet(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "ci",
                "share-links",
                "--failure-class",
                "python_test_failure",
                "--channel",
                "show-hn",
                "--traffic-delivered",
                "2",
                "--format",
                "json",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["measurement"]["utm_source"], "show-hn")
        self.assertEqual(
            payload["measurement"]["utm_campaign"],
            "sku1-organic-distribution-show-hn",
        )
        self.assertEqual(payload["measurement"]["distribution_channel"], "show-hn")
        self.assertEqual(payload["measurement"]["estimated_visits"], 120)
        self.assertEqual(payload["measurement"]["traffic_target"], 300)
        self.assertEqual(payload["measurement"]["traffic_delivered"], 2)
        self.assertEqual(payload["measurement"]["traffic_gap_before"], 298)
        self.assertEqual(payload["measurement"]["traffic_gap_after"], 178)
        self.assertEqual(payload["measurement"]["estimated_gap_closed"], 120)
        self.assertFalse(payload["measurement"]["traffic_target_reached"])
        self.assertEqual(
            payload["measurement"]["next_measurement_step"],
            "ship_next_distribution_channel_or_guarded_paid_boost",
        )
        self.assertTrue(payload["publication_handoff"]["required"])
        self.assertFalse(payload["publication_handoff"]["copy_file_ready"])
        self.assertIn(
            "--copy-file <copywriter-approved-copy-file>",
            payload["publication_handoff"]["commands"]["claim_command"],
        )
        self.assertEqual(
            payload["links"]["free_sample"],
            "https://patchrail.gumroad.com/l/iwycg"
            "?utm_source=show-hn&utm_campaign=sku1-organic-distribution-show-hn",
        )
        self.assertFalse(payload["safety"]["counts_as_external_adoption"])

    def test_ci_share_links_writes_local_distribution_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            receipt = Path(tmpdir) / "receipts" / "show-hn-python-test.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "share-links",
                    "--failure-class",
                    "python_test_failure",
                    "--channel",
                    "show-hn",
                    "--traffic-delivered",
                    "2",
                    "--receipt-out",
                    str(receipt),
                    "--format",
                    "text",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("distribution_channel: show-hn\n", result.stdout)
        self.assertEqual(receipt_payload["schema_version"], "patchrail.ci_share_links.v1")
        self.assertEqual(receipt_payload["measurement"]["distribution_channel"], "show-hn")
        self.assertEqual(receipt_payload["measurement"]["traffic_delivered"], 2)
        self.assertEqual(receipt_payload["measurement"]["traffic_gap_after"], 178)
        self.assertTrue(receipt_payload["safety"]["local_only"])
        self.assertFalse(receipt_payload["safety"]["network_required"])

    def test_ci_share_links_writes_facts_only_social_copy_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            brief = Path(tmpdir) / "requests" / "show-hn-python-test.json"
            copy_file = Path(tmpdir) / "posts" / "show-hn-approved.md"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "share-links",
                    "--failure-class",
                    "python_test_failure",
                    "--channel",
                    "show-hn",
                    "--traffic-delivered",
                    "2",
                    "--copy-brief-out",
                    str(brief),
                    "--copy-file",
                    str(copy_file),
                    "--brief-urgency",
                    "high",
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            payload = json.loads(result.stdout)
            brief_payload = json.loads(brief.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["copy_brief_write"]["status"], "written")
        self.assertEqual(payload["copy_brief_write"]["path"], str(brief))
        self.assertEqual(payload["copy_brief_write"]["prohibited_fields_present"], [])
        self.assertTrue(payload["publication_handoff"]["required"])
        self.assertTrue(payload["publication_handoff"]["copy_file_ready"])
        self.assertEqual(payload["publication_handoff"]["copy_file"], str(copy_file))
        self.assertIn(
            f"claim --channel show-hn --copy-file {copy_file}",
            payload["publication_handoff"]["commands"]["claim_command"],
        )
        self.assertIn(
            "record --channel show-hn --url <submission_url>",
            payload["publication_handoff"]["commands"]["record_command"],
        )
        self.assertEqual(brief_payload["type"], "social_post")
        self.assertEqual(brief_payload["channel"], "show-hn")
        self.assertEqual(brief_payload["lead"], "SKU #1 CI Triage $19")
        self.assertEqual(brief_payload["urgency"], "high")
        self.assertEqual(brief_payload["copy_file"], str(copy_file))
        self.assertTrue(
            any(
                fact
                == (
                    "Channel URL with UTM: https://patchrail.gumroad.com/l/ci-failure-triage"
                    "?utm_source=show-hn&utm_campaign=sku1-organic-distribution-show-hn."
                )
                for fact in brief_payload["key_facts"]
            )
        )
        self.assertNotIn("body", brief_payload)
        self.assertNotIn("draft", brief_payload)
        self.assertNotIn("email_body", brief_payload)

    def test_ci_share_links_can_auto_name_social_copy_brief_in_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            requests_dir = Path(tmpdir) / "requests"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "share-links",
                    "--failure-class",
                    "python_test_failure",
                    "--channel",
                    "devto",
                    "--traffic-delivered",
                    "2",
                    "--copy-brief-dir",
                    str(requests_dir),
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            written_files = list(requests_dir.glob("*.json"))
            brief_payload = json.loads(written_files[0].read_text(encoding="utf-8"))
            payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(written_files), 1)
        self.assertRegex(
            written_files[0].name,
            r"^\d{8}T\d{6}Z-ci-share-links-devto-python-test-failure\.json$",
        )
        self.assertEqual(payload["copy_brief_write"]["status"], "written")
        self.assertTrue(payload["copy_brief_write"]["auto_named"])
        self.assertEqual(payload["copy_brief_write"]["directory"], str(requests_dir))
        self.assertEqual(payload["copy_brief_write"]["path"], str(written_files[0]))
        self.assertEqual(brief_payload["type"], "social_post")
        self.assertEqual(brief_payload["channel"], "devto")
        self.assertNotIn("body", brief_payload)
        self.assertNotIn("draft", brief_payload)
        self.assertNotIn("email_body", brief_payload)

    def test_ci_share_links_skips_copy_brief_when_channel_receipt_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            brief = Path(tmpdir) / "requests" / "show-hn-python-test.json"
            posted_dir = Path(tmpdir) / "posted"
            posted_dir.mkdir()
            receipt = posted_dir / "show-hn-20260701T071152Z.json"
            receipt.write_text(
                json.dumps(
                    {
                        "channel": "show-hn",
                        "status": "blocked",
                        "reason": "browser_extension_setup_required",
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "share-links",
                    "--failure-class",
                    "python_test_failure",
                    "--channel",
                    "show-hn",
                    "--traffic-delivered",
                    "2",
                    "--copy-brief-out",
                    str(brief),
                    "--posted-dir",
                    str(posted_dir),
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(brief.exists())
        self.assertEqual(payload["copy_brief_write"]["status"], "skipped")
        self.assertEqual(payload["copy_brief_write"]["reason"], "channel_receipt_exists")
        self.assertEqual(payload["copy_brief_write"]["channel"], "show-hn")
        self.assertEqual(payload["copy_brief_write"]["receipt_path"], str(receipt))
        self.assertEqual(payload["copy_brief_write"]["receipt_status"], "blocked")
        self.assertFalse(payload["publication_handoff"]["required"])
        self.assertEqual(payload["publication_handoff"]["reason"], "channel_receipt_exists")
        self.assertEqual(payload["publication_handoff"]["receipt_path"], str(receipt))
        self.assertEqual(payload["publication_handoff"]["receipt_status"], "blocked")

    def test_ci_share_links_copy_brief_dir_skips_when_channel_receipt_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            requests_dir = Path(tmpdir) / "requests"
            posted_dir = Path(tmpdir) / "posted"
            posted_dir.mkdir()
            receipt = posted_dir / "devto-20260701T071152Z.json"
            receipt.write_text(
                json.dumps(
                    {
                        "channel": "devto",
                        "status": "posted",
                        "url": "https://dev.to/patchrail/post",
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "patchrail",
                    "ci",
                    "share-links",
                    "--failure-class",
                    "python_test_failure",
                    "--channel",
                    "devto",
                    "--copy-brief-dir",
                    str(requests_dir),
                    "--posted-dir",
                    str(posted_dir),
                    "--format",
                    "json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(requests_dir.exists())
        self.assertEqual(payload["copy_brief_write"]["status"], "skipped")
        self.assertEqual(payload["copy_brief_write"]["reason"], "channel_receipt_exists")
        self.assertEqual(payload["copy_brief_write"]["channel"], "devto")
        self.assertEqual(payload["copy_brief_write"]["receipt_path"], str(receipt))
        self.assertEqual(payload["copy_brief_write"]["receipt_status"], "posted")

    def test_ci_share_links_reports_measurement_step_when_channel_completes_target(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "ci",
                "share-links",
                "--failure-class",
                "python_test_failure",
                "--channel",
                "show-hn",
                "--traffic-delivered",
                "250",
                "--format",
                "text",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("estimated_gap_closed: 50\n", result.stdout)
        self.assertIn("traffic_gap_after: 0\n", result.stdout)
        self.assertIn("next_measurement_step: measure_sales_before_pivot_decision\n", result.stdout)

    def test_ci_share_links_unknown_class_uses_index_campaign_not_dead_fix_page(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "ci",
                "share-links",
                "--failure-class",
                "pre_commit_hook_failure",
                "--format",
                "markdown",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# PatchRail CI Links: pre-commit-hook-failure", result.stdout)
        self.assertIn("- Fix guide: https://getpatchrail.com/fix?utm_source=cli", result.stdout)
        self.assertNotIn("/fix/pre-commit-hook-failure", result.stdout)
        self.assertIn("- UTM campaign: `index`", result.stdout)


class FixGuideSlugConsistencyTests(unittest.TestCase):
    """Guard the CLI -> getpatchrail.com/fix cross-sell funnel.

    Every slug the CLI advertises a dedicated guide for must correspond to a
    real classifier failure class. If a class is renamed in classify.py without
    updating the slug set, the CLI would emit a /fix/<slug> URL that 404s on the
    site (broken link + lost conversion). This locks that invariant.
    """

    @staticmethod
    def _classifier_slugs() -> set[str]:
        return {
            rule["failure_class"].replace("_", "-")
            for rule in RULES
            if rule["failure_class"] != "unknown"
        }

    def test_every_fix_guide_slug_maps_to_a_real_failure_class(self) -> None:
        orphan_slugs = _FIX_GUIDE_SLUGS - self._classifier_slugs()
        self.assertEqual(
            orphan_slugs,
            set(),
            f"_FIX_GUIDE_SLUGS advertises /fix pages for classes the classifier "
            f"never emits (would 404 / misattribute): {sorted(orphan_slugs)}",
        )

    def test_known_slug_round_trips_to_dedicated_guide_url(self) -> None:
        for slug in sorted(_FIX_GUIDE_SLUGS):
            failure_class = slug.replace("-", "_")
            url = _fix_guide_url(failure_class)
            self.assertEqual(
                url,
                f"https://getpatchrail.com/fix/{slug}?utm_source=cli&utm_campaign={slug}",
            )

    def test_class_without_guide_degrades_to_index_not_a_dead_link(self) -> None:
        # pre_commit_hook_failure is a recognized class with no published /fix
        # guide (the field guide ships 31 classes). It must degrade to the index,
        # never to a /fix/<slug> page that does not exist.
        ungraded = self._classifier_slugs() - _FIX_GUIDE_SLUGS
        for slug in ungraded:
            url = _fix_guide_url(slug.replace("-", "_"))
            self.assertEqual(url, "https://getpatchrail.com/fix?utm_source=cli")
            self.assertNotIn("/fix/", url)

    def test_pack_url_uses_failure_class_campaign_for_known_guides(self) -> None:
        for slug in sorted(_FIX_GUIDE_SLUGS):
            failure_class = slug.replace("-", "_")
            url = _ci_triage_pack_url(failure_class)
            self.assertEqual(
                url,
                "https://patchrail.gumroad.com/l/ci-failure-triage"
                f"?utm_source=cli&utm_campaign={slug}",
            )

    def test_pack_url_uses_index_campaign_for_unknown_or_unlisted_classes(self) -> None:
        self.assertEqual(
            _ci_triage_pack_url("unknown"),
            "https://patchrail.gumroad.com/l/ci-failure-triage?utm_source=cli&utm_campaign=index",
        )

    def test_sample_url_uses_failure_class_campaign_for_known_guides(self) -> None:
        for slug in sorted(_FIX_GUIDE_SLUGS):
            failure_class = slug.replace("-", "_")
            url = _ci_triage_sample_url(failure_class)
            self.assertEqual(
                url,
                f"https://patchrail.gumroad.com/l/iwycg?utm_source=cli&utm_campaign={slug}",
            )

    def test_sample_url_uses_index_campaign_for_unknown_or_unlisted_classes(self) -> None:
        self.assertEqual(
            _ci_triage_sample_url("unknown"),
            "https://patchrail.gumroad.com/l/iwycg?utm_source=cli&utm_campaign=index",
        )

    def test_action_url_uses_failure_class_campaign_for_known_guides(self) -> None:
        for slug in sorted(_FIX_GUIDE_SLUGS):
            failure_class = slug.replace("-", "_")
            url = _ci_triage_action_url(failure_class)
            self.assertEqual(
                url,
                f"https://github.com/patchrail/ci-triage-action?utm_source=cli&utm_campaign={slug}",
            )

    def test_action_url_uses_index_campaign_for_unknown_or_unlisted_classes(self) -> None:
        self.assertEqual(
            _ci_triage_action_url("unknown"),
            "https://github.com/patchrail/ci-triage-action?utm_source=cli&utm_campaign=index",
        )


if __name__ == "__main__":
    unittest.main()
