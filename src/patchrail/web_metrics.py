from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from patchrail.funded_issues import (
    FundedIssue,
    load_funded_issues,
    report_funded_issues,
    score_funded_issues,
)
from patchrail.funded_issues.store import load_store, store_status


SOURCE_NAMES = [
    "GitHub Issues",
    "Algora",
    "OpenPledge",
    "Replit Bounties",
    "BountyHub",
    "Bountysource",
    "IssueHunt",
    "Buidl",
]

PLATFORM_TO_SOURCE = {
    "github": "GitHub Issues",
    "polar": "GitHub Issues",
    "algora": "Algora",
    "openpledge": "OpenPledge",
    "replit": "Replit Bounties",
    "bountyhub": "BountyHub",
    "bountysource": "Bountysource",
    "issuehunt": "IssueHunt",
    "buidl": "Buidl",
}

TEXT_SUFFIXES = {".json", ".md", ".txt", ".csv"}
SIGNAL_NAME_RE = re.compile(r"(bount|funded|opportunit)", re.IGNORECASE)
COUNT_PATTERNS = [
    re.compile(
        r"\b(?P<count>\d{1,5})\s+issues?\s+bount(?:y|ies)\s+(?:abiertos|open)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<count>\d{1,5})\s+(?:open\s+)?(?:paid\s+)?bount(?:y|ies)\s+issues?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<count>\d{1,5})\s+(?:open\s+)?paid\s+bount(?:y|ies)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bfilas:\s*(?P<count>\d{1,5})\s+issues?\s+open\b", re.IGNORECASE),
]
WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}


@dataclass(frozen=True)
class DeskSignal:
    source_name: str
    active_count: int
    bounty_usd: int
    mtime: float


def utc_iso(epoch: float) -> str:
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def stable_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_if_changed(path: Path, text: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return True


def default_funded_source(product_repo: Path) -> Path:
    return product_repo / "examples" / "funded-issues-readonly" / "issues.json"


def product_commit(product_repo: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(product_repo), "log", "-1", "--format=%H%x00%ct%x00%s"],
            text=True,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return {"hash": None, "short": None, "committed_at": None, "subject": None}
    parts = proc.stdout.rstrip("\n").split("\x00", 2)
    if len(parts) != 3:
        return {"hash": None, "short": None, "committed_at": None, "subject": None}
    commit_hash, epoch_text, subject = parts
    try:
        committed_at = utc_iso(float(epoch_text))
    except ValueError:
        committed_at = None
    return {
        "hash": commit_hash,
        "short": commit_hash[:7],
        "committed_at": committed_at,
        "subject": subject,
    }


def source_for_text(text: str) -> str:
    lower = text.lower()
    for token, source_name in PLATFORM_TO_SOURCE.items():
        if token in lower and source_name != "GitHub Issues":
            return source_name
    return "GitHub Issues"


def extract_active_count(text: str) -> int:
    counts: list[int] = []
    for pattern in COUNT_PATTERNS:
        for match in pattern.finditer(text):
            counts.append(int(match.group("count")))
    word_pattern = re.compile(
        r"\b(?P<word>"
        + "|".join(WORD_NUMBERS)
        + r")\s+(?:open\s+)?(?:paid\s+)?bount(?:y|ies)\s+issues?\b",
        re.IGNORECASE,
    )
    for match in word_pattern.finditer(text):
        counts.append(WORD_NUMBERS[match.group("word").lower()])
    return max(counts) if counts else 0


def extract_bounty_usd(text: str) -> int:
    amounts: list[int] = []
    seen_spans: set[tuple[int, int]] = set()
    patterns = [
        re.compile(r"\[Bounty\s+\$([0-9][0-9,]*)\]", re.IGNORECASE),
        re.compile(r"\bBounty\s+\$([0-9][0-9,]*)\b", re.IGNORECASE),
    ]
    for pattern in patterns:
        for match in pattern.finditer(text):
            if match.span(1) in seen_spans:
                continue
            seen_spans.add(match.span(1))
            amounts.append(int(match.group(1).replace(",", "")))
    return sum(amounts)


def iter_signal_files(desk_dir: Path | None) -> list[Path]:
    if desk_dir is None:
        return []
    roots = [desk_dir / "research", desk_dir / "prospecting"]
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if SIGNAL_NAME_RE.search(path.name):
                files.append(path)
    return sorted(files)


def desk_signals(desk_dir: Path | None) -> list[DeskSignal]:
    signals: list[DeskSignal] = []
    for path in iter_signal_files(desk_dir):
        try:
            if path.stat().st_size > 1_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            active_count = extract_active_count(text)
            bounty_usd = extract_bounty_usd(text)
            if active_count == 0 and bounty_usd == 0:
                continue
            signals.append(
                DeskSignal(
                    source_name=source_for_text(text),
                    active_count=active_count,
                    bounty_usd=bounty_usd,
                    mtime=path.stat().st_mtime,
                )
            )
        except OSError:
            continue
    return signals


def source_volumes(report: dict[str, Any], signals: list[DeskSignal]) -> dict[str, int]:
    volumes = {name: 0 for name in SOURCE_NAMES}
    for platform, count in report["breakdown"]["platforms"].items():
        source_name = PLATFORM_TO_SOURCE.get(str(platform).lower(), "GitHub Issues")
        volumes[source_name] += int(count)
    for signal in signals:
        volumes[signal.source_name] += signal.active_count
    return volumes


def source_fingerprint(payload: Any) -> str:
    digest = hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()
    return digest[:16]


def known_usd_from_issues(issues: list[FundedIssue]) -> int:
    return int(
        sum(
            issue.funding_amount
            for issue in issues
            if issue.funding_currency == "USD" and issue.funding_amount is not None
        )
    )


def load_tracker_store_status(desk_dir: Path | None, now_iso: str) -> dict[str, Any] | None:
    """Load the canonical tracker store and return its status plus live volumes.

    Returns ``None`` when ``desk_dir`` is ``None``, the store file does not
    exist, or the store cannot be read. Otherwise returns a mapping with the
    ``store_status`` payload, the source file ``mtime``, and the volume of live
    entries (states ``open`` / ``active``) per ``SOURCE_NAMES`` source.
    """

    if desk_dir is None:
        return None
    store_path = desk_dir / "tracker" / "funded-issues-store.json"
    if not store_path.exists():
        return None
    try:
        store = load_store(store_path)
        status = store_status(store, now=now_iso)
        mtime = store_path.stat().st_mtime
    except (ValueError, OSError):
        return None

    live_by_source = {name: 0 for name in SOURCE_NAMES}
    for entry in store.get("entries", {}).values():
        if entry.get("state") not in ("open", "active"):
            continue
        platform = str((entry.get("issue") or {}).get("platform", "")).lower()
        source_name = PLATFORM_TO_SOURCE.get(platform, "GitHub Issues")
        live_by_source[source_name] += 1

    return {
        "status": status,
        "mtime": mtime,
        "live_by_source": live_by_source,
    }


def build_payloads(
    *,
    web_dir: Path,
    product_repo: Path,
    funded_source: Path,
    desk_dir: Path | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    issues = load_funded_issues(funded_source)
    report = report_funded_issues(issues)
    score_report = score_funded_issues(issues)
    signals = desk_signals(desk_dir)
    volumes = source_volumes(report, signals)
    commit = product_commit(product_repo)

    now_epoch = datetime.now(tz=timezone.utc).timestamp()
    now_iso = utc_iso(now_epoch)
    day_ago = now_epoch - 86400
    week_ago = now_epoch - (7 * 86400)

    tracker = load_tracker_store_status(desk_dir, now_iso)

    product_usd = known_usd_from_issues(issues)
    evidence_usd_week = sum(signal.bounty_usd for signal in signals if signal.mtime >= week_ago)
    heuristic_usd_week = product_usd + evidence_usd_week
    new_24h = sum(signal.active_count for signal in signals if signal.mtime >= day_ago)
    if funded_source.stat().st_mtime >= day_ago:
        new_24h += report["totals"]["loaded"]

    if tracker is not None:
        store_summary = tracker["status"]
        live_volumes = tracker["live_by_source"]
        volumes = live_volumes
        active_bounties = sum(live_volumes.values())
        if store_summary["added_24h"] is not None:
            new_24h = store_summary["added_24h"]
        if store_summary["usd_entries"] > 0:
            tracked_this_week_usd = int(round(store_summary["total_usd"]))
        else:
            tracked_this_week_usd = heuristic_usd_week
    else:
        active_bounties = sum(volumes.values())
        tracked_this_week_usd = heuristic_usd_week

    signal_mtimes = [signal.mtime for signal in signals]
    as_of_inputs = [funded_source.stat().st_mtime, *signal_mtimes]
    if tracker is not None:
        as_of_inputs.append(tracker["mtime"])
    as_of_epoch = max(as_of_inputs or [now_epoch])
    as_of = utc_iso(as_of_epoch)

    fingerprint_input = {
        "funded_source_mtime": int(funded_source.stat().st_mtime),
        "funded_source_size": funded_source.stat().st_size,
        "report": report,
        "signals": [
            {
                "source": signal.source_name,
                "active_count": signal.active_count,
                "bounty_usd": signal.bounty_usd,
                "mtime": int(signal.mtime),
            }
            for signal in signals
        ],
        "product_commit": commit["hash"],
        "volumes": volumes,
    }
    if tracker is not None:
        store_status_payload = {
            key: value for key, value in tracker["status"].items() if key != "now"
        }
        fingerprint_input["tracker_store"] = {
            "store_status": store_status_payload,
            "mtime": int(tracker["mtime"]),
        }
    fingerprint = source_fingerprint(fingerprint_input)

    values = {
        "tracked_this_week_usd": tracked_this_week_usd,
        "active_bounties": active_bounties,
        "sources_monitored": sum(1 for volume in volumes.values() if volume > 0),
        "new_24h": new_24h,
    }

    if tracker is not None:
        tracker_store_block = {
            "present": True,
            "total_entries": tracker["status"]["total_entries"],
            "states": tracker["status"]["states"],
            "added_24h": tracker["status"]["added_24h"],
            "total_usd": tracker["status"]["total_usd"],
            "usd_entries": tracker["status"]["usd_entries"],
            "live_by_source": tracker["live_by_source"],
        }
    else:
        tracker_store_block = {"present": False}

    evidence = {
        "schema_version": "patchrail.web_evidence_metrics.v1",
        "source_fingerprint": fingerprint,
        "read_only": True,
        "requirements": {
            "network_required": False,
            "github_write_permission_required": False,
            "billing_required": False,
            "external_model_required": False,
        },
        "product_commit": commit,
        "funded_issues": {
            "totals": report["totals"],
            "breakdown": report["breakdown"],
            "no_go_moat": report["no_go_moat"],
            "known_usd_from_source": product_usd,
        },
        "desk_tracker": {
            "evidence_files_scanned": len(iter_signal_files(desk_dir)),
            "evidence_files_with_counts": len(signals),
            "active_count_from_evidence": sum(signal.active_count for signal in signals),
            "active_count_new_24h": sum(
                signal.active_count for signal in signals if signal.mtime >= day_ago
            ),
            "known_bounty_usd_week": evidence_usd_week,
        },
        "tracker_store": tracker_store_block,
    }

    existing_landing = load_json(web_dir / "public" / "api" / "landing-metrics.json") or {}
    existing_evidence = (
        existing_landing.get("evidence")
        if isinstance(existing_landing.get("evidence"), dict)
        else {}
    )
    if (
        existing_evidence.get("source_fingerprint") == fingerprint
        and existing_landing.get("values") == values
        and isinstance(existing_landing.get("loading_snapshot"), dict)
    ):
        loading_snapshot = existing_landing["loading_snapshot"]
    else:
        loading_snapshot = (
            existing_landing.get("values")
            if isinstance(existing_landing.get("values"), dict)
            else values
        )

    landing_payload = {
        "as_of": as_of,
        "values": values,
        "loading_snapshot": loading_snapshot,
        "evidence": evidence,
    }
    sources_payload = {
        "as_of": as_of,
        "sources": [{"name": name, "volume": volumes[name]} for name in SOURCE_NAMES],
        "evidence": {
            "schema_version": "patchrail.source_volumes.v1",
            "source_fingerprint": fingerprint,
            "read_only": True,
            "sources_with_volume": sum(1 for volume in volumes.values() if volume > 0),
        },
    }
    product_payload = {
        "as_of": as_of,
        "schema_version": "patchrail.product_metrics.v1",
        "product": {
            "name": "PatchRail Bounty Radar",
            "repository": "patchrail/patchrail",
            "commit": commit,
        },
        "tracker": {
            "active_bounties": values["active_bounties"],
            "tracked_this_week_usd": values["tracked_this_week_usd"],
            "sources_monitored": values["sources_monitored"],
            "new_24h": values["new_24h"],
            "source_fingerprint": fingerprint,
        },
        "readiness": {
            "funded_issues_loaded": report["totals"]["loaded"],
            "safe_to_list": report["totals"]["safe_to_list"],
            "high_risk": report["totals"]["high_risk"],
            "go_candidates": score_report["rating_counts"].get("go_candidate", 0),
            "watchlist": score_report["rating_counts"].get("watchlist", 0),
            "no_go": score_report["rating_counts"].get("no_go", 0),
            "known_usd_from_source": product_usd,
        },
        "opportunity_desk": {
            "evidence_files_scanned": len(iter_signal_files(desk_dir)),
            "evidence_files_with_counts": len(signals),
            "active_count_from_evidence": sum(signal.active_count for signal in signals),
            "known_bounty_usd_week": evidence_usd_week,
        },
        "tracker_store": tracker_store_block,
        "automation": {
            "generated_by": "patchrail web-metrics update",
            "static_api_files": [
                "public/api/landing-metrics.json",
                "public/api/sources-volumes.json",
                "public/api/product-metrics.json",
            ],
            "read_only": True,
            "network_required": False,
            "github_write_permission_required": False,
        },
        "requirements": {
            "network_required": False,
            "github_write_permission_required": False,
            "billing_required": False,
            "external_model_required": False,
        },
    }
    summary = {
        "status": "prepared",
        "fingerprint": fingerprint,
        "as_of": as_of,
        "values": values,
        "source_volumes": {name: volumes[name] for name in SOURCE_NAMES if volumes[name] > 0},
        "product_metrics": {
            "safe_to_list": product_payload["readiness"]["safe_to_list"],
            "go_candidates": product_payload["readiness"]["go_candidates"],
            "no_go": product_payload["readiness"]["no_go"],
            "evidence_files_scanned": product_payload["opportunity_desk"]["evidence_files_scanned"],
        },
        "product_commit": commit["short"],
    }
    return landing_payload, sources_payload, product_payload, summary


def update_web_metrics(
    *,
    web_dir: Path,
    product_repo: Path,
    desk_dir: Path | None = None,
    funded_source: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    web_dir = web_dir.resolve()
    product_repo = product_repo.resolve()
    desk_dir = desk_dir.resolve() if desk_dir is not None else None
    funded_source = (
        funded_source.resolve()
        if funded_source is not None
        else default_funded_source(product_repo)
    )

    landing_payload, sources_payload, product_payload, summary = build_payloads(
        web_dir=web_dir,
        product_repo=product_repo,
        funded_source=funded_source,
        desk_dir=desk_dir,
    )

    landing_path = web_dir / "public" / "api" / "landing-metrics.json"
    sources_path = web_dir / "public" / "api" / "sources-volumes.json"
    product_path = web_dir / "public" / "api" / "product-metrics.json"
    changed_paths: list[str] = []
    if dry_run:
        if not landing_path.exists() or landing_path.read_text(encoding="utf-8") != stable_json(
            landing_payload
        ):
            changed_paths.append("public/api/landing-metrics.json")
        if not sources_path.exists() or sources_path.read_text(encoding="utf-8") != stable_json(
            sources_payload
        ):
            changed_paths.append("public/api/sources-volumes.json")
        if not product_path.exists() or product_path.read_text(encoding="utf-8") != stable_json(
            product_payload
        ):
            changed_paths.append("public/api/product-metrics.json")
    else:
        if write_if_changed(landing_path, stable_json(landing_payload)):
            changed_paths.append("public/api/landing-metrics.json")
        if write_if_changed(sources_path, stable_json(sources_payload)):
            changed_paths.append("public/api/sources-volumes.json")
        if write_if_changed(product_path, stable_json(product_payload)):
            changed_paths.append("public/api/product-metrics.json")

    status = "updated" if changed_paths else "unchanged"
    if dry_run and changed_paths:
        status = "would_update"
    return {
        **summary,
        "status": status,
        "changed": bool(changed_paths),
        "written": [] if dry_run else changed_paths,
        "would_write": changed_paths if dry_run else [],
    }


def render_text(summary: dict[str, Any]) -> str:
    values = summary["values"]
    lines = [
        f"Status: {summary['status']}",
        f"Fingerprint: {summary['fingerprint']}",
        f"As of: {summary['as_of']}",
        f"Tracked this week USD: {values['tracked_this_week_usd']}",
        f"Active bounties: {values['active_bounties']}",
        f"Sources monitored: {values['sources_monitored']}",
        f"New 24h: {values['new_24h']}",
        f"Safe-to-list funded issues: {summary['product_metrics']['safe_to_list']}",
        f"Go candidates: {summary['product_metrics']['go_candidates']}",
    ]
    written = summary.get("written") or summary.get("would_write") or []
    lines.append(f"Files changed: {', '.join(written) if written else 'none'}")
    return "\n".join(lines) + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Update PatchRail website metrics from read-only product/tracker evidence."
    )
    parser.add_argument("--web-dir", type=Path, required=True)
    parser.add_argument("--product-repo", type=Path, default=Path("."))
    parser.add_argument("--desk-dir", type=Path)
    parser.add_argument("--funded-source", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format.",
    )
    return parser


def run_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return update_web_metrics(
        web_dir=args.web_dir,
        product_repo=args.product_repo,
        desk_dir=args.desk_dir,
        funded_source=args.funded_source,
        dry_run=args.dry_run,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        summary = run_from_args(args)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    if args.format == "text":
        print(render_text(summary), end="")
    else:
        print(json.dumps(summary, sort_keys=True))
    return 0
