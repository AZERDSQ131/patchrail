"""Parse a saved Algora organization bounty-board page into funded issues.

Algora renders each organization's public bounty board at
``https://algora.io/<org>/bounties``. The initial server-rendered HTML carries
the board's open/completed totals and a table of open bounties with the four
public facts the tracker needs and that generic issue scraping cannot provide:

* the **funder-stated USD amount** (the board is the funding organization's own
  listing, so the amount is primary-source evidence, not aggregator hearsay);
* the GitHub issue URL and reference;
* the posting age shown on the board;
* the number of **claims** (declared solve attempts) on the bounty.

This module is a pure, offline parser for a *locally saved copy* of that page:
save the board with your browser or any HTTP client, then run
``patchrail funded-issues import-algora-board``. Keeping the fetch outside the
toolkit preserves the tracker's no-network rule (network access requires
explicit opt-in) and keeps tests hermetic. Nothing here claims, comments, or
writes to any third party.

Honesty note: the server-rendered table contains only the first page of open
bounties (about ten rows); the board's ``open_count`` is still the true total,
so the payload reports both and never pretends the visible subset is complete.
"""

from __future__ import annotations

import html as html_lib
import re
from typing import Any

from patchrail.funded_issues.discovery import (
    BLOCKED_ACTIONS,
    COMPETITION_THRESHOLDS,
    CONTESTED_BOUNTY_FLAG,
    FundedIssue,
    score_funded_issues,
)

ALGORA_BOARD_SCHEMA_VERSION = "patchrail.funded_issues.algora_board.v1"

# Stable markers in the board's server-rendered markup. The page is a LiveView
# app, but these classes/attributes have been stable across organizations; the
# parser fails loudly (ValueError) when the board scaffolding is absent so a
# login redirect or an unrelated page is never silently parsed as zero bounties.
_BOARD_MARKER = 'phx-value-tab="open"'
_ROW_SPLIT_RE = re.compile(r"<tr\b")
_AMOUNT_RE = re.compile(r"font-extrabold text-emerald-300[^\"]*\">\s*\$([\d,]+(?:\.\d{1,2})?)")
_ISSUE_LINK_RE = re.compile(
    r"<a href=\"https://github\.com/([^/\"]+)/([^/\"]+)/issues/(\d+)\"[^>]*class=\"group/issue"
)
_TITLE_RE = re.compile(r"line-clamp-2[^\"]*\">\s*(.*?)\s*</p>", re.S)
_AGE_RE = re.compile(r"text-xs text-gray-400\">\s*([^<]+?)\s*</p>")
_CLAIMS_RE = re.compile(r">\s*([\d,]+)\s+claims?\s*<")
_TAB_COUNT_RE_TEMPLATE = r"{label}</div>\s*<span[^>]*>\s*([\d,]+)\s*</span>"
_AGE_TEXT_RE = re.compile(r"(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago")

_AGE_UNIT_DAYS = {
    "minute": 0.0,
    "hour": 1.0 / 24.0,
    "day": 1.0,
    "week": 7.0,
    "month": 30.0,
    "year": 365.0,
}


def board_url(org: str) -> str:
    """Public URL of an organization's Algora bounty board."""

    return f"https://algora.io/{org}/bounties"


def _to_int(text: str) -> int:
    return int(text.replace(",", ""))


def _tab_count(html: str, label: str) -> int | None:
    match = re.search(_TAB_COUNT_RE_TEMPLATE.format(label=label), html, re.S)
    return _to_int(match.group(1)) if match else None


def approximate_age_days(text: str) -> int | None:
    """Approximate days from a board age label like ``"3 weeks ago"``.

    Months count as 30 days and years as 365; sub-day labels round to 0. Returns
    ``None`` for labels the board has not been observed to use -- an unknown
    label must read as "age unknown", never as "brand new".
    """

    match = _AGE_TEXT_RE.search(text.strip().lower())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    return int(value * _AGE_UNIT_DAYS[unit])


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(value)).strip()


def parse_board_html(html: str, org: str) -> dict[str, Any]:
    """Parse one saved board page into a normalized board mapping.

    Returns ``org``, ``source_url``, the board's true ``open_count`` /
    ``completed_count`` (when rendered), and the visible ``bounties``: each with
    ``amount_usd``, ``repository`` (GitHub ``owner/repo``, which may differ from
    the Algora org handle), ``issue_number``, ``url``, ``title``, ``age``
    (board label plus ``approx_days``), and ``attempt_count`` (declared claims).
    Rows missing an amount or issue link are skipped rather than guessed.
    Raises ``ValueError`` when ``html`` is not an Algora bounty board (for
    example a login redirect).
    """

    if _BOARD_MARKER not in html:
        raise ValueError(
            "source is not a server-rendered Algora bounty board page "
            "(expected the open-bounties tab marker)"
        )
    bounties: list[dict[str, Any]] = []
    for chunk in _ROW_SPLIT_RE.split(html)[1:]:
        amount_match = _AMOUNT_RE.search(chunk)
        link_match = _ISSUE_LINK_RE.search(chunk)
        if not amount_match or not link_match:
            continue
        owner, repo, number = link_match.group(1), link_match.group(2), link_match.group(3)
        title_match = _TITLE_RE.search(chunk)
        age_match = _AGE_RE.search(chunk)
        claims_match = _CLAIMS_RE.search(chunk)
        age_text = _clean_text(age_match.group(1)) if age_match else None
        bounties.append(
            {
                "amount_usd": float(amount_match.group(1).replace(",", "")),
                "repository": f"{owner}/{repo}",
                "issue_number": int(number),
                "url": f"https://github.com/{owner}/{repo}/issues/{number}",
                "title": _clean_text(title_match.group(1)) if title_match else "Untitled bounty",
                "age": {
                    "text": age_text,
                    "approx_days": approximate_age_days(age_text) if age_text else None,
                },
                "attempt_count": _to_int(claims_match.group(1)) if claims_match else 0,
            }
        )
    return {
        "schema_version": ALGORA_BOARD_SCHEMA_VERSION,
        "org": org,
        "source_url": board_url(org),
        "open_count": _tab_count(html, "Open"),
        "completed_count": _tab_count(html, "Completed"),
        "bounties": bounties,
        "visible_usd_total": round(sum(b["amount_usd"] for b in bounties), 2),
        # The server renders only the first page of open bounties; open_count is
        # the true total, so consumers can see exactly how partial the table is.
        "server_rendered_rows_only": True,
    }


def board_issue_records(
    board: dict[str, Any], *, retrieved_at: str | None = None
) -> list[dict[str, Any]]:
    """Convert a parsed board into scored, store-ready issue records.

    Each record is a normalized :class:`FundedIssue` mapping (so risk flags,
    readiness score, and the read-only contract match every other tracker
    source) extended with the board evidence: ``funding.verified`` /
    ``funding.evidence_url`` (the funder's own public board), ``attempt_count``,
    ``posted`` age, and the ``board`` provenance. A bounty whose declared claims
    reach the contested threshold carries the existing ``contested_bounty``
    flag. The records feed ``merge_into_store`` directly.
    """

    contested_at = COMPETITION_THRESHOLDS["distinct_claimants_contested"]
    issues = []
    for bounty in board["bounties"]:
        risk_flags = ["no_contribution_guidelines", "spam_attractive"]
        if bounty["attempt_count"] >= contested_at:
            risk_flags.append(CONTESTED_BOUNTY_FLAG)
        issues.append(
            FundedIssue(
                id=f"algora-board-{bounty['repository']}#{bounty['issue_number']}",
                platform="algora",
                repository=bounty["repository"],
                issue_number=bounty["issue_number"],
                title=bounty["title"],
                url=bounty["url"],
                funding_amount=bounty["amount_usd"],
                funding_currency="USD",
                labels=["bounty"],
                risk_flags=sorted(risk_flags),
                opportunity_state="active",
            )
        )
    by_url = {bounty["url"]: bounty for bounty in board["bounties"]}
    records: list[dict[str, Any]] = []
    for row in score_funded_issues(issues)["scores"]:
        record = dict(row["issue"])
        record["score"] = row["score"]
        bounty = by_url[record["url"]]
        record["funding"] = {
            **record["funding"],
            "verified": True,
            "evidence_url": board["source_url"],
        }
        record["attempt_count"] = bounty["attempt_count"]
        record["posted"] = dict(bounty["age"])
        record["board"] = {
            "org": board["org"],
            "source": "algora_board",
            "retrieved_at": retrieved_at,
        }
        records.append(record)
    return records


def board_payload(
    board: dict[str, Any], records: list[dict[str, Any]], *, retrieved_at: str | None = None
) -> dict[str, Any]:
    """Wrap parsed board records in the standard read-only payload envelope."""

    return {
        "schema_version": ALGORA_BOARD_SCHEMA_VERSION,
        "org": board["org"],
        "source_url": board["source_url"],
        "retrieved_at": retrieved_at,
        "open_count": board["open_count"],
        "completed_count": board["completed_count"],
        "visible_rows": len(records),
        "visible_usd_total": board["visible_usd_total"],
        "server_rendered_rows_only": board["server_rendered_rows_only"],
        "read_only": True,
        "blocked_actions": list(BLOCKED_ACTIONS),
        "requirements": {
            "network_required": False,
            "github_write_permission_required": False,
            "external_model_required": False,
            "billing_required": False,
        },
        "issues": records,
    }
