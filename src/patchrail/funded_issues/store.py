"""Persistent local JSON store for the read-only funded-issues tracker.

This module keeps a small append/update store of already-discovered funded
issues so the read-only tracker can answer "what is new since last time" and
"how has the public state of this opportunity changed" without ever touching a
third party. It performs zero network calls and never claims, comments on, or
otherwise writes to any funded issue: inputs are normalized records produced by
``load_funded_issues`` / the importers, merged into a local file keyed by the
canonical issue URL.

Determinism: every mutation takes an explicit ``now`` ISO-8601 UTC timestamp so
tests (and the CLI ``--now`` flag) get reproducible output. Re-merging the same
inputs is idempotent -- only ``last_checked`` moves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from patchrail.funded_issues.blocklist import is_blocklisted_record
from patchrail.funded_issues.discovery import (
    BLOCKED_ACTIONS,
    SCHEMA_VERSION,
    VALID_OPPORTUNITY_STATES,
    FundedIssue,
)

STORE_SCHEMA_VERSION = "patchrail.funded_issues.store.v1"
STORE_STATUS_SCHEMA_VERSION = "patchrail.funded_issues.store_status.v1"
RECHECK_SUMMARY_SCHEMA_VERSION = "patchrail.funded_issues.recheck_summary.v1"

# State vocabulary tracked per entry. ``open`` is accepted as an inbound alias
# for ``active`` so imported provider exports that label issues "open" land in a
# single canonical state, matching the discovery normalizer.
VALID_STORE_STATES = VALID_OPPORTUNITY_STATES | {"open"}
_STATE_ALIASES = {"open": "active"}

_SAFE_REQUIREMENTS = {
    "network_required": False,
    "github_write_permission_required": False,
    "external_model_required": False,
    "billing_required": False,
}


def _normalize_store_state(value: Any) -> str:
    if value is None:
        return "unknown"
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    normalized = _STATE_ALIASES.get(normalized, normalized)
    return normalized if normalized in VALID_OPPORTUNITY_STATES else "unknown"


@dataclass
class MergeSummary:
    """Counts describing what a :func:`merge_into_store` call changed."""

    added: int = 0
    updated: int = 0
    transitioned: int = 0
    unchanged: int = 0
    blocked: int = 0
    transitions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "updated": self.updated,
            "transitioned": self.transitioned,
            "unchanged": self.unchanged,
            "blocked": self.blocked,
            "transitions": list(self.transitions),
        }


@dataclass
class RecheckSummary:
    """Counts describing what an :func:`apply_recheck_to_store` call changed.

    Observations whose URL is not present in the store are ignored for state
    purposes and counted under ``unmatched``. ``checked`` counts every inbound
    observation; ``matched`` counts the subset that hit an existing entry.
    """

    checked: int = 0
    matched: int = 0
    unmatched: int = 0
    unchanged: int = 0
    to_closed: int = 0
    to_stale: int = 0
    to_active: int = 0
    transitions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "matched": self.matched,
            "unmatched": self.unmatched,
            "transitions": {
                "to_closed": self.to_closed,
                "to_stale": self.to_stale,
                "to_active": self.to_active,
            },
            "unchanged": self.unchanged,
            "transition_log": list(self.transitions),
        }


def empty_store() -> dict[str, Any]:
    """Return a fresh, valid store object with no entries."""

    return {
        "schema_version": STORE_SCHEMA_VERSION,
        "source_schema_version": SCHEMA_VERSION,
        "read_only": True,
        "blocked_actions": list(BLOCKED_ACTIONS),
        "requirements": dict(_SAFE_REQUIREMENTS),
        "entries": {},
    }


def load_store(path: Path) -> dict[str, Any]:
    """Load a store file, or return an empty store when the file is absent.

    A missing file is treated as an empty store so the first ``track`` run does
    not require a bootstrap step. An existing file must carry the expected
    ``schema_version``.
    """

    path = Path(path)
    if not path.exists():
        return empty_store()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("store source must contain an object")
    if payload.get("schema_version") != STORE_SCHEMA_VERSION:
        raise ValueError(f"store must use schema_version {STORE_SCHEMA_VERSION}")
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("store must contain an entries object")
    store = empty_store()
    store["entries"] = {str(url): dict(entry) for url, entry in entries.items()}
    return store


def save_store(path: Path, store: dict[str, Any]) -> None:
    """Write ``store`` to ``path`` as canonical, sorted JSON."""

    path = Path(path)
    if path.parent != Path(""):
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _issue_record(issue: FundedIssue | dict[str, Any]) -> dict[str, Any]:
    if isinstance(issue, FundedIssue):
        return issue.to_dict()
    if isinstance(issue, dict):
        return dict(issue)
    raise ValueError("each issue must be a FundedIssue or a normalized issue mapping")


def _issue_url(record: dict[str, Any]) -> str:
    url = record.get("url")
    if not url:
        raise ValueError("each issue must carry a canonical url")
    return str(url)


def _issue_state(record: dict[str, Any]) -> str:
    return _normalize_store_state(record.get("opportunity_state"))


def _issue_score(issue: FundedIssue | dict[str, Any], record: dict[str, Any]) -> int | None:
    if isinstance(issue, dict):
        score = issue.get("score")
        if score is not None:
            return int(score)
    score = record.get("score")
    return int(score) if score is not None else None


def merge_into_store(
    store: dict[str, Any],
    issues: list[FundedIssue | dict[str, Any]],
    now: str,
) -> MergeSummary:
    """Incrementally merge ``issues`` into ``store`` in place.

    For each issue (keyed by canonical URL):

    * new URL -> add the entry with ``first_seen`` / ``last_seen`` /
      ``last_checked`` set to ``now`` and an initial ``state_history`` entry.
    * known URL -> refresh ``last_seen`` / ``last_checked`` and the stored issue
      record; append a ``state_history`` transition only when the normalized
      state actually changed.

    Merging the same inputs twice is idempotent apart from ``last_checked``.
    Records owned by a permanently blocklisted source
    (:mod:`patchrail.funded_issues.blocklist`) are dropped before any other
    handling and counted under ``blocked`` -- this is the single choke point
    through which issues enter a store, so a blocklisted owner can never
    re-enter one. Returns a :class:`MergeSummary` of what changed.
    """

    entries = store.setdefault("entries", {})
    summary = MergeSummary()

    for issue in issues:
        record = _issue_record(issue)
        if is_blocklisted_record(record):
            summary.blocked += 1
            continue
        url = _issue_url(record)
        state = _issue_state(record)
        score = _issue_score(issue, record)
        existing = entries.get(url)

        if existing is None:
            entry = {
                "issue": record,
                "first_seen": now,
                "last_seen": now,
                "last_checked": now,
                "state": state,
                "state_history": [{"state": state, "at": now, "from": None}],
                # Owner-level source-noise flags are populated out of band by
                # patchrail.funded_issues.source_noise; default empty so every
                # entry carries the field and it survives recheck/merge.
                "noise_flags": [],
            }
            if score is not None:
                entry["score"] = score
            entries[url] = entry
            summary.added += 1
            continue

        previous_state = existing.get("state")
        # Backfill the field on legacy entries without disturbing the existing
        # owner verdict; a real re-assessment goes through source_noise.
        existing.setdefault("noise_flags", [])
        # last_checked always advances; it is the one field allowed to move on a
        # no-op re-merge, so it never counts as an "update" by itself.
        existing["last_checked"] = now
        existing["last_seen"] = now

        changed = False
        if existing.get("issue") != record:
            existing["issue"] = record
            changed = True
        if score is not None and existing.get("score") != score:
            existing["score"] = score
            changed = True

        if state != previous_state:
            transition = {"state": state, "at": now, "from": previous_state}
            existing.setdefault("state_history", []).append(transition)
            existing["state"] = state
            summary.transitioned += 1
            summary.transitions.append({"url": url, **transition})
        elif changed:
            summary.updated += 1
        else:
            summary.unchanged += 1

    return summary


def _observation_url(observation: dict[str, Any]) -> str | None:
    url = observation.get("url")
    if not url:
        return None
    return str(url)


def _recheck_target_state(
    observation: dict[str, Any],
    *,
    now_dt: datetime,
    stale_after_days: int,
) -> str:
    """Map a single recheck observation to a canonical opportunity state.

    ``state=closed`` always wins. An ``open`` observation becomes ``stale`` once
    its ``updated_at`` is strictly older than ``stale_after_days`` days relative
    to ``now``; otherwise it is ``active`` (which also revives a stale entry).
    A fresh ``open`` with an unparseable/absent ``updated_at`` is treated as
    ``active`` -- we never invent staleness from missing data.
    """

    raw_state = observation.get("state")
    normalized = str(raw_state).strip().lower() if raw_state is not None else ""
    if normalized == "closed":
        return "closed"

    updated_at = observation.get("updated_at")
    if updated_at:
        try:
            updated_dt = _parse_iso(str(updated_at))
        except ValueError:
            return "active"
        if now_dt - updated_dt > timedelta(days=stale_after_days):
            return "stale"
    return "active"


def apply_recheck_to_store(
    store: dict[str, Any],
    observations: list[dict[str, Any]],
    now: str,
    stale_after_days: int = 45,
) -> RecheckSummary:
    """Apply read-only recheck ``observations`` to ``store`` in place.

    Each observation is a mapping carrying at least a ``url`` (matched against
    stored entries with the same canonical-URL criterion as
    :func:`merge_into_store`) and a ``state`` (``"open"`` or ``"closed"``). It
    may also carry ``updated_at`` / ``closed_at`` (ISO-8601) and the lightweight
    public signals ``assignee_count`` and ``comments``.

    State rules, evaluated against ``now``:

    * ``state=closed`` -> opportunity_state ``"closed"``.
    * ``state=open`` and ``now - updated_at`` exceeds ``stale_after_days`` days
      -> ``"stale"``.
    * ``state=open`` and fresh -> ``"active"`` (this also revives a previously
      ``stale`` entry back to ``active``).

    ``last_checked`` always advances for a matched entry. A ``state_history``
    transition (same shape as :func:`merge_into_store`) is appended only on a
    real state change, so a second identical pass yields zero transitions.
    Observations whose URL is unknown to the store are ignored and counted as
    ``unmatched``. Returns a :class:`RecheckSummary`.

    ``now`` must be a parseable ISO-8601 timestamp; otherwise ``ValueError`` is
    raised before any mutation occurs.
    """

    now_dt = _parse_iso(now)
    entries = store.setdefault("entries", {})
    summary = RecheckSummary()

    for observation in observations:
        summary.checked += 1
        url = _observation_url(observation)
        existing = entries.get(url) if url is not None else None
        if existing is None:
            summary.unmatched += 1
            continue

        summary.matched += 1
        previous_state = existing.get("state")
        existing["last_checked"] = now

        target_state = _recheck_target_state(
            observation,
            now_dt=now_dt,
            stale_after_days=stale_after_days,
        )

        if target_state != previous_state:
            transition = {"state": target_state, "at": now, "from": previous_state}
            existing.setdefault("state_history", []).append(transition)
            existing["state"] = target_state
            summary.transitions.append({"url": url, **transition})
            if target_state == "closed":
                summary.to_closed += 1
            elif target_state == "stale":
                summary.to_stale += 1
            else:
                summary.to_active += 1
        else:
            summary.unchanged += 1

    return summary


def _added_within(entries: dict[str, Any], now: str, *, hours: int) -> int | None:
    try:
        reference = _parse_iso(now)
    except ValueError:
        return None
    window = timedelta(hours=hours)
    count = 0
    for entry in entries.values():
        first_seen = entry.get("first_seen")
        if not first_seen:
            return None
        try:
            seen = _parse_iso(str(first_seen))
        except ValueError:
            return None
        delta = reference - seen
        if timedelta(0) <= delta <= window:
            count += 1
    return count


def _parse_iso(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def store_status(store: dict[str, Any], now: str | None = None) -> dict[str, Any]:
    """Build a read-only summary payload for a store.

    Aggregates totals by tracked state, the total USD across entries that carry
    an amount, and (when ``now`` is supplied and all entries carry parseable
    ``first_seen`` timestamps) the number of entries first seen in the last 24h.
    """

    entries = store.get("entries", {})
    states: dict[str, int] = {state: 0 for state in sorted(VALID_OPPORTUNITY_STATES)}
    total_usd = 0.0
    usd_entries = 0
    noise_flagged = 0
    clean_active = 0
    for entry in entries.values():
        state = _normalize_store_state(entry.get("state"))
        states[state] = states.get(state, 0) + 1
        is_noise = bool(entry.get("noise_flags"))
        if is_noise:
            noise_flagged += 1
        elif state == "active":
            clean_active += 1
        funding = (entry.get("issue") or {}).get("funding") or {}
        amount = funding.get("amount")
        currency = funding.get("currency")
        if amount is not None and str(currency).upper() == "USD":
            total_usd += float(amount)
            usd_entries += 1

    added_24h = _added_within(entries, now, hours=24) if now is not None else None

    return {
        "schema_version": STORE_STATUS_SCHEMA_VERSION,
        "source_schema_version": SCHEMA_VERSION,
        "read_only": True,
        "blocked_actions": list(BLOCKED_ACTIONS),
        "requirements": dict(_SAFE_REQUIREMENTS),
        "now": now,
        "total_entries": len(entries),
        "states": states,
        # Owner-level source-noise breakdown: separate the noise-flagged entries
        # from the clean live ones instead of reporting a single inflated
        # "active" total. ``tracked_total`` mirrors ``total_entries``.
        "tracked_total": len(entries),
        "noise_flagged": noise_flagged,
        "clean_active": clean_active,
        "added_24h": added_24h,
        "total_usd": round(total_usd, 2) if usd_entries else None,
        "usd_entries": usd_entries,
    }
