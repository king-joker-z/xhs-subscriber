"""Pure-memory resolver for synthetic governance decision conflicts."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_RULES = frozenset({
    "purpose_before_result",
    "tls_before_success",
    "terminal_after_block",
    "baseline_provenance_approval",
    "governance_sequence",
})
_OUTCOMES = frozenset({
    "accepted_public_single_work",
    "quality_degraded",
    "review_required",
    "access_restricted",
    "tls_failure",
    "block",
})
_ACTIONS = frozenset({
    "continue_processing",
    "quality_guidance_shown",
    "review_sample_created",
    "quality_guarantee",
    "retain_standard",
    "retain_minimal",
})
_FIELDS = frozenset({"rule_id", "outcome", "allowed_actions", "retention_level", "terminal"})
_RETENTION_RANK = {"none": 0, "minimal": 1, "standard": 2}
_PRIORITY = {
    "accepted_public_single_work": 0,
    "quality_degraded": 1,
    "review_required": 2,
    "tls_failure": 3,
    "access_restricted": 4,
    "block": 5,
}
_ALLOWED_OUTCOMES_BY_RULE = {
    "purpose_before_result": frozenset({"accepted_public_single_work", "block"}),
    "tls_before_success": frozenset({"accepted_public_single_work", "tls_failure", "block"}),
    "terminal_after_block": frozenset({"accepted_public_single_work", "access_restricted", "tls_failure", "block"}),
    "baseline_provenance_approval": frozenset({"accepted_public_single_work", "review_required", "access_restricted", "block"}),
    "governance_sequence": _OUTCOMES,
}
_INPUT_ALLOWED_ACTIONS_BY_OUTCOME = {
    "accepted_public_single_work": frozenset({"continue_processing", "quality_guidance_shown", "review_sample_created", "quality_guarantee", "retain_standard", "retain_minimal"}),
    "quality_degraded": frozenset({"continue_processing", "quality_guidance_shown"}),
    "review_required": frozenset({"continue_processing", "review_sample_created"}),
    "access_restricted": frozenset(),
    "tls_failure": frozenset(),
    "block": frozenset(),
}
_OUTPUT_ALLOWED_ACTIONS_BY_OUTCOME = {
    "accepted_public_single_work": _INPUT_ALLOWED_ACTIONS_BY_OUTCOME["accepted_public_single_work"],
    "quality_degraded": frozenset({"quality_guidance_shown"}),
    "review_required": frozenset({"review_sample_created"}),
    "access_restricted": frozenset(),
    "tls_failure": frozenset(),
    "block": frozenset(),
}
_ALLOWED_RETENTION_BY_OUTCOME = {
    "accepted_public_single_work": frozenset({"minimal", "standard"}),
    "quality_degraded": frozenset({"none", "minimal"}),
    "review_required": frozenset({"none", "minimal"}),
    "access_restricted": frozenset({"none"}),
    "tls_failure": frozenset({"none"}),
    "block": frozenset({"none"}),
}


def resolve_governance_conflict(decisions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Resolve only explicit synthetic decisions; no runtime state or I/O is used."""
    if not isinstance(decisions, Sequence) or isinstance(decisions, (str, bytes)) or not decisions:
        return _default_deny()
    seen: set[str] = set()
    parsed: list[dict[str, Any]] = []
    for decision in decisions:
        if not isinstance(decision, Mapping) or set(decision) != _FIELDS:
            return _invalid()
        rule_id, outcome = decision.get("rule_id"), decision.get("outcome")
        actions, retention, terminal = decision.get("allowed_actions"), decision.get("retention_level"), decision.get("terminal")
        if (
            not isinstance(rule_id, str)
            or rule_id not in _RULES
            or rule_id in seen
            or not isinstance(outcome, str)
            or outcome not in _ALLOWED_OUTCOMES_BY_RULE[rule_id]
            or not _valid_actions(actions, outcome)
            or not isinstance(retention, str)
            or retention not in _ALLOWED_RETENTION_BY_OUTCOME[outcome]
            or type(terminal) is not bool
        ):
            return _invalid()
        seen.add(rule_id)
        parsed.append({"outcome": outcome, "actions": frozenset(actions), "retention": retention, "terminal": terminal})

    selected = max(parsed, key=lambda item: _PRIORITY[item["outcome"]])["outcome"]
    terminal = any(item["terminal"] for item in parsed)
    if terminal:
        return _resolved("block", [], "none", True)
    actions = set.intersection(*(set(item["actions"]) for item in parsed))
    if not actions and selected not in {"access_restricted", "tls_failure", "block"}:
        return _default_deny()
    if selected in {"quality_degraded", "review_required"}:
        actions.intersection_update(_OUTPUT_ALLOWED_ACTIONS_BY_OUTCOME[selected])
    retention = min(parsed, key=lambda item: _RETENTION_RANK[item["retention"]])["retention"]
    if selected in {"access_restricted", "tls_failure", "block"}:
        actions, retention = set(), "none"
    return _resolved(selected, actions, retention, False)


def _resolved(outcome: str, actions: set[str] | list[str], retention: str, terminal: bool) -> dict[str, Any]:
    safe_actions = [] if outcome in {"access_restricted", "tls_failure", "block"} else sorted(actions)
    return {"status": "valid", "reason": "resolved", "outcome": outcome, "allowed_actions": safe_actions, "retention_level": retention, "terminal": terminal}


def _valid_actions(value: Any, outcome: str) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and all(isinstance(action, str) for action in value)
        and len(set(value)) == len(value)
        and set(value).issubset(_ACTIONS)
        and set(value).issubset(_INPUT_ALLOWED_ACTIONS_BY_OUTCOME[outcome])
    )


def _default_deny() -> dict[str, Any]:
    return {"status": "rejected", "reason": "default_deny", "outcome": "block", "allowed_actions": [], "retention_level": "none", "terminal": True}


def _invalid() -> dict[str, Any]:
    return {"status": "rejected", "reason": "invalid_decision", "outcome": "block", "allowed_actions": [], "retention_level": "none", "terminal": True}
