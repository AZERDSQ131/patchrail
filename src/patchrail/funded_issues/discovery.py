from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "patchrail.funded_issues.v1"
CLIENT_PROFILE_SCHEMA_VERSION = "patchrail.funded_issues.client_profile.v1"
VALIDATION_SCHEMA_VERSION = "patchrail.funded_issues.validation.v1"
SHORTLIST_SCHEMA_VERSION = "patchrail.funded_issues.shortlist.v1"
RECHECK_QUEUE_SCHEMA_VERSION = "patchrail.funded_issues.recheck_queue.v1"
CASH_ACTIONS_SCHEMA_VERSION = "patchrail.funded_issues.cash_actions.v1"
FULFILLMENT_PACKET_SCHEMA_VERSION = "patchrail.funded_issues.fulfillment_packet.v1"
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
    "closed_or_inactive",
    "requires_external_contact",
    "no_contribution_guidelines",
    "spam_attractive",
    "stale_no_maintainer_signal",
}

VALID_OPPORTUNITY_STATES = {"active", "closed", "stale", "unknown"}
VALID_RISK_LEVELS = {"high", "low", "medium"}
VALID_DECISION_GATES = {
    "go_after_recheck",
    "needs_authorization",
    "needs_funding_verification",
    "no_go",
    "watchlist",
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
    opportunity_state: str = "unknown"

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
        return self.risk_level != "high" and self.opportunity_state not in {"closed", "stale"}

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
            "opportunity_state": self.opportunity_state,
            "maintainer_permission": self.maintainer_permission,
            "contribution_guidelines_url": self.contribution_guidelines_url,
            "read_only": True,
            "blocked_actions": BLOCKED_ACTIONS,
        }


@dataclass(frozen=True)
class ClientProfile:
    name: str | None = None
    languages: tuple[str, ...] = ()
    min_usd: float | None = None
    allowed_opportunity_states: tuple[str, ...] = ()
    allowed_risk_levels: tuple[str, ...] = ()
    excluded_risk_flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CLIENT_PROFILE_SCHEMA_VERSION,
            "name": self.name,
            "languages": list(self.languages),
            "min_usd": self.min_usd,
            "allowed_opportunity_states": list(self.allowed_opportunity_states),
            "allowed_risk_levels": list(self.allowed_risk_levels),
            "excluded_risk_flags": list(self.excluded_risk_flags),
            "read_only": True,
        }


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected a list")
    return [str(item) for item in value]


def _as_normalized_tuple(value: Any) -> tuple[str, ...]:
    return tuple(sorted({item.strip().lower() for item in _as_string_list(value) if item.strip()}))


def _profile_from_mapping(raw: dict[str, Any]) -> ClientProfile:
    schema_version = raw.get("schema_version")
    if schema_version != CLIENT_PROFILE_SCHEMA_VERSION:
        raise ValueError(f"profile must use schema_version {CLIENT_PROFILE_SCHEMA_VERSION}")
    min_usd = raw.get("min_usd")
    if min_usd is not None:
        min_usd = float(min_usd)
        if min_usd < 0:
            raise ValueError("profile min_usd must be >= 0")
    states = tuple(
        _normalize_opportunity_state_filter(state)
        for state in _as_normalized_tuple(raw.get("allowed_opportunity_states"))
    )
    risk_levels = tuple(
        _normalize_risk_level_filter(risk_level)
        for risk_level in _as_normalized_tuple(raw.get("allowed_risk_levels"))
    )
    return ClientProfile(
        name=str(raw["name"]) if raw.get("name") else None,
        languages=_as_normalized_tuple(raw.get("languages")),
        min_usd=min_usd,
        allowed_opportunity_states=states,
        allowed_risk_levels=risk_levels,
        excluded_risk_flags=_as_normalized_tuple(raw.get("excluded_risk_flags")),
    )


def load_client_profile(source: Path) -> ClientProfile:
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("profile source must contain an object")
    return _profile_from_mapping(payload)


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
        opportunity_state=_normalize_opportunity_state(
            raw.get("opportunity_state") or raw.get("state") or raw.get("status")
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
    stale_or_closed = [
        issue.reference for issue in issues if issue.opportunity_state in {"closed", "stale"}
    ]
    warnings = {
        "duplicate_ids": duplicate_ids,
        "duplicate_references": duplicate_references,
        "missing_funding": missing_funding,
        "missing_contribution_guidelines": missing_guidelines,
        "missing_contribution_signals": missing_signals,
        "high_risk": high_risk,
        "stale_or_closed": stale_or_closed,
    }
    warning_count = sum(len(items) for items in warnings.values())
    risk_levels = Counter(issue.risk_level for issue in issues)
    opportunity_states = Counter(issue.opportunity_state for issue in issues)
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
            "active": opportunity_states.get("active", 0),
            "stale": opportunity_states.get("stale", 0),
            "closed": opportunity_states.get("closed", 0),
            "unknown_state": opportunity_states.get("unknown", 0),
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
    profile: ClientProfile | None = None,
    platform: str | None = None,
    language: str | None = None,
    min_usd: float | None = None,
    opportunity_state: str | None = None,
    risk_level: str | None = None,
) -> dict[str, Any]:
    opportunity_state = _normalize_opportunity_state_filter(opportunity_state)
    risk_level = _normalize_risk_level_filter(risk_level)
    filtered: list[FundedIssue] = []
    for issue in issues:
        if safe_only and not issue.safe_to_list:
            continue
        if not _matches_report_filter(
            issue,
            profile=profile,
            platform=platform,
            language=language,
            min_usd=min_usd,
            opportunity_state=opportunity_state,
            risk_level=risk_level,
        ):
            continue
        filtered.append(issue)
    return {
        "schema_version": SCHEMA_VERSION,
        "read_only": True,
        "safe_only": safe_only,
        "blocked_actions": BLOCKED_ACTIONS,
        "total_loaded": len(issues),
        "total_returned": len(filtered),
        "filters": {
            "profile": profile.to_dict() if profile else None,
            "platform": platform,
            "language": language,
            "min_usd": min_usd,
            "opportunity_state": opportunity_state,
            "risk_level": risk_level,
        },
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
    profile: ClientProfile | None = None,
    platform: str | None = None,
    language: str | None = None,
    min_usd: float | None = None,
    opportunity_state: str | None = None,
    risk_level: str | None = None,
) -> dict[str, Any]:
    opportunity_state = _normalize_opportunity_state_filter(opportunity_state)
    risk_level = _normalize_risk_level_filter(risk_level)
    client_fit_gaps = _client_fit_gaps(issues, profile)
    summary = summarize_issues(
        issues,
        safe_only=safe_only,
        profile=profile,
        platform=platform,
        language=language,
        min_usd=min_usd,
        opportunity_state=opportunity_state,
        risk_level=risk_level,
    )
    scoped_issues = [
        issue
        for issue in issues
        if _matches_report_filter(
            issue,
            profile=profile,
            platform=platform,
            language=language,
            min_usd=min_usd,
            opportunity_state=opportunity_state,
            risk_level=risk_level,
        )
    ]
    returned_issues = [_issue_from_mapping(issue) for issue in summary["issues"]]
    risk_levels = Counter(issue.risk_level for issue in scoped_issues)
    platforms = Counter(issue.platform for issue in scoped_issues)
    languages = Counter(issue.language or "unknown" for issue in scoped_issues)
    risk_flags = Counter(flag for issue in scoped_issues for flag in issue.risk_flags)
    opportunity_states = Counter(issue.opportunity_state for issue in scoped_issues)
    funding_known = sum(1 for issue in scoped_issues if issue.funding_amount is not None)
    funding_unknown = len(scoped_issues) - funding_known
    scored_rows = [_score_issue(issue) for issue in scoped_issues]
    decision_summary = _decision_summary(scored_rows)
    delivery_budget = _delivery_budget(scored_rows)
    source_quality = _source_quality(scored_rows)
    recheck_plan = _recheck_plan(scored_rows)
    client_fit_summary = _client_fit_summary(issues, profile, client_fit_gaps)
    intake_followup = _intake_followup(
        client_fit_summary=client_fit_summary,
        recheck_plan=recheck_plan,
        delivery_budget=delivery_budget,
        source_quality=source_quality,
        decision_summary=decision_summary,
    )
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
            "profile": profile.to_dict() if profile else None,
            "platform": platform,
            "language": language,
            "min_usd": min_usd,
            "opportunity_state": opportunity_state,
            "risk_level": risk_level,
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
            "opportunity_states": dict(sorted(opportunity_states.items())),
        },
        "no_go_moat": {
            "high_risk_or_excluded": sum(1 for issue in scoped_issues if not issue.safe_to_list),
            "missing_contribution_guidelines": sum(
                1 for issue in scoped_issues if not issue.contribution_guidelines_url
            ),
            "ambiguous_scope": risk_flags.get("ambiguous_scope", 0),
            "spam_attractive": risk_flags.get("spam_attractive", 0),
            "funding_unknown": funding_unknown,
            "stale_or_closed": sum(
                1 for issue in scoped_issues if issue.opportunity_state in {"closed", "stale"}
            ),
        },
        "decision_summary": decision_summary,
        "delivery_budget": delivery_budget,
        "delivery_pack": _delivery_pack(scored_rows),
        "source_quality": source_quality,
        "recheck_plan": recheck_plan,
        "client_fit_summary": client_fit_summary,
        "client_fit_gaps": client_fit_gaps,
        "intake_followup": intake_followup,
        "cash_path_status": _cash_path_status(intake_followup),
        "top_safe_candidates": [
            {
                "reference": issue.reference,
                "title": issue.title,
                "platform": issue.platform,
                "funding": issue.funding_display,
                "opportunity_state": issue.opportunity_state,
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
    profile: ClientProfile | None = None,
    platform: str | None = None,
    language: str | None = None,
    min_usd: float | None = None,
    opportunity_state: str | None = None,
    risk_level: str | None = None,
) -> dict[str, Any]:
    opportunity_state = _normalize_opportunity_state_filter(opportunity_state)
    risk_level = _normalize_risk_level_filter(risk_level)
    scored = [
        _score_issue(issue)
        for issue in issues
        if _matches_report_filter(
            issue,
            profile=profile,
            platform=platform,
            language=language,
            min_usd=min_usd,
            opportunity_state=opportunity_state,
            risk_level=risk_level,
        )
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
            "profile": profile.to_dict() if profile else None,
            "platform": platform,
            "language": language,
            "min_usd": min_usd,
            "opportunity_state": opportunity_state,
            "risk_level": risk_level,
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
    profile: ClientProfile | None = None,
    platform: str | None = None,
    language: str | None = None,
    min_usd: float | None = None,
    opportunity_state: str | None = None,
    risk_level: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    score_payload = score_funded_issues(
        issues,
        safe_only=False,
        profile=profile,
        platform=platform,
        language=language,
        min_usd=min_usd,
        opportunity_state=opportunity_state,
        risk_level=risk_level,
    )
    report_payload = report_funded_issues(
        issues,
        safe_only=safe_only,
        profile=profile,
        platform=platform,
        language=language,
        min_usd=min_usd,
        opportunity_state=opportunity_state,
        risk_level=risk_level,
    )
    candidate_rows = [
        row
        for row in score_payload["scores"]
        if row["rating"] in {"go_candidate", "watchlist"}
        and (not safe_only or row["issue"]["safe_to_list"])
    ]
    no_go_rows = [row for row in score_payload["scores"] if row["rating"] == "no_go"]
    decision_summary = _decision_summary(score_payload["scores"])
    delivery_budget = _delivery_budget(score_payload["scores"])
    source_quality = _source_quality(score_payload["scores"])
    recheck_plan = _recheck_plan(score_payload["scores"])
    client_fit_summary = _client_fit_summary(issues, profile, report_payload["client_fit_gaps"])
    intake_followup = _intake_followup(
        client_fit_summary=client_fit_summary,
        recheck_plan=recheck_plan,
        delivery_budget=delivery_budget,
        source_quality=source_quality,
        decision_summary=decision_summary,
    )
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
            "opportunity_states": report_payload["breakdown"]["opportunity_states"],
        },
        "shortlist": candidate_rows[:limit],
        "no_go_evidence": no_go_rows,
        "no_go_moat": report_payload["no_go_moat"],
        "decision_summary": {
            **decision_summary,
            "candidate_rows": len(candidate_rows),
            "no_go_rows": len(no_go_rows),
        },
        "delivery_budget": delivery_budget,
        "delivery_pack": _delivery_pack(score_payload["scores"]),
        "source_quality": source_quality,
        "recheck_plan": recheck_plan,
        "client_fit_summary": client_fit_summary,
        "client_fit_gaps": report_payload["client_fit_gaps"],
        "intake_followup": intake_followup,
        "cash_path_status": _cash_path_status(intake_followup),
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


def recheck_funded_issues(
    issues: list[FundedIssue],
    *,
    safe_only: bool = False,
    profile: ClientProfile | None = None,
    platform: str | None = None,
    language: str | None = None,
    min_usd: float | None = None,
    opportunity_state: str | None = None,
    risk_level: str | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    if max_rows is not None and max_rows < 1:
        raise ValueError("max_rows must be at least 1")
    score_payload = score_funded_issues(
        issues,
        safe_only=safe_only,
        profile=profile,
        platform=platform,
        language=language,
        min_usd=min_usd,
        opportunity_state=opportunity_state,
        risk_level=risk_level,
    )
    scored_rows = score_payload["scores"]
    recheck_plan = _recheck_plan(scored_rows)
    queue_rows = [
        _recheck_queue_row(row)
        for row in scored_rows
        if _recheck_action_for_gate(str(row["decision_gate"])) != "archive_as_no_go_evidence"
    ]
    queue_rows.sort(
        key=lambda row: (
            _recheck_priority_rank(row["priority"]),
            row["platform"],
            row["reference"],
        )
    )
    queue_rows_before_limit = len(queue_rows)
    if max_rows is not None:
        queue_rows = queue_rows[:max_rows]
    return {
        "schema_version": RECHECK_QUEUE_SCHEMA_VERSION,
        "source_schema_version": SCHEMA_VERSION,
        "read_only": True,
        "safe_only": safe_only,
        "blocked_actions": BLOCKED_ACTIONS,
        "filters": score_payload["filters"],
        "queue_limit": max_rows,
        "total_loaded": score_payload["total_loaded"],
        "total_scored": score_payload["total_scored"],
        "queue_rows_before_limit": queue_rows_before_limit,
        "queue_rows": len(queue_rows),
        "no_go_archive_rows": recheck_plan["no_go_rows"],
        "priority_counts": recheck_plan["priority_counts"],
        "action_counts": recheck_plan["action_counts"],
        "items": queue_rows,
        "requirements": {
            "network_required": False,
            "github_write_permission_required": False,
            "external_model_required": False,
            "billing_required": False,
        },
        "boundary": (
            "Recheck queue is local read-only tracker work. It schedules evidence review only; "
            "it does not claim rewards, post comments, contact maintainers, open pull requests, "
            "or guarantee merge or payout outcomes."
        ),
    }


def cash_actions_funded_issues(
    issues: list[FundedIssue],
    *,
    safe_only: bool = False,
    profile: ClientProfile | None = None,
    platform: str | None = None,
    language: str | None = None,
    min_usd: float | None = None,
    opportunity_state: str | None = None,
    risk_level: str | None = None,
    max_actions: int | None = None,
) -> dict[str, Any]:
    if max_actions is not None and max_actions < 1:
        raise ValueError("max_actions must be at least 1")
    report_payload = report_funded_issues(
        issues,
        safe_only=safe_only,
        profile=profile,
        platform=platform,
        language=language,
        min_usd=min_usd,
        opportunity_state=opportunity_state,
        risk_level=risk_level,
    )
    actions = _cash_action_rows(report_payload)
    actions_before_limit = len(actions)
    if max_actions is not None:
        actions = actions[:max_actions]
    return {
        "schema_version": CASH_ACTIONS_SCHEMA_VERSION,
        "source_schema_version": SCHEMA_VERSION,
        "read_only": True,
        "safe_only": safe_only,
        "blocked_actions": BLOCKED_ACTIONS,
        "filters": report_payload["filters"],
        "cash_path_status": report_payload["cash_path_status"],
        "intake_followup": report_payload["intake_followup"],
        "delivery_pack": report_payload["delivery_pack"],
        "source_quality": report_payload["source_quality"],
        "action_limit": max_actions,
        "actions_before_limit": actions_before_limit,
        "action_rows": len(actions),
        "items": actions,
        "requirements": {
            "network_required": False,
            "github_write_permission_required": False,
            "external_model_required": False,
            "billing_required": False,
        },
        "boundary": (
            "Cash actions are internal structured handoff only, not external prose. They do "
            "not create a payment route, claim rewards, post comments, contact maintainers, "
            "open pull requests, or guarantee merge or payout outcomes."
        ),
    }


def fulfillment_packet_funded_issues(
    issues: list[FundedIssue],
    *,
    safe_only: bool = False,
    profile: ClientProfile | None = None,
    platform: str | None = None,
    language: str | None = None,
    min_usd: float | None = None,
    opportunity_state: str | None = None,
    risk_level: str | None = None,
    max_items: int | None = None,
) -> dict[str, Any]:
    if max_items is not None and max_items < 1:
        raise ValueError("max_items must be at least 1")
    report_payload = report_funded_issues(
        issues,
        safe_only=safe_only,
        profile=profile,
        platform=platform,
        language=language,
        min_usd=min_usd,
        opportunity_state=opportunity_state,
        risk_level=risk_level,
    )
    recheck_payload = recheck_funded_issues(
        issues,
        safe_only=safe_only,
        profile=profile,
        platform=platform,
        language=language,
        min_usd=min_usd,
        opportunity_state=opportunity_state,
        risk_level=risk_level,
    )
    cash_payload = cash_actions_funded_issues(
        issues,
        safe_only=safe_only,
        profile=profile,
        platform=platform,
        language=language,
        min_usd=min_usd,
        opportunity_state=opportunity_state,
        risk_level=risk_level,
    )
    items = _fulfillment_items(
        report_payload=report_payload,
        recheck_payload=recheck_payload,
        cash_payload=cash_payload,
    )
    qa_gates = _fulfillment_qa_gates(report_payload)
    items_before_limit = len(items)
    if max_items is not None:
        items = items[:max_items]
    return {
        "schema_version": FULFILLMENT_PACKET_SCHEMA_VERSION,
        "source_schema_version": SCHEMA_VERSION,
        "read_only": True,
        "safe_only": safe_only,
        "blocked_actions": BLOCKED_ACTIONS,
        "filters": report_payload["filters"],
        "packet_limit": max_items,
        "items_before_limit": items_before_limit,
        "item_rows": len(items),
        "status": _fulfillment_status(report_payload),
        "suggested_package": report_payload["delivery_budget"]["suggested_package"],
        "cash_path_status": report_payload["cash_path_status"],
        "totals": {
            "loaded": report_payload["totals"]["loaded"],
            "in_scope": report_payload["totals"]["in_scope"],
            "candidate_references": len(
                report_payload["delivery_pack"]["handoff"]["candidate_references"]
            ),
            "verification_references": len(
                report_payload["delivery_pack"]["handoff"]["verification_references"]
            ),
            "no_go_references": len(report_payload["delivery_pack"]["handoff"]["no_go_references"]),
            "active_rechecks": report_payload["recheck_plan"]["recheck_rows"],
            "source_count": len(report_payload["source_quality"]["sources"]),
        },
        "qa_gates": qa_gates,
        "delivery_readiness": _fulfillment_delivery_readiness(
            qa_gates=qa_gates,
            items=items,
            report_payload=report_payload,
        ),
        "handoff": {
            "candidate_references": report_payload["delivery_pack"]["handoff"][
                "candidate_references"
            ],
            "verification_references": report_payload["delivery_pack"]["handoff"][
                "verification_references"
            ],
            "no_go_references": report_payload["delivery_pack"]["handoff"]["no_go_references"],
            "sections": [
                "client_fit_summary",
                "source_quality",
                "delivery_pack",
                "recheck_queue",
                "cash_actions",
            ],
            "external_body_allowed": False,
            "payment_route_allowed_now": False,
            "requires_written_acceptance_before_payment_route": True,
        },
        "items": items,
        "requirements": {
            "network_required": False,
            "github_write_permission_required": False,
            "external_model_required": False,
            "billing_required": False,
        },
        "boundary": (
            "Fulfillment packet is internal delivery operations data for read-only decision "
            "support. It is not customer-facing prose, does not create a payment route, "
            "does not claim rewards, post comments, contact maintainers, open pull requests, "
            "or guarantee merge or payout outcomes."
        ),
    }


def _cash_action_rows(report_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cash_path_status = report_payload["cash_path_status"]
    intake_followup = report_payload["intake_followup"]
    recheck_plan = report_payload["recheck_plan"]
    delivery_pack = report_payload["delivery_pack"]
    source_quality = report_payload["source_quality"]

    if cash_path_status["next_revenue_action"] == "collect_buyer_intake":
        rows.append(
            _cash_action_row(
                action="collect_buyer_intake",
                priority="high",
                reason="Required buyer-fit fields are missing before paid delivery.",
                requested_fields=[
                    field["field"]
                    for field in intake_followup["requested_fields"]
                    if field["required_before_paid_delivery"]
                ],
                evidence_references=delivery_pack["handoff"]["candidate_references"],
                suggested_package=intake_followup["suggested_package"],
                copy_brief_allowed=True,
            )
        )

    if recheck_plan["recheck_rows"]:
        rows.append(
            _cash_action_row(
                action="run_read_only_recheck",
                priority="high"
                if cash_path_status["next_revenue_action"] == "run_read_only_recheck"
                else "medium",
                reason="Candidate or watchlist rows need current public-state evidence.",
                requested_fields=[
                    field["field"]
                    for field in intake_followup["requested_fields"]
                    if field["field"] == "public_state_recheck_window"
                ],
                evidence_references=[row["reference"] for row in recheck_plan["next_rows"]],
                suggested_package=intake_followup["suggested_package"],
                copy_brief_allowed=False,
            )
        )

    if cash_path_status["next_revenue_action"] == "confirm_paid_scope":
        rows.append(
            _cash_action_row(
                action="confirm_paid_scope",
                priority="high",
                reason="Rows are buyer-ready after local checks; confirm package and written scope.",
                requested_fields=[],
                evidence_references=delivery_pack["handoff"]["candidate_references"],
                suggested_package=intake_followup["suggested_package"],
                copy_brief_allowed=True,
            )
        )

    if cash_path_status["next_revenue_action"] == "expand_permitted_sources":
        rows.append(
            _cash_action_row(
                action="expand_permitted_sources",
                priority="medium",
                reason="Current filters produced no buyer-ready candidates.",
                requested_fields=[
                    field["field"]
                    for field in intake_followup["requested_fields"]
                    if field["field"] in {"permitted_sources", "source_expansion_preferences"}
                ],
                evidence_references=[],
                suggested_package=intake_followup["suggested_package"],
                copy_brief_allowed=False,
                source_names=sorted(source_quality["sources"].keys()),
            )
        )

    if not rows:
        rows.append(
            _cash_action_row(
                action="expand_permitted_sources",
                priority="medium",
                reason="No internal cash action matched this batch; expand permitted sources.",
                requested_fields=[],
                evidence_references=[],
                suggested_package=intake_followup["suggested_package"],
                copy_brief_allowed=False,
                source_names=sorted(source_quality["sources"].keys()),
            )
        )

    return sorted(rows, key=lambda row: (_recheck_priority_rank(row["priority"]), row["action"]))


def _cash_action_row(
    *,
    action: str,
    priority: str,
    reason: str,
    requested_fields: list[str],
    evidence_references: list[str],
    suggested_package: str,
    copy_brief_allowed: bool,
    source_names: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "action": action,
        "priority": priority,
        "reason": reason,
        "requested_fields": requested_fields,
        "evidence_references": evidence_references,
        "source_names": source_names or [],
        "suggested_package": suggested_package,
        "copy_brief_allowed": copy_brief_allowed,
        "external_body_allowed": False,
        "payment_route_allowed_now": False,
        "requires_written_acceptance_before_payment_route": True,
        "blocked_actions": BLOCKED_ACTIONS,
        "boundary": (
            "Internal facts-only handoff. Do not write external prose here, create a payment "
            "route, claim rewards, post comments, contact maintainers, open pull requests, "
            "or imply merge/payout certainty."
        ),
    }


def _fulfillment_status(report_payload: dict[str, Any]) -> str:
    status = str(report_payload["intake_followup"]["status"])
    return {
        "needs_buyer_intake": "needs_buyer_intake",
        "ready_after_read_only_recheck": "needs_read_only_recheck",
        "ready_for_scope_confirmation": "ready_for_scope_confirmation",
        "needs_source_expansion": "needs_source_expansion",
    }[status]


def _fulfillment_qa_gates(report_payload: dict[str, Any]) -> list[dict[str, Any]]:
    intake_followup = report_payload["intake_followup"]
    recheck_plan = report_payload["recheck_plan"]
    source_quality = report_payload["source_quality"]
    delivery_pack = report_payload["delivery_pack"]
    return [
        _fulfillment_qa_gate(
            gate="buyer_intake_fields_complete",
            passed=intake_followup["required_before_paid_delivery"] == 0,
            reason=("Required buyer-fit fields must be present before paid delivery can start."),
            evidence=[
                field["field"]
                for field in intake_followup["requested_fields"]
                if field["required_before_paid_delivery"]
            ],
        ),
        _fulfillment_qa_gate(
            gate="public_state_recheck_complete",
            passed=recheck_plan["recheck_rows"] == 0,
            reason="Candidate rows need current public-state evidence before delivery use.",
            evidence=[row["reference"] for row in recheck_plan["next_rows"]],
        ),
        _fulfillment_qa_gate(
            gate="source_quality_recorded",
            passed=bool(source_quality["sources"]),
            reason="The packet needs at least one permitted local source row.",
            evidence=sorted(source_quality["sources"].keys()),
        ),
        _fulfillment_qa_gate(
            gate="no_go_evidence_preserved",
            passed=True,
            reason="No-go rows stay in the packet as exclusion evidence, not work targets.",
            evidence=delivery_pack["handoff"]["no_go_references"],
        ),
        _fulfillment_qa_gate(
            gate="payment_route_written_acceptance",
            passed=False,
            reason="Payment routes require written buyer acceptance or a buyer-requested route.",
            evidence=[],
        ),
        _fulfillment_qa_gate(
            gate="third_party_write_boundary",
            passed=True,
            reason=("Fulfillment is local read-only work and does not authorize external writes."),
            evidence=BLOCKED_ACTIONS,
        ),
    ]


def _fulfillment_qa_gate(
    *,
    gate: str,
    passed: bool,
    reason: str,
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "gate": gate,
        "passed": passed,
        "reason": reason,
        "evidence": evidence,
    }


def _fulfillment_delivery_readiness(
    *,
    qa_gates: list[dict[str, Any]],
    items: list[dict[str, Any]],
    report_payload: dict[str, Any],
) -> dict[str, Any]:
    blocking_gates = [gate["gate"] for gate in qa_gates if not gate["passed"]]
    blocking_items = [item for item in items if item["blocks_paid_delivery"]]
    ready_for_paid_delivery = not blocking_gates and not blocking_items
    return {
        "ready_for_paid_delivery": ready_for_paid_delivery,
        "status": "ready_for_paid_delivery" if ready_for_paid_delivery else "blocked_internal",
        "passed_gates": [gate["gate"] for gate in qa_gates if gate["passed"]],
        "blocking_gates": blocking_gates,
        "blocking_item_actions": sorted({str(item["action"]) for item in blocking_items}),
        "blocking_reference_scope": sorted(
            {reference for item in blocking_items for reference in item["reference_scope"]}
        ),
        "next_internal_action": report_payload["cash_path_status"]["next_revenue_action"],
        "payment_route_allowed_now": False,
        "external_body_allowed": False,
        "boundary": (
            "Delivery readiness is internal operations status only. It does not authorize "
            "customer-facing prose, payment routes, claims, comments, maintainer contact, "
            "pull requests, or merge/payout guarantees."
        ),
    }


def _fulfillment_items(
    *,
    report_payload: dict[str, Any],
    recheck_payload: dict[str, Any],
    cash_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in cash_payload["items"]:
        items.append(
            _fulfillment_item(
                stage="cash_path",
                priority=row["priority"],
                action=row["action"],
                reference_scope=row["evidence_references"] or row["source_names"],
                evidence_required=row["requested_fields"],
                reason=row["reason"],
                blocks_paid_delivery=row["action"]
                in {"collect_buyer_intake", "confirm_paid_scope"},
            )
        )
    for row in recheck_payload["items"]:
        items.append(
            _fulfillment_item(
                stage="public_state_recheck",
                priority=row["priority"],
                action=row["action"],
                reference_scope=[row["reference"]],
                evidence_required=row["evidence_checklist"],
                reason=row["reason"],
                blocks_paid_delivery=True,
            )
        )
    if not report_payload["source_quality"]["sources"]:
        items.append(
            _fulfillment_item(
                stage="source_expansion",
                priority="high",
                action="expand_permitted_sources",
                reference_scope=[],
                evidence_required=["permitted public/API source name", "source URL"],
                reason="No permitted source rows matched this packet.",
                blocks_paid_delivery=True,
            )
        )
    return sorted(
        items,
        key=lambda item: (
            _recheck_priority_rank(str(item["priority"])),
            str(item["stage"]),
            str(item["action"]),
        ),
    )


def _fulfillment_item(
    *,
    stage: str,
    priority: str,
    action: str,
    reference_scope: list[str],
    evidence_required: list[str],
    reason: str,
    blocks_paid_delivery: bool,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "priority": priority,
        "action": action,
        "reference_scope": reference_scope,
        "evidence_required": evidence_required,
        "reason": reason,
        "blocks_paid_delivery": blocks_paid_delivery,
        "external_body_allowed": False,
        "payment_route_allowed_now": False,
        "github_write_permission_required": False,
        "network_required": False,
        "blocked_actions": BLOCKED_ACTIONS,
        "boundary": (
            "Internal read-only fulfillment item. Do not write customer prose here, create "
            "a payment route, claim rewards, post comments, contact maintainers, open pull "
            "requests, or imply merge/payout certainty."
        ),
    }


def _recheck_queue_row(row: dict[str, Any]) -> dict[str, Any]:
    issue = row["issue"]
    decision_gate = str(row["decision_gate"])
    action = _recheck_action_for_gate(decision_gate)
    return {
        "reference": issue["reference"],
        "title": issue["title"],
        "url": issue["url"],
        "platform": issue["platform"],
        "funding": issue["funding"]["display"],
        "opportunity_state": issue["opportunity_state"],
        "risk_level": issue["risk_level"],
        "score": row["score"],
        "confidence": row["confidence"],
        "decision_gate": decision_gate,
        "priority": _recheck_priority_for_gate(decision_gate),
        "action": action,
        "reason": _recheck_reason_for_gate(decision_gate),
        "evidence_checklist": _recheck_evidence_checklist(action),
        "recommended_next_step": row["recommended_next_step"],
        "blocked_actions": BLOCKED_ACTIONS,
    }


def _recheck_evidence_checklist(action: str) -> list[str]:
    checklists = {
        "recheck_public_issue_state": [
            "confirm issue is still open from permitted public/API source",
            "confirm no assignee or active competing pull request",
            "confirm funding is still visible before paid shortlist use",
        ],
        "recheck_scope_and_noise": [
            "confirm scope is still narrow enough for paid review",
            "confirm recent maintainer signal or clear acceptance criteria",
            "confirm row is not only useful as no-go evidence",
        ],
        "verify_funding_visibility": [
            "confirm visible amount and currency from permitted public/API source",
            "record funding source URL or park as funding unclear",
            "do not rank by amount until funding is verified",
        ],
        "confirm_client_authorization": [
            "keep row parked unless buyer authorizes bounded review",
            "do not contact maintainers or touch third-party repositories",
            "record authorization boundary before any deeper analysis",
        ],
    }
    return checklists.get(
        action,
        ["review public evidence locally and preserve read-only boundaries"],
    )


def _decision_summary(scored_rows: list[dict[str, Any]]) -> dict[str, Any]:
    gate_counts = Counter(str(row["decision_gate"]) for row in scored_rows)
    gate_counts = Counter({gate: gate_counts.get(gate, 0) for gate in sorted(VALID_DECISION_GATES)})
    candidate_rows = sum(1 for row in scored_rows if row["rating"] in {"go_candidate", "watchlist"})
    no_go_rows = sum(1 for row in scored_rows if row["rating"] == "no_go")
    return {
        "total_rows": len(scored_rows),
        "candidate_rows": candidate_rows,
        "no_go_rows": no_go_rows,
        "gate_counts": dict(gate_counts),
        "verification_needed": gate_counts["needs_funding_verification"],
        "authorization_needed": gate_counts["needs_authorization"],
        "recommended_batch_action": _recommended_batch_action(
            candidate_rows=candidate_rows,
            no_go_rows=no_go_rows,
            verification_needed=gate_counts["needs_funding_verification"],
            authorization_needed=gate_counts["needs_authorization"],
        ),
        "safety_boundary": (
            "Use for local decision support only; re-check public state before any engagement "
            "decision and do not claim, comment, pull-request, or contact maintainers automatically."
        ),
    }


def _recommended_batch_action(
    *,
    candidate_rows: int,
    no_go_rows: int,
    verification_needed: int,
    authorization_needed: int,
) -> str:
    if candidate_rows:
        return (
            "Review go-after-recheck and watchlist candidates locally; keep no-go rows as "
            "exclusion evidence and verify public state before any engagement decision."
        )
    if verification_needed:
        return (
            "Verify funding and current issue state from permitted public/API sources before "
            "ranking this batch."
        )
    if authorization_needed:
        return (
            "Keep authorization-gated rows parked unless the client separately requests a "
            "bounded review."
        )
    if no_go_rows:
        return "Do not spend engineering time on this batch; use no-go rows as evidence."
    return "No in-scope rows; expand permitted read-only sources before ranking."


def _delivery_budget(scored_rows: list[dict[str, Any]]) -> dict[str, Any]:
    minutes_by_gate = {
        "go_after_recheck": 10,
        "watchlist": 10,
        "needs_funding_verification": 4,
        "needs_authorization": 3,
        "no_go": 3,
    }
    package = _suggested_package_for_rows(len(scored_rows))
    max_paid_hours = {
        "none": 0,
        "mini_diagnostic": 3,
        "validation_sprint": 5,
        "opportunity_shortlist": 10,
        "custom_batch": None,
    }[package]
    estimated_minutes = sum(
        minutes_by_gate.get(str(row["decision_gate"]), 3) for row in scored_rows
    )
    estimated_hours = round(estimated_minutes / 60, 2)
    l2_rows = sum(1 for row in scored_rows if row["rating"] in {"go_candidate", "watchlist"})
    l1_rows = len(scored_rows) - l2_rows
    return {
        "suggested_package": package,
        "estimated_review_minutes": estimated_minutes,
        "estimated_review_hours": estimated_hours,
        "max_paid_hours": max_paid_hours,
        "within_margin_budget": (
            True if max_paid_hours is None else estimated_hours <= max_paid_hours
        ),
        "analysis_rows": {
            "l1_state_and_noise_review": l1_rows,
            "l2_scope_and_readiness_review": l2_rows,
            "l3_deep_dive_deferred": 0,
        },
        "boundary": (
            "Budget is for local read-only triage. Do not clone repos, run deep repro, "
            "contact maintainers, claim rewards, or open pull requests before paid scope."
        ),
    }


def _delivery_pack(scored_rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_rows = [
        row for row in scored_rows if row["decision_gate"] in {"go_after_recheck", "watchlist"}
    ]
    verification_rows = [
        row
        for row in scored_rows
        if row["decision_gate"] in {"needs_funding_verification", "needs_authorization"}
    ]
    no_go_rows = [row for row in scored_rows if row["decision_gate"] == "no_go"]
    phases = [
        _delivery_phase(
            phase="l1_state_and_noise_review",
            rows=verification_rows + no_go_rows,
            objective="Confirm current public state, funding visibility, and exclusion evidence.",
            exit_criteria="Every row is parked for missing evidence or excluded as no-go evidence.",
        ),
        _delivery_phase(
            phase="l2_shortlist_readiness_review",
            rows=candidate_rows,
            objective="Re-check active candidate rows before using paid shortlist time.",
            exit_criteria="Candidate rows have current public state, scope, and contribution rules checked.",
        ),
        _delivery_phase(
            phase="l3_deep_dive_deferred",
            rows=[],
            objective="Defer reproduction and implementation research until paid scope is explicit.",
            exit_criteria="No deep-dive work starts from this read-only tracker artifact.",
        ),
    ]
    return {
        "suggested_package": _suggested_package_for_rows(len(scored_rows)),
        "phase_counts": {phase["phase"]: phase["row_count"] for phase in phases},
        "phases": phases,
        "handoff": {
            "candidate_references": _delivery_references(candidate_rows),
            "verification_references": _delivery_references(verification_rows),
            "no_go_references": _delivery_references(no_go_rows),
        },
        "boundary": (
            "Delivery pack is a local read-only work plan for paid decision support. It does "
            "not authorize claiming, commenting, contacting maintainers, opening pull requests, "
            "or guaranteeing merge or payout outcomes."
        ),
    }


def _delivery_phase(
    *,
    phase: str,
    rows: list[dict[str, Any]],
    objective: str,
    exit_criteria: str,
) -> dict[str, Any]:
    return {
        "phase": phase,
        "row_count": len(rows),
        "references": _delivery_references(rows),
        "objective": objective,
        "exit_criteria": exit_criteria,
    }


def _delivery_references(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(str(row["issue"]["reference"]) for row in rows)


def _source_quality(scored_rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in scored_rows:
        source = str(row["issue"]["platform"])
        grouped.setdefault(source, []).append(row)

    sources: dict[str, dict[str, Any]] = {}
    for source, rows in sorted(grouped.items()):
        total_rows = len(rows)
        candidate_rows = sum(1 for row in rows if row["rating"] in {"go_candidate", "watchlist"})
        no_go_rows = sum(1 for row in rows if row["rating"] == "no_go")
        safe_to_list = sum(1 for row in rows if row["issue"]["safe_to_list"])
        funding_verification_needed = sum(
            1 for row in rows if row["decision_gate"] == "needs_funding_verification"
        )
        authorization_needed = sum(
            1 for row in rows if row["decision_gate"] == "needs_authorization"
        )
        scores = [int(row["score"]) for row in rows]
        usable_signal_ratio = round(candidate_rows / total_rows, 2) if total_rows else 0
        sources[source] = {
            "total_rows": total_rows,
            "candidate_rows": candidate_rows,
            "no_go_rows": no_go_rows,
            "safe_to_list": safe_to_list,
            "funding_verification_needed": funding_verification_needed,
            "authorization_needed": authorization_needed,
            "average_score": round(sum(scores) / total_rows, 2) if total_rows else 0,
            "usable_signal_ratio": usable_signal_ratio,
            "recommended_use": _recommended_source_use(
                candidate_rows=candidate_rows,
                no_go_rows=no_go_rows,
                funding_verification_needed=funding_verification_needed,
                authorization_needed=authorization_needed,
            ),
        }
    return {
        "summary": _source_quality_rollup(sources),
        "sources": sources,
        "boundary": (
            "Source quality is read-only benchmarking for Opportunity Desk triage. It is not "
            "permission to scrape aggressively, claim rewards, contact maintainers, comment, "
            "or open pull requests."
        ),
    }


def _source_quality_rollup(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source_count = len(sources)
    total_rows = sum(int(source["total_rows"]) for source in sources.values())
    candidate_rows = sum(int(source["candidate_rows"]) for source in sources.values())
    no_go_rows = sum(int(source["no_go_rows"]) for source in sources.values())
    funding_verification_needed = sum(
        int(source["funding_verification_needed"]) for source in sources.values()
    )
    authorization_needed = sum(int(source["authorization_needed"]) for source in sources.values())
    candidate_source_count = sum(1 for source in sources.values() if source["candidate_rows"])
    no_go_only_source_count = sum(
        1 for source in sources.values() if source["no_go_rows"] and not source["candidate_rows"]
    )
    status = _source_quality_status(
        source_count=source_count,
        candidate_source_count=candidate_source_count,
        funding_verification_needed=funding_verification_needed,
        authorization_needed=authorization_needed,
        no_go_only_source_count=no_go_only_source_count,
    )
    return {
        "source_count": source_count,
        "total_rows": total_rows,
        "candidate_rows": candidate_rows,
        "no_go_rows": no_go_rows,
        "candidate_source_count": candidate_source_count,
        "no_go_only_source_count": no_go_only_source_count,
        "funding_verification_needed": funding_verification_needed,
        "authorization_needed": authorization_needed,
        "status": status,
        "next_tracker_action": _source_quality_next_tracker_action(status),
        "boundary": (
            "Source summary is local tracker evidence only. It does not authorize scraping, "
            "claims, comments, maintainer contact, pull requests, or payout/merge guarantees."
        ),
    }


def _source_quality_status(
    *,
    source_count: int,
    candidate_source_count: int,
    funding_verification_needed: int,
    authorization_needed: int,
    no_go_only_source_count: int,
) -> str:
    if source_count == 0:
        return "no_sources"
    if candidate_source_count:
        return "candidate_sources_available"
    if funding_verification_needed:
        return "needs_funding_verification"
    if authorization_needed:
        return "needs_authorization"
    if no_go_only_source_count:
        return "no_go_only_sources"
    return "collect_more_rows"


def _source_quality_next_tracker_action(status: str) -> str:
    return {
        "no_sources": "Expand permitted public/API sources before ranking this batch.",
        "candidate_sources_available": (
            "Run read-only public-state recheck on candidate sources before paid shortlist use."
        ),
        "needs_funding_verification": (
            "Verify visible funding and current state from permitted public/API sources."
        ),
        "needs_authorization": "Keep authorization-gated source rows parked until buyer scope exists.",
        "no_go_only_sources": (
            "Use these sources as no-go moat evidence and expand coverage before pitching."
        ),
        "collect_more_rows": "Collect more permitted source rows before ranking this batch.",
    }[status]


def _recheck_plan(scored_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for row in scored_rows:
        issue = row["issue"]
        decision_gate = str(row["decision_gate"])
        action = _recheck_action_for_gate(decision_gate)
        priority = _recheck_priority_for_gate(decision_gate)
        rows.append(
            {
                "reference": issue["reference"],
                "platform": issue["platform"],
                "decision_gate": decision_gate,
                "priority": priority,
                "action": action,
                "reason": _recheck_reason_for_gate(decision_gate),
            }
        )

    active_rechecks = [row for row in rows if row["action"] != "archive_as_no_go_evidence"]
    priority_counts = Counter(row["priority"] for row in active_rechecks)
    action_counts = Counter(row["action"] for row in rows)
    return {
        "total_rows": len(rows),
        "recheck_rows": len(active_rechecks),
        "no_go_rows": action_counts.get("archive_as_no_go_evidence", 0),
        "priority_counts": dict(sorted(priority_counts.items())),
        "action_counts": dict(sorted(action_counts.items())),
        "next_rows": sorted(
            active_rechecks,
            key=lambda row: (
                _recheck_priority_rank(row["priority"]),
                row["platform"],
                row["reference"],
            ),
        ),
        "boundary": (
            "Recheck plan is local read-only tracker triage. It schedules evidence review only; "
            "it does not claim, comment, contact maintainers, open pull requests, or guarantee payout."
        ),
    }


def _recheck_action_for_gate(decision_gate: str) -> str:
    return {
        "go_after_recheck": "recheck_public_issue_state",
        "watchlist": "recheck_scope_and_noise",
        "needs_funding_verification": "verify_funding_visibility",
        "needs_authorization": "confirm_client_authorization",
        "no_go": "archive_as_no_go_evidence",
    }.get(decision_gate, "recheck_public_issue_state")


def _recheck_priority_for_gate(decision_gate: str) -> str:
    return {
        "go_after_recheck": "high",
        "needs_funding_verification": "high",
        "watchlist": "medium",
        "needs_authorization": "medium",
        "no_go": "none",
    }.get(decision_gate, "medium")


def _recheck_reason_for_gate(decision_gate: str) -> str:
    return {
        "go_after_recheck": "Candidate rows need current public state recheck before shortlist use.",
        "watchlist": "Watchlist rows need scope/noise recheck before paid review time.",
        "needs_funding_verification": (
            "Funding or current state is unclear and must be verified from permitted sources."
        ),
        "needs_authorization": "Row should stay parked until client authorization is explicit.",
        "no_go": "Keep as exclusion evidence; do not spend delivery time.",
    }.get(decision_gate, "Review public state before ranking this row.")


def _recheck_priority_rank(priority: str) -> int:
    return {"high": 0, "medium": 1, "low": 2, "none": 3}.get(priority, 2)


def _client_fit_gaps(
    issues: list[FundedIssue],
    profile: ClientProfile | None,
) -> list[dict[str, Any]]:
    if profile is None:
        return []

    rows: list[dict[str, Any]] = []
    for issue in issues:
        gaps = _client_fit_gap_codes(issue, profile)
        if not gaps:
            continue
        rows.append(
            {
                "reference": issue.reference,
                "title": issue.title,
                "url": issue.url,
                "platform": issue.platform,
                "gap_codes": gaps,
                "gap_summary": _client_fit_gap_summary(gaps),
            }
        )
    return rows


def _client_fit_summary(
    issues: list[FundedIssue],
    profile: ClientProfile | None,
    client_fit_gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    total_rows = len(issues)
    excluded_rows = len(client_fit_gaps) if profile else 0
    matching_rows = max(0, total_rows - excluded_rows)
    gap_counts = Counter(gap_code for row in client_fit_gaps for gap_code in row["gap_codes"])
    return {
        "profile_name": profile.name if profile and profile.name else None,
        "status": _client_fit_status(profile, total_rows, matching_rows, excluded_rows),
        "total_rows": total_rows,
        "matching_rows": matching_rows,
        "excluded_rows": excluded_rows,
        "gap_counts": dict(sorted(gap_counts.items())),
        "recommended_action": _client_fit_recommended_action(
            profile=profile,
            total_rows=total_rows,
            matching_rows=matching_rows,
            excluded_rows=excluded_rows,
        ),
        "boundary": (
            "Client fit is local buyer-fit evidence only. It does not authorize claiming "
            "rewards, contacting maintainers, posting comments, or opening pull requests."
        ),
    }


def _client_fit_status(
    profile: ClientProfile | None,
    total_rows: int,
    matching_rows: int,
    excluded_rows: int,
) -> str:
    if profile is None:
        return "no_profile"
    if total_rows == 0:
        return "no_rows"
    if matching_rows == 0:
        return "no_matching_rows"
    if excluded_rows:
        return "partial_match"
    return "all_rows_match"


def _client_fit_recommended_action(
    *,
    profile: ClientProfile | None,
    total_rows: int,
    matching_rows: int,
    excluded_rows: int,
) -> str:
    if profile is None:
        return "Attach a read-only client profile before buyer-specific shortlist delivery."
    if total_rows == 0:
        return "Expand permitted read-only sources before buyer-fit ranking."
    if matching_rows == 0:
        return (
            "Do not pitch this batch as buyer-ready; expand sources or adjust the client profile."
        )
    if excluded_rows:
        return "Use matching rows for shortlist review and keep excluded rows as fit-gap evidence."
    return "Use this batch for buyer-specific shortlist review after public-state recheck."


def _intake_followup(
    *,
    client_fit_summary: dict[str, Any],
    recheck_plan: dict[str, Any],
    delivery_budget: dict[str, Any],
    source_quality: dict[str, Any],
    decision_summary: dict[str, Any],
) -> dict[str, Any]:
    requested_fields: list[dict[str, Any]] = []
    if client_fit_summary["status"] == "no_profile":
        requested_fields.extend(
            [
                _intake_field(
                    "preferred_languages",
                    "Needed to filter funded issues to stacks the buyer can actually work.",
                    True,
                ),
                _intake_field(
                    "minimum_payout_usd",
                    "Needed to keep low-value rows out of a paid shortlist.",
                    True,
                ),
                _intake_field(
                    "allowed_risk_levels",
                    "Needed to avoid proposing high-risk rows as buyer-ready.",
                    True,
                ),
            ]
        )
    elif client_fit_summary["status"] in {"no_matching_rows", "partial_match"}:
        requested_fields.append(
            _intake_field(
                "profile_gap_confirmation",
                "Needed to decide whether to expand sources or adjust buyer-fit filters.",
                True,
            )
        )

    if recheck_plan["recheck_rows"]:
        requested_fields.append(
            _intake_field(
                "public_state_recheck_window",
                "Needed because active candidates require read-only public-state recheck before delivery.",
                False,
            )
        )

    if not source_quality["sources"]:
        requested_fields.append(
            _intake_field(
                "permitted_sources",
                "Needed because no source rows matched the current filters.",
                True,
            )
        )
    elif decision_summary["candidate_rows"] == 0 and decision_summary["no_go_rows"] > 0:
        requested_fields.append(
            _intake_field(
                "source_expansion_preferences",
                "Needed because the current batch is useful as no-go evidence but has no candidates.",
                False,
            )
        )

    required_count = sum(1 for field in requested_fields if field["required_before_paid_delivery"])
    if required_count:
        status = "needs_buyer_intake"
    elif recheck_plan["recheck_rows"]:
        status = "ready_after_read_only_recheck"
    elif decision_summary["candidate_rows"]:
        status = "ready_for_scope_confirmation"
    else:
        status = "needs_source_expansion"

    return {
        "status": status,
        "suggested_package": delivery_budget["suggested_package"],
        "required_before_paid_delivery": required_count,
        "requested_fields": requested_fields,
        "next_internal_action": _intake_next_internal_action(status),
        "boundary": (
            "Intake follow-up is structured internal handoff data. It is not customer-facing "
            "email copy and does not authorize claims, comments, pull requests, maintainer "
            "outreach, payout guarantees, or payment routes without written buyer acceptance."
        ),
    }


def _intake_field(
    field: str,
    reason: str,
    required_before_paid_delivery: bool,
) -> dict[str, Any]:
    return {
        "field": field,
        "reason": reason,
        "required_before_paid_delivery": required_before_paid_delivery,
    }


def _intake_next_internal_action(status: str) -> str:
    return {
        "needs_buyer_intake": (
            "Use these fields as facts in a PatchRail copy-brief after buyer interest; do not write "
            "external prose here."
        ),
        "ready_after_read_only_recheck": (
            "Run read-only public-state recheck before turning candidates into a paid report."
        ),
        "ready_for_scope_confirmation": (
            "Confirm paid scope and package; create payment route only after written buyer acceptance."
        ),
        "needs_source_expansion": (
            "Expand permitted read-only sources before pitching this batch as buyer-ready."
        ),
    }[status]


def _cash_path_status(intake_followup: dict[str, Any]) -> dict[str, Any]:
    status = str(intake_followup["status"])
    next_actions = {
        "needs_buyer_intake": "collect_buyer_intake",
        "ready_after_read_only_recheck": "run_read_only_recheck",
        "ready_for_scope_confirmation": "confirm_paid_scope",
        "needs_source_expansion": "expand_permitted_sources",
    }
    return {
        "status": status,
        "next_revenue_action": next_actions[status],
        "copy_brief_facts_available": status
        in {"needs_buyer_intake", "ready_for_scope_confirmation"},
        "payment_route_allowed_now": False,
        "requires_written_acceptance_before_payment_route": True,
        "buyer_ready": status == "ready_for_scope_confirmation",
        "boundary": (
            "Cash-path status is internal structured handoff only. It is not external prose, "
            "does not create a payment route, and does not authorize claims, comments, pull "
            "requests, maintainer outreach, or payout/merge guarantees."
        ),
    }


def _client_fit_gap_codes(issue: FundedIssue, profile: ClientProfile) -> list[str]:
    gaps: list[str] = []
    if profile.languages and (issue.language or "").lower() not in profile.languages:
        gaps.append("LANGUAGE_MISMATCH")
    if profile.min_usd is not None:
        if issue.funding_amount is None:
            gaps.append("FUNDING_UNKNOWN")
        elif issue.funding_currency != "USD":
            gaps.append("FUNDING_CURRENCY_NOT_USD")
        elif issue.funding_amount < profile.min_usd:
            gaps.append("FUNDING_BELOW_MIN_USD")
    if (
        profile.allowed_opportunity_states
        and issue.opportunity_state not in profile.allowed_opportunity_states
    ):
        gaps.append("OPPORTUNITY_STATE_NOT_ALLOWED")
    if profile.allowed_risk_levels and issue.risk_level not in profile.allowed_risk_levels:
        gaps.append("RISK_LEVEL_NOT_ALLOWED")
    if profile.excluded_risk_flags:
        excluded_flags = sorted(set(issue.risk_flags).intersection(profile.excluded_risk_flags))
        gaps.extend(f"EXCLUDED_RISK_FLAG:{flag}" for flag in excluded_flags)
    return gaps


def _client_fit_gap_summary(gaps: list[str]) -> str:
    if not gaps:
        return "Matches the local client profile."
    labels = {
        "LANGUAGE_MISMATCH": "language outside the profile",
        "FUNDING_UNKNOWN": "funding is unknown",
        "FUNDING_CURRENCY_NOT_USD": "funding is not in USD",
        "FUNDING_BELOW_MIN_USD": "funding below profile minimum",
        "OPPORTUNITY_STATE_NOT_ALLOWED": "opportunity state outside the profile",
        "RISK_LEVEL_NOT_ALLOWED": "risk level outside the profile",
    }
    rendered = [
        labels.get(gap, f"excluded risk flag {gap.split(':', 1)[1]}")
        if gap.startswith("EXCLUDED_RISK_FLAG:")
        else labels.get(gap, gap.lower())
        for gap in gaps
    ]
    return "; ".join(rendered)


def _recommended_source_use(
    *,
    candidate_rows: int,
    no_go_rows: int,
    funding_verification_needed: int,
    authorization_needed: int,
) -> str:
    if candidate_rows:
        return "Prioritize for L2 review after public-state recheck."
    if funding_verification_needed:
        return "Use only after funding and current-state verification."
    if authorization_needed:
        return "Park until a client separately authorizes bounded review."
    if no_go_rows:
        return "Use as no-go moat evidence before expanding this source."
    return "Collect more rows before ranking this source."


def _suggested_package_for_rows(row_count: int) -> str:
    if row_count == 0:
        return "none"
    if row_count <= 5:
        return "mini_diagnostic"
    if row_count <= 20:
        return "validation_sprint"
    if row_count <= 50:
        return "opportunity_shortlist"
    return "custom_batch"


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

    if issue.opportunity_state == "closed":
        components["risk_penalty"] -= 35
        reason_codes.append("CLOSED_OR_INACTIVE")
    elif issue.opportunity_state == "stale":
        components["risk_penalty"] -= 30
        reason_codes.append("STALE_NO_MAINTAINER_SIGNAL")
    elif issue.opportunity_state == "unknown":
        reason_codes.append("OPPORTUNITY_STATE_UNCLEAR")

    score += sum(value for key, value in components.items() if key != "base")
    score = max(0, min(100, score))
    if issue.risk_level == "high" or issue.opportunity_state in {"closed", "stale"}:
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
        "confidence": _confidence_for_issue(issue),
        "rating": rating,
        "decision_gate": _decision_gate_for_score(issue, rating, reason_codes),
        "reason_codes": sorted(set(reason_codes)) or ["NO_MAJOR_REVIEW_GAPS"],
        "components": components,
        "recommended_next_step": _recommended_next_step_for_score(issue, rating, reason_codes),
    }


def _confidence_for_issue(issue: FundedIssue) -> float:
    confidence = 0.5
    if issue.funding_amount is not None and issue.funding_currency:
        confidence += 0.15
    if issue.contribution_guidelines_url:
        confidence += 0.15
    confidence += min(len(issue.contribution_signals), 3) * 0.05

    if issue.opportunity_state == "active":
        confidence += 0.05
    elif issue.opportunity_state == "unknown":
        confidence -= 0.15
    elif issue.opportunity_state in {"closed", "stale"}:
        confidence -= 0.2

    confidence -= min(len(issue.risk_flags), 4) * 0.05
    if issue.risk_level == "high":
        confidence -= 0.1
    return round(max(0.05, min(0.99, confidence)), 2)


def _decision_gate_for_score(
    issue: FundedIssue,
    rating: str,
    reason_codes: list[str],
) -> str:
    reason_code_set = set(reason_codes)
    if issue.opportunity_state in {"closed", "stale"}:
        return "no_go"
    if "NEEDS_AUTHORIZATION" in reason_code_set:
        return "needs_authorization"
    if "FUNDING_STATE_UNCLEAR" in reason_code_set or issue.opportunity_state == "unknown":
        return "needs_funding_verification"
    if issue.risk_level == "high":
        return "no_go"
    if rating == "go_candidate":
        return "go_after_recheck"
    if rating == "watchlist":
        return "watchlist"
    return "no_go"


def _recommended_next_step_for_score(
    issue: FundedIssue,
    rating: str,
    reason_codes: list[str],
) -> str:
    reason_code_set = set(reason_codes)
    if issue.opportunity_state in {"closed", "stale"}:
        return "Do not engage unless public project evidence shows the opportunity is live again."
    if issue.risk_level == "high":
        return "Keep as no-go evidence unless the client separately authorizes a bounded review."
    if "FUNDING_STATE_UNCLEAR" in reason_code_set or issue.opportunity_state == "unknown":
        return "Verify funding and current issue state from permitted public/API sources before ranking."
    if "NO_CONTRIBUTION_GUIDELINES" in reason_code_set:
        return "Treat as watchlist until contribution rules and maintainer expectations are clear."
    if rating == "go_candidate":
        return "Reproduce locally and re-check assignment, active PRs, and funding before any engagement decision."
    if rating == "watchlist":
        return "Keep in the watchlist and wait for clearer public maintainer or testability signal."
    return "Do not spend engineering time on this opportunity in the current batch."


def _risk_reason_code(flag: str) -> str:
    return {
        "ambiguous_scope": "SCOPE_TOO_BROAD",
        "bounty_farming_language": "BOUNTY_FARMING_RISK",
        "requires_external_contact": "NEEDS_AUTHORIZATION",
        "no_contribution_guidelines": "NO_CONTRIBUTION_GUIDELINES",
        "spam_attractive": "SPAM_ATTRACTIVE",
        "stale_no_maintainer_signal": "STALE_NO_MAINTAINER_SIGNAL",
        "closed_or_inactive": "CLOSED_OR_INACTIVE",
    }.get(flag, f"RISK_{flag.upper()}")


def _normalize_opportunity_state(value: Any) -> str:
    if value is None:
        return "unknown"
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"active", "open", "opened", "live", "available"}:
        return "active"
    if normalized in {"closed", "completed", "done", "paid", "resolved", "cancelled"}:
        return "closed"
    if normalized in {"stale", "inactive", "abandoned", "expired"}:
        return "stale"
    return normalized if normalized in VALID_OPPORTUNITY_STATES else "unknown"


def _normalize_opportunity_state_filter(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _normalize_opportunity_state(value)
    if normalized not in VALID_OPPORTUNITY_STATES:
        raise ValueError(f"invalid opportunity_state: {value}")
    return normalized


def _normalize_risk_level_filter(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in VALID_RISK_LEVELS:
        raise ValueError(f"invalid risk_level: {value}")
    return normalized


def _matches_report_filter(
    issue: FundedIssue,
    *,
    profile: ClientProfile | None,
    platform: str | None,
    language: str | None,
    min_usd: float | None,
    opportunity_state: str | None,
    risk_level: str | None,
) -> bool:
    if profile:
        if profile.languages and (issue.language or "").lower() not in profile.languages:
            return False
        effective_min_usd = profile.min_usd
        if effective_min_usd is not None:
            if issue.funding_currency != "USD" or issue.funding_amount is None:
                return False
            if issue.funding_amount < effective_min_usd:
                return False
        if (
            profile.allowed_opportunity_states
            and issue.opportunity_state not in profile.allowed_opportunity_states
        ):
            return False
        if profile.allowed_risk_levels and issue.risk_level not in profile.allowed_risk_levels:
            return False
        if profile.excluded_risk_flags and set(issue.risk_flags).intersection(
            profile.excluded_risk_flags
        ):
            return False
    if platform and issue.platform.lower() != platform.lower():
        return False
    if language and (issue.language or "").lower() != language.lower():
        return False
    if min_usd is not None:
        if issue.funding_currency != "USD" or issue.funding_amount is None:
            return False
        if issue.funding_amount < min_usd:
            return False
    if opportunity_state and issue.opportunity_state != opportunity_state:
        return False
    if risk_level and issue.risk_level != risk_level:
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
