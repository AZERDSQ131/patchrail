"""Guard against silent drift between src/patchrail/schemas/*.v1.schema.json
and the payloads the CLI actually emits.

The schemas under src/patchrail/schemas/ are served verbatim by
`patchrail ci schema <name>` and documented in docs/api-reference.md, but
until now nothing validated real output against them: `_load_schema()` in
cli.py only reads the schema file as text to print it, it never parses it as
JSON Schema or checks a payload against it. A field could be renamed, added,
or dropped in a payload builder without any test catching the schema going
stale.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from patchrail.ci.classify import classify_ci_log

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "src" / "patchrail" / "schemas"
FIXTURES_DIR = ROOT / "examples" / "ci-triage"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / f"{name}.v1.schema.json").read_text(encoding="utf-8"))


def _run_json(*args: str) -> dict:
    # Some commands (e.g. `ci fixture-check`) exit non-zero when cases fail
    # without that affecting whether the emitted JSON is well-formed and
    # schema-valid, which is all this helper needs to check.
    proc = subprocess.run(
        [sys.executable, "-m", "patchrail", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.stdout, proc.stderr
    return json.loads(proc.stdout)


CI_RESULT_SCHEMA = _load_schema("ci-result")
FIXTURE_LOGS = sorted(FIXTURES_DIR.glob("*.log"))


@pytest.mark.parametrize("log_path", FIXTURE_LOGS, ids=lambda p: p.stem)
def test_classify_ci_log_output_matches_ci_result_schema(log_path: Path) -> None:
    result = classify_ci_log(log_path.read_text(encoding="utf-8", errors="replace"))
    jsonschema.validate(instance=result, schema=CI_RESULT_SCHEMA)


def test_ci_benchmark_output_matches_schema() -> None:
    payload = _run_json("ci", "benchmark", "examples/ci-triage", "--format", "json")
    jsonschema.validate(instance=payload, schema=_load_schema("ci-benchmark"))


def test_ci_fixture_check_output_matches_schema() -> None:
    payload = _run_json("ci", "fixture-check", "examples/ci-triage", "--format", "json")
    jsonschema.validate(instance=payload, schema=_load_schema("ci-fixture-check"))
