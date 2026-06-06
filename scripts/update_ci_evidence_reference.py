#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


RUN_URL_RE = re.compile(r"^https://github\.com/patchrail/patchrail/actions/runs/(\d+)$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DOCS_BLOCK_RE = re.compile(
    r"- Recent successful public CI run:\n"
    r"  <https://github\.com/patchrail/patchrail/actions/runs/\d+> completed\n"
    r"  successfully for commit `[0-9a-f]{40}`, including\n"
    r"  Python 3\.11/3\.12/3\.13 tests, fixture benchmark, CLI smoke,\n"
    r"  package-smoke, and the OSS evidence snapshot job\. The uploaded\n"
    r"  `patchrail-oss-evidence` artifact includes the general snapshot, Agent\n"
    r"  Control Plane evidence, application dossier, and the reviewer-facing local queue bundle\.",
    re.MULTILINE,
)
TEST_PAIR_RE = re.compile(
    r'assert "https://github\.com/patchrail/patchrail/actions/runs/\d+" in evidence\n'
    r'    assert "[0-9a-f]{40}" in evidence'
)


def _build_docs_block(run_url: str, commit: str) -> str:
    return "\n".join(
        [
            "- Recent successful public CI run:",
            f"  <{run_url}> completed",
            f"  successfully for commit `{commit}`, including",
            "  Python 3.11/3.12/3.13 tests, fixture benchmark, CLI smoke,",
            "  package-smoke, and the OSS evidence snapshot job. The uploaded",
            "  `patchrail-oss-evidence` artifact includes the general snapshot, Agent",
            "  Control Plane evidence, application dossier, and the reviewer-facing local queue bundle.",
        ]
    )


def _replace_once(pattern: re.Pattern[str], replacement: str, text: str, path: Path) -> str:
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f"expected exactly one CI evidence reference in {path}")
    return updated


def _validate(run_url: str, commit: str) -> None:
    if RUN_URL_RE.fullmatch(run_url) is None:
        raise ValueError("run URL must be a patchrail/patchrail GitHub Actions run URL")
    if COMMIT_RE.fullmatch(commit) is None:
        raise ValueError("commit must be a full 40-character lowercase hex SHA")


def update_ci_reference(root: Path, run_url: str, commit: str, *, dry_run: bool) -> list[Path]:
    _validate(run_url, commit)

    docs_path = root / "docs" / "openai-codex-for-oss-evidence.md"
    test_path = root / "tests" / "test_public_workflows.py"
    targets = [docs_path, test_path]

    docs_text = docs_path.read_text(encoding="utf-8")
    test_text = test_path.read_text(encoding="utf-8")

    next_docs = _replace_once(
        DOCS_BLOCK_RE, _build_docs_block(run_url, commit), docs_text, docs_path
    )
    next_test = _replace_once(
        TEST_PAIR_RE,
        f'assert "{run_url}" in evidence\n    assert "{commit}" in evidence',
        test_text,
        test_path,
    )

    if not dry_run:
        docs_path.write_text(next_docs, encoding="utf-8")
        test_path.write_text(next_test, encoding="utf-8")
    return targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize the public CI evidence run/commit in docs and guardrail tests."
    )
    parser.add_argument("--repo", type=Path, default=Path("."), help="PatchRail checkout root")
    parser.add_argument("--run-url", required=True, help="GitHub Actions run URL")
    parser.add_argument("--commit", required=True, help="Full commit SHA for the run")
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate and report without writing"
    )
    args = parser.parse_args(argv)

    try:
        targets = update_ci_reference(
            args.repo.resolve(), args.run_url, args.commit, dry_run=args.dry_run
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    action = "validated" if args.dry_run else "updated"
    for target in targets:
        print(f"{action}: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
