from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
CI_TRIAGE_LOG_PATH_RE = re.compile(r"examples/ci-triage/[A-Za-z0-9_.-]+\.log")
PIPX_INSTALL_COMMAND = "pipx install patchrail"
GITHUB_SOURCE_COMMAND = "uvx --from git+https://github.com/patchrail/patchrail patchrail"
GITHUB_RELEASE_WHEEL_URL = (
    "https://github.com/patchrail/patchrail/releases/download/v0.1.0/"
    "patchrail-0.1.0-py3-none-any.whl"
)


def _local_markdown_link_target(markdown_file: Path, raw_target: str) -> Path | None:
    target = raw_target.strip()
    if not target:
        return None

    target = target.split()[0].strip("<>")
    if (
        target.startswith("#")
        or target.startswith("http://")
        or target.startswith("https://")
        or target.startswith("mailto:")
        or "://" in target
    ):
        return None

    target = target.split("#", 1)[0].split("?", 1)[0]
    if not target:
        return None

    return (markdown_file.parent / target).resolve()


def _markdown_files_with_reviewer_facing_links() -> list[Path]:
    return [
        ROOT / "README.md",
        *sorted((ROOT / "docs").glob("*.md")),
        *sorted((ROOT / "examples").glob("*/README.md")),
        *sorted((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.md")),
        ROOT / ".github" / "pull_request_template.md",
    ]


def _line_context(lines: list[str], line_index: int) -> str:
    start = max(0, line_index - 1)
    end = min(len(lines), line_index + 2)
    return " ".join(line.strip().lower() for line in lines[start:end])


def test_ci_triage_workflow_is_read_only_and_human_reviewed() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci-triage.yml").read_text(encoding="utf-8")

    assert "contents: read" in workflow
    assert "actions: read" in workflow
    assert "issues: write" not in workflow
    assert "pull-requests: write" not in workflow
    assert "uv run patchrail ci explain --redact" in workflow
    assert "uv run patchrail ci classify --redact" in workflow
    assert "actions/upload-artifact@v7.0.1" in workflow
    assert "gh pr create" not in workflow
    assert "gh issue comment" not in workflow


def test_github_action_docs_preserve_safety_boundary() -> None:
    docs = (ROOT / "docs" / "github-action.md").read_text(encoding="utf-8")

    assert "does not comment on issues or pull requests" in docs
    assert "does not open pull requests" in docs
    assert "does not call external models" in docs
    assert "contents: read" in docs
    assert "actions: read" in docs
    assert "patchrail-ci-triage" in docs
    assert "examples/github-action" in docs
    assert "JavaScript Action Runtime Review" in docs
    assert "Reviewed on 2026-06-03" in docs
    assert "actions/checkout" in docs
    assert "`v6` | `node24` | No" in docs
    assert "actions/setup-python" in docs
    assert "astral-sh/setup-uv" in docs
    assert "`v8.1.0` | `node24` | No" in docs
    assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" in docs
    assert "read-only" in docs


def test_github_actions_runtime_review_keeps_workflows_node24_ready() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    triage = (ROOT / ".github" / "workflows" / "ci-triage.yml").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "github-action.md").read_text(encoding="utf-8")

    combined = "\n".join([ci, triage])
    assert 'FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"' in ci
    assert 'FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"' in triage
    assert "actions/checkout@v6" in combined
    assert "actions/setup-python@v6" in combined
    assert "astral-sh/setup-uv@v8.1.0" in combined
    assert "actions/download-artifact@v8.0.1" in triage
    assert "actions/upload-artifact@v7.0.1" in triage

    assert "contents: read" in triage
    assert "actions: read" in triage
    assert "issues: write" not in triage
    assert "pull-requests: write" not in triage
    assert "gh pr create" not in combined
    assert "gh issue comment" not in combined

    assert "`actions/checkout` | `v6` | `node24` | No" in docs
    assert "`actions/setup-python` | `v6` | `node24` | No" in docs
    assert "`astral-sh/setup-uv` | `v8.1.0` | `node24` | No" in docs
    assert "`actions/download-artifact` | `v8.0.1` | `node24` | No" in docs
    assert "`actions/upload-artifact` | `v7.0.1` | `node24` | No" in docs


def test_reviewer_facing_markdown_links_resolve_locally() -> None:
    missing_links: list[str] = []

    for markdown_file in _markdown_files_with_reviewer_facing_links():
        text = markdown_file.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK_RE.findall(text):
            local_target = _local_markdown_link_target(markdown_file, raw_target)
            if local_target is None:
                continue
            if not local_target.exists():
                relative_markdown = markdown_file.relative_to(ROOT)
                missing_links.append(f"{relative_markdown}: {raw_target}")

    assert missing_links == []


def test_reviewer_facing_ci_fixture_paths_resolve_with_expected_metadata() -> None:
    missing_fixtures: list[str] = []
    missing_expected_metadata: list[str] = []

    for markdown_file in _markdown_files_with_reviewer_facing_links():
        text = markdown_file.read_text(encoding="utf-8")
        for raw_path in sorted(set(CI_TRIAGE_LOG_PATH_RE.findall(text))):
            fixture_path = ROOT / raw_path
            if not fixture_path.exists():
                missing_fixtures.append(f"{markdown_file.relative_to(ROOT)}: {raw_path}")
                continue

            expected_path = fixture_path.with_suffix(".expected.json")
            if not expected_path.exists():
                missing_expected_metadata.append(
                    f"{markdown_file.relative_to(ROOT)}: {expected_path.relative_to(ROOT)}"
                )

    assert missing_fixtures == []
    assert missing_expected_metadata == []


def test_pipx_install_mentions_stay_marked_as_pre_pypi_unavailable() -> None:
    unsafe_mentions: list[str] = []

    for markdown_file in _markdown_files_with_reviewer_facing_links():
        lines = markdown_file.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if PIPX_INSTALL_COMMAND not in line:
                continue

            context = _line_context(lines, index)
            if not (
                "pypi publishing is pending" in context
                or "do not use" in context
                or "will not work yet" in context
            ):
                unsafe_mentions.append(f"{markdown_file.relative_to(ROOT)}:{index + 1}")

    assert unsafe_mentions == []


def test_pre_pypi_install_docs_offer_working_source_and_wheel_paths() -> None:
    incomplete_mentions: list[str] = []

    for markdown_file in _markdown_files_with_reviewer_facing_links():
        text = markdown_file.read_text(encoding="utf-8")
        if PIPX_INSTALL_COMMAND not in text:
            continue

        if GITHUB_SOURCE_COMMAND not in text or GITHUB_RELEASE_WHEEL_URL not in text:
            incomplete_mentions.append(str(markdown_file.relative_to(ROOT)))

    assert incomplete_mentions == []


def test_pre_pypi_install_verification_is_recorded_without_pypi_claims() -> None:
    evidence = (ROOT / "docs" / "openai-codex-for-oss-evidence.md").read_text(encoding="utf-8")
    program_evidence = (ROOT / "docs" / "oss-program-evidence.md").read_text(encoding="utf-8")
    combined = "\n".join([evidence, program_evidence])
    normalized = " ".join(combined.split())

    assert "Pre-PyPI install verification, 2026-06-06" in evidence
    assert "Pre-PyPI install verification, 2026-06-06" in program_evidence
    assert "clean temporary OpenClaw workspace" in normalized
    assert "clean `/tmp` context" not in combined
    assert "5d335368476b9c8739c01ffc16ba74d18d10b259" not in combined
    assert "uvx --from git+https://github.com/patchrail/patchrail patchrail --help" in normalized
    assert "87106e60c8c7ae630b079d8fac66c1531cce7ea6" in evidence
    assert "Root cause: python_test_failure" in combined
    assert GITHUB_RELEASE_WHEEL_URL in combined
    assert "Monthly PyPI downloads: pending first PyPI release" in combined
    assert "do not use `pipx install patchrail` yet until PyPI publish" in normalized


def test_readme_and_quickstart_do_not_promise_pypi_before_publish() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "patchrail", "ci", "explain"],
        input=("python -m pytest -q\nFAILED tests/test_app.py::test_ok - AssertionError\n"),
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    real_stdin_demo = proc.stdout

    surfaces = {
        "README.md": (ROOT / "README.md").read_text(encoding="utf-8"),
        "docs/quickstart.md": (ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8"),
    }

    for path, text in surfaces.items():
        assert "PyPI publishing is pending" in text, path
        assert GITHUB_SOURCE_COMMAND in text, path
        assert "patchrail ci explain" in text, path
        assert "FAILED tests/test_app.py::test_ok" in text, path
        assert f"python -m pip install {GITHUB_RELEASE_WHEEL_URL}" in text, path
        assert "pipx install patchrail" in text, path
        assert "That pre-PyPI smoke test prints" in text, path
        assert "10-second reviewer demo" in text, path
        assert "No install is required to inspect the current behavior." in text, path
        assert "tests compare that file against the command output to prevent drift" in text, path
        assert "uv run --extra dev python scripts/reviewer_quick_check.py" in text, path

        for expected_line in (
            "- Root cause: `python_test_failure`",
            "- Confidence: `0.89`",
            "- Subsystem: Python tests",
            "- Reproduce: `python -m pytest -q`",
            "- `FAILED .*::`",
            "PatchRail classified this log locally.",
        ):
            assert expected_line in real_stdin_demo
            assert expected_line in text, f"{path}: {expected_line}"


def test_versioned_demo_output_matches_real_cli_output() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "patchrail",
            "ci",
            "explain",
            "--log",
            "examples/ci-triage/dependency-failure.log",
            "--format",
            "markdown",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    demo = (ROOT / "examples" / "ci-triage" / "demo-output.md").read_text(encoding="utf-8")

    assert (
        "uv run --extra dev patchrail ci explain --log examples/ci-triage/dependency-failure.log --format markdown"
        in demo
    )
    assert proc.stdout.strip() in demo
    assert "- Root cause: `python_dependency_resolution`" in demo
    assert "PatchRail classified this log locally." in demo


def test_reviewer_quick_check_script_outputs_local_demo_and_fail_closed_gate() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/reviewer_quick_check.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    output = proc.stdout
    assert "# PatchRail Reviewer Quick Check" in output
    assert "## 1. Local Doctor" in output
    assert "## 2. CI Triage Demo" in output
    assert "## 3. Release Readiness Evidence" in output
    assert "## 4. Agent Control Plane Evidence" in output
    assert "## 5. HTTP API Evidence" in output
    assert "## 6. Application Gate" in output
    assert "## 7. Application Dossier Contract" in output
    assert "- Root cause: `python_dependency_resolution`" in output
    assert "# PatchRail Release Readiness" in output
    assert "- Published to PyPI: `False`" in output
    assert "- Created release tag: `False`" in output
    assert "- Release readiness evidence generated: `True`" in output
    assert "Status: `local_demo_ready`" in output
    assert "- Bundle reviewer status: `ready_for_reviewer_handoff`" in output
    assert "- Bundle reviewer execution allowed: `False`" in output
    assert "Status: `local_http_api_ready`" in output
    assert "- Human gate write actions unlocked: `False`" in output
    assert "- HTTP API evidence generated: `True`" in output
    assert "Status: not_ready" in output
    assert "Decision: do_not_apply_yet" in output
    assert "Status: draft_only_do_not_submit" in output
    assert "Maintainer tap required: True" in output
    assert "Agent may submit: False" in output
    assert "patchrail.application_dossier.v1" in output
    assert "patchrail.reviewer_quick_check_artifacts.v1" in output
    assert "- Network required: `False`" in output
    assert "- Write action required: `False`" in output
    assert "- Application form submission performed: `False`" in output
    assert "- Agent Control Plane evidence generated: `True`" in output
    assert "- Application dossier generated: `True`" in output
    assert "- Application dossier schema available: `True`" in output
    assert "- Reviewer packet manifest schema available: `True`" in output
    assert "- Artifact packet generated: `False`" in output
    assert "publish to PyPI" in output
    assert "create pull requests" in output


def test_reviewer_quick_check_can_write_local_artifact_packet() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir) / "reviewer-packet"
        proc = subprocess.run(
            [sys.executable, "scripts/reviewer_quick_check.py", "--out-dir", str(out_dir)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        assert proc.returncode == 0, proc.stderr
        assert "## 8. Artifact Packet" in proc.stdout
        assert "- Artifact packet generated: `True`" in proc.stdout

        expected_files = {
            "README.md",
            "reviewer-quick-check.md",
            "ci-triage-demo.md",
            "release-readiness.md",
            "release-readiness.json",
            "control-plane-evidence.md",
            "control-plane-evidence.json",
            "http-api-evidence.md",
            "http-api-evidence.json",
            "application-gate.txt",
            "application-dossier.txt",
            "application-dossier.json",
            "application-dossier.schema.json",
            "reviewer-quick-check-artifacts.schema.json",
            "manifest.json",
        }
        assert {path.name for path in out_dir.iterdir()} == expected_files

        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        schema_proc = subprocess.run(
            [sys.executable, "-m", "patchrail", "schema", "reviewer-quick-check-artifacts"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert schema_proc.returncode == 0, schema_proc.stderr
        schema = json.loads(schema_proc.stdout)

        assert manifest == {
            "schema_version": "patchrail.reviewer_quick_check_artifacts.v1",
            "generated_from": "local_checkout",
            "network_required": False,
            "write_action_required": False,
            "application_form_submission_performed": False,
            "artifacts": [
                "reviewer-quick-check.md",
                "README.md",
                "application-dossier.json",
                "application-dossier.schema.json",
                "application-dossier.txt",
                "application-gate.txt",
                "ci-triage-demo.md",
                "control-plane-evidence.json",
                "control-plane-evidence.md",
                "http-api-evidence.json",
                "http-api-evidence.md",
                "release-readiness.json",
                "release-readiness.md",
                "reviewer-quick-check-artifacts.schema.json",
            ],
        }
        assert schema["properties"]["schema_version"]["const"] == manifest["schema_version"]
        assert schema["properties"]["generated_from"]["const"] == manifest["generated_from"]
        assert schema["properties"]["network_required"]["const"] is manifest["network_required"]
        assert (
            schema["properties"]["write_action_required"]["const"]
            is manifest["write_action_required"]
        )
        assert (
            schema["properties"]["application_form_submission_performed"]["const"]
            is manifest["application_form_submission_performed"]
        )
        assert set(manifest["artifacts"]) <= set(schema["properties"]["artifacts"]["items"]["enum"])
        assert (
            json.loads(
                (out_dir / "reviewer-quick-check-artifacts.schema.json").read_text(encoding="utf-8")
            )
            == schema
        )

        dossier = json.loads((out_dir / "application-dossier.json").read_text(encoding="utf-8"))
        assert dossier["schema_version"] == "patchrail.application_dossier.v1"
        assert dossier["status"] == "draft_only_do_not_submit"
        assert dossier["submission_policy"]["agent_may_submit"] is False
        assert dossier["submission_policy"]["maintainer_tap_required"] is True
        control_plane = json.loads(
            (out_dir / "control-plane-evidence.json").read_text(encoding="utf-8")
        )
        assert control_plane["schema_version"] == "patchrail.control_plane_evidence.v1"
        assert control_plane["status"] == "local_demo_ready"
        assert control_plane["signals"]["bundle_reviewer_status"] == "ready_for_reviewer_handoff"
        assert control_plane["safety"]["bundle_reviewer_execution_allowed"] is False
        assert control_plane["safety"]["bundle_reviewer_human_gates_complete"] is True
        http_api = json.loads((out_dir / "http-api-evidence.json").read_text(encoding="utf-8"))
        assert http_api["schema_version"] == "patchrail.http_api_evidence.v1"
        assert http_api["status"] == "local_http_api_ready"
        assert http_api["server"]["bind_host"] == "127.0.0.1"
        assert http_api["artifact_presence"]["required_endpoints_present"] is True
        assert http_api["artifact_presence"]["required_events_present"] is True
        assert http_api["signals"]["human_gate_status"] == "no_pending_decisions"
        assert http_api["safety"]["bind_host_local_only"] is True
        assert http_api["safety"]["human_gate_write_actions_unlocked"] is False
        assert http_api["safety"]["approval_records_execute_actions"] is False
        release_readiness = json.loads(
            (out_dir / "release-readiness.json").read_text(encoding="utf-8")
        )
        assert release_readiness["schema_version"] == "patchrail.release_readiness.v1"
        assert release_readiness["published"] is False
        assert release_readiness["checks"]["build"] == "passed"
        assert release_readiness["checks"]["twine_check"] == "passed"
        assert release_readiness["checks"]["wheel_smoke"] == "passed"
        assert release_readiness["safety"]["published_to_pypi"] is False
        assert release_readiness["safety"]["created_release_tag"] is False

        packet_readme = (out_dir / "README.md").read_text(encoding="utf-8")
        assert "# PatchRail Reviewer Packet" in packet_readme
        assert "## Review Order" in packet_readme
        assert "`reviewer-quick-check.md`" in packet_readme
        assert "`release-readiness.md` and `release-readiness.json`" in packet_readme
        assert "`control-plane-evidence.md` and `control-plane-evidence.json`" in packet_readme
        assert "`http-api-evidence.md` and `http-api-evidence.json`" in packet_readme
        assert "- Network required: `False`" in packet_readme
        assert "- Write action required: `False`" in packet_readme
        assert "- Application form submission performed: `False`" in packet_readme
        assert "- PyPI publish performed: `False`" in packet_readme
        assert "Third-party pull request, issue comment, or funded-issue claim performed" in (
            packet_readme
        )
        assert "/Volumes/" not in packet_readme
        assert "/Users/" not in packet_readme
        assert "/home/" not in packet_readme

        packet = (out_dir / "reviewer-quick-check.md").read_text(encoding="utf-8")
        assert "Status: draft_only_do_not_submit" in packet
        assert "Status: `local_demo_ready`" in packet
        assert "Status: `local_http_api_ready`" in packet
        assert "Published to PyPI: `False`" in packet
        assert "patchrail.application_dossier.v1" in packet
        assert "patchrail.reviewer_quick_check_artifacts.v1" in packet
        assert "/Volumes/" not in packet
        assert "/Users/" not in packet
        assert "/home/" not in packet


def test_reviewer_quick_check_cli_can_write_local_artifact_packet() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir) / "reviewer-packet"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "patchrail",
                "evidence",
                "reviewer-packet",
                "--out-dir",
                str(out_dir),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        assert proc.returncode == 0, proc.stderr
        assert "# PatchRail Reviewer Quick Check" in proc.stdout
        assert "## 8. Artifact Packet" in proc.stdout
        assert "- Artifact packet generated: `True`" in proc.stdout
        assert "- Release readiness evidence generated: `True`" in proc.stdout
        assert "- Agent Control Plane evidence generated: `True`" in proc.stdout
        assert "- HTTP API evidence generated: `True`" in proc.stdout
        assert "patchrail.application_dossier.v1" in proc.stdout
        assert "patchrail.reviewer_quick_check_artifacts.v1" in proc.stdout

        expected_files = {
            "README.md",
            "reviewer-quick-check.md",
            "ci-triage-demo.md",
            "release-readiness.md",
            "release-readiness.json",
            "control-plane-evidence.md",
            "control-plane-evidence.json",
            "http-api-evidence.md",
            "http-api-evidence.json",
            "application-gate.txt",
            "application-dossier.txt",
            "application-dossier.json",
            "application-dossier.schema.json",
            "reviewer-quick-check-artifacts.schema.json",
            "manifest.json",
        }
        assert {path.name for path in out_dir.iterdir()} == expected_files

        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["schema_version"] == "patchrail.reviewer_quick_check_artifacts.v1"
        assert manifest["network_required"] is False
        assert manifest["write_action_required"] is False
        assert manifest["application_form_submission_performed"] is False

        packet = (out_dir / "reviewer-quick-check.md").read_text(encoding="utf-8")
        assert "Status: draft_only_do_not_submit" in packet
        assert "ready_for_reviewer_handoff" in packet
        assert "local_http_api_ready" in packet
        assert "Published to PyPI: `False`" in packet
        assert "/Volumes/" not in packet
        assert "/Users/" not in packet
        assert "/home/" not in packet


def test_reviewer_quick_check_schema_is_publicly_documented() -> None:
    api_reference = (ROOT / "docs" / "api-reference.md").read_text(encoding="utf-8")
    oss_evidence = (ROOT / "docs" / "oss-program-evidence.md").read_text(encoding="utf-8")
    codex_evidence = (ROOT / "docs" / "openai-codex-for-oss-evidence.md").read_text(
        encoding="utf-8"
    )
    combined_evidence = "\n".join([oss_evidence, codex_evidence])
    normalized_evidence = " ".join(combined_evidence.split())
    packaged_schema = json.loads(
        (
            ROOT / "src" / "patchrail" / "schemas" / "reviewer-quick-check-artifacts.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    mirrored_schema = json.loads(
        (ROOT / "schemas" / "reviewer_quick_check_artifacts.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert "patchrail schema reviewer-quick-check-artifacts" in api_reference
    assert "patchrail evidence reviewer-packet --out-dir patchrail-reviewer-packet" in api_reference
    assert "src/patchrail/schemas/reviewer-quick-check-artifacts.v1.schema.json" in api_reference
    assert "schemas/reviewer_quick_check_artifacts.schema.json" in api_reference
    assert "no network, write action, public publish, or application submission" in api_reference
    assert (
        "patchrail evidence reviewer-packet --out-dir patchrail-reviewer-packet"
        in combined_evidence
    )
    assert "reviewer-quick-check-artifacts.schema.json" in combined_evidence
    assert "README.md" in combined_evidence
    assert "control-plane-evidence.json" in combined_evidence
    assert "control-plane-evidence.md" in combined_evidence
    assert "http-api-evidence.json" in combined_evidence
    assert "http-api-evidence.md" in combined_evidence
    assert "release-readiness.json" in combined_evidence
    assert "release-readiness.md" in combined_evidence
    assert "own manifest schema for offline validation" in normalized_evidence
    assert mirrored_schema == packaged_schema


def test_evidence_snapshot_summarizes_public_oss_signals_without_write_actions() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "patchrail", "evidence", "snapshot", "--format", "json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == "patchrail.evidence_snapshot.v1"
    assert payload["repository"] == "patchrail/patchrail"
    assert payload["generated_from"] == "local_checkout"
    assert payload["status"] == "needs_more_evidence"
    assert payload["signals"]["ci_fixtures"] == 143
    assert payload["signals"]["ci_expected_files"] == 143
    assert payload["signals"]["ci_benchmark_passed"] == 143
    assert payload["signals"]["ci_benchmark_failed"] == 0
    assert payload["signals"]["public_external_adopters"] == 0
    assert payload["signals"]["pilot_summary_count"] == 1
    assert payload["signals"]["owned_repo_issue_pr_cycles"] == 20
    assert "release-v0.4.0-evidence.md" in payload["signals"]["release_evidence_pages"]
    assert payload["workstreams"]["ci_janitor"]["benchmark_green"] is True
    assert payload["workstreams"]["github_action"]["read_only_permissions"] is True
    assert payload["workstreams"]["agent_control_plane"]["demo_present"] is True
    assert payload["workstreams"]["funded_issue_scout"]["demo_present"] is True
    assert payload["workstreams"]["release_packaging"]["package_smoke_in_ci"] is True
    assert payload["workstreams"]["public_review_triage"]["status"] == "owned_repo_visible"
    assert payload["workstreams"]["public_review_triage"]["owned_issue_pr_cycles"] == 20
    assert payload["workstreams"]["public_review_triage"]["focused_maintainer_prs"] == 20
    assert (
        payload["workstreams"]["public_review_triage"]["review_packet_command"]
        == "patchrail evidence review-packet"
    )
    assert payload["workstreams"]["public_review_triage"]["formal_codex_review_links"] is False
    assert payload["safety"]["read_only_ci_triage_workflow"] is True
    assert payload["safety"]["github_write_permission_required"] is False
    assert payload["safety"]["external_model_required"] is False
    assert payload["safety"]["billing_required"] is False
    assert payload["safety"]["network_required"] is False
    assert payload["safety"]["missing_required_docs"] == []
    assert "first PyPI publish and download telemetry" in payload["remaining_evidence_gaps"]
    assert (
        "formal visible Codex review links and external maintainer triage examples"
        in (payload["remaining_evidence_gaps"])
    )
    assert "/Volumes/" not in proc.stdout
    assert "/Users/" not in proc.stdout
    assert "/home/" not in proc.stdout


def test_ci_evidence_artifact_includes_control_plane_bundle() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    oss_program_evidence = (ROOT / "docs" / "oss-program-evidence.md").read_text(encoding="utf-8")
    release_v03 = (ROOT / "docs" / "release-v0.3.0-evidence.md").read_text(encoding="utf-8")
    docs = "\n".join([oss_program_evidence, release_v03])

    assert (
        "uv run patchrail evidence snapshot --format json --out patchrail-oss-evidence/evidence-snapshot.json"
        in workflow
    )
    assert (
        "uv run patchrail evidence snapshot --format markdown --out patchrail-oss-evidence/evidence-snapshot.md"
        in workflow
    )
    assert (
        "uv run patchrail evidence control-plane --format json --out patchrail-oss-evidence/control-plane-evidence.json"
        in workflow
    )
    assert (
        "uv run patchrail evidence control-plane --format markdown --out patchrail-oss-evidence/control-plane-evidence.md"
        in workflow
    )
    assert (
        "uv run patchrail evidence application-dossier --format json --out patchrail-oss-evidence/application-dossier.json"
        in workflow
    )
    assert (
        "uv run patchrail evidence application-dossier --format markdown --out patchrail-oss-evidence/application-dossier.md"
        in workflow
    )
    assert (
        "uv run patchrail evidence reviewer-packet --out-dir patchrail-oss-evidence/reviewer-packet"
        in workflow
    )
    assert (
        "uv run python examples/local-agent-queue/run_demo.py --output .patchrail-ci-local-agent-queue --force"
        in workflow
    )
    assert (
        "cp .patchrail-ci-local-agent-queue/summary.json patchrail-oss-evidence/local-agent-queue/summary.json"
        in workflow
    )
    assert (
        "cp .patchrail-ci-local-agent-queue/bundle.json patchrail-oss-evidence/local-agent-queue/bundle.json"
        in workflow
    )
    assert (
        "cp .patchrail-ci-local-agent-queue/bundle.md patchrail-oss-evidence/local-agent-queue/bundle.md"
        in workflow
    )
    assert "if-no-files-found: error" in workflow

    assert "control-plane-evidence.json" in docs
    assert "control-plane-evidence.md" in docs
    assert "application-dossier.json" in docs
    assert "application-dossier.md" in docs
    assert "reviewer-packet/" in docs
    assert "patchrail evidence reviewer-packet --out-dir" in docs
    assert "local-agent-queue/summary.json" in docs
    assert "local-agent-queue/bundle.json" in docs
    assert "local-agent-queue/bundle.md" in docs
    assert "does not count as external adoption or PyPI download evidence" in docs


def test_roadmap_audit_tracks_versions_and_weeks_without_external_claims() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "patchrail", "evidence", "roadmap", "--format", "json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == "patchrail.roadmap_audit.v1"
    assert payload["repository"] == "patchrail/patchrail"
    assert payload["generated_from"] == "local_checkout"
    assert payload["status"] == "active_not_ready_for_external_application"
    assert set(payload["versions"]) == {"v0.1.0", "v0.2.0", "v0.3.0", "v0.4.0"}
    assert len(payload["weeks"]) == 12
    assert payload["versions"]["v0.1.0"]["status"] == "github_release_ready_pypi_blocked"
    assert (
        "first PyPI publish and clean install verification"
        in (payload["versions"]["v0.1.0"]["gaps"])
    )
    assert payload["versions"]["v0.2.0"]["signals"]["ci_fixtures"] == 143
    assert payload["versions"]["v0.2.0"]["signals"]["ci_benchmark_failed"] == 0
    assert payload["versions"]["v0.2.0"]["signals"]["read_only_github_action"] is True
    assert payload["versions"]["v0.3.0"]["signals"]["owned_repo_issue_pr_cycles"] == 20
    assert (
        payload["versions"]["v0.3.0"]["signals"]["evidence_command"]
        == "patchrail evidence control-plane"
    )
    assert payload["versions"]["v0.4.0"]["signals"]["money_goal_retired"] is True
    assert (
        "do not process bounties, payouts, claims, outbound, or money-ranked leads"
        in (payload["versions"]["v0.4.0"]["gaps"])
    )
    assert payload["weeks"]["week_2"]["status"] == "partial_pypi_blocked"
    assert payload["weeks"]["week_8"]["status"] == "pending_external_permission"
    assert payload["weeks"]["week_12"]["status"] == "not_ready"
    assert payload["safety"]["network_required"] is False
    assert payload["safety"]["github_write_permission_required"] is False
    assert payload["safety"]["billing_required"] is False
    assert payload["safety"]["external_model_required"] is False
    assert payload["safety"]["money_goal_retired"] is True
    assert payload["artifact_presence"]["release_v0_1"] is True
    assert payload["artifact_presence"]["agent_control_plane_demo"] is True
    assert payload["artifact_presence"]["funded_issues_read_only_demo"] is True
    assert "/Volumes/" not in proc.stdout
    assert "/Users/" not in proc.stdout
    assert "/home/" not in proc.stdout

    roadmap = (ROOT / "docs" / "roadmap.md").read_text(encoding="utf-8")
    assert "patchrail evidence roadmap --format markdown" in roadmap
    assert "does not replace public PyPI download telemetry" in roadmap


def test_application_gate_fails_closed_until_public_evidence_is_real() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "patchrail", "evidence", "application-gate", "--format", "json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 1, proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == "patchrail.application_gate.v1"
    assert payload["repository"] == "patchrail/patchrail"
    assert payload["generated_from"] == "local_checkout"
    assert payload["status"] == "not_ready"
    assert payload["decision"] == "do_not_apply_yet"
    assert payload["checks"]["public_repository_present"] is True
    assert payload["checks"]["ci_benchmark_green"] is True
    assert payload["checks"]["read_only_ci_triage_workflow"] is True
    assert payload["checks"]["agent_control_plane_demo_ready"] is True
    assert payload["checks"]["pypi_release_published"] is False
    assert payload["checks"]["external_adopters_present"] is False
    assert payload["checks"]["formal_visible_review_links_present"] is False
    assert payload["checks"]["no_placeholder_metrics_in_application_copy"] is True
    assert payload["checks"]["money_goal_retired"] is True
    assert payload["checks"]["no_network_or_write_required"] is True
    assert "first PyPI publish and download telemetry" in payload["blockers"]
    assert "permissioned external maintainer pilots or adopters" in payload["blockers"]
    assert "formal visible review links" in payload["blockers"]
    assert payload["blocked_dependencies"] == [
        {
            "blocker": "first PyPI publish and download telemetry",
            "owner": "maintainer_human_gate",
            "required_evidence": (
                "PyPI Trusted Publisher or package-index credentials plus real download telemetry"
            ),
            "safe_local_alternative": (
                "keep release-readiness, wheel smoke, and pre-PyPI install documentation green"
            ),
        },
        {
            "blocker": "permissioned external maintainer pilots or adopters",
            "owner": "external_maintainer_permission",
            "required_evidence": ("a maintainer-approved public pilot summary or adopter listing"),
            "safe_local_alternative": (
                "improve consent-only pilot docs, redaction, and fixture contribution paths"
            ),
        },
        {
            "blocker": "formal visible review links",
            "owner": "public_review_artifact",
            "required_evidence": (
                "public review or triage links that are real and attributable without placeholder claims"
            ),
            "safe_local_alternative": (
                "continue owned-repo issue-to-PR cycles and review-packet evidence"
            ),
        },
    ]
    assert payload["safe_local_work_while_blocked"] == [
        "extend CI Failure Zoo fixtures and benchmark guardrails",
        "improve Agent Control Plane queue, approval, and audit evidence",
        "keep README, quickstart, release-readiness, and application-gate docs honest",
        "prepare upstream contributions only when a real bug or maintenance improvement exists",
    ]
    assert payload["signals"]["ci_fixtures"] == 143
    assert payload["signals"]["public_external_adopters"] == 0
    assert payload["signals"]["owned_repo_issue_pr_cycles"] == 20
    assert payload["safety"]["network_required"] is False
    assert payload["safety"]["github_write_permission_required"] is False
    assert payload["safety"]["external_model_required"] is False
    assert payload["safety"]["billing_required"] is False
    assert payload["safety"]["money_goal_retired"] is True
    assert "/Volumes/" not in proc.stdout
    assert "/Users/" not in proc.stdout
    assert "/home/" not in proc.stdout

    markdown_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "patchrail",
            "evidence",
            "application-gate",
            "--format",
            "markdown",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert markdown_proc.returncode == 1, markdown_proc.stdout
    assert "# PatchRail Application Gate" in markdown_proc.stdout
    assert "- Decision: `do_not_apply_yet`" in markdown_proc.stdout
    assert "## Blocked Dependencies" in markdown_proc.stdout
    assert "- Owner: `maintainer_human_gate`" in markdown_proc.stdout
    assert "- Owner: `external_maintainer_permission`" in markdown_proc.stdout
    assert "- Owner: `public_review_artifact`" in markdown_proc.stdout
    assert "keep application copy blocked while any metric is pending" in markdown_proc.stdout
    assert "## Safe Local Work While Blocked" in markdown_proc.stdout
    assert "improve Agent Control Plane queue, approval, and audit evidence" in (
        markdown_proc.stdout
    )


def test_control_plane_evidence_audits_local_demo_without_write_actions() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "patchrail", "evidence", "control-plane", "--format", "json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == "patchrail.control_plane_evidence.v1"
    assert payload["repository"] == "patchrail/patchrail"
    assert payload["generated_from"] == "local_checkout"
    assert payload["summary_file"] == "examples/local-agent-queue/demo-summary.expected.json"
    assert payload["status"] == "local_demo_ready"
    assert payload["signals"]["artifact_count"] == 21
    assert payload["signals"]["audit_event_count"] == 9
    assert payload["signals"]["source_failure_class"] == "python_dependency_resolution"
    assert payload["signals"]["item_approval_state"] == "approved"
    assert payload["signals"]["proposal_approval_state"] == "approved"
    assert payload["signals"]["proposal_risk_level"] == "low"
    assert payload["signals"]["rejected_item_approval_state"] == "rejected"
    assert payload["signals"]["rejected_proposal_approval_state"] == "rejected"
    assert payload["signals"]["audit_summary_status"] == "human_gates_exercised"
    assert payload["signals"]["bundle_status"] == "ready_for_handoff"
    assert payload["signals"]["bundle_remaining_gate_gaps"] == []
    assert payload["safety"]["local_first"] is True
    assert payload["safety"]["write_actions_allowed"] is False
    assert payload["safety"]["rejected_item_write_actions_allowed"] is False
    assert payload["safety"]["human_approval_gate_exercised"] is True
    assert payload["safety"]["proposal_approval_gate_exercised"] is True
    assert payload["safety"]["risky_proposal_rejection_exercised"] is True
    assert payload["safety"]["audit_summary_human_gates_exercised"] is True
    assert payload["safety"]["github_write_permission_required"] is False
    assert payload["safety"]["external_model_required"] is False
    assert payload["safety"]["billing_required"] is False
    assert payload["safety"]["network_required"] is False
    assert payload["safety"]["bundle_is_read_only"] is True
    assert payload["safety"]["bundle_records_audit_event"] is False
    assert payload["safety"]["bundle_local_paths_redacted"] is True
    assert payload["artifact_presence"]["required_events_present"] is True
    assert payload["artifact_presence"]["required_artifacts_present"] is True
    assert payload["artifact_presence"]["source_files_present"] is True
    assert payload["artifact_presence"]["missing_events"] == []
    assert payload["artifact_presence"]["missing_artifacts"] == []
    assert payload["artifact_presence"]["missing_source_files"] == []
    assert payload["artifact_presence"]["audit_summary_missing_required_events"] == []
    assert payload["artifact_presence"]["safety_gaps"] == []
    assert (
        "permissioned external maintainer control-plane demo"
        in (payload["remaining_evidence_gaps"])
    )
    assert "/Volumes/" not in proc.stdout
    assert "/Users/" not in proc.stdout
    assert "/home/" not in proc.stdout

    markdown_proc = subprocess.run(
        [sys.executable, "-m", "patchrail", "evidence", "control-plane", "--format", "markdown"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert markdown_proc.returncode == 0, markdown_proc.stderr
    assert "Bundle is read-only: `True`" in markdown_proc.stdout
    assert "Bundle records audit event: `False`" in markdown_proc.stdout
    assert "Bundle local paths redacted: `True`" in markdown_proc.stdout
    assert "Bundle reviewer status: `ready_for_reviewer_handoff`" in markdown_proc.stdout
    assert "Bundle reviewer pending decisions: `0`" in markdown_proc.stdout
    assert "Bundle reviewer human gates complete: `True`" in markdown_proc.stdout
    assert "Bundle reviewer execution allowed: `False`" in markdown_proc.stdout

    agent_control_plane = (ROOT / "docs" / "agent-control-plane.md").read_text(encoding="utf-8")
    api_reference = (ROOT / "docs" / "api-reference.md").read_text(encoding="utf-8")
    oss_program_evidence = (ROOT / "docs" / "oss-program-evidence.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap.md").read_text(encoding="utf-8")
    release_v03 = (ROOT / "docs" / "release-v0.3.0-evidence.md").read_text(encoding="utf-8")
    docs = "\n".join(
        [agent_control_plane, api_reference, oss_program_evidence, roadmap, release_v03]
    )
    assert "patchrail evidence control-plane --format markdown" in docs
    assert "patchrail evidence http-api --format markdown" in docs
    assert "patchrail queue bundle --format markdown" in docs
    assert "reviewer summary" in docs
    assert "ready_for_reviewer_handoff" in docs
    assert "local_demo_ready" in docs
    assert "risky-proposal rejection" in docs


def test_http_api_evidence_smokes_ephemeral_local_server_without_write_actions() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "patchrail", "evidence", "http-api", "--format", "json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == "patchrail.http_api_evidence.v1"
    assert payload["repository"] == "patchrail/patchrail"
    assert payload["generated_from"] == "ephemeral_local_http_server"
    assert payload["status"] == "local_http_api_ready"
    assert payload["server"]["bind_host"] == "127.0.0.1"
    assert payload["server"]["base_url"].startswith("http://127.0.0.1:")
    assert payload["server"]["database"] == "temporary SQLite database"
    assert "GET /health" in payload["endpoints_checked"]
    assert "GET /status" in payload["endpoints_checked"]
    assert "POST /work-items" in payload["endpoints_checked"]
    assert "POST /proposals" in payload["endpoints_checked"]
    assert "POST /proposals/{id}/approve" in payload["endpoints_checked"]
    assert "POST /proposals/{id}/reject" in payload["endpoints_checked"]
    assert "POST /work-items/{id}/approve" in payload["endpoints_checked"]
    assert "POST /work-items/{id}/reject" in payload["endpoints_checked"]
    assert "GET /audit-events" in payload["endpoints_checked"]
    assert payload["signals"]["work_items_total"] == 2
    assert payload["signals"]["proposals_total"] == 2
    assert payload["signals"]["audit_events_total"] == 8
    assert payload["signals"]["approved_work_items"] == 1
    assert payload["signals"]["rejected_work_items"] == 1
    assert payload["signals"]["approved_proposals"] == 1
    assert payload["signals"]["rejected_proposals"] == 1
    assert payload["signals"]["human_gate_status"] == "no_pending_decisions"
    assert payload["signals"]["human_gate_total_pending_decisions"] == 0
    assert payload["signals"]["human_gate_pending_work_items"] == 0
    assert payload["signals"]["human_gate_pending_proposals"] == 0
    assert payload["signals"]["human_gate_write_actions_unlocked"] is False
    assert payload["safety"]["local_first"] is True
    assert payload["safety"]["bind_host_local_only"] is True
    assert payload["safety"]["network_required"] is False
    assert payload["safety"]["github_write_permission_required"] is False
    assert payload["safety"]["external_model_required"] is False
    assert payload["safety"]["billing_required"] is False
    assert payload["safety"]["approval_records_execute_actions"] is False
    assert payload["safety"]["approved_item_write_actions_allowed"] is False
    assert payload["safety"]["rejected_item_write_actions_allowed"] is False
    assert payload["safety"]["proposal_approval_gate_exercised"] is True
    assert payload["safety"]["proposal_rejection_gate_exercised"] is True
    assert payload["safety"]["human_gate_summary_exposed"] is True
    assert payload["safety"]["human_gate_write_actions_unlocked"] is False
    assert payload["artifact_presence"]["required_events_present"] is True
    assert payload["artifact_presence"]["required_endpoints_present"] is True
    assert payload["artifact_presence"]["missing_events"] == []
    assert payload["artifact_presence"]["missing_endpoints"] == []
    assert payload["artifact_presence"]["safety_gaps"] == []
    assert "/Volumes/" not in proc.stdout
    assert "/Users/" not in proc.stdout
    assert "/home/" not in proc.stdout


def test_review_packet_summarizes_owned_repo_workflows_without_external_claims() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "patchrail", "evidence", "review-packet", "--format", "json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == "patchrail.review_packet.v1"
    assert payload["repository"] == "patchrail/patchrail"
    assert payload["generated_from"] == "local_checkout"
    assert payload["source_file"] == "docs/public-workflow-ledger.md"
    assert payload["status"] == "owned_repo_review_packet_ready"
    assert payload["signals"]["issue_to_pr_cycles"] == 20
    assert payload["signals"]["focused_maintainer_prs"] == 20
    assert payload["signals"]["total_owned_review_items"] == 40
    assert payload["boundaries"]["owned_repository_only"] is True
    assert payload["boundaries"]["external_adoption_claimed"] is False
    assert payload["boundaries"]["formal_codex_review_claimed"] is False
    assert payload["boundaries"]["pypi_download_claimed"] is False
    assert payload["boundaries"]["third_party_write_actions_claimed"] is False
    assert payload["requirements"]["billing_required"] is False
    assert payload["requirements"]["external_model_required"] is False
    assert payload["requirements"]["network_required"] is False
    assert payload["requirements"]["github_write_permission_required"] is False
    assert payload["issue_to_pr_cycles"][0]["issue"]["url"].endswith("/issues/69")
    assert payload["issue_to_pr_cycles"][0]["pull_request"]["url"].endswith("/pull/79")
    assert payload["focused_maintainer_prs"][-1]["pull_request"]["url"].endswith("/pull/102")
    assert payload["focused_maintainer_prs"][-1]["public_ci_evidence"]["url"].endswith(
        "/actions/runs/26911478559"
    )
    assert "formal visible Codex review links" in payload["remaining_evidence_gaps"]
    assert "/Volumes/" not in proc.stdout
    assert "/Users/" not in proc.stdout
    assert "/home/" not in proc.stdout

    markdown_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "patchrail",
            "evidence",
            "review-packet",
            "--format",
            "markdown",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert markdown_proc.returncode == 0, markdown_proc.stderr
    assert "# PatchRail Public Review Packet" in markdown_proc.stdout
    assert "- External adoption claimed: `False`" in markdown_proc.stdout
    assert "https://github.com/patchrail/patchrail/pull/102" in markdown_proc.stdout


def test_github_action_artifact_example_is_report_only_and_sanitized() -> None:
    artifact_dir = ROOT / "examples" / "github-action" / "patchrail-ci-triage-artifact"
    readme = (ROOT / "examples" / "github-action" / "README.md").read_text(encoding="utf-8")
    report = (artifact_dir / "ci-report.md").read_text(encoding="utf-8")
    benchmark_summary = (artifact_dir / "fixture-benchmark-summary.md").read_text(encoding="utf-8")
    result = json.loads((artifact_dir / "ci-result.json").read_text(encoding="utf-8"))
    benchmark = json.loads((artifact_dir / "fixture-benchmark.json").read_text(encoding="utf-8"))
    doctor = json.loads((artifact_dir / "doctor.json").read_text(encoding="utf-8"))

    assert "patchrail-ci-triage" in readme
    assert "does not comment on issues or pull requests" in readme
    assert "does not open pull requests" in readme
    assert "does not call external models" in readme
    assert "Copy The Workflow" in readme
    assert "permissions:" in readme
    assert "contents: read" in readme
    assert "actions: read" in readme
    assert 'gh workflow run "PatchRail CI Triage"' in readme
    assert "gh run download" in readme
    assert "--name patchrail-ci-triage" in readme
    assert "Artifact Contents" in readme
    assert "`ci-report.md`: Markdown summary for maintainers" in readme
    assert "`ci-result.json`: structured classifier output" in readme
    assert "`fixture-benchmark.json`: benchmark result" in readme
    assert "`fixture-benchmark-summary.md`: short Markdown benchmark summary" in readme
    assert "`doctor.json`: local safety check" in readme
    assert "Do not paste raw CI logs, secrets, private paths" in readme

    assert "PatchRail classified this log locally" in report
    assert "did not create a pull request" in report
    assert "# PatchRail CI Benchmark" in benchmark_summary
    assert "- Total cases: `143`" in benchmark_summary
    assert "## Class summary" in benchmark_summary
    assert "## Cases" not in benchmark_summary
    assert result["failure_class"] == "python_dependency_resolution"
    assert result["requirements"]["billing_required"] is False
    assert result["requirements"]["external_model_required"] is False
    assert benchmark["total_cases"] == 143
    assert benchmark["failed"] == 0
    assert benchmark["accuracy"]["top_1"] == 1.0
    assert benchmark["class_summary"]["python_dependency_resolution"]["total_cases"] == 27
    assert benchmark["class_summary"]["node_dependency_install"]["total_cases"] == 19
    assert benchmark["class_summary"]["typescript_typecheck"]["total_cases"] == 19
    assert benchmark["class_summary"]["ruby_bundle_failure"]["total_cases"] == 8
    assert benchmark["class_summary"]["java_build_failure"]["total_cases"] == 4
    assert benchmark["class_summary"]["php_composer_failure"]["total_cases"] == 4
    assert benchmark["class_summary"]["dotnet_build_failure"]["total_cases"] == 4
    assert doctor["status"] == "ok"
    assert doctor["requirements"]["github_write_permission_required"] is False

    serialized = "\n".join(
        [
            readme,
            report,
            benchmark_summary,
            json.dumps(result),
            json.dumps(benchmark),
            json.dumps(doctor),
        ]
    )
    assert "/Volumes/" not in serialized
    assert "/Users/" not in serialized
    assert "/home/runner/" not in serialized


def test_oss_plan_canonical_docs_exist_and_preserve_human_gates() -> None:
    codex_workflows = (ROOT / "docs" / "codex-workflows.md").read_text(encoding="utf-8")
    evidence = (ROOT / "docs" / "openai-codex-for-oss-evidence.md").read_text(encoding="utf-8")
    oss_program_evidence = (ROOT / "docs" / "oss-program-evidence.md").read_text(encoding="utf-8")
    workflow_ledger = (ROOT / "docs" / "public-workflow-ledger.md").read_text(encoding="utf-8")
    api_reference = (ROOT / "docs" / "api-reference.md").read_text(encoding="utf-8")
    pilot_guide = (ROOT / "docs" / "pilot-guide.md").read_text(encoding="utf-8")
    pilot_request_package = (ROOT / "docs" / "pilot-request-package.md").read_text(encoding="utf-8")
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    threat_model = (ROOT / "docs" / "threat-model.md").read_text(encoding="utf-8")
    metrics = (ROOT / "docs" / "metrics.md").read_text(encoding="utf-8")
    adopters = (ROOT / "ADOPTERS.md").read_text(encoding="utf-8")
    pilot_outcome = (ROOT / "examples" / "pilot-outcome" / "README.md").read_text(encoding="utf-8")
    own_repo_pilot = (
        ROOT / "examples" / "pilot-outcome" / "patchrail-own-repo-20260603.md"
    ).read_text(encoding="utf-8")
    own_repo_pilot_json = json.loads(
        (
            ROOT / "examples" / "pilot-outcome" / "patchrail-own-repo-20260603.summary.json"
        ).read_text(encoding="utf-8")
    )
    adopter_report = (ROOT / ".github" / "ISSUE_TEMPLATE" / "adopter_report.md").read_text(
        encoding="utf-8"
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    quickstart = (ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap.md").read_text(encoding="utf-8")
    release_v02 = (ROOT / "docs" / "release-v0.2.0-evidence.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    skill_dir = ROOT / ".agents" / "skills"
    ci_skill = (skill_dir / "patchrail-ci-triage" / "SKILL.md").read_text(encoding="utf-8")
    release_skill = (skill_dir / "patchrail-release-captain" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    guardrails_skill = (skill_dir / "patchrail-review-guardrails" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "docs/codex-workflows.md" in readme
    assert "docs/openai-codex-for-oss-evidence.md" in readme
    assert "docs/public-workflow-ledger.md" in readme
    assert "docs/api-reference.md" in readme
    assert "docs/pilot-guide.md" in readme
    assert "docs/pilot-request-package.md" in readme
    assert "examples/pilot-outcome/README.md" in readme
    assert "docs/metrics.md" in readme
    assert "patchrail ci pilot-pack --log failed.log --out-dir patchrail-pilot-pack" in readme
    assert "patchrail evidence snapshot --format markdown" in readme
    assert "ADOPTERS.md" in readme
    assert ".github/ISSUE_TEMPLATE/ci_failure_fixture.md" in readme
    assert ".agents/skills" in readme
    assert "pipx install patchrail" in readme
    assert "pipx install patchrail" in quickstart
    assert "patchrail ci explain --log failed-github-actions.log" in quickstart
    assert "patchrail ci pilot-pack --log failed-github-actions.log" in quickstart
    assert "The v0.1 release does not require Codex or any external model" in codex_workflows
    assert "no automatic pull requests" in codex_workflows
    assert "public-workflow-ledger.md" in codex_workflows
    assert "own-repo evidence, not third-party adoption" in codex_workflows
    assert "patchrail-ci-triage" in codex_workflows
    assert "patchrail-release-captain" in codex_workflows
    assert "patchrail-review-guardrails" in codex_workflows
    assert "Human approval gates for write actions" in evidence
    assert "No automatic bounty claiming" in evidence
    assert ".agents/skills/patchrail-ci-triage" in evidence
    assert "PyPI publishing is pending" in evidence
    assert "uvx --from git+https://github.com/patchrail/patchrail patchrail" in evidence
    assert "Recent successful public CI run" in evidence
    assert "https://github.com/patchrail/patchrail/actions/runs/27054439302" in evidence
    assert "c4fbd859d4d69c00215faf1acec2be5e24e98b03" in evidence
    assert "patchrail-oss-evidence" in evidence
    assert "Agent Control Plane evidence" in evidence
    assert "reviewer-facing local queue bundle" in evidence
    for artifact_name in (
        "reviewer-quick-check.md",
        "ci-triage-demo.md",
        "release-readiness.md",
        "release-readiness.json",
        "application-gate.txt",
        "application-dossier.txt",
        "application-dossier.json",
        "application-dossier.schema.json",
        "control-plane-evidence.md",
        "control-plane-evidence.json",
        "reviewer-quick-check-artifacts.schema.json",
        "manifest.json",
    ):
        assert artifact_name in evidence
        assert artifact_name in oss_program_evidence
    assert "Versioned reviewer demo" in evidence
    assert "examples/ci-triage/demo-output.md" in evidence
    assert (
        "patchrail ci explain --log examples/ci-triage/dependency-failure.log --format markdown"
        in evidence
    )
    assert "https://github.com/jamie8johnson/cqs/pull/1650" in evidence
    assert "https://github.com/pypa/twine/pull/1329" in evidence
    assert "1 passed, 231 deselected" in evidence
    assert "External maintainer checks and" in evidence
    assert "merge remain controlled by the upstream project." in evidence
    assert "Public maintenance workflow ledger" in evidence
    assert "public-workflow-ledger.md" in evidence
    assert "formal visible Codex" in evidence
    assert "blocked_dependencies" in evidence
    assert "safe_local_work_while_blocked" in evidence
    assert "maintainer_human_gate" in evidence
    assert "external_maintainer_permission" in evidence
    assert "public_review_artifact" in evidence
    assert "#61 -> #62" in evidence
    assert "#59 -> #60" in evidence
    assert "Consent-only pilot outcome example" in evidence
    assert "examples/pilot-outcome" in evidence
    assert "Public CI fixtures: 143 sanitized synthetic fixtures" in oss_program_evidence
    assert "Local evidence snapshot: `patchrail evidence snapshot --format markdown`" in (
        oss_program_evidence
    )
    assert "Public maintenance workflow ledger" in oss_program_evidence
    assert "owned-repo issue-to-PR cycles" in oss_program_evidence
    assert "patchrail evidence review-packet --format markdown" in oss_program_evidence
    assert "patchrail evidence review-packet --format json" in oss_program_evidence
    assert "not_ready" in oss_program_evidence
    assert "does not apply yet" not in oss_program_evidence
    assert "do_not_apply_yet" in oss_program_evidence
    assert 'not_ready` means "do not apply yet" rather than "stop' in (oss_program_evidence)
    assert "blocked_dependencies" in oss_program_evidence
    assert "safe_local_work_while_blocked" in oss_program_evidence
    assert "#61 -> #62" in oss_program_evidence
    assert "#59 -> #60" in oss_program_evidence
    assert "Consent-only pilot outcome example" in oss_program_evidence
    assert "https://github.com/patchrail/patchrail/issues/27" in oss_program_evidence
    assert "https://github.com/patchrail/patchrail/issues/37" in oss_program_evidence
    assert "https://github.com/patchrail/patchrail/issues/1>" not in oss_program_evidence
    assert "https://github.com/patchrail/patchrail/issues/27" in evidence
    assert "https://github.com/patchrail/patchrail/issues/37" in evidence
    assert "https://github.com/patchrail/patchrail/issues/1>" not in evidence
    assert "Review And Triage Boundary" in workflow_ledger
    assert "formal Codex review unless a public review link is listed" in workflow_ledger
    assert "third-party adoption" in workflow_ledger
    assert "[#69](https://github.com/patchrail/patchrail/issues/69)" in workflow_ledger
    assert "[#79](https://github.com/patchrail/patchrail/pull/79)" in workflow_ledger
    assert "[#78](https://github.com/patchrail/patchrail/pull/78)" in workflow_ledger
    assert "[#77](https://github.com/patchrail/patchrail/pull/77)" in workflow_ledger
    assert "[#76](https://github.com/patchrail/patchrail/pull/76)" in workflow_ledger
    assert "[#68](https://github.com/patchrail/patchrail/issues/68)" in workflow_ledger
    assert "[#75](https://github.com/patchrail/patchrail/pull/75)" in workflow_ledger
    assert "[#86](https://github.com/patchrail/patchrail/pull/86)" in workflow_ledger
    assert "[#87](https://github.com/patchrail/patchrail/pull/87)" in workflow_ledger
    assert "[#94](https://github.com/patchrail/patchrail/pull/94)" in workflow_ledger
    assert "[#102](https://github.com/patchrail/patchrail/pull/102)" in workflow_ledger
    assert "patchrail evidence review-packet --format markdown" in workflow_ledger
    assert (
        "Fixture hygiene gate: `patchrail ci fixture-check examples/ci-triage --format json`"
        in oss_program_evidence
    )
    assert (
        "Tests: `uv run --extra dev pytest -q` -> 84 passed, 6 subtests passed."
        in oss_program_evidence
    )
    assert (
        "Fixture hygiene: `uv run --extra dev patchrail ci fixture-check "
        "examples/ci-triage --format json` -> 143 / 143 fixtures passed."
    ) in oss_program_evidence
    assert "GitHub Release: <https://github.com/patchrail/patchrail/releases/tag/v0.1.0>" in (
        oss_program_evidence
    )
    assert "Agent Control Plane demo" in oss_program_evidence
    assert "Pilot pack importer: `patchrail queue add --from-pilot-pack patchrail-pilot-pack`" in (
        oss_program_evidence
    )
    assert "validates `pilot-manifest.json`, confirms the raw log was not copied" in (
        oss_program_evidence
    )
    assert "Local queue API: `patchrail serve --host 127.0.0.1 --port 8765`" in (
        oss_program_evidence
    )
    assert "human gate summary" in oss_program_evidence
    assert "write actions remain locked" in oss_program_evidence
    assert "Funded issue read-only demo" in oss_program_evidence
    assert "External repositories using PatchRail: pending pilots" in oss_program_evidence
    assert "PyPI release link after package index publish" in oss_program_evidence
    assert "This ledger tracks public PatchRail maintenance cycles" in workflow_ledger
    assert "it does not claim external adoption" in workflow_ledger
    assert "it does not claim formal Codex review unless a visible review link exists" in (
        workflow_ledger
    )
    assert "Public workflow evidence ledger" in workflow_ledger
    assert "[#61](https://github.com/patchrail/patchrail/issues/61)" in workflow_ledger
    assert "[#62](https://github.com/patchrail/patchrail/pull/62)" in workflow_ledger
    assert "Consent-only pilot outcome example" in workflow_ledger
    assert "[#59](https://github.com/patchrail/patchrail/issues/59)" in workflow_ledger
    assert "[#60](https://github.com/patchrail/patchrail/pull/60)" in workflow_ledger
    assert "[#57](https://github.com/patchrail/patchrail/issues/57)" in workflow_ledger
    assert "[#58](https://github.com/patchrail/patchrail/pull/58)" in workflow_ledger
    assert "[#37](https://github.com/patchrail/patchrail/issues/37)" in workflow_ledger
    assert "[#43](https://github.com/patchrail/patchrail/pull/43)" in workflow_ledger
    assert "external adopters: pending consent-only pilots" in workflow_ledger
    assert "formal Codex review examples: pending visible review links" in workflow_ledger
    assert "This is not a substitute for external adoption" in workflow_ledger
    for release_page in [
        ROOT / "docs" / "release-v0.2.0-evidence.md",
        ROOT / "docs" / "release-v0.3.0-evidence.md",
        ROOT / "docs" / "release-v0.4.0-evidence.md",
    ]:
        release_text = release_page.read_text(encoding="utf-8")
        assert "Public workflow ledger: [docs/public-workflow-ledger.md]" in release_text
        assert "Owned-repo issue-to-PR evidence now exists" in release_text
        assert "formal visible\n  Codex review links remain pending" in release_text
        assert (
            "Public Codex review/triage evidence is still pending real PR/issue examples"
            not in (release_text)
        )
    assert "patchrail.queue_api.v1" in api_reference
    assert "write_actions_allowed_by_default" in api_reference
    assert "Approval does not open a pull request" in api_reference
    assert "human gate summary" in api_reference
    assert "write actions remain locked" in api_reference
    assert "patchrail schema queue-work-item" in api_reference
    assert "patchrail schema queue-audit-summary" in api_reference
    assert "patchrail schema application-dossier" in api_reference
    assert "schemas/queue_work_item.schema.json" in api_reference
    assert "schemas/queue_audit_summary.schema.json" in api_reference
    assert "schemas/application_dossier.schema.json" in api_reference
    assert "agent_may_submit=false" in api_reference
    assert "## CLI Audit Summary" in api_reference
    assert "patchrail queue --db patchrail-pilot.sqlite audit-summary --format markdown" in (
        api_reference
    )
    assert "patchrail.queue_audit_summary.v1" in api_reference
    assert "## CLI Queue Bundle" in api_reference
    assert "patchrail queue --db patchrail-pilot.sqlite bundle --format markdown" in api_reference
    assert "patchrail.queue_bundle.v1" in api_reference
    assert "## CLI Queue Imports" in api_reference
    assert "patchrail queue --db patchrail-pilot.sqlite add" in api_reference
    assert "--from-pilot-pack patchrail-pilot-pack" in api_reference
    assert "requires `schema_version=patchrail.ci_pilot_pack.v1`" in api_reference
    assert "rejects manifests where `source.raw_log_copied` is not `false`" in api_reference
    assert "keeps `write_actions_allowed=false`" in api_reference
    assert "does not read or store the original raw CI log" in api_reference
    assert "## CLI Pilot Metrics" in api_reference
    assert "patchrail ci pilot-metrics pilot-summary-*.json --format markdown" in api_reference
    assert "repository_mention_approved=true" in api_reference
    assert "requires no network, external model, billing, or GitHub write permission" in (
        api_reference
    )
    assert "consent-only" in pilot_guide
    assert "does not give PatchRail write access" in pilot_guide
    assert "See [examples/pilot-outcome](../examples/pilot-outcome/README.md)" in pilot_guide
    assert "patchrail redact --log failed-ci.log" in pilot_guide
    assert "patchrail ci classify --log failed-ci.redacted.log --format json" in pilot_guide
    assert "patchrail queue --db patchrail-pilot.sqlite add --from-ci-result" in pilot_guide
    assert "patchrail queue --db patchrail-pilot.sqlite add --from-pilot-pack" in pilot_guide
    assert "The importer validates that the manifest did not copy the raw log" in pilot_guide
    assert "patchrail ci pilot-pack --log failed-ci.log --out-dir patchrail-pilot-pack" in (
        pilot_guide
    )
    assert "patchrail ci pilot-summary --pack patchrail-pilot-pack" in pilot_guide
    assert "--repository-mention-approved yes" in pilot_guide
    assert "defaults to `--repository-mention-approved no`" in pilot_guide
    assert "patchrail ci pilot-metrics pilot-summary-*.json --format markdown" in pilot_guide
    assert "Private or unapproved\nrepository names remain excluded" in pilot_guide
    assert "It does not copy the raw log into the output directory" in pilot_guide
    assert "## Pilot pack boundary" in security
    assert "schema_version=patchrail.ci_pilot_pack.v1" in security
    assert "source.raw_log_copied=false" in security
    assert "creates a pending work item with `write_actions_allowed=false`" in security
    assert "## Pilot pack trust boundary" in threat_model
    assert "`patchrail queue add --from-pilot-pack` accepts either the pack directory" in (
        threat_model
    )
    assert "rejects manifests where" in threat_model
    assert "`source.raw_log_copied` is not `false`" in threat_model
    assert "Queue approval remains local" in threat_model
    assert "pilot-manifest.json" in pilot_guide
    assert "patchrail ci pilot-pack" in roadmap
    assert "patchrail ci pilot-pack" in release_v02
    assert "Synthetic pilot outcome example for safe adopter feedback summaries" in release_v02
    assert "local redacted bundle generated without copying the raw log" in release_v02
    assert "Pilot pack command: `patchrail ci pilot-pack`" in evidence
    assert "Pilot summary command: `patchrail ci pilot-summary`" in evidence
    assert "Pilot pack queue importer: `patchrail queue add --from-pilot-pack`" in evidence
    assert "Pilot summary command: `patchrail ci pilot-summary --pack patchrail-pilot-pack`" in (
        oss_program_evidence
    )
    assert "no raw log copy" in evidence
    assert "Do not share raw logs that contain secrets or personal data" in pilot_guide
    assert "Consent-Only Pilot Request Package" in pilot_request_package
    assert "It is not an outreach automation\ntemplate" in pilot_request_package
    assert "PatchRail should count a pilot as public evidence only after" in (pilot_request_package)
    assert "the maintainer owns the repository or is authorized to test it" in (
        pilot_request_package
    )
    assert "no pull request, issue comment, funded-issue claim, or other write action" in (
        pilot_request_package
    )
    assert "no external model or billing service was required for the pilot" in (
        pilot_request_package
    )
    assert "If any item is missing, keep the result as private feedback" in (pilot_request_package)
    assert "pipx install patchrail" in pilot_request_package
    assert "patchrail doctor --format markdown" in pilot_request_package
    assert "patchrail ci pilot-pack --log failed-ci.log --out-dir patchrail-pilot-pack" in (
        pilot_request_package
    )
    assert "patchrail ci pilot-summary" in pilot_request_package
    assert "--repository owner/repo --repository-mention-approved yes" in (pilot_request_package)
    assert "does not grant repository write permission" in pilot_request_package
    assert "claim funded issues" in pilot_request_package
    assert "The aggregate may count reviewed summaries and approved public repository" in (
        pilot_request_package
    )
    assert "must not turn unapproved private pilots into adopter listings" in (
        pilot_request_package
    )
    assert "docs/pilot-request-package.md" in metrics
    assert "patchrail ci pilot-metrics examples/pilot-outcome/*.summary.json --format markdown" in (
        metrics
    )
    assert "Countable external adopters:" in metrics
    assert "docs/pilot-request-package.md" in adopters
    assert "Consent-only pilot request package" in oss_program_evidence
    assert "Pilot request package" in oss_program_evidence
    assert "Consent-only pilot metrics: `uv run --extra dev patchrail ci pilot-metrics" in (
        oss_program_evidence
    )
    assert "Public review packet: `uv run --extra dev patchrail evidence review-packet" in (
        oss_program_evidence
    )
    assert "Sanitized fixture contribution path" in contributing
    assert "patchrail redact --log failed-ci.log > failed-ci.redacted.log" in contributing
    assert "patchrail ci fixture-check examples/ci-triage --format json" in contributing
    assert "patchrail ci benchmark examples/ci-triage --format json" in contributing
    assert "Do not commit it" in contributing
    assert "the fixture is synthetic" in contributing
    assert "PatchRail tracks adoption and quality metrics" in metrics
    assert "Monthly PyPI downloads" in metrics
    assert "Pending first PyPI release" in metrics
    assert "Public external adopters | 0" in metrics
    assert "patchrail evidence snapshot --format markdown" in metrics
    assert "does not replace\npublic GitHub, PyPI, or adopter metrics" in metrics
    assert "Synthetic consent-only pilot examples | 1" in metrics
    assert "Owned-repo consent-only pilot outcomes | 1" in metrics
    assert "not an external adopter" in metrics
    assert "Public releases | 1" in metrics
    assert "Fixture hygiene gate | 143 / 143 passing" in metrics
    assert "Ruby, PHP, .NET, GitHub Actions, Docker/Compose, browser E2E" in metrics
    assert "Do not use placeholders as evidence" in metrics
    assert "public PRs reviewed with Codex" in metrics
    assert "only with explicit maintainer permission" in adopters
    assert "There are no public external adopters listed yet" in adopters
    assert "examples/pilot-outcome" in adopters
    assert "Use `patchrail redact`" in adopters
    assert "Consent-Only Pilot Outcome Example" in pilot_outcome
    assert "The repository name, log path, and outcome below are synthetic" in pilot_outcome
    assert "Do not count this example as adoption evidence" in pilot_outcome
    assert "patchrail-own-repo-20260603.md" in pilot_outcome
    assert "not an\nexternal adopter listing" in pilot_outcome
    assert "Raw CI log: kept outside the report and never copied into the pilot pack" in (
        pilot_outcome
    )
    assert "Write actions: not allowed" in pilot_outcome
    assert "External models: not used" in pilot_outcome
    assert "patchrail ci pilot-summary --pack patchrail-pilot-pack" in pilot_outcome
    assert "`--repository-mention-approved yes` only after the maintainer explicitly" in (
        pilot_outcome
    )
    assert "Repository approved for public mention: no" in pilot_outcome
    assert "The raw log remains private and was not copied into the pilot pack" in pilot_outcome
    assert "claims that PatchRail fixed code, opened a pull request" in pilot_outcome
    assert "/Volumes/" not in pilot_outcome
    assert "/Users/" not in pilot_outcome
    assert "Repository: `patchrail/patchrail`" in own_repo_pilot
    assert "Root cause: `python_dependency_resolution`" in own_repo_pilot
    assert "PatchRail ran locally" in own_repo_pilot
    assert "did not copy the raw log" in own_repo_pilot
    assert own_repo_pilot_json["public_listing"]["repository"] == "patchrail/patchrail"
    assert own_repo_pilot_json["public_listing"]["repository_mention_approved"] is True
    assert own_repo_pilot_json["pilot_pack"]["manifest_path"] == "pilot-manifest.json"
    assert own_repo_pilot_json["pilot_pack"]["raw_log_copied"] is False
    assert own_repo_pilot_json["requirements"]["external_model_required"] is False
    assert own_repo_pilot_json["requirements"]["github_write_permission_required"] is False
    assert "/Volumes/" not in own_repo_pilot
    assert "/Users/" not in own_repo_pilot
    assert "/home/" not in own_repo_pilot
    assert "/Volumes/" not in json.dumps(own_repo_pilot_json)
    assert "/Users/" not in json.dumps(own_repo_pilot_json)
    assert "/home/" not in json.dumps(own_repo_pilot_json)
    metrics_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "patchrail",
            "ci",
            "pilot-metrics",
            "examples/pilot-outcome/patchrail-own-repo-20260603.summary.json",
            "--format",
            "json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert metrics_proc.returncode == 0, metrics_proc.stderr
    pilot_metrics = json.loads(metrics_proc.stdout)
    assert pilot_metrics["owned_repository_mentions"] == 1
    assert pilot_metrics["external_repository_mentions"] == 0
    assert pilot_metrics["evidence_readiness"]["status"] == "owned_repo_evidence_only"
    assert pilot_metrics["evidence_readiness"]["external_adopters_countable"] == 0
    assert pilot_metrics["owned_repositories"] == ["patchrail/patchrail"]
    assert pilot_metrics["external_repositories"] == []
    assert "/Volumes/" not in metrics_proc.stdout
    assert "/Users/" not in metrics_proc.stdout
    assert "/home/" not in metrics_proc.stdout
    assert "Adopter or pilot report" in adopter_report
    assert "I maintain this repository or have permission" in adopter_report
    assert "PatchRail may list the repository in `ADOPTERS.md`" in adopter_report
    assert "did not need repository write access" in adopter_report
    assert "did not claim a funded issue" in adopter_report
    assert "Use `patchrail redact`" in adopter_report
    assert "Do not quote raw logs that may contain secrets" in ci_skill
    assert "uv run --extra dev patchrail ci benchmark examples/ci-triage --format json" in ci_skill
    assert "Do not publish to PyPI without an explicit maintainer release request" in release_skill
    assert "uv run --extra dev twine check dist/*" in release_skill
    assert "automatic bounty or funded-issue claiming" in guardrails_skill
    assert "GitHub write actions without dry-run and human approval" in guardrails_skill


def test_release_evidence_pages_cover_v01_to_v04_without_publish_actions() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    release_process = (ROOT / "docs" / "release-process.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap.md").read_text(encoding="utf-8")
    oss_evidence = (ROOT / "docs" / "openai-codex-for-oss-evidence.md").read_text(encoding="utf-8")

    for version in ("v0.1.0", "v0.2.0", "v0.3.0", "v0.4.0"):
        path = ROOT / "docs" / f"release-{version}-evidence.md"
        doc = path.read_text(encoding="utf-8")

        assert f"docs/release-{version}-evidence.md" in readme
        assert f"release-{version}-evidence.md" in release_process
        assert f"release-{version}-evidence.md" in oss_evidence
        assert "PyPI" in doc
        assert "external applications" in doc or "external program" in doc

    v01 = (ROOT / "docs" / "release-v0.1.0-evidence.md").read_text(encoding="utf-8")
    assert "Published release:" in v01
    assert "Manual Gates Remaining" in v01
    assert "publish the package to PyPI when package index credentials are available" in v01
    assert "announce the release publicly" in v01
    assert "submit the Codex for Open Source application" in v01

    for version in ("v0.2.0", "v0.3.0", "v0.4.0"):
        doc = (ROOT / "docs" / f"release-{version}-evidence.md").read_text(encoding="utf-8")
        assert "Status:" in doc
        assert "not a published release" in doc
        assert "Manual Gates Before Publishing" in doc
        assert "Publish to PyPI only when the maintainer has configured the credential" in doc
        assert "Announce or request external program review only with real, current metrics" in doc
        assert (
            ("contact third-party" in doc and "maintainers" in doc)
            or "external applications" in doc
            or "external program applications" in doc
        )

    v03 = (ROOT / "docs" / "release-v0.3.0-evidence.md").read_text(encoding="utf-8")
    v04 = (ROOT / "docs" / "release-v0.4.0-evidence.md").read_text(encoding="utf-8")

    assert "Agent Control Plane" in roadmap
    assert "v0.3.0 release-candidate evidence page" in roadmap
    assert "Funded Issue Scout read-only" in roadmap
    assert "v0.4.0 release-candidate evidence page" in roadmap

    assert "examples/local-agent-queue/run_demo.py" in v03
    assert "queue add --from-pilot-pack" in v03
    assert "patchrail queue bundle" in v03
    assert "patchrail schema queue-work-item" in v03
    assert "patchrail serve --host 127.0.0.1 --port 8765" in v03
    assert "Proposal approval/rejection records human decisions only" in release_process
    assert "No pull request creation" in v03
    assert "GitHub write permissions" in v03

    assert "examples/funded-issues-readonly/run_demo.py" in v04
    assert "patchrail funded-issues list" in v04
    assert "patchrail funded-issues import" in v04
    assert "No funded issue command fetches provider APIs" in release_process
    assert "automatic claims" in v04
    assert "money-only ranking" in v04


def test_local_agent_queue_demo_runs_end_to_end_with_stable_summary() -> None:
    expected = json.loads(
        (ROOT / "examples" / "local-agent-queue" / "demo-summary.expected.json").read_text(
            encoding="utf-8"
        )
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = subprocess.run(
            [
                sys.executable,
                "examples/local-agent-queue/run_demo.py",
                "--output",
                tmpdir,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        assert proc.returncode == 0, proc.stderr
        summary = json.loads((Path(tmpdir) / "summary.json").read_text(encoding="utf-8"))
        assert summary == expected

        for artifact in expected["artifact_files"]:
            assert (Path(tmpdir) / artifact).exists()

        report = (Path(tmpdir) / "pilot-pack" / "patchrail-report.md").read_text(encoding="utf-8")
        item = json.loads((Path(tmpdir) / "approved.json").read_text(encoding="utf-8"))
        rejected_item = json.loads(
            (Path(tmpdir) / "rejected-item.json").read_text(encoding="utf-8")
        )
        queue_before_decisions = json.loads(
            (Path(tmpdir) / "queue-before-decisions.json").read_text(encoding="utf-8")
        )
        proposal = json.loads((Path(tmpdir) / "proposal-approved.json").read_text(encoding="utf-8"))
        rejected_proposal = json.loads(
            (Path(tmpdir) / "proposal-rejected.json").read_text(encoding="utf-8")
        )
        rejected_proposal_markdown = (Path(tmpdir) / "proposal-rejected.md").read_text(
            encoding="utf-8"
        )
        bundle = json.loads((Path(tmpdir) / "bundle.json").read_text(encoding="utf-8"))
        bundle_markdown = (Path(tmpdir) / "bundle.md").read_text(encoding="utf-8")
        events = [
            json.loads(line)
            for line in (Path(tmpdir) / "audit-events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]

        assert "PatchRail classified this log locally" in report
        assert "did not create a pull request" in report
        assert item["write_actions_allowed"] is False
        assert item["payload"]["markdown_report"] == "pilot-pack/patchrail-report.md"
        assert item["payload"]["ci_result"]["requirements"]["external_model_required"] is False
        assert item["payload"]["pilot_pack"]["raw_log_copied"] is False
        assert item["payload"]["pilot_pack"]["maintainer_review_required_before_sharing"] is True
        assert rejected_item["approval_state"] == "rejected"
        assert rejected_item["write_actions_allowed"] is False
        assert len(queue_before_decisions["work_items"]) == 2
        assert proposal["approval_state"] == "approved"
        assert proposal["risk_level"] == "low"
        assert rejected_proposal["approval_state"] == "rejected"
        assert rejected_proposal["risk_level"] == "high"
        assert "Open a pull request immediately" in rejected_proposal_markdown
        assert "does not push commits" in rejected_proposal_markdown
        assert bundle["status"] == "ready_for_handoff"
        assert bundle["remaining_gate_gaps"] == []
        assert bundle["safety"]["bundle_is_read_only"] is True
        assert bundle["safety"]["bundle_records_audit_event"] is False
        assert bundle["safety"]["local_paths_redacted"] is True
        assert "/Volumes/" not in json.dumps(bundle)
        assert "/Users/" not in json.dumps(bundle)
        assert "/home/" not in json.dumps(bundle)
        assert "# PatchRail Queue Bundle" in bundle_markdown
        assert "Bundle is read-only: `True`" in bundle_markdown
        assert [event["event_type"] for event in events] == expected["audit_event_types"]


def test_funded_issues_docs_preserve_read_only_boundary() -> None:
    docs = (ROOT / "docs" / "funded-issues-ethics.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap.md").read_text(encoding="utf-8")
    example = (ROOT / "examples" / "funded-issues-readonly" / "README.md").read_text(
        encoding="utf-8"
    )

    combined = "\n".join([docs, roadmap, example])
    assert "patchrail funded-issues list" in combined
    assert "patchrail funded-issues explain" in combined
    assert "does not claim rewards" in combined
    assert "does not permit write actions" in combined
    assert "No automatic claims, comments, pull requests" in roadmap
    assert "local JSON" in combined


def test_ci_workflow_builds_and_smokes_installable_package() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    release_process = (ROOT / "docs" / "release-process.md").read_text(encoding="utf-8")
    release_evidence = (ROOT / "docs" / "release-v0.1.0-evidence.md").read_text(encoding="utf-8")
    release_v02_evidence = (ROOT / "docs" / "release-v0.2.0-evidence.md").read_text(
        encoding="utf-8"
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    oss_evidence = (ROOT / "docs" / "openai-codex-for-oss-evidence.md").read_text(encoding="utf-8")
    program_evidence = (ROOT / "docs" / "oss-program-evidence.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "release_readiness.py").read_text(encoding="utf-8")

    assert "package-smoke:" in workflow
    assert "uv run --extra dev python -m build" in workflow
    assert "uv run --extra dev twine check dist/*" in workflow
    assert "uv run ruff format --check ." in workflow
    assert '"/.agents"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"/scripts"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "python -m venv .pkg-smoke" in workflow
    assert "python -m pip install dist/*.whl" in workflow
    assert "patchrail doctor --format json" in workflow
    assert '"/ADOPTERS.md"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "oss-evidence-snapshot:" in workflow
    assert "needs: [test, package-smoke]" in workflow
    assert "uv run patchrail evidence snapshot --format json" in workflow
    assert "uv run patchrail evidence snapshot --format markdown" in workflow
    assert "actions/upload-artifact@v7.0.1" in workflow
    assert "name: patchrail-oss-evidence" in workflow
    assert "patchrail-oss-evidence/evidence-snapshot.json" in workflow
    assert "patchrail-oss-evidence/evidence-snapshot.md" in workflow

    assert "patchrail evidence release-readiness --clean-dist" in readme
    assert "patchrail evidence release-readiness --clean-dist" in release_process
    assert "patchrail evidence release-readiness --clean-dist" in release_evidence
    assert "scripts/release_readiness.py" in release_evidence
    assert "patchrail.release_readiness.v1" in script
    assert "--no-index" in script
    assert "published_to_pypi" in script
    assert "created_release_tag" in script
    assert "contacted_third_parties" in script
    assert "github_write_permission_required" in script

    assert "python -m pip install dist/*.whl" in release_process
    assert "patchrail ci explain --log examples/ci-triage/dependency-failure.log" in release_process
    assert "release-v0.1.0-evidence.md" in release_process
    assert "release-v0.2.0-evidence.md" in release_process
    assert "docs/release-v0.1.0-evidence.md" in readme
    assert "release-v0.1.0-evidence.md" in oss_evidence

    assert "dist/patchrail-0.1.0.tar.gz" in release_evidence
    assert "dist/patchrail-0.1.0-py3-none-any.whl" in release_evidence
    assert "Tests: 32 passed." in release_evidence
    assert "Tests: 34 passed." in release_evidence
    assert "Benchmark: 124 total, 124 passed, 0 failed." in release_evidence
    assert "https://github.com/patchrail/patchrail/pull/17" in release_evidence

    assert "Status: release candidate evidence, not a published release." in release_v02_evidence
    assert "uv run --extra dev patchrail ci fixture-check examples/ci-triage --format json" in (
        release_v02_evidence
    )
    assert "Tests: 54 passed." in release_v02_evidence
    assert "Format: 20 files already formatted." in release_v02_evidence
    assert "Fixture hygiene: 143 / 143 fixtures passed." in release_v02_evidence
    assert "Benchmark: 143 total, 143 passed, 0 failed." in release_v02_evidence
    assert "Top-1 fixture accuracy: 1.0." in release_v02_evidence
    assert "Class coverage: 14 root-cause families." in release_v02_evidence
    assert "Bump `pyproject.toml` from `0.1.0` to `0.2.0`." in release_v02_evidence
    assert "Publish to PyPI only when the maintainer has configured the credential." in (
        release_v02_evidence
    )
    assert "External adoption evidence is still pending consent-only pilots." in (
        release_v02_evidence
    )
    assert "release-v0.2.0-evidence.md" in program_evidence
    assert "v0.2.0 release-candidate evidence page" in roadmap
    assert "## 0.2.0 - draft" in changelog
    assert "https://github.com/patchrail/patchrail/actions/runs/26869827161" in release_evidence
    assert "https://github.com/patchrail/patchrail/releases/tag/v0.1.0" in release_evidence
    assert "07b4934d91866c3ea2978c2aff265f923cd232bf" in release_evidence
    assert "5f1f91e36fce4197a6cf8405da2ac5bfcbb6cefa1cb393464349c868e9719dfd" in release_evidence
    assert "package-smoke" in release_evidence
    assert "manual maintainer gate" in release_evidence
    assert "publish the package to PyPI" in release_evidence
    assert "no automatic pull requests" in release_evidence


def test_release_readiness_evidence_cli_is_documented_and_non_publishing() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "patchrail", "evidence", "release-readiness", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    cli = (ROOT / "src" / "patchrail" / "cli.py").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "release_readiness.py").read_text(encoding="utf-8")

    assert proc.returncode == 0, proc.stderr
    assert "Build and smoke-test local release artifacts without publishing" in proc.stdout
    assert "--clean-dist" in proc.stdout
    assert "--dist-dir" in proc.stdout
    assert "_evidence_release_readiness" in cli
    assert "scripts/release_readiness.py" in cli
    assert "published_to_pypi" in script
    assert "created_release_tag" in script
    assert "contacted_third_parties" in script


def test_application_dossier_compiles_evidence_without_submission_permission() -> None:
    help_proc = subprocess.run(
        [sys.executable, "-m", "patchrail", "evidence", "application-dossier", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    json_proc = subprocess.run(
        [sys.executable, "-m", "patchrail", "evidence", "application-dossier", "--format", "json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    markdown_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "patchrail",
            "evidence",
            "application-dossier",
            "--format",
            "markdown",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    oss_evidence = (ROOT / "docs" / "oss-program-evidence.md").read_text(encoding="utf-8")
    codex_evidence = (ROOT / "docs" / "openai-codex-for-oss-evidence.md").read_text(
        encoding="utf-8"
    )
    cli = (ROOT / "src" / "patchrail" / "cli.py").read_text(encoding="utf-8")

    assert help_proc.returncode == 0, help_proc.stderr
    assert json_proc.returncode == 0, json_proc.stderr
    assert markdown_proc.returncode == 0, markdown_proc.stderr
    assert "Compile a local external-program application dossier without submitting it" in (
        help_proc.stdout
    )

    payload = json.loads(json_proc.stdout)
    assert payload["schema_version"] == "patchrail.application_dossier.v1"
    assert payload["status"] == "draft_only_do_not_submit"
    assert payload["application_gate"]["decision"] == "do_not_apply_yet"
    assert payload["signals"]["ci_fixtures"] == 143
    assert payload["signals"]["upstream_contribution_count"] == 2
    assert payload["signals"]["merged_upstream_contribution_count"] == 1
    assert payload["signals"]["open_upstream_pr_count"] == 1
    assert payload["reviewer_quick_checks"] == [
        {
            "name": "single-command local reviewer check",
            "command": (
                "uv run --extra dev patchrail evidence reviewer-packet "
                "--out-dir patchrail-reviewer-packet"
            ),
            "expected": (
                "local Markdown and JSON packet with doctor, CI demo, fail-closed "
                "application gate, and application dossier contract"
            ),
            "network_required": False,
            "write_action_required": False,
        },
        {
            "name": "10-second no-install demo",
            "command": (
                "open examples/ci-triage/demo-output.md and compare with "
                "uv run --extra dev patchrail ci explain --log "
                "examples/ci-triage/dependency-failure.log --format markdown"
            ),
            "expected": "real CLI output for the bundled fixture; tests prevent drift",
            "network_required": False,
            "write_action_required": False,
        },
        {
            "name": "pre-PyPI source install smoke",
            "command": "uvx --from git+https://github.com/patchrail/patchrail patchrail --help",
            "expected": "runs from GitHub source while PyPI publish is pending",
            "network_required": True,
            "write_action_required": False,
        },
        {
            "name": "fail-closed application gate",
            "command": "patchrail evidence application-gate --format markdown",
            "expected": "returns not_ready / do_not_apply_yet until real public evidence exists",
            "network_required": False,
            "write_action_required": False,
        },
        {
            "name": "local application dossier",
            "command": "patchrail evidence application-dossier --format markdown",
            "expected": "draft only; maintainer tap required before any external form submission",
            "network_required": False,
            "write_action_required": False,
        },
    ]
    assert payload["submission_policy"]["maintainer_tap_required"] is True
    assert payload["submission_policy"]["agent_may_submit"] is False
    assert payload["submission_policy"]["form_submission_allowed_by_gate"] is False
    assert payload["submission_policy"]["no_money_goal"] is True
    assert payload["safety"]["network_required"] is False
    assert payload["safety"]["github_write_permission_required"] is False
    assert payload["safety"]["third_party_write_actions_allowed"] is False
    assert payload["safety"]["application_form_write_action"] is True
    assert "https://github.com/jamie8johnson/cqs/pull/1650" in json_proc.stdout
    assert "https://github.com/pypa/twine/pull/1329" in json_proc.stdout
    assert "## Reviewer Quick Checks" in markdown_proc.stdout
    assert "single-command local reviewer check" in markdown_proc.stdout
    assert "10-second no-install demo" in markdown_proc.stdout
    assert "pre-PyPI source install smoke" in markdown_proc.stdout
    assert "Write action required: `False`" in markdown_proc.stdout
    assert "Maintainer tap required: `True`" in markdown_proc.stdout
    assert "Agent may submit: `False`" in markdown_proc.stdout

    combined_docs = "\n".join([readme, oss_evidence, codex_evidence])
    assert "patchrail evidence application-dossier --format markdown" in readme
    assert "patchrail evidence application-dossier --format json" in combined_docs
    assert "reviewer_quick_checks" in combined_docs
    assert "scripts/reviewer_quick_check.py" in combined_docs
    assert "patchrail schema application-dossier" in combined_docs
    assert "schemas/application_dossier.schema.json" in combined_docs
    assert "Single-command reviewer check" in combined_docs
    assert "reviewer_quick_checks" in codex_evidence
    assert "patchrail.application_dossier.v1" in codex_evidence
    assert "fail-closed application gate" in codex_evidence
    assert "10-second no-install demo" in combined_docs
    assert "pre-PyPI source install smoke" in combined_docs
    assert "agent_may_submit=false" in combined_docs
    assert "maintainer tap" in combined_docs
    normalized_combined_docs = combined_docs.replace("\n  ", " ")
    assert "merged upstream fixes = 1" in combined_docs
    assert "open upstream PRs awaiting external maintainer review = 1" in (normalized_combined_docs)
    normalized_codex_evidence = codex_evidence.replace("\n  ", " ")
    assert "not counted as a merge or adoption signal" in normalized_codex_evidence
    assert "_evidence_application_dossier" in cli
    assert "patchrail.application_dossier.v1" in cli


def test_ci_evidence_reference_refresh_script_is_local_and_guardrailed() -> None:
    script = ROOT / "scripts" / "update_ci_evidence_reference.py"
    release_process = (ROOT / "docs" / "release-process.md").read_text(encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--repo",
            str(ROOT),
            "--run-url",
            "https://github.com/patchrail/patchrail/actions/runs/27054439302",
            "--commit",
            "c4fbd859d4d69c00215faf1acec2be5e24e98b03",
            "--dry-run",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    bad_proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--repo",
            str(ROOT),
            "--run-url",
            "https://github.com/example/project/actions/runs/1",
            "--commit",
            "c4fbd859d4d69c00215faf1acec2be5e24e98b03",
            "--dry-run",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert "validated:" in proc.stdout
    assert "docs/openai-codex-for-oss-evidence.md" in proc.stdout
    assert "tests/test_public_workflows.py" in proc.stdout
    assert bad_proc.returncode == 2
    assert "patchrail/patchrail GitHub Actions run URL" in bad_proc.stderr
    assert (
        "scripts/update_ci_evidence_reference.py --run-url <actions-run-url> --commit <full-sha>"
        in release_process
    )
