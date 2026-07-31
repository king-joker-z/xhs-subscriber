"""Pure-memory contracts for synthetic governance event sequences.

This test helper deliberately has no runtime, file, or network dependency.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_EVENT_FIELDS = frozenset({"sequence", "event"})
_EVENTS = frozenset({
    "purpose_confirmed",
    "second_confirmation_passed",
    "allowed_external_action",
    "tls_verified",
    "result_classified",
    "success_classified",
    "terminal_policy_assigned",
    "review_sample_created",
    "quality_guidance_shown",
    "summary_generated",
    "provenance_link_verified",
    "approval_freshness_verified",
    "manifest_adoptable",
    "precheck_blocked",
    "tls_failure",
    "access_restricted",
    "platform_rejected",
})
_TERMINAL_EVENTS = frozenset({
    "precheck_blocked", "tls_failure", "access_restricted", "platform_rejected",
})


def validate_governance_sequence(events: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Validate a fixed, synthetic event partial order without retaining trace data."""
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)) or not events:
        return {"status": "rejected", "reason": "invalid_trace"}

    prior: set[str] = set()
    blocked = False
    for expected, item in enumerate(events, start=1):
        if not isinstance(item, Mapping) or set(item) != _EVENT_FIELDS:
            return {"status": "rejected", "reason": "invalid_trace"}
        sequence = item.get("sequence")
        event = item.get("event")
        if type(sequence) is not int or sequence != expected or not isinstance(event, str) or event not in _EVENTS:
            return {"status": "rejected", "reason": "invalid_trace"}
        if event in prior:
            return {"status": "rejected", "reason": "invalid_trace"}
        if blocked:
            return {"status": "rejected", "reason": "terminal_after_block"}
        if event == "result_classified" and "purpose_confirmed" not in prior:
            return {"status": "rejected", "reason": "purpose_before_result"}
        if event == "allowed_external_action" and "second_confirmation_passed" not in prior:
            return {"status": "rejected", "reason": "invalid_trace"}
        if event == "success_classified":
            if "tls_verified" not in prior:
                return {"status": "rejected", "reason": "tls_before_success"}
            if "result_classified" not in prior:
                return {"status": "rejected", "reason": "invalid_trace"}
        if event in {"terminal_policy_assigned", "review_sample_created", "quality_guidance_shown"}:
            if "result_classified" not in prior:
                return {"status": "rejected", "reason": "invalid_trace"}
        if event == "summary_generated":
            if not {"result_classified", "terminal_policy_assigned"} <= prior:
                return {"status": "rejected", "reason": "invalid_trace"}
        if event == "approval_freshness_verified" and "provenance_link_verified" not in prior:
            return {"status": "rejected", "reason": "approval_before_manifest"}
        if event == "manifest_adoptable":
            if not {"provenance_link_verified", "approval_freshness_verified"} <= prior:
                return {"status": "rejected", "reason": "approval_before_manifest"}
        prior.add(event)
        if event in _TERMINAL_EVENTS:
            blocked = True
    return {"status": "valid"}
