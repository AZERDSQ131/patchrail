#!/usr/bin/env python3
from __future__ import annotations

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


def main() -> int:
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
    dossier_schema = _run_patchrail(["schema", "application-dossier"])

    print("# PatchRail Reviewer Quick Check")
    print()
    print("This local smoke test uses the checked-out source tree only. It does not")
    print("publish to PyPI, create pull requests, post comments, claim funding, call")
    print("external models, or require GitHub write permissions.")
    print()
    print("## 1. Local Doctor")
    print()
    print(_fenced("text", doctor.stdout))
    print()
    print("## 2. CI Triage Demo")
    print()
    print(
        _fenced(
            "bash",
            (
                "uv run --extra dev patchrail ci explain --log "
                "examples/ci-triage/dependency-failure.log --format markdown"
            ),
        )
    )
    print()
    print(_fenced("markdown", ci_report.stdout))
    print()
    print("## 3. Application Gate")
    print()
    print("The gate is expected to fail closed until public evidence is real.")
    print()
    print(_fenced("text", gate.stdout))
    print()
    print("## 4. Application Dossier Contract")
    print()
    print("The dossier is a local draft artifact. It does not submit the external")
    print("application and keeps maintainer tap required.")
    print()
    print(_fenced("text", dossier.stdout))
    print()
    print("Schema smoke:")
    print()
    print(_fenced("json", dossier_schema.stdout))
    print()
    print("## Result")
    print()
    print("- Reviewer demo generated: `True`")
    print("- Application dossier generated: `True`")
    print("- Application dossier schema available: `True`")
    print("- Network required: `False`")
    print("- Write action required: `False`")
    print("- Application form submission performed: `False`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
