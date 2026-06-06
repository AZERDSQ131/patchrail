from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from typing import Any

from patchrail import __version__
from patchrail.queue.store import (
    DEFAULT_QUEUE_PATH,
    export_audit_events,
    init_queue,
    list_proposals,
    list_work_items,
)

QUEUE_STATUS_SCHEMA_VERSION = "patchrail.queue_status.v1"
QUEUE_AUDIT_SUMMARY_SCHEMA_VERSION = "patchrail.queue_audit_summary.v1"
QUEUE_BUNDLE_SCHEMA_VERSION = "patchrail.queue_bundle.v1"
QUEUE_GATE_REPORT_SCHEMA_VERSION = "patchrail.queue_gate_report.v1"
QUEUE_REVIEW_SCHEMA_VERSION = "patchrail.queue_review.v1"
QUEUE_POLICY_SCAN_SCHEMA_VERSION = "patchrail.queue_policy_scan.v1"

DEFAULT_REQUIRED_AUDIT_EVENTS = [
    "work_item_added",
    "proposal_added",
    "proposal_approved",
    "proposal_rejected",
    "work_item_approved",
    "work_item_rejected",
    "work_items_exported",
]

SAFE_QUEUE_REQUIREMENTS = {
    "billing_required": False,
    "external_model_required": False,
    "network_required": False,
    "github_write_permission_required": False,
    "write_actions_allowed_by_default": False,
}

SAFE_QUEUE_STATUS = {
    **SAFE_QUEUE_REQUIREMENTS,
    "approval_records_execute_actions": False,
}

LOCAL_PATH_PATTERN = re.compile(
    r"(/Volumes|/Users|/home|/tmp|/private/tmp|/var/folders|/private/var)/[^\s\"'`]+"
)

POLICY_SCAN_RULES = {
    "automatic_pull_request": [
        "automatic pr",
        "automatic pull request",
        "auto pr",
        "auto-submit",
        "auto submit",
        "open pr automatically",
        "open pull request automatically",
    ],
    "automatic_issue_comment": [
        "automatic issue comment",
        "comment automatically",
        "mass comment",
        "post a comment",
        "post comment",
    ],
    "outbound_contact": [
        "contact maintainers",
        "devrel",
        "lead",
        "outbound",
        "sales",
        "send email",
    ],
    "funding_or_claim": [
        "bounty",
        "claim reward",
        "funding claim",
        "invoice",
        "paid pilot",
        "payment link",
        "payout",
        "pricing",
    ],
    "identity_or_money_gate": [
        "bank",
        "card",
        "government id",
        "kyc",
        "phone",
        "postal address",
        "tax form",
    ],
    "external_write": [
        "external repo",
        "force-push",
        "third-party",
    ],
}


def _redact_local_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_local_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_local_paths(item) for item in value]
    if isinstance(value, str):
        return LOCAL_PATH_PATTERN.sub(
            lambda match: f"<local-path>/{Path(match.group(0)).name}",
            value,
        )
    return value


def _policy_scan_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=True)


def _policy_matches(text: str) -> list[dict[str, str]]:
    normalized = " ".join(text.lower().replace("_", " ").replace("-", " ").split())
    matches: list[dict[str, str]] = []
    for category, terms in POLICY_SCAN_RULES.items():
        for term in terms:
            normalized_term = " ".join(term.lower().replace("_", " ").replace("-", " ").split())
            if normalized_term in normalized:
                matches.append({"category": category, "term": term})
    return matches


def _policy_scan_work_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if item["status"] == "skipped" or item["approval_state"] == "rejected":
        return None
    haystack = "\n".join(
        [
            _policy_scan_text(item.get("kind")),
            _policy_scan_text(item.get("title")),
            _policy_scan_text(item.get("source")),
            _policy_scan_text(item.get("payload")),
            _policy_scan_text(item.get("decision_note")),
        ]
    )
    matches = _policy_matches(haystack)
    if not matches:
        return None
    return {
        "record_type": "work_item",
        "id": item["id"],
        "title": item["title"],
        "status": item["status"],
        "approval_state": item["approval_state"],
        "source": item["source"],
        "matched_categories": sorted({match["category"] for match in matches}),
        "matched_terms": sorted({match["term"] for match in matches}),
        "recommended_action": "reject_or_skip_before_handoff",
    }


def _policy_scan_proposal(proposal: dict[str, Any]) -> dict[str, Any] | None:
    if proposal["approval_state"] == "rejected":
        return None
    haystack = "\n".join(
        [
            _policy_scan_text(proposal.get("title")),
            _policy_scan_text(proposal.get("summary")),
            _policy_scan_text(proposal.get("patch_plan")),
            _policy_scan_text(proposal.get("decision_note")),
        ]
    )
    matches = _policy_matches(haystack)
    if not matches:
        return None
    return {
        "record_type": "proposal",
        "id": proposal["id"],
        "work_item_id": proposal["work_item_id"],
        "title": proposal["title"],
        "risk_level": proposal["risk_level"],
        "approval_state": proposal["approval_state"],
        "matched_categories": sorted({match["category"] for match in matches}),
        "matched_terms": sorted({match["term"] for match in matches}),
        "recommended_action": "reject_before_handoff",
    }


def queue_status_payload(
    db_path: Path = DEFAULT_QUEUE_PATH,
    *,
    include_api_compat: bool = False,
) -> dict[str, Any]:
    init_result = init_queue(db_path)
    work_items = _redact_local_paths([item.to_dict() for item in list_work_items(db_path=db_path)])
    proposals = _redact_local_paths(
        [proposal.to_dict() for proposal in list_proposals(db_path=db_path)]
    )
    audit_events = _redact_local_paths(export_audit_events(db_path=db_path)["audit_events"])
    work_item_approval_counts = Counter(item["approval_state"] for item in work_items)
    work_item_status_counts = Counter(item["status"] for item in work_items)
    proposal_approval_counts = Counter(proposal["approval_state"] for proposal in proposals)
    pending_work_items = work_item_approval_counts.get("pending", 0)
    pending_proposals = proposal_approval_counts.get("pending", 0)
    total_pending_decisions = pending_work_items + pending_proposals
    latest_audit_event = audit_events[-1] if audit_events else None
    payload: dict[str, Any] = {
        "schema_version": QUEUE_STATUS_SCHEMA_VERSION,
        "queue_schema_version": init_result["schema_version"],
        "patchrail_version": __version__,
        "db_path": _redact_local_paths(str(db_path)),
        "local_first": True,
        "host_boundary": "127.0.0.1 only by default",
        "counts": {
            "work_items_total": len(work_items),
            "work_items_by_status": dict(sorted(work_item_status_counts.items())),
            "work_items_by_approval_state": dict(sorted(work_item_approval_counts.items())),
            "proposals_total": len(proposals),
            "proposals_by_approval_state": dict(sorted(proposal_approval_counts.items())),
            "audit_events_total": len(audit_events),
        },
        "human_gate_summary": {
            "status": (
                "awaiting_human_review" if total_pending_decisions > 0 else "no_pending_decisions"
            ),
            "pending_work_items": pending_work_items,
            "pending_proposals": pending_proposals,
            "total_pending_decisions": total_pending_decisions,
            "approved_work_items": work_item_approval_counts.get("approved", 0),
            "rejected_work_items": work_item_approval_counts.get("rejected", 0),
            "approved_proposals": proposal_approval_counts.get("approved", 0),
            "rejected_proposals": proposal_approval_counts.get("rejected", 0),
            "write_actions_unlocked": False,
        },
        "latest_audit_event": latest_audit_event,
        "safety": SAFE_QUEUE_STATUS,
    }
    if include_api_compat:
        payload["requirements"] = SAFE_QUEUE_REQUIREMENTS
        payload["queue"] = {
            "schema_version": init_result["schema_version"],
            "work_items": len(work_items),
            "pending_work_items": work_item_approval_counts.get("pending", 0),
            "proposals": len(proposals),
            "pending_proposals": proposal_approval_counts.get("pending", 0),
        }
    return payload


def queue_audit_summary_payload(
    db_path: Path = DEFAULT_QUEUE_PATH,
    *,
    required_events: list[str] | None = None,
) -> dict[str, Any]:
    init_result = init_queue(db_path)
    audit_events = export_audit_events(db_path=db_path)["audit_events"]
    work_items = [item.to_dict() for item in list_work_items(db_path=db_path)]
    proposals = [proposal.to_dict() for proposal in list_proposals(db_path=db_path)]
    event_counts = Counter(event["event_type"] for event in audit_events)
    required = required_events or DEFAULT_REQUIRED_AUDIT_EVENTS
    missing_required_events = [event for event in required if event_counts.get(event, 0) == 0]
    affected_work_items = sorted(
        {
            str(event["work_item_id"])
            for event in audit_events
            if event.get("work_item_id") is not None
        }
    )
    gates = {
        "work_item_approval_gate_exercised": event_counts.get("work_item_approved", 0) > 0,
        "work_item_rejection_gate_exercised": event_counts.get("work_item_rejected", 0) > 0,
        "work_item_skip_gate_exercised": event_counts.get("work_item_skipped", 0) > 0,
        "proposal_approval_gate_exercised": event_counts.get("proposal_approved", 0) > 0,
        "proposal_rejection_gate_exercised": event_counts.get("proposal_rejected", 0) > 0,
        "queue_export_recorded": event_counts.get("work_items_exported", 0) > 0,
    }
    return {
        "schema_version": QUEUE_AUDIT_SUMMARY_SCHEMA_VERSION,
        "queue_schema_version": init_result["schema_version"],
        "patchrail_version": __version__,
        "db_path": _redact_local_paths(str(db_path)),
        "local_first": True,
        "status": "human_gates_exercised"
        if not missing_required_events
        else "needs_more_audit_evidence",
        "counts": {
            "audit_events_total": len(audit_events),
            "event_types": dict(sorted(event_counts.items())),
            "work_items_total": len(work_items),
            "proposals_total": len(proposals),
            "affected_work_items": len(affected_work_items),
        },
        "required_events": required,
        "missing_required_events": missing_required_events,
        "gates": gates,
        "affected_work_item_ids": affected_work_items,
        "latest_audit_event": audit_events[-1] if audit_events else None,
        "safety": SAFE_QUEUE_STATUS,
    }


def queue_bundle_payload(
    db_path: Path = DEFAULT_QUEUE_PATH,
    *,
    required_events: list[str] | None = None,
) -> dict[str, Any]:
    status = _redact_local_paths(queue_status_payload(db_path))
    audit_summary = _redact_local_paths(
        queue_audit_summary_payload(db_path, required_events=required_events)
    )
    work_items = _redact_local_paths([item.to_dict() for item in list_work_items(db_path=db_path)])
    proposals = _redact_local_paths(
        [proposal.to_dict() for proposal in list_proposals(db_path=db_path)]
    )
    audit_events = _redact_local_paths(export_audit_events(db_path=db_path)["audit_events"])
    ready = audit_summary["status"] == "human_gates_exercised"
    gate_summary = status["human_gate_summary"]
    remaining_gate_gaps = audit_summary["missing_required_events"]
    reviewer_summary = {
        "status": "ready_for_reviewer_handoff" if ready else "needs_more_gate_evidence",
        "ready_for_handoff": ready,
        "human_gates_complete": ready,
        "pending_decisions": gate_summary["total_pending_decisions"],
        "approved_work_items": gate_summary["approved_work_items"],
        "rejected_work_items": gate_summary["rejected_work_items"],
        "approved_proposals": gate_summary["approved_proposals"],
        "rejected_proposals": gate_summary["rejected_proposals"],
        "remaining_gate_gaps": remaining_gate_gaps,
        "review_steps": [
            "Inspect work_items for local CI evidence and write_actions_allowed=false.",
            "Inspect proposals for approved low-risk plans and rejected risky plans.",
            "Inspect audit_summary for required human gate events.",
            "Inspect safety to confirm the bundle is read-only and local paths are redacted.",
        ],
        "execution_allowed": False,
    }
    return {
        "schema_version": QUEUE_BUNDLE_SCHEMA_VERSION,
        "queue_schema_version": status["queue_schema_version"],
        "patchrail_version": __version__,
        "db_path": _redact_local_paths(str(db_path)),
        "local_first": True,
        "status": "ready_for_handoff" if ready else "needs_more_gate_evidence",
        "counts": {
            "work_items_total": len(work_items),
            "proposals_total": len(proposals),
            "audit_events_total": len(audit_events),
        },
        "status_summary": status,
        "audit_summary": audit_summary,
        "work_items": work_items,
        "proposals": proposals,
        "audit_events": audit_events,
        "reviewer_summary": reviewer_summary,
        "safety": {
            **SAFE_QUEUE_STATUS,
            "bundle_is_read_only": True,
            "bundle_records_audit_event": False,
            "local_paths_redacted": True,
        },
        "remaining_gate_gaps": remaining_gate_gaps,
    }


def queue_gate_report_payload(
    db_path: Path = DEFAULT_QUEUE_PATH,
    *,
    required_events: list[str] | None = None,
) -> dict[str, Any]:
    status = _redact_local_paths(queue_status_payload(db_path))
    audit_summary = _redact_local_paths(
        queue_audit_summary_payload(db_path, required_events=required_events)
    )
    gate_summary = status["human_gate_summary"]
    missing_required_events = audit_summary["missing_required_events"]
    pending_decisions = gate_summary["total_pending_decisions"]
    ready = pending_decisions == 0 and not missing_required_events
    reviewer_actions: list[str] = []
    if pending_decisions:
        reviewer_actions.append("Review or reject all pending work items and proposals.")
    if missing_required_events:
        reviewer_actions.append("Exercise the missing local human-gate audit events.")
    if not reviewer_actions:
        reviewer_actions.append("Inspect the queue bundle before any separate write action.")
    return {
        "schema_version": QUEUE_GATE_REPORT_SCHEMA_VERSION,
        "queue_schema_version": status["queue_schema_version"],
        "patchrail_version": __version__,
        "db_path": _redact_local_paths(str(db_path)),
        "local_first": True,
        "status": "ready_for_reviewer_handoff" if ready else "needs_reviewer_decisions",
        "ready_for_reviewer_handoff": ready,
        "pending_decisions": pending_decisions,
        "missing_required_events": missing_required_events,
        "decision_counts": {
            "pending_work_items": gate_summary["pending_work_items"],
            "pending_proposals": gate_summary["pending_proposals"],
            "approved_work_items": gate_summary["approved_work_items"],
            "rejected_work_items": gate_summary["rejected_work_items"],
            "approved_proposals": gate_summary["approved_proposals"],
            "rejected_proposals": gate_summary["rejected_proposals"],
        },
        "audit_counts": audit_summary["counts"],
        "gates": audit_summary["gates"],
        "reviewer_actions": reviewer_actions,
        "safety": {
            **SAFE_QUEUE_STATUS,
            "report_is_read_only": True,
            "report_records_audit_event": False,
            "local_paths_redacted": True,
            "execution_allowed": False,
        },
    }


def _compact_work_item(item: dict[str, Any]) -> dict[str, Any]:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    return {
        "id": item["id"],
        "kind": item["kind"],
        "title": item["title"],
        "source": item["source"],
        "status": item["status"],
        "approval_state": item["approval_state"],
        "write_actions_allowed": item["write_actions_allowed"],
        "decision_note": item.get("decision_note"),
        "payload_keys": sorted(str(key) for key in payload),
    }


def _compact_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": proposal["id"],
        "work_item_id": proposal["work_item_id"],
        "title": proposal["title"],
        "risk_level": proposal["risk_level"],
        "approval_state": proposal["approval_state"],
        "decision_note": proposal.get("decision_note"),
    }


def queue_review_payload(db_path: Path = DEFAULT_QUEUE_PATH) -> dict[str, Any]:
    status = queue_status_payload(db_path)
    work_items = _redact_local_paths([item.to_dict() for item in list_work_items(db_path=db_path)])
    proposals = _redact_local_paths(
        [proposal.to_dict() for proposal in list_proposals(db_path=db_path)]
    )
    pending_work_items = [
        _compact_work_item(item) for item in work_items if item["approval_state"] == "pending"
    ]
    pending_proposals = [
        _compact_proposal(proposal)
        for proposal in proposals
        if proposal["approval_state"] == "pending"
    ]
    approved_work_items = [
        _compact_work_item(item) for item in work_items if item["approval_state"] == "approved"
    ]
    approved_proposals = [
        _compact_proposal(proposal)
        for proposal in proposals
        if proposal["approval_state"] == "approved"
    ]
    rejected_work_items = [
        _compact_work_item(item) for item in work_items if item["approval_state"] == "rejected"
    ]
    rejected_proposals = [
        _compact_proposal(proposal)
        for proposal in proposals
        if proposal["approval_state"] == "rejected"
    ]
    pending_decisions = len(pending_work_items) + len(pending_proposals)
    reviewer_actions: list[str] = []
    if pending_work_items:
        reviewer_actions.append("Review pending work items, then approve, reject, or skip them.")
    if pending_proposals:
        reviewer_actions.append("Review pending proposals, then approve or reject each local plan.")
    if not reviewer_actions:
        reviewer_actions.append("No pending decisions remain; inspect gate-report or bundle next.")
    return {
        "schema_version": QUEUE_REVIEW_SCHEMA_VERSION,
        "queue_schema_version": status["queue_schema_version"],
        "patchrail_version": __version__,
        "db_path": _redact_local_paths(str(db_path)),
        "local_first": True,
        "status": "awaiting_human_review" if pending_decisions else "clear_for_handoff",
        "ready_for_reviewer_handoff": pending_decisions == 0,
        "pending_decisions": pending_decisions,
        "counts": status["counts"],
        "review_groups": {
            "pending_work_items": pending_work_items,
            "pending_proposals": pending_proposals,
            "approved_work_items": approved_work_items,
            "approved_proposals": approved_proposals,
            "rejected_work_items": rejected_work_items,
            "rejected_proposals": rejected_proposals,
        },
        "reviewer_actions": reviewer_actions,
        "safety": {
            **SAFE_QUEUE_STATUS,
            "review_is_read_only": True,
            "review_records_audit_event": False,
            "local_paths_redacted": True,
            "execution_allowed": False,
        },
    }


def queue_policy_scan_payload(db_path: Path = DEFAULT_QUEUE_PATH) -> dict[str, Any]:
    status = queue_status_payload(db_path)
    work_items = _redact_local_paths([item.to_dict() for item in list_work_items(db_path=db_path)])
    proposals = _redact_local_paths(
        [proposal.to_dict() for proposal in list_proposals(db_path=db_path)]
    )
    matches = [
        *(match for item in work_items if (match := _policy_scan_work_item(item)) is not None),
        *(
            match
            for proposal in proposals
            if (match := _policy_scan_proposal(proposal)) is not None
        ),
    ]
    reviewer_actions = (
        [
            "Reject or skip matching local records before any handoff.",
            "Keep historical records visible; do not delete queue data to hide policy drift.",
        ]
        if matches
        else ["No policy-blocking queue records found; continue with gate-report or bundle."]
    )
    return {
        "schema_version": QUEUE_POLICY_SCAN_SCHEMA_VERSION,
        "queue_schema_version": status["queue_schema_version"],
        "patchrail_version": __version__,
        "db_path": _redact_local_paths(str(db_path)),
        "local_first": True,
        "status": "blocked_records_present" if matches else "policy_clear",
        "blocked_records_count": len(matches),
        "scanned_counts": {
            "work_items_total": len(work_items),
            "proposals_total": len(proposals),
            "audit_events_total": status["counts"]["audit_events_total"],
        },
        "policy_categories": sorted(POLICY_SCAN_RULES),
        "matches": matches,
        "reviewer_actions": reviewer_actions,
        "safety": {
            **SAFE_QUEUE_STATUS,
            "scan_is_read_only": True,
            "scan_records_audit_event": False,
            "local_paths_redacted": True,
            "execution_allowed": False,
        },
    }
