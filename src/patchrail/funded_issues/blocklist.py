"""Permanent source-level blocklist for the read-only funded-issues tracker.

The owner-level heuristic in :mod:`patchrail.funded_issues.source_noise` flags
suspicious sources *after* they are already in a tracker store. That is the
wrong layer for sources that have been positively verified as fake: a honeypot
owner that floods the feed with templated "Test Bounty" issues and unverifiable
payouts should never be allowed back in, no matter how its metadata looks on a
later screening pass.

This module is that hard gate. :data:`BLOCKLISTED_OWNERS` holds owners whose
listings were manually verified as fake bounty postings (templated test issues,
no payout trail, throwaway accounts). Records attributed to a blocklisted owner
are dropped at ingest time by :func:`patchrail.funded_issues.store.merge_into_store`,
and :func:`purge_blocklisted_entries` removes any that predate the blocklist
from existing stores -- the ``track`` CLI command runs it on every merge so old
stores self-heal.

Like the rest of the tracker this module is pure and offline: matching is
string comparison on already-collected records, nothing here performs a network
call or writes to any third party. The list is intentionally code, not config:
removing an owner requires a reviewed change, which is the point.
"""

from __future__ import annotations

import re
from typing import Any

BLOCKLIST_SCHEMA_VERSION = "patchrail.funded_issues.blocklist.v1"

# Owners verified as fake-bounty sources (2026-06-10 screening: templated
# honeypot issues, unverifiable payouts, throwaway accounts). Lowercase.
# Permanent: entries leave this set only via a reviewed code change.
BLOCKLISTED_OWNERS = frozenset(
    {
        "clankernation",
        "securebananalabs",
        "xevrion-v2",
    }
)

# Owner extraction mirrors source_noise: GitHub API references keep the owner in
# a ``/repos/<owner>/`` segment, browser URLs in ``github.com/<owner>/``.
_REPOS_URL_OWNER_RE = re.compile(r"/repos/([^/]+)/")
_HTML_URL_OWNER_RE = re.compile(r"github\.com/([^/\s]+)/")


def is_blocklisted_owner(owner: Any) -> bool:
    """True when ``owner`` (case-insensitive) is on the permanent blocklist."""

    return str(owner or "").strip().lower() in BLOCKLISTED_OWNERS


def record_owner(record: dict[str, Any]) -> str:
    """Derive the owning account from a normalized issue record.

    Prefers an explicit ``owner``, then the ``/repos/<owner>/`` segment of the
    canonical URL, then a ``github.com/<owner>/`` browser URL, and finally the
    leading segment of ``repository`` (skipping the API-style ``repos/`` prefix).
    Returns ``""`` when no owner can be derived -- unknown owners are never
    treated as blocklisted.
    """

    owner = record.get("owner")
    if owner:
        return str(owner)
    url = str(record.get("url") or "")
    match = _REPOS_URL_OWNER_RE.search(url)
    if match:
        return match.group(1)
    match = _HTML_URL_OWNER_RE.search(url)
    if match:
        return match.group(1)
    repository = str(record.get("repository") or "")
    segments = [part for part in repository.split("/") if part]
    if len(segments) >= 2 and segments[0] == "repos":
        return segments[1]
    if segments:
        return segments[0]
    return ""


def is_blocklisted_record(record: dict[str, Any]) -> bool:
    """True when a normalized issue record belongs to a blocklisted owner."""

    return is_blocklisted_owner(record_owner(record))


def purge_blocklisted_entries(store: dict[str, Any]) -> dict[str, Any]:
    """Remove every blocklisted owner's entries from ``store`` in place.

    Returns a summary with the number of ``removed`` entries and a sorted
    ``removed_owners`` list of the blocklisted owners that were present. Safe to
    run repeatedly; a clean store is left untouched.
    """

    entries = store.get("entries", {})
    removed_owners: set[str] = set()
    removed_urls = []
    for url, entry in entries.items():
        issue = entry.get("issue") or {}
        owner = record_owner(issue) or record_owner({"url": url})
        if is_blocklisted_owner(owner):
            removed_urls.append(url)
            removed_owners.add(owner.lower())
    for url in removed_urls:
        del entries[url]
    return {
        "schema_version": BLOCKLIST_SCHEMA_VERSION,
        "removed": len(removed_urls),
        "removed_owners": sorted(removed_owners),
    }
