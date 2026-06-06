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


def _write_artifacts(
    out_dir: Path,
    *,
    ci_report: str,
    control_plane_text: str,
    control_plane_json: str,
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
        "control-plane-evidence.md": control_plane_text,
        "control-plane-evidence.json": control_plane_json,
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
3. `control-plane-evidence.md` and `control-plane-evidence.json` - local queue
   handoff evidence with human gates complete and execution disabled.
4. `application-gate.txt` - expected fail-closed result until public evidence
   is real.
5. `application-dossier.txt` and `application-dossier.json` - local draft
   dossier; it does not submit any external form.
6. `manifest.json` plus the schema files - offline validation contract.

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
    control_plane = _run_patchrail(
        ["evidence", "control-plane", "--format", "markdown"],
        root=root,
    )
    control_plane_json = _run_patchrail(
        ["evidence", "control-plane", "--format", "json"],
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
        "## 3. Agent Control Plane Evidence",
        "",
        "The local queue demo must be ready for reviewer handoff, exercise human",
        "approval gates, and keep execution disabled.",
        "",
        _fenced("markdown", control_plane.stdout),
        "",
        "## 4. Application Gate",
        "",
        "The gate is expected to fail closed until public evidence is real.",
        "",
        _fenced("text", gate.stdout),
        "",
        "## 5. Application Dossier Contract",
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
            control_plane_text=control_plane.stdout,
            control_plane_json=control_plane_json.stdout,
            gate_text=gate.stdout,
            dossier_text=dossier.stdout,
            dossier_json=dossier_json.stdout,
            dossier_schema=dossier_schema.stdout,
            reviewer_packet_schema=reviewer_packet_schema.stdout,
        )
        lines.extend(
            [
                "## 6. Artifact Packet",
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
            "- Agent Control Plane evidence generated: `True`",
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
