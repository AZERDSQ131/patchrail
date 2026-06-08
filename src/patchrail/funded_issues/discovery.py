from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "patchrail.funded_issues.v1"
VALIDATION_SCHEMA_VERSION = "patchrail.funded_issues.validation.v1"
SHORTLIST_SCHEMA_VERSION = "patchrail.funded_issues.shortlist.v1"
BLOCKED_ACTIONS = [
    "automatic_claims",
    "automatic_pull_requests",
    "automatic_issue_comments",
    "mass_outreach",
    "ranking_by_money_only",
]

HIGH_RISK_FLAGS = {
    "ambiguous_scope",
    "bounty_farming_language",
    "requires_external_contact",
    "no_contribution_guidelines",
    "spam_attractive",
}


@dataclass(frozen=True)
class FundedIssue:
    id: str
    platform: str
    repository: str
    issue_number: int | None
    title: str
    url: str
    funding_amount: float | None = None
    funding_currency: str | None = None
    language: str | None = None
    labels: list[str] = field(default_factory=list)
    contribution_signals: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    maintainer_permission: str = "public_issue_only"
    contribution_guidelines_url: str | None = None

    @property
    def reference(self) -> str:
        if self.issue_number is None:
            return self.repository
        return f"{self.repository}#{self.issue_number}"

    @property
    def funding_display(self) -> str:
        if self.funding_amount is None or self.funding_currency is None:
            return "unknown"
        amount = (
            int(self.funding_amount) if self.funding_amount.is_integer() else self.funding_amount
        )
        return f"{amount} {self.funding_currency}"

    @property
    def risk_level(self) -> str:
        if any(flag in HIGH_RISK_FLAGS for flag in self.risk_flags):
            return "high"
        if not self.contribution_guidelines_url:
            return "medium"
        return "low"

    @property
    def safe_to_list(self) -> bool:
        return self.risk_level != "high"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "platform": self.platform,
            "repository": self.repository,
            "issue_number": self.issue_number,
            "reference": self.reference,
            "title": self.title,
            "url": self.url,
            "funding": {
                "amount": self.funding_amount,
                "currency": self.funding_currency,
                "display": self.funding_display,
            },
            "language": self.language,
            "labels": self.labels,
            "contribution_signals": self.contribution_signals,
            "risk_flags": self.risk_flags,
            "risk_level": self.risk_level,
            "safe_to_list": self.safe_to_list,
            "maintainer_permission": self.maintainer_permission,
            "contribution_guidelines_url": self.contribution_guidelines_url,
            "read_only": True,
            "blocked_actions": BLOCKED_ACTIONS,
        }


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected a list")
    return [str(item) for item in value]


def _issue_from_mapping(raw: dict[str, Any]) -> FundedIssue:
    funding = raw.get("funding") or {}
    if not isinstance(funding, dict):
        raise ValueError("funding must be an object")
    amount = funding.get("amount")
    if amount is not None:
        amount = float(amount)
    issue_number = raw.get("issue_number")
    if issue_number is not None:
        issue_number = int(issue_number)
    return FundedIssue(
        id=str(raw["id"]),
        platform=str(raw["platform"]),
        repository=str(raw["repository"]),
        issue_number=issue_number,
        title=str(raw["title"]),
        url=str(raw["url"]),
        funding_amount=amount,
        funding_currency=str(funding["currency"]) if funding.get("currency") else None,
        language=str(raw["language"]) if raw.get("language") else None,
        labels=_as_string_list(raw.get("labels")),
        contribution_signals=_as_string_list(raw.get("contribution_signals")),
        risk_flags=_as_string_list(raw.get("risk_flags")),
        maintainer_permission=str(raw.get("maintainer_permission") or "public_issue_only"),
        contribution_guidelines_url=(
            str(raw["contribution_guidelines_url"])
            if raw.get("contribution_guidelines_url")
            else None
        ),
    )


def load_funded_issues(source: Path) -> list[FundedIssue]:
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"source must use schema_version {SCHEMA_VERSION}")
    raw_issues = payload.get("issues")
    if not isinstance(raw_issues, list):
        raise ValueError("source must contain an issues list")
    issues = []
    for raw_issue in raw_issues:
        if not isinstance(raw_issue, dict):
            raise ValueError("each issue must be an object")
        issues.append(_issue_from_mapping(raw_issue))
    return issues


def funded_issues_payload(
    issues: list[FundedIssue],
    *,
    import_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "read_only": True,
        "blocked_actions": BLOCKED_ACTIONS,
        "issues": [issue.to_dict() for issue in issues],
        "requirements": {
            "network_required": False,
            "github_write_permission_required": False,
            "external_model_required": False,
            "billing_required": False,
        },
    }
    if import_source:
        payload["import_source"] = import_source
    return payload


def validate_funded_issues(issues: list[FundedIssue]) -> dict[str, Any]:
    duplicate_ids = _duplicates(issue.id for issue in issues)
    duplicate_references = _duplicates(issue.reference for issue in issues)
    missing_funding = [
        issue.reference
        for issue in issues
        if issue.funding_amount is None or issue.funding_currency is None
    ]
    missing_guidelines = [
        issue.reference for issue in issues if not issue.contribution_guidelines_url
    ]
    missing_signals = [issue.reference for issue in issues if not issue.contribution_signals]
    high_risk = [issue.reference for issue in issues if issue.risk_level == "high"]
    warnings = {
        "duplicate_ids": duplicate_ids,
        "duplicate_references": duplicate_references,
        "missing_funding": missing_funding,
        "missing_contribution_guidelines": missing_guidelines,
        "missing_contribution_signals": missing_signals,
        "high_risk": high_risk,
    }
    warning_count = sum(len(items) for items in warnings.values())
    risk_levels = Counter(issue.risk_level for issue in issues)
    return {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "source_schema_version": SCHEMA_VERSION,
        "status": "ok" if warning_count == 0 else "needs_review",
        "read_only": True,
        "total_loaded": len(issues),
        "warning_count": warning_count,
        "warnings": warnings,
        "counts": {
            "safe_to_list": sum(1 for issue in issues if issue.safe_to_list),
            "high_risk": risk_levels.get("high", 0),
            "medium_risk": risk_levels.get("medium", 0),
            "low_risk": risk_levels.get("low", 0),
        },
        "blocked_actions": BLOCKED_ACTIONS,
        "requirements": {
            "network_required": False,
            "github_write_permission_required": False,
            "external_model_required": False,
            "billing_required": False,
        },
        "boundary": (
            "Validation is local and read-only. Warnings require human review before the dataset "
            "is used as paid-opportunity evidence."
        ),
    }


def _duplicates(values: Any) -> list[str]:
    counts = Counter(str(value) for value in values)
    return sorted(value for value, count in counts.items() if count > 1)


def summarize_issues(
    issues: list[FundedIssue],
    *,
    safe_only: bool = True,
    platform: str | None = None,
    language: str | None = None,
    min_usd: float | None = None,
) -> dict[str, Any]:
    filtered: list[FundedIssue] = []
    for issue in issues:
        if safe_only and not issue.safe_to_list:
            continue
        if platform and issue.platform.lower() != platform.lower():
            continue
        if language and (issue.language or "").lower() != language.lower():
            continue
        if min_usd is not None:
            if issue.funding_currency != "USD" or issue.funding_amount is None:
                continue
            if issue.funding_amount < min_usd:
                continue
        filtered.append(issue)
    return {
        "schema_version": SCHEMA_VERSION,
        "read_only": True,
        "safe_only": safe_only,
        "blocked_actions": BLOCKED_ACTIONS,
        "total_loaded": len(issues),
        "total_returned": len(filtered),
        "issues": [issue.to_dict() for issue in filtered],
        "requirements": {
            "network_required": False,
            "github_write_permission_required": False,
            "external_model_required": False,
            "billing_required": False,
        },
    }


def report_funded_issues(
    issues: list[FundedIssue],
    *,
    safe_only: bool = False,
    platform: str | None = None,
    language: str | None = None,
    min_usd: float | None = None,
) -> dict[str, Any]:
    summary = summarize_issues(
        issues,
        safe_only=safe_only,
        platform=platform,
        language=language,
        min_usd=min_usd,
    )
    scoped_issues = [
        issue
        for issue in issues
        if _matches_report_filter(issue, platform=platform, language=language, min_usd=min_usd)
    ]
    returned_issues = [_issue_from_mapping(issue) for issue in summary["issues"]]
    risk_levels = Counter(issue.risk_level for issue in scoped_issues)
    platforms = Counter(issue.platform for issue in scoped_issues)
    languages = Counter(issue.language or "unknown" for issue in scoped_issues)
    risk_flags = Counter(flag for issue in scoped_issues for flag in issue.risk_flags)
    funding_known = sum(1 for issue in scoped_issues if issue.funding_amount is not None)
    funding_unknown = len(scoped_issues) - funding_known
    safe_candidates = sorted(
        (issue for issue in returned_issues if issue.safe_to_list),
        key=_candidate_sort_key,
    )
    return {
        "schema_version": "patchrail.funded_issues.report.v1",
        "source_schema_version": SCHEMA_VERSION,
        "read_only": True,
        "safe_only": safe_only,
        "blocked_actions": BLOCKED_ACTIONS,
        "filters": {
            "platform": platform,
            "language": language,
            "min_usd": min_usd,
        },
        "totals": {
            "loaded": len(issues),
            "in_scope": len(scoped_issues),
            "returned": len(returned_issues),
            "safe_to_list": sum(1 for issue in scoped_issues if issue.safe_to_list),
            "high_risk": risk_levels.get("high", 0),
            "funding_known": funding_known,
            "funding_unknown": funding_unknown,
        },
        "breakdown": {
            "risk_levels": dict(sorted(risk_levels.items())),
            "platforms": dict(sorted(platforms.items())),
            "languages": dict(sorted(languages.items())),
            "risk_flags": dict(sorted(risk_flags.items())),
        },
        "no_go_moat": {
            "high_risk_or_excluded": sum(1 for issue in scoped_issues if not issue.safe_to_list),
            "missing_contribution_guidelines": sum(
                1 for issue in scoped_issues if not issue.contribution_guidelines_url
            ),
            "ambiguous_scope": risk_flags.get("ambiguous_scope", 0),
            "spam_attractive": risk_flags.get("spam_attractive", 0),
            "funding_unknown": funding_unknown,
        },
        "top_safe_candidates": [
            {
                "reference": issue.reference,
                "title": issue.title,
                "platform": issue.platform,
                "funding": issue.funding_display,
                "risk_level": issue.risk_level,
                "signals": issue.contribution_signals,
                "url": issue.url,
            }
            for issue in safe_candidates
        ],
        "requirements": {
            "network_required": False,
            "github_write_permission_required": False,
            "external_model_required": False,
            "billing_required": False,
        },
        "boundary": (
            "Local read-only report only. PatchRail does not claim rewards, post comments, "
            "open pull requests, contact maintainers, or rank work by money alone."
        ),
    }


def score_funded_issues(
    issues: list[FundedIssue],
    *,
    safe_only: bool = False,
    platform: str | None = None,
    language: str | None = None,
    min_usd: float | None = None,
) -> dict[str, Any]:
    scored = [
        _score_issue(issue)
        for issue in issues
        if _matches_report_filter(issue, platform=platform, language=language, min_usd=min_usd)
    ]
    if safe_only:
        scored = [row for row in scored if row["issue"]["safe_to_list"]]
    ratings = Counter(row["rating"] for row in scored)
    return {
        "schema_version": "patchrail.funded_issues.score.v1",
        "source_schema_version": SCHEMA_VERSION,
        "read_only": True,
        "safe_only": safe_only,
        "blocked_actions": BLOCKED_ACTIONS,
        "filters": {
            "platform": platform,
            "language": language,
            "min_usd": min_usd,
        },
        "total_loaded": len(issues),
        "total_scored": len(scored),
        "rating_counts": dict(sorted(ratings.items())),
        "scores": sorted(
            scored,
            key=lambda row: (-int(row["score"]), row["issue"]["reference"]),
        ),
        "requirements": {
            "network_required": False,
            "github_write_permission_required": False,
            "external_model_required": False,
            "billing_required": False,
        },
        "boundary": (
            "Local read-only readiness scoring only. Funding is context, not an instruction to "
            "claim rewards, post comments, open pull requests, or contact maintainers."
        ),
    }


def shortlist_funded_issues(
    issues: list[FundedIssue],
    *,
    safe_only: bool = False,
    platform: str | None = None,
    language: str | None = None,
    min_usd: float | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    score_payload = score_funded_issues(
        issues,
        safe_only=False,
        platform=platform,
        language=language,
        min_usd=min_usd,
    )
    report_payload = report_funded_issues(
        issues,
        safe_only=safe_only,
        platform=platform,
        language=language,
        min_usd=min_usd,
    )
    candidate_rows = [
        row
        for row in score_payload["scores"]
        if row["rating"] in {"go_candidate", "watchlist"}
        and (not safe_only or row["issue"]["safe_to_list"])
    ]
    no_go_rows = [row for row in score_payload["scores"] if row["rating"] == "no_go"]
    return {
        "schema_version": SHORTLIST_SCHEMA_VERSION,
        "source_schema_version": SCHEMA_VERSION,
        "read_only": True,
        "safe_only": safe_only,
        "limit": limit,
        "blocked_actions": BLOCKED_ACTIONS,
        "filters": score_payload["filters"],
        "summary": {
            "total_loaded": score_payload["total_loaded"],
            "total_scored": score_payload["total_scored"],
            "rating_counts": score_payload["rating_counts"],
            "in_scope": report_payload["totals"]["in_scope"],
            "safe_to_list": report_payload["totals"]["safe_to_list"],
            "high_risk": report_payload["totals"]["high_risk"],
        },
        "shortlist": candidate_rows[:limit],
        "no_go_evidence": no_go_rows,
        "no_go_moat": report_payload["no_go_moat"],
        "requirements": {
            "network_required": False,
            "github_write_permission_required": False,
            "external_model_required": False,
            "billing_required": False,
        },
        "boundary": (
            "Decision support only. PatchRail does not claim rewards, post comments, open pull "
            "requests, contact maintainers, or guarantee merge or payout outcomes."
        ),
    }


def _score_issue(issue: FundedIssue) -> dict[str, Any]:
    score = 35
    components: dict[str, int] = {
        "base": 35,
        "funding_visible": 0,
        "guidelines_visible": 0,
        "contribution_signals": 0,
        "risk_penalty": 0,
        "safe_boundary_bonus": 0,
    }
    reason_codes: list[str] = []

    if issue.funding_amount is not None and issue.funding_currency:
        components["funding_visible"] = 15
    else:
        reason_codes.append("FUNDING_STATE_UNCLEAR")

    if issue.contribution_guidelines_url:
        components["guidelines_visible"] = 15
    else:
        reason_codes.append("NO_CONTRIBUTION_GUIDELINES")

    components["contribution_signals"] = min(len(issue.contribution_signals), 3) * 8
    if not issue.contribution_signals:
        reason_codes.append("NO_REPRO_OR_CONTRIBUTION_SIGNAL")

    if issue.risk_flags:
        risk_penalty = 15 * len(issue.risk_flags)
        if issue.risk_level == "high":
            risk_penalty += 20
        components["risk_penalty"] = -risk_penalty
        reason_codes.extend(_risk_reason_code(flag) for flag in issue.risk_flags)
    else:
        components["safe_boundary_bonus"] = 10

    score += sum(value for key, value in components.items() if key != "base")
    score = max(0, min(100, score))
    if issue.risk_level == "high":
        rating = "no_go"
    elif score >= 80:
        rating = "go_candidate"
    elif score >= 55:
        rating = "watchlist"
    else:
        rating = "no_go"

    return {
        "issue": issue.to_dict(),
        "score": score,
        "rating": rating,
        "reason_codes": sorted(set(reason_codes)) or ["NO_MAJOR_REVIEW_GAPS"],
        "components": components,
    }


def _risk_reason_code(flag: str) -> str:
    return {
        "ambiguous_scope": "SCOPE_TOO_BROAD",
        "bounty_farming_language": "BOUNTY_FARMING_RISK",
        "requires_external_contact": "NEEDS_AUTHORIZATION",
        "no_contribution_guidelines": "NO_CONTRIBUTION_GUIDELINES",
        "spam_attractive": "SPAM_ATTRACTIVE",
    }.get(flag, f"RISK_{flag.upper()}")


def _matches_report_filter(
    issue: FundedIssue,
    *,
    platform: str | None,
    language: str | None,
    min_usd: float | None,
) -> bool:
    if platform and issue.platform.lower() != platform.lower():
        return False
    if language and (issue.language or "").lower() != language.lower():
        return False
    if min_usd is not None:
        if issue.funding_currency != "USD" or issue.funding_amount is None:
            return False
        if issue.funding_amount < min_usd:
            return False
    return True


def _candidate_sort_key(issue: FundedIssue) -> tuple[int, int, float, str]:
    has_guidelines = 1 if issue.contribution_guidelines_url else 0
    signal_count = len(issue.contribution_signals)
    funding_amount = issue.funding_amount if issue.funding_currency == "USD" else 0.0
    return (-has_guidelines, -signal_count, -funding_amount, issue.reference)


def explain_issue(issues: list[FundedIssue], reference: str) -> dict[str, Any]:
    for issue in issues:
        if reference in {issue.id, issue.reference, issue.url}:
            return {
                "schema_version": SCHEMA_VERSION,
                "read_only": True,
                "issue": issue.to_dict(),
                "ethics": {
                    "allowed": [
                        "read public funding metadata",
                        "review contribution guidelines",
                        "prepare a local maintainer-readiness note",
                    ],
                    "blocked": BLOCKED_ACTIONS,
                },
                "recommendation": _recommendation_for(issue),
            }
    raise KeyError(reference)


def _recommendation_for(issue: FundedIssue) -> str:
    if issue.risk_level == "high":
        return (
            "Do not pursue automatically. Keep this as read-only metadata unless a maintainer "
            "explicitly invites help and the scope is clarified."
        )
    if issue.risk_level == "medium":
        return (
            "Review contribution guidelines before any work. Treat funding as context, not as the "
            "primary ranking signal."
        )
    return (
        "Safe to keep in a local funded-maintenance shortlist. Any contribution still requires "
        "normal maintainer review and project rules."
    )
