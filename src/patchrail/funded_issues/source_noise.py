"""Owner-level source-noise heuristic for the read-only funded-issues tracker.

The per-issue scoring in :mod:`patchrail.funded_issues.discovery` cannot tell a
throwaway trap org (a brand-new account spamming near-identical honeypot
bounties) apart from a credible sponsor running a noisy program -- every issue
lands at ``risk_level=high`` regardless of *who* posted it. This module adds the
missing *owner-level* signal: given one owner's already-collected public GitHub
metadata plus the list of tracker-store entries attributed to that owner, it
derives a list of ``noise_flags`` and a single ``source_noise`` verdict.

It is pure and fully offline -- callers pass metadata that was gathered
read-only elsewhere; nothing here performs a network call, and (like the rest of
the tracker) it never writes to any third party.

Flags
-----
Each owner is screened for the following flags (constants below hold the
thresholds):

* ``new_account`` (strong) -- account younger than
  :data:`NEW_ACCOUNT_MAX_AGE_DAYS` days.
* ``no_website`` (strong) -- no public website/blog declared. Absent metadata is
  treated as "no website": for a noise screen, an unproven signal is a negative
  one.
* ``unverifiable_payout`` (strong) -- payout cannot be verified from a primary
  public source. Absent metadata is likewise treated as unverifiable.
* ``anomalous_volume`` (strong) -- the owner contributes at least
  :data:`ANOMALOUS_MIN_VOLUME` tracked entries and at least
  :data:`ANOMALOUS_DUP_RATIO` of them collapse to one near-identical title
  signature (the honeypot/aggregator template pattern).
* ``low_repos`` (supporting) -- at most :data:`LOW_REPO_MAX` public repos.
* ``few_followers`` (supporting) -- at most :data:`FEW_FOLLOWERS_MAX` followers.

Verdict criterion
-----------------
``source_noise`` is ``True`` when the owner trips **at least**
:data:`STRONG_FLAG_THRESHOLD` *strong* flags (the members of
:data:`STRONG_NOISE_FLAGS`). Supporting flags add colour to a report but never,
on their own, flip the verdict -- so a legitimate one-repo sponsor with a
website and verifiable payouts stays clean, while a new website-less org with
unverifiable payouts and templated volume is flagged.

Issue-level manual overrides
----------------------------
The owner-level pass is necessarily coarse: it condemns or clears *every* issue
from an owner at once. Sometimes a human needs to override a single issue --
flag one "Test Bounty" from an otherwise legitimate owner, or clear one issue
from a flagged owner. :func:`apply_source_noise_to_store` accepts a
``manual_overrides`` mapping (issue URL -> list of flags) for exactly this. The
overrides are *issue-level* and always win over the heuristic. Because the
caller passes them on **every** apply, they survive re-applies of the owner-level
heuristic that would otherwise reset the entry's ``noise_flags`` -- there is no
hidden state, just a deterministic re-stamp on each pass.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

SOURCE_NOISE_SCHEMA_VERSION = "patchrail.funded_issues.source_noise.v1"

# Thresholds. Tuned against the 2026-06-10 screening: trap orgs created within
# the last ~4 weeks with a single repo and a couple of followers.
NEW_ACCOUNT_MAX_AGE_DAYS = 90
LOW_REPO_MAX = 1
FEW_FOLLOWERS_MAX = 5
ANOMALOUS_MIN_VOLUME = 5
ANOMALOUS_DUP_RATIO = 0.6
STRONG_FLAG_THRESHOLD = 2

# Flags that, in sufficient number, flip ``source_noise``. The supporting flags
# (``low_repos`` / ``few_followers``) are deliberately excluded: weak corporate
# signals should never condemn an owner on their own.
STRONG_NOISE_FLAGS = frozenset(
    {"new_account", "no_website", "unverifiable_payout", "anomalous_volume"}
)

_TITLE_TOKEN_RE = re.compile(r"[a-z]+")
# How many leading title tokens form the near-identical signature. Honeypot and
# aggregator templates share a long fixed prefix; six tokens is enough to cluster
# them while keeping genuinely distinct issues apart.
_SIGNATURE_TOKENS = 6


def _parse_iso(value: str) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _account_age_days(metadata: dict[str, Any], now: str | None) -> int | None:
    """Resolve account age in days, preferring an explicit ``account_age_days``.

    Falls back to ``created_at`` differenced against ``now`` when both are
    present and parseable. Returns ``None`` when age cannot be established, in
    which case the ``new_account`` flag is simply not raised.
    """

    age = metadata.get("account_age_days")
    if age is not None:
        try:
            return int(age)
        except (TypeError, ValueError):
            return None

    created_at = metadata.get("created_at")
    if created_at and now:
        try:
            return (_parse_iso(now) - _parse_iso(str(created_at))).days
        except ValueError:
            return None
    return None


def _title_signature(title: Any) -> tuple[str, ...]:
    tokens = _TITLE_TOKEN_RE.findall(str(title).lower())
    return tuple(tokens[:_SIGNATURE_TOKENS])


def _entry_title(entry: dict[str, Any]) -> str:
    issue = entry.get("issue") or {}
    return str(issue.get("title") or "")


def _is_anomalous_volume(entries: list[dict[str, Any]]) -> bool:
    """True when the owner posts a high volume of near-identical issue titles.

    Titles are reduced to a leading-token signature; if the largest cluster of
    identical signatures covers at least :data:`ANOMALOUS_DUP_RATIO` of a
    sufficiently large batch, the volume is anomalous.
    """

    total = len(entries)
    if total < ANOMALOUS_MIN_VOLUME:
        return False
    counts: dict[tuple[str, ...], int] = {}
    for entry in entries:
        signature = _title_signature(_entry_title(entry))
        if not signature:
            continue
        counts[signature] = counts.get(signature, 0) + 1
    if not counts:
        return False
    largest_cluster = max(counts.values())
    return largest_cluster / total >= ANOMALOUS_DUP_RATIO


_REPOS_URL_OWNER_RE = re.compile(r"/repos/([^/]+)/")


def _entry_owner(entry: dict[str, Any]) -> str:
    """Derive the owning account for a store entry.

    Prefers an explicit ``issue.owner``, then the ``/repos/<owner>/`` segment of
    ``issue.url`` (the canonical GitHub API reference, always present in stores
    built by discovery), and finally ``issue.repository`` — which appears both
    as ``owner/repo`` and as the API-derived ``repos/<owner>`` form.
    """

    issue = entry.get("issue") or {}
    owner = issue.get("owner")
    if owner:
        return str(owner)
    match = _REPOS_URL_OWNER_RE.search(str(issue.get("url") or ""))
    if match:
        return match.group(1)
    repository = str(issue.get("repository") or "")
    segments = [part for part in repository.split("/") if part]
    if len(segments) >= 2 and segments[0] == "repos":
        return segments[1]
    if segments:
        return segments[0]
    return repository


def assess_owner_source_noise(
    owner_metadata: dict[str, Any],
    entries: list[dict[str, Any]],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    """Screen one owner for source noise from offline public signals.

    ``owner_metadata`` is a mapping of public signals for the owner
    (``account_age_days`` or ``created_at``, ``public_repos``, ``followers``,
    ``has_website``, ``payout_verifiable``). ``entries`` is the list of tracker
    store entries attributed to that owner (used for the volume heuristic).

    Returns a mapping with the sorted ``noise_flags``, the ``strong_flags``
    subset that drives the verdict, ``strong_flag_count``, the boolean
    ``source_noise`` verdict (see module docstring for the criterion), and the
    ``tracked_entries`` count. Performs no network calls.
    """

    metadata = owner_metadata or {}
    flags: list[str] = []

    age = _account_age_days(metadata, now)
    if age is not None and age < NEW_ACCOUNT_MAX_AGE_DAYS:
        flags.append("new_account")

    public_repos = metadata.get("public_repos")
    if public_repos is not None and int(public_repos) <= LOW_REPO_MAX:
        flags.append("low_repos")

    followers = metadata.get("followers")
    if followers is not None and int(followers) <= FEW_FOLLOWERS_MAX:
        flags.append("few_followers")

    if not metadata.get("has_website", False):
        flags.append("no_website")

    if not metadata.get("payout_verifiable", False):
        flags.append("unverifiable_payout")

    if _is_anomalous_volume(entries):
        flags.append("anomalous_volume")

    noise_flags = sorted(flags)
    strong_flags = [flag for flag in noise_flags if flag in STRONG_NOISE_FLAGS]
    return {
        "schema_version": SOURCE_NOISE_SCHEMA_VERSION,
        "noise_flags": noise_flags,
        "strong_flags": strong_flags,
        "strong_flag_count": len(strong_flags),
        "source_noise": len(strong_flags) >= STRONG_FLAG_THRESHOLD,
        "tracked_entries": len(entries),
    }


def entries_by_owner(store: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Group a store's entries by derived owner, preserving entry references."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in store.get("entries", {}).values():
        grouped.setdefault(_entry_owner(entry), []).append(entry)
    return grouped


def _validate_manual_overrides(
    manual_overrides: dict[str, list[str]] | None,
) -> dict[str, list[str]]:
    """Return validated overrides, raising ``ValueError`` on malformed flags.

    Every value must be a list whose members are all non-empty strings. A
    non-string or empty/blank string is a caller bug, not noise data, so it is
    rejected loudly rather than silently coerced.
    """

    overrides = manual_overrides or {}
    for url, flags in overrides.items():
        if not isinstance(flags, list):
            raise ValueError(
                f"manual_overrides[{url!r}] must be a list of flag strings, "
                f"got {type(flags).__name__}"
            )
        for flag in flags:
            if not isinstance(flag, str) or not flag.strip():
                raise ValueError(
                    f"manual_overrides[{url!r}] contains an invalid flag "
                    f"{flag!r}: flags must be non-empty strings"
                )
    return overrides


def apply_source_noise_to_store(
    store: dict[str, Any],
    owner_metadata: dict[str, dict[str, Any]] | None = None,
    *,
    now: str | None = None,
    manual_overrides: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Stamp the owner-level ``source_noise`` verdict onto store entries in place.

    Entries are grouped by owner; each owner is assessed once via
    :func:`assess_owner_source_noise` using ``owner_metadata[owner]`` (an empty
    mapping when absent). Every entry for a *flagged* owner has its
    ``noise_flags`` set to the owner's flag list; entries for a *clean* owner are
    reset to ``[]``. This keeps the per-entry ``noise_flags`` an honest mirror of
    the current owner verdict, so re-applying with refreshed metadata can clear a
    previously-flagged owner.

    ``manual_overrides`` is an optional, *issue-level* escape hatch mapping an
    exact ``store["entries"]`` URL key to a list of flag strings. It is applied
    **after** the owner-level pass and always wins:

    * a non-empty flag list marks the entry as noise -- merged with (and
      de-duplicated against) any owner-level flags, then sorted -- even when the
      owner is clean;
    * an empty list ``[]`` forces the entry clean, overriding a flagged owner.

    Because the caller supplies the overrides on every apply, they persist across
    re-applies of the heuristic without any stored state. Malformed overrides
    (non-string or empty flags) raise :class:`ValueError`. Returns a summary of
    the pass.
    """

    metadata_by_owner = owner_metadata or {}
    overrides = _validate_manual_overrides(manual_overrides)
    summary = {
        "owners_assessed": 0,
        "owners_flagged": 0,
        "owners_without_metadata": [],
        "entries_flagged": 0,
        "entries_cleared": 0,
        "entries_manual_noise": 0,
        "entries_manual_clean": 0,
        "manual_urls_not_in_store": [],
    }
    entries = store.get("entries", {})
    for owner, owner_entries in entries_by_owner(store).items():
        if owner not in metadata_by_owner:
            # Absent metadata reads as negative signals (see module docstring),
            # so surface it: a long list here means the caller is screening
            # owners it never actually looked up.
            summary["owners_without_metadata"].append(owner)
        assessment = assess_owner_source_noise(
            metadata_by_owner.get(owner, {}), owner_entries, now=now
        )
        summary["owners_assessed"] += 1
        flagged = assessment["source_noise"]
        if flagged:
            summary["owners_flagged"] += 1
        for entry in owner_entries:
            if flagged:
                entry["noise_flags"] = list(assessment["noise_flags"])
                summary["entries_flagged"] += 1
            else:
                entry["noise_flags"] = []
                summary["entries_cleared"] += 1

    # Issue-level overrides win over the heuristic. Applied as a second pass over
    # the store's URL keys so an override on a clean owner's entry still lands.
    for url, manual_flags in overrides.items():
        entry = entries.get(url)
        if entry is None:
            summary["manual_urls_not_in_store"].append(url)
            continue
        if manual_flags:
            owner_flags = entry.get("noise_flags") or []
            entry["noise_flags"] = sorted(set(owner_flags) | set(manual_flags))
            summary["entries_manual_noise"] += 1
        else:
            entry["noise_flags"] = []
            summary["entries_manual_clean"] += 1
    return summary
