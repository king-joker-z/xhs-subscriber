"""Pure-memory validation for synthetic governance rule coverage declarations."""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_SCHEMA_VERSION = "rule_coverage_contract/v1"
_RULES = frozenset({
    "purpose_before_result",
    "tls_before_success",
    "terminal_after_block",
    "baseline_provenance_approval",
    "governance_sequence",
})
_SEVERITIES = frozenset({"required", "info"})
_ASSERTIONS = frozenset({
    "purpose_guard",
    "tls_guard",
    "terminal_guard",
    "approval_guard",
    "sequence_guard",
})
_RULE_ASSERTIONS = {
    "purpose_before_result": "purpose_guard",
    "tls_before_success": "tls_guard",
    "terminal_after_block": "terminal_guard",
    "baseline_provenance_approval": "approval_guard",
    "governance_sequence": "sequence_guard",
}
_REASONS_BY_RULE = {
    "purpose_before_result": frozenset({"purpose_before_result"}),
    "tls_before_success": frozenset({"tls_before_success"}),
    "terminal_after_block": frozenset({"terminal_after_block"}),
    "baseline_provenance_approval": frozenset({"approval_before_manifest", "reapproval_required"}),
    "governance_sequence": frozenset({"invalid_trace"}),
}
_MANIFEST_FIELDS = frozenset({"schema_version", "contract_version", "fixture_version", "rules"})
_RULE_FIELDS = frozenset({"rule_id", "severity", "positive_case", "negative_case"})
_POSITIVE_FIELDS = frozenset({"fixture_digest", "assertion_id", "passed"})
_NEGATIVE_FIELDS = frozenset({"fixture_digest", "assertion_id", "passed", "expected_rejection"})
_HEX_RE = re.compile(r"[0-9a-f]{64}")


def validate_rule_coverage(
    manifest: Mapping[str, Any], active_contract_version: str, active_fixture_version: str,
) -> dict[str, str]:
    """Validate only explicit synthetic evidence declarations; no tests are executed."""
    if not isinstance(manifest, Mapping) or not isinstance(active_contract_version, str) or not isinstance(active_fixture_version, str):
        return {"status": "rejected", "reason": "invalid_coverage"}
    try:
        if set(manifest) != _MANIFEST_FIELDS or manifest["schema_version"] != _SCHEMA_VERSION:
            return {"status": "rejected", "reason": "invalid_coverage"}
        if (manifest["contract_version"] != active_contract_version or
                manifest["fixture_version"] != active_fixture_version):
            return {"status": "rejected", "reason": "version_mismatch"}
        rules = manifest["rules"]
        if not isinstance(rules, Sequence) or isinstance(rules, (str, bytes)):
            return {"status": "rejected", "reason": "invalid_coverage"}
        seen: set[str] = set()
        for rule in rules:
            if not isinstance(rule, Mapping) or set(rule) != _RULE_FIELDS:
                return {"status": "rejected", "reason": "invalid_coverage"}
            rule_id = rule["rule_id"]
            if not isinstance(rule_id, str) or rule_id not in _RULES or rule_id in seen:
                return {"status": "rejected", "reason": "invalid_coverage"}
            severity = rule["severity"]
            if severity != "required":
                return {"status": "rejected", "reason": "invalid_coverage"}
            positive = rule["positive_case"]
            negative = rule["negative_case"]
            if positive is None:
                return {"status": "rejected", "reason": "coverage_missing_positive_case"}
            if negative is None:
                return {"status": "rejected", "reason": "coverage_missing_negative_case"}
            if (not _valid_positive(positive) or not _valid_negative(negative) or
                    positive["assertion_id"] != _RULE_ASSERTIONS[rule_id] or
                    negative["assertion_id"] != _RULE_ASSERTIONS[rule_id]):
                return {"status": "rejected", "reason": "invalid_coverage"}
            if (not positive["passed"] or not negative["passed"] or
                    negative["expected_rejection"] not in _REASONS_BY_RULE[rule_id]):
                return {"status": "rejected", "reason": "negative_case_not_effective"}
            seen.add(rule_id)
        if not _RULES <= seen:
            missing = _RULES - seen
            return {"status": "rejected", "reason": "coverage_missing_positive_case" if missing else "invalid_coverage"}
    except (KeyError, TypeError):
        return {"status": "rejected", "reason": "invalid_coverage"}
    return {"status": "valid"}


def _valid_positive(case: Any) -> bool:
    return (isinstance(case, Mapping) and set(case) == _POSITIVE_FIELDS and
            _valid_evidence(case) and type(case["passed"]) is bool)


def _valid_negative(case: Any) -> bool:
    return (isinstance(case, Mapping) and set(case) == _NEGATIVE_FIELDS and _valid_evidence(case) and
            type(case["passed"]) is bool and isinstance(case["expected_rejection"], str))


def _valid_evidence(case: Mapping[str, Any]) -> bool:
    return (isinstance(case["fixture_digest"], str) and bool(_HEX_RE.fullmatch(case["fixture_digest"])) and
            isinstance(case["assertion_id"], str) and case["assertion_id"] in _ASSERTIONS)
