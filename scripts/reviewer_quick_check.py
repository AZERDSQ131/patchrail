#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_patchrail(
    args: list[str], *, allow_nonzero: bool = False
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        [sys.executable, "-m", "patchrail", *args],
        cwd=ROOT,
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


def _display_path(path: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def _write_artifacts(
    out_dir: Path,
    *,
    ci_report: str,
    gate_text: str,
    dossier_text: str,
    dossier_json: str,
    dossier_schema: str,
) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "ci-triage-demo.md": ci_report,
        "application-gate.txt": gate_text,
        "application-dossier.txt": dossier_text,
        "application-dossier.json": dossier_json,
        "application-dossier.schema.json": dossier_schema,
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a local PatchRail reviewer quick check packet."
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Optional directory for reviewer-facing Markdown/JSON artifacts.",
    )
    args = parser.parse_args(argv)

    doctor = _run_patchrail(["doctor", "--format", "text"])
    ci_report = _run_patchrail(
        [
            "ci",
            "explain",
            "--log",
            "examples/ci-triage/dependency-failure.log",
            "--format",
            "markdown",
        ]
    )
    gate = _run_patchrail(["evidence", "application-gate", "--format", "text"], allow_nonzero=True)
    dossier = _run_patchrail(["evidence", "application-dossier", "--format", "text"])
    dossier_json = _run_patchrail(["evidence", "application-dossier", "--format", "json"])
    dossier_schema = _run_patchrail(["schema", "application-dossier"])

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
        "## 3. Application Gate",
        "",
        "The gate is expected to fail closed until public evidence is real.",
        "",
        _fenced("text", gate.stdout),
        "",
        "## 4. Application Dossier Contract",
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
    ]
    written_artifacts: list[str] = []
    if args.out_dir:
        written_artifacts = _write_artifacts(
            args.out_dir,
            ci_report=ci_report.stdout,
            gate_text=gate.stdout,
            dossier_text=dossier.stdout,
            dossier_json=dossier_json.stdout,
            dossier_schema=dossier_schema.stdout,
        )
        lines.extend(
            [
                "## 5. Artifact Packet",
                "",
                f"Output directory: `{_display_path(args.out_dir)}`",
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
            "- Application dossier generated: `True`",
            "- Application dossier schema available: `True`",
            f"- Artifact packet generated: `{'True' if written_artifacts else 'False'}`",
            "- Network required: `False`",
            "- Write action required: `False`",
            "- Application form submission performed: `False`",
        ]
    )
    final_output = "\n".join(lines)
    if args.out_dir:
        (args.out_dir / "reviewer-quick-check.md").write_text(final_output + "\n", encoding="utf-8")
    print(final_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
