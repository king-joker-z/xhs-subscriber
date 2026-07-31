"""Pure-memory validation for synthetic governance coverage and evidence declarations."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

_SCHEMA_VERSION = "rule_coverage_contract/v1"
_EVIDENCE_SCHEMA_VERSION = "governance-rule-evidence/v1"
_RULES = frozenset({"purpose_before_result", "tls_before_success", "terminal_after_block", "baseline_provenance_approval", "governance_sequence"})
_RULE_ASSERTIONS = {"purpose_before_result": "purpose_guard", "tls_before_success": "tls_guard", "terminal_after_block": "terminal_guard", "baseline_provenance_approval": "approval_guard", "governance_sequence": "sequence_guard"}
_REASONS_BY_RULE = {"purpose_before_result": frozenset({"purpose_before_result"}), "tls_before_success": frozenset({"tls_before_success"}), "terminal_after_block": frozenset({"terminal_after_block"}), "baseline_provenance_approval": frozenset({"approval_before_manifest", "reapproval_required"}), "governance_sequence": frozenset({"invalid_trace"})}
_MANIFEST_FIELDS = frozenset({"schema_version", "contract_version", "fixture_version", "rules"})
_RULE_FIELDS = frozenset({"rule_id", "severity", "positive_case", "negative_case"})
_POSITIVE_FIELDS = frozenset({"fixture_digest", "assertion_id", "passed"})
_NEGATIVE_FIELDS = _POSITIVE_FIELDS | frozenset({"expected_rejection"})
_EVIDENCE_MANIFEST_FIELDS = frozenset({"schema_version", "contract_version", "fixture_version", "rules", "coverage_evidence_digest"})
_EVIDENCE_RULE_FIELDS = frozenset({"rule_id", "assertion_id", "positive", "negative"})
_EVIDENCE_POSITIVE_FIELDS = frozenset({"fixture_digest", "replay_outcome", "verified_contract_version", "verified_fixture_version", "verified_schema_version", "verified_at_utc", "valid_until_utc", "replay_digest"})
_EVIDENCE_NEGATIVE_FIELDS = _EVIDENCE_POSITIVE_FIELDS | frozenset({"expected_rejection"})
_HEX_RE = re.compile(r"[0-9a-f]{64}")


def canonical_evidence_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


def validate_rule_coverage(manifest: Mapping[str, Any], active_contract_version: str, active_fixture_version: str) -> dict[str, str]:
    if not isinstance(manifest, Mapping) or not isinstance(active_contract_version, str) or not isinstance(active_fixture_version, str):
        return {"status": "rejected", "reason": "invalid_coverage"}
    try:
        if set(manifest) != _MANIFEST_FIELDS or manifest["schema_version"] != _SCHEMA_VERSION:
            return {"status": "rejected", "reason": "invalid_coverage"}
        if manifest["contract_version"] != active_contract_version or manifest["fixture_version"] != active_fixture_version:
            return {"status": "rejected", "reason": "version_mismatch"}
        rules, seen = manifest["rules"], set()
        if not isinstance(rules, Sequence) or isinstance(rules, (str, bytes)):
            return {"status": "rejected", "reason": "invalid_coverage"}
        for rule in rules:
            if not isinstance(rule, Mapping) or set(rule) != _RULE_FIELDS or rule["rule_id"] not in _RULES or rule["rule_id"] in seen or rule["severity"] != "required":
                return {"status": "rejected", "reason": "invalid_coverage"}
            positive, negative, rule_id = rule["positive_case"], rule["negative_case"], rule["rule_id"]
            if positive is None: return {"status": "rejected", "reason": "coverage_missing_positive_case"}
            if negative is None: return {"status": "rejected", "reason": "coverage_missing_negative_case"}
            if not _valid_case(positive, _POSITIVE_FIELDS) or not _valid_case(negative, _NEGATIVE_FIELDS) or positive["assertion_id"] != _RULE_ASSERTIONS[rule_id] or negative["assertion_id"] != _RULE_ASSERTIONS[rule_id]:
                return {"status": "rejected", "reason": "invalid_coverage"}
            if not positive["passed"] or not negative["passed"] or negative["expected_rejection"] not in _REASONS_BY_RULE[rule_id]:
                return {"status": "rejected", "reason": "negative_case_not_effective"}
            seen.add(rule_id)
        return {"status": "valid"} if seen == _RULES else {"status": "rejected", "reason": "coverage_missing_positive_case"}
    except (KeyError, TypeError):
        return {"status": "rejected", "reason": "invalid_coverage"}


def validate_rule_evidence_freshness(evidence_manifest: Mapping[str, Any], active_contract_version: str, active_fixture_version: str, now_utc: str, expected_fixture_digest: str) -> dict[str, str]:
    try:
        if not isinstance(expected_fixture_digest, str) or not _HEX_RE.fullmatch(expected_fixture_digest):
            return {"status": "rejected", "reason": "invalid_evidence"}
        now = _parse_utc(now_utc)
        if not isinstance(evidence_manifest, Mapping) or set(evidence_manifest) != _EVIDENCE_MANIFEST_FIELDS or evidence_manifest["schema_version"] != _EVIDENCE_SCHEMA_VERSION:
            return {"status": "rejected", "reason": "invalid_evidence"}
        if evidence_manifest["contract_version"] != active_contract_version or evidence_manifest["fixture_version"] != active_fixture_version:
            return {"status": "rejected", "reason": "coverage_evidence_stale"}
        rules, seen, payload_rules = evidence_manifest["rules"], set(), []
        if not isinstance(rules, Sequence) or isinstance(rules, (str, bytes)): return {"status": "rejected", "reason": "invalid_evidence"}
        for rule in rules:
            if not isinstance(rule, Mapping) or set(rule) != _EVIDENCE_RULE_FIELDS or rule["rule_id"] not in _RULES or rule["rule_id"] in seen or rule["assertion_id"] != _RULE_ASSERTIONS[rule["rule_id"]]:
                return {"status": "rejected", "reason": "invalid_evidence"}
            if rule["positive"] is None or rule["negative"] is None: return {"status": "rejected", "reason": "coverage_negative_not_effective"}
            for case, negative in ((rule["positive"], False), (rule["negative"], True)):
                result = _validate_evidence_case(case, negative, rule["rule_id"], active_contract_version, active_fixture_version, now, expected_fixture_digest)
                if result: return result
            payload_rules.append(dict(rule)); seen.add(rule["rule_id"])
        if seen != _RULES: return {"status": "rejected", "reason": "coverage_negative_not_effective"}
        expected = canonical_evidence_digest({"schema_version": _EVIDENCE_SCHEMA_VERSION, "contract_version": active_contract_version, "fixture_version": active_fixture_version, "rules": payload_rules})
        if evidence_manifest["coverage_evidence_digest"] != expected: return {"status": "rejected", "reason": "replay_mismatch"}
    except (KeyError, TypeError, ValueError):
        return {"status": "rejected", "reason": "invalid_evidence"}
    return {"status": "valid"}


def _validate_evidence_case(case: Any, negative: bool, rule_id: str, contract: str, fixture: str, now: datetime, expected_fixture_digest: str) -> dict[str, str] | None:
    fields = _EVIDENCE_NEGATIVE_FIELDS if negative else _EVIDENCE_POSITIVE_FIELDS
    if not isinstance(case, Mapping) or set(case) != fields or not isinstance(case["fixture_digest"], str) or not _HEX_RE.fullmatch(case["fixture_digest"]): return {"status": "rejected", "reason": "invalid_evidence"}
    if case["fixture_digest"] != expected_fixture_digest: return {"status": "rejected", "reason": "coverage_evidence_stale"}
    if case["verified_contract_version"] != contract or case["verified_fixture_version"] != fixture or case["verified_schema_version"] != _EVIDENCE_SCHEMA_VERSION: return {"status": "rejected", "reason": "coverage_evidence_stale"}
    verified, until = _parse_utc(case["verified_at_utc"]), _parse_utc(case["valid_until_utc"])
    if verified > until: return {"status": "rejected", "reason": "invalid_evidence"}
    if now < verified: return {"status": "rejected", "reason": "coverage_evidence_not_yet_valid"}
    if now > until: return {"status": "rejected", "reason": "coverage_evidence_expired"}
    outcome = case["replay_outcome"]
    if (not isinstance(case["replay_digest"], str) or not _HEX_RE.fullmatch(case["replay_digest"]) or (negative and (outcome not in _REASONS_BY_RULE[rule_id] or case["expected_rejection"] != outcome))): return {"status": "rejected", "reason": "coverage_negative_not_effective" if negative else "replay_mismatch"}
    if not negative and outcome != "valid": return {"status": "rejected", "reason": "replay_mismatch"}
    payload = {"rule_id": rule_id, "fixture_digest": case["fixture_digest"], "replay_outcome": outcome, "contract_version": contract, "fixture_version": fixture, "schema_version": _EVIDENCE_SCHEMA_VERSION}
    return None if case["replay_digest"] == canonical_evidence_digest(payload) else {"status": "rejected", "reason": "replay_mismatch"}


def _valid_case(case: Any, fields: frozenset[str]) -> bool:
    return isinstance(case, Mapping) and set(case) == fields and isinstance(case.get("fixture_digest"), str) and bool(_HEX_RE.fullmatch(case["fixture_digest"])) and isinstance(case.get("assertion_id"), str) and type(case.get("passed")) is bool and ("expected_rejection" not in case or isinstance(case["expected_rejection"], str))


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str): raise ValueError("invalid")
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value: raise ValueError("invalid")
    return parsed
