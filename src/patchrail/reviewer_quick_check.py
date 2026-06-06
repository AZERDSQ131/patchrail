from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _run_patchrail(
    args: list[str], *, root: Path, allow_nonzero: bool = False
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        [sys.executable, "-m", "patchrail", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 and not allow_nonzero:
        sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode)
    return proc


def _fenced(label: str, text: str) -> str:
    cleaned = text.strip()
    return f"```{label}\n{cleaned}\n```"


def _display_path(path: Path, *, root: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _release_readiness_markdown(payload: dict[str, object]) -> str:
    checks = payload["checks"]
    safety = payload["safety"]
    if not isinstance(checks, dict) or not isinstance(safety, dict):
        raise ValueError("release readiness payload must include checks and safety objects")

    lines = [
        "# PatchRail Release Readiness",
        "",
        f"- Schema: `{payload['schema_version']}`",
        f"- Version: `{payload['version']}`",
        f"- Published to PyPI: `{payload['published']}`",
        f"- Build: `{checks['build']}`",
        f"- Twine check: `{checks['twine_check']}`",
        f"- Wheel smoke: `{checks['wheel_smoke']}`",
        f"- Doctor status: `{checks['doctor_status']}`",
        f"- Fixture smoke class: `{checks['fixture_failure_class']}`",
        "",
        "## Artifacts",
        "",
    ]
    artifacts = payload["artifacts"]
    if not isinstance(artifacts, list):
        raise ValueError("release readiness payload must include an artifacts list")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("release readiness artifacts must be objects")
        lines.append(
            f"- `{artifact['file']}`: sha256 `{artifact['sha256']}`, {artifact['size_bytes']} bytes"
        )

    lines.extend(
        [
            "",
            "## Safety",
            "",
            f"- Local-first: `{safety['local_first']}`",
            f"- Created release tag: `{safety['created_release_tag']}`",
            f"- Announced publicly: `{safety['announced_publicly']}`",
            f"- Contacted third parties: `{safety['contacted_third_parties']}`",
            f"- GitHub write permission required: `{safety['github_write_permission_required']}`",
            f"- External model required: `{safety['external_model_required']}`",
            "",
            "## Manual Gates Remaining",
            "",
        ]
    )
    gates = payload["manual_gates_remaining"]
    if not isinstance(gates, list):
        raise ValueError("release readiness payload must include manual gates")
    lines.extend(f"- {gate}" for gate in gates)
    return "\n".join(lines) + "\n"


def _write_artifacts(
    out_dir: Path,
    *,
    ci_report: str,
    release_readiness_text: str,
    release_readiness_json: str,
    control_plane_text: str,
    control_plane_json: str,
    http_api_text: str,
    http_api_json: str,
    gate_text: str,
    dossier_text: str,
    dossier_json: str,
    dossier_schema: str,
    reviewer_packet_schema: str,
) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "README.md": _reviewer_packet_readme(),
        "ci-triage-demo.md": ci_report,
        "release-readiness.md": release_readiness_text,
        "release-readiness.json": release_readiness_json,
        "control-plane-evidence.md": control_plane_text,
        "control-plane-evidence.json": control_plane_json,
        "http-api-evidence.md": http_api_text,
        "http-api-evidence.json": http_api_json,
        "application-gate.txt": gate_text,
        "application-dossier.txt": dossier_text,
        "application-dossier.json": dossier_json,
        "application-dossier.schema.json": dossier_schema,
        "reviewer-quick-check-artifacts.schema.json": reviewer_packet_schema,
    }
    for name, content in artifacts.items():
        (out_dir / name).write_text(content.strip() + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "patchrail.reviewer_quick_check_artifacts.v1",
        "generated_from": "local_checkout",
        "network_required": False,
        "write_action_required": False,
        "application_form_submission_performed": False,
        "artifacts": ["reviewer-quick-check.md", *sorted(artifacts)],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ["reviewer-quick-check.md", *sorted(artifacts), "manifest.json"]


def _reviewer_packet_readme() -> str:
    return """
# PatchRail Reviewer Packet

This directory is a local, reviewer-facing evidence bundle generated from a
checked-out PatchRail source tree.

## Review Order

1. `reviewer-quick-check.md` - human-readable walkthrough of the local smoke
   test, CI triage demo, Agent Control Plane evidence, fail-closed application
   gate, and application dossier contract.
2. `ci-triage-demo.md` - real local CI Janitor output for the bundled fixture.
3. `release-readiness.md` and `release-readiness.json` - local build,
   `twine check`, wheel smoke, and manual publish gates. They do not publish to
   PyPI or create a release tag.
4. `control-plane-evidence.md` and `control-plane-evidence.json` - local queue
   handoff evidence with human gates complete and execution disabled.
5. `http-api-evidence.md` and `http-api-evidence.json` - ephemeral
   `127.0.0.1` HTTP API smoke evidence with endpoints and human gates checked.
6. `application-gate.txt` - expected fail-closed result until public evidence
   is real.
7. `application-dossier.txt` and `application-dossier.json` - local draft
   dossier; it does not submit any external form.
8. `manifest.json` plus the schema files - offline validation contract.

## Safety Boundary

- Network required: `False`
- Write action required: `False`
- Application form submission performed: `False`
- PyPI publish performed: `False`
- Third-party pull request, issue comment, or funded-issue claim performed:
  `False`
"""


def build_reviewer_quick_check(*, root: Path, out_dir: Path | None = None) -> str:
    doctor = _run_patchrail(["doctor", "--format", "text"], root=root)
    ci_report = _run_patchrail(
        [
            "ci",
            "explain",
            "--log",
            "examples/ci-triage/dependency-failure.log",
            "--format",
            "markdown",
        ],
        root=root,
    )
    release_readiness_json = _run_patchrail(
        ["evidence", "release-readiness", "--clean-dist", "--format", "json"],
        root=root,
    )
    release_readiness_text = _release_readiness_markdown(json.loads(release_readiness_json.stdout))
    control_plane = _run_patchrail(
        ["evidence", "control-plane", "--format", "markdown"],
        root=root,
    )
    control_plane_json = _run_patchrail(
        ["evidence", "control-plane", "--format", "json"],
        root=root,
    )
    http_api = _run_patchrail(
        ["evidence", "http-api", "--format", "markdown"],
        root=root,
    )
    http_api_json = _run_patchrail(
        ["evidence", "http-api", "--format", "json"],
        root=root,
    )
    gate = _run_patchrail(
        ["evidence", "application-gate", "--format", "text"],
        root=root,
        allow_nonzero=True,
    )
    dossier = _run_patchrail(["evidence", "application-dossier", "--format", "text"], root=root)
    dossier_json = _run_patchrail(
        ["evidence", "application-dossier", "--format", "json"], root=root
    )
    dossier_schema = _run_patchrail(["schema", "application-dossier"], root=root)
    reviewer_packet_schema = _run_patchrail(["schema", "reviewer-quick-check-artifacts"], root=root)

    lines = [
        "# PatchRail Reviewer Quick Check",
        "",
        "This local smoke test uses the checked-out source tree only. It does not",
        "publish to PyPI, create pull requests, post comments, claim funding, call",
        "external models, or require GitHub write permissions.",
        "",
        "## 1. Local Doctor",
        "",
        _fenced("text", doctor.stdout),
        "",
        "## 2. CI Triage Demo",
        "",
        _fenced(
            "bash",
            (
                "uv run --extra dev patchrail ci explain --log "
                "examples/ci-triage/dependency-failure.log --format markdown"
            ),
        ),
        "",
        _fenced("markdown", ci_report.stdout),
        "",
        "## 3. Release Readiness Evidence",
        "",
        "This local evidence builds and smoke-tests release artifacts, but leaves",
        "PyPI publish, release tagging, public announcements, and external program",
        "submission behind manual gates.",
        "",
        _fenced("markdown", release_readiness_text),
        "",
        "## 4. Agent Control Plane Evidence",
        "",
        "The local queue demo must be ready for reviewer handoff, exercise human",
        "approval gates, and keep execution disabled.",
        "",
        _fenced("markdown", control_plane.stdout),
        "",
        "## 5. HTTP API Evidence",
        "",
        "The local HTTP smoke starts an ephemeral loopback server, exercises the",
        "public endpoints, records approval/rejection decisions, and confirms",
        "that write actions remain locked.",
        "",
        _fenced("markdown", http_api.stdout),
        "",
        "## 6. Application Gate",
        "",
        "The gate is expected to fail closed until public evidence is real.",
        "",
        _fenced("text", gate.stdout),
        "",
        "## 7. Application Dossier Contract",
        "",
        "The dossier is a local draft artifact. It does not submit the external",
        "application and keeps maintainer tap required.",
        "",
        _fenced("text", dossier.stdout),
        "",
        "Schema smoke:",
        "",
        _fenced("json", dossier_schema.stdout),
        "",
        "Reviewer packet manifest schema smoke:",
        "",
        _fenced("json", reviewer_packet_schema.stdout),
        "",
    ]
    written_artifacts: list[str] = []
    if out_dir:
        written_artifacts = _write_artifacts(
            out_dir,
            ci_report=ci_report.stdout,
            release_readiness_text=release_readiness_text,
            release_readiness_json=release_readiness_json.stdout,
            control_plane_text=control_plane.stdout,
            control_plane_json=control_plane_json.stdout,
            http_api_text=http_api.stdout,
            http_api_json=http_api_json.stdout,
            gate_text=gate.stdout,
            dossier_text=dossier.stdout,
            dossier_json=dossier_json.stdout,
            dossier_schema=dossier_schema.stdout,
            reviewer_packet_schema=reviewer_packet_schema.stdout,
        )
        lines.extend(
            [
                "## 8. Artifact Packet",
                "",
                f"Output directory: `{_display_path(out_dir, root=root)}`",
                "",
                *[f"- `{name}`" for name in written_artifacts],
                "",
            ]
        )

    lines.extend(
        [
            "## Result",
            "",
            "- Reviewer demo generated: `True`",
            "- Release readiness evidence generated: `True`",
            "- Agent Control Plane evidence generated: `True`",
            "- HTTP API evidence generated: `True`",
            "- Application dossier generated: `True`",
            "- Application dossier schema available: `True`",
            "- Reviewer packet manifest schema available: `True`",
            f"- Artifact packet generated: `{'True' if written_artifacts else 'False'}`",
            "- Network required: `False`",
            "- Write action required: `False`",
            "- Application form submission performed: `False`",
        ]
    )
    final_output = "\n".join(lines)
    if out_dir:
        (out_dir / "reviewer-quick-check.md").write_text(final_output + "\n", encoding="utf-8")
    return final_output + "\n"


def main(argv: list[str] | None = None, *, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a local PatchRail reviewer quick check packet."
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Optional directory for reviewer-facing Markdown/JSON artifacts.",
    )
    args = parser.parse_args(argv)
    print(build_reviewer_quick_check(root=root or Path("."), out_dir=args.out_dir), end="")
    return 0
