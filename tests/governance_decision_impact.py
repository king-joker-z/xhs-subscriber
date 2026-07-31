"""Pure-memory impact analysis for explicit synthetic governance decisions.

Future adoption must call this helper explicitly; it does not connect to runtime
execution, governance sequences, Summary, or any external system.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
import re

_SCENARIOS = frozenset({
    "public_single_work", "quality_degraded", "review_required",
    "access_restricted", "tls_failure", "terminal_block",
})
_OUTCOMES = frozenset({
    "accepted_public_single_work", "quality_degraded", "review_required",
    "access_restricted", "tls_failure", "block",
})
_ACTIONS = frozenset({
    "continue_processing", "quality_guidance_shown", "review_sample_created",
    "quality_guarantee", "retain_standard", "retain_minimal",
})
_FIELDS = frozenset({"scenario_id", "outcome", "allowed_actions", "retention_level", "terminal", "matrix_version", "fixture_digest", "contract_version"})
_OUTCOME_RANK = {
    "accepted_public_single_work": 0,
    "quality_degraded": 1,
    "review_required": 2,
    "tls_failure": 3,
    "access_restricted": 4,
    "block": 5,
}
_RETENTION_RANK = {"none": 0, "minimal": 1, "standard": 2}
_HEX = re.compile(r"[0-9a-f]{64}")
_VERSION = re.compile(r"governance-decision-matrix/v[1-9][0-9]*")
_SAFE_ACTIONS_BY_OUTCOME = {
    "accepted_public_single_work": frozenset({"continue_processing", "quality_guidance_shown", "review_sample_created", "quality_guarantee", "retain_standard", "retain_minimal"}),
    "quality_degraded": frozenset({"quality_guidance_shown"}),
    "review_required": frozenset({"review_sample_created"}),
    "access_restricted": frozenset(),
    "tls_failure": frozenset(),
    "block": frozenset(),
}


def analyze_decision_impact(before: Sequence[Mapping[str, Any]], after: Sequence[Mapping[str, Any]], expected_fixture_digest: str, active_contract_version: str) -> dict[str, Any]:
    """Compare explicit synthetic matrices and accept only equivalent/tighter outcomes."""
    if not isinstance(expected_fixture_digest, str) or not _HEX.fullmatch(expected_fixture_digest):
        return _invalid()
    if not isinstance(active_contract_version, str) or not active_contract_version:
        return _invalid()
    parsed_before = _parse_matrix(before, expected_fixture_digest, active_contract_version)
    parsed_after = _parse_matrix(after, expected_fixture_digest, active_contract_version)
    if parsed_before is None or parsed_after is None:
        return _invalid()
    before_versions = {entry["matrix_version"] for entry in parsed_before.values()}
    after_versions = {entry["matrix_version"] for entry in parsed_after.values()}
    if len(before_versions) != 1 or len(after_versions) != 1 or before_versions != after_versions:
        return _version_mismatch()
    if not parsed_before or not parsed_after or set(parsed_before) != set(parsed_after):
        return _coverage_missing()
    for scenario in parsed_before:
        if parsed_before[scenario]["terminal"] and not parsed_after[scenario]["terminal"]:
            return _reject("decision_impact_terminal_weakened")
    if any(not entry["safe"] for entry in (*parsed_before.values(), *parsed_after.values())):
        return _invalid()

    for scenario in parsed_before:
        old, new = parsed_before[scenario], parsed_after[scenario]
        if old["terminal"] and not new["terminal"]:
            return _reject("decision_impact_terminal_weakened")
        if _OUTCOME_RANK[new["outcome"]] < _OUTCOME_RANK[old["outcome"]]:
            return _reject("decision_impact_terminal_weakened")
        if not new["actions"].issubset(old["actions"]):
            return _reject("decision_impact_actions_weakened")
        if _RETENTION_RANK[new["retention_level"]] > _RETENTION_RANK[old["retention_level"]]:
            return _reject("decision_impact_retention_weakened")
    return {
        "status": "valid",
        "reason": "impact_tightened_or_equal",
        "matrix_version_before": next(iter(before_versions)),
        "matrix_version_after": next(iter(after_versions)),
        "scenario_count": len(parsed_before),
        "outcome_tightened_count": sum(_OUTCOME_RANK[parsed_after[key]["outcome"]] > _OUTCOME_RANK[parsed_before[key]["outcome"]] for key in parsed_before),
        "actions_reduced_count": sum(parsed_after[key]["actions"] < parsed_before[key]["actions"] for key in parsed_before),
        "retention_tightened_count": sum(_RETENTION_RANK[parsed_after[key]["retention_level"]] < _RETENTION_RANK[parsed_before[key]["retention_level"]] for key in parsed_before),
    }


def _parse_matrix(value: Any, expected_digest: str, contract: str) -> dict[str, dict[str, Any]] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    parsed: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping) or set(item) != _FIELDS:
            return None
        scenario, outcome = item.get("scenario_id"), item.get("outcome")
        actions, retention, terminal = item.get("allowed_actions"), item.get("retention_level"), item.get("terminal")
        version, digest, item_contract = item.get("matrix_version"), item.get("fixture_digest"), item.get("contract_version")
        if (
            not isinstance(scenario, str) or scenario not in _SCENARIOS or scenario in parsed
            or not isinstance(outcome, str) or outcome not in _OUTCOMES
            or not isinstance(actions, Sequence) or isinstance(actions, (str, bytes))
            or any(not isinstance(action, str) for action in actions) or len(set(actions)) != len(actions) or not set(actions).issubset(_ACTIONS)
            or not isinstance(retention, str) or retention not in _RETENTION_RANK
            or type(terminal) is not bool or not isinstance(version, str) or not _VERSION.fullmatch(version)
            or not isinstance(digest, str) or digest != expected_digest or not _HEX.fullmatch(digest)
            or item_contract != contract
        ):
            return None
        if terminal and (actions or retention != "none"):
            return None
        parsed[scenario] = {"outcome": outcome, "actions": frozenset(actions), "retention_level": retention, "terminal": terminal, "matrix_version": version, "safe": _safe_shape(outcome, frozenset(actions), retention, terminal)}
    return parsed


def _safe_shape(outcome: str, actions: frozenset[str], retention: str, terminal: bool) -> bool:
    if outcome in {"block", "access_restricted", "tls_failure"}:
        return terminal and not actions and retention == "none"
    if outcome == "accepted_public_single_work":
        return not terminal and retention in {"minimal", "standard"} and actions.issubset(_SAFE_ACTIONS_BY_OUTCOME[outcome])
    if outcome in {"quality_degraded", "review_required"}:
        return not terminal and retention in {"none", "minimal"} and actions.issubset(_SAFE_ACTIONS_BY_OUTCOME[outcome])
    return False


def _reject(reason: str) -> dict[str, Any]:
    return {"status": "rejected", "reason": reason}


def _coverage_missing() -> dict[str, Any]:
    return {"status": "rejected", "reason": "decision_impact_coverage_missing"}


def _version_mismatch() -> dict[str, Any]:
    return {"status": "rejected", "reason": "version_mismatch"}


def _invalid() -> dict[str, Any]:
    return {"status": "rejected", "reason": "invalid_impact"}
