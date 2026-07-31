"""Pure offline helpers for anonymous compliance-contract test summaries.

This module has no runtime/API dependency and never reads files or performs I/O.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from collections.abc import Mapping, Sequence
from typing import Any

_SCHEMA_VERSION = "compliance-summary/v1"
_SUITE_VERSION = "guest-compliance-contract/v1"
_FIXTURE_VERSION = "offline-fixtures/v1"
_SCENARIOS = frozenset({
    "preflight", "dual_confirmation", "tls", "platform_rejected",
    "active_delete", "expiry_delete", "review", "ab_guidance",
})
_VIOLATION_CATEGORIES = frozenset({
    "token_like", "cookie_like", "signature_like", "url_like", "absolute_path_like",
})
_TOP_LEVEL_FIELDS = frozenset({
    "schema_version", "suite_version", "fixture_version", "run_at_utc", "coverage",
    "passed", "failed", "external_requests", "sensitive_violations", "status", "integrity",
})
_TOKEN_ASSIGNMENT_RE = re.compile(r"(?:^|[?&;,\s])(?:token|xsec(?:_token)?)\s*=\s*[^\s&;,]{3,}", re.IGNORECASE)
_COOKIE_ASSIGNMENT_RE = re.compile(r"(?:^|[?&;,\s])(?:cookie|session|a1)\s*=\s*[^\s&;,]{3,}", re.IGNORECASE)
_SIGNATURE_ASSIGNMENT_RE = re.compile(r"(?:^|[?&;,\s])(?:signature|sign|x-s)\s*=\s*[^\s&;,]{3,}", re.IGNORECASE)
_URL_RE = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
_ABSOLUTE_PATH_RE = re.compile(r"(?:^/|^[A-Za-z]:[\\/]|^~[\\/])")
_DIFF_FIELDS = frozenset({"status", "reasons", "coverage_reduced", "sensitive_categories", "counts", "versions"})
_DIFF_REASONS = frozenset({
    "coverage_reduced", "new_sensitive_category", "assertion_failures_increased", "schema_or_fixture_changed",
})
_DIFF_VERSION_FIELDS = frozenset({"schema_version_changed", "suite_version_changed", "fixture_version_changed"})
_MANIFEST_SCHEMA_VERSION = "baseline-change-manifest/v1"
_MANIFEST_FIELDS = frozenset({
    "schema_version", "old_integrity", "new_integrity", "change_types", "impact_scopes",
    "reason_code", "external_requests", "no_sensitive_data_in_manifest", "human_approval_required",
    "approval_state", "approved_at_utc", "approval_valid_until_utc", "approved_change_digest", "approved_by_role",
})
_MANIFEST_CHANGE_TYPES = frozenset({"schema_changed", "assertion_changed"})
_MANIFEST_REASON_CODES = frozenset({"test_fixture_update", "policy_change", "schema_migration", "assertion_maintenance"})
_PROVENANCE_FIELDS = frozenset({
    "run_id", "fixture_digest", "contract_version", "summary_schema_version",
    "baseline_before", "baseline_after",
})
_PROVENANCE_REASONS = frozenset({
    "missing_artifact", "run_id_mismatch", "fixture_or_contract_mismatch", "baseline_mismatch", "schema_mismatch",
})


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Encode one object deterministically without accessing disk or network."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def scan_synthetic_values(values: Sequence[object]) -> dict[str, int]:
    """Classify explicit synthetic values without retaining or returning any value."""
    counts = {category: 0 for category in sorted(_VIOLATION_CATEGORIES)}
    for value in values:
        if not isinstance(value, str):
            continue
        if _TOKEN_ASSIGNMENT_RE.search(value):
            counts["token_like"] += 1
        if _COOKIE_ASSIGNMENT_RE.search(value):
            counts["cookie_like"] += 1
        if _SIGNATURE_ASSIGNMENT_RE.search(value):
            counts["signature_like"] += 1
        if _URL_RE.search(value):
            counts["url_like"] += 1
        if _ABSOLUTE_PATH_RE.search(value):
            counts["absolute_path_like"] += 1
    return counts


def _fixed_counts(values: Mapping[str, object], allowed: frozenset[str], label: str) -> dict[str, int]:
    if set(values) != set(allowed):
        raise ValueError(f"unsupported {label}")
    result: dict[str, int] = {}
    for key in sorted(allowed):
        value = values[key]
        if type(value) is not int or value < 0:
            raise ValueError(f"invalid {label}")
        result[key] = value
    return result


def build_summary(
    *,
    run_at_utc: str,
    coverage: Mapping[str, object],
    passed: int,
    failed: int,
    sensitive_violations: Mapping[str, object],
    external_requests: int = 0,
    schema_version: str = _SCHEMA_VERSION,
    suite_version: str = _SUITE_VERSION,
    fixture_version: str = _FIXTURE_VERSION,
) -> dict[str, Any]:
    """Build a deterministic, aggregate-only compliance result summary."""
    if not isinstance(run_at_utc, str):
        raise ValueError("invalid UTC run time")
    try:
        parsed_time = datetime.strptime(run_at_utc, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ValueError("invalid UTC run time") from None
    if parsed_time.strftime("%Y-%m-%dT%H:%M:%SZ") != run_at_utc:
        raise ValueError("invalid UTC run time")
    if type(passed) is not int or type(failed) is not int or passed < 0 or failed < 0:
        raise ValueError("invalid result counts")
    if external_requests != 0:
        raise ValueError("external requests are forbidden")
    if not all(isinstance(value, str) and value for value in (schema_version, suite_version, fixture_version)):
        raise ValueError("invalid summary version")
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "suite_version": suite_version,
        "fixture_version": fixture_version,
        "run_at_utc": run_at_utc,
        "coverage": _fixed_counts(coverage, _SCENARIOS, "coverage"),
        "passed": passed,
        "failed": failed,
        "external_requests": 0,
        "sensitive_violations": _fixed_counts(sensitive_violations, _VIOLATION_CATEGORIES, "violation categories"),
        "status": "failed" if failed else "passed",
    }
    payload["integrity"] = {"sha256": hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}
    return payload



def compare_baseline(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    """Compare two validated aggregate summaries without retaining either summary."""
    if not verify_summary(current) or not verify_summary(baseline):
        raise ValueError("invalid summary")
    coverage_reduced = {
        scenario: 1
        for scenario in sorted(_SCENARIOS)
        if current["coverage"][scenario] < baseline["coverage"][scenario]
    }
    sensitive_categories = {
        category: 1
        for category in sorted(_VIOLATION_CATEGORIES)
        if baseline["sensitive_violations"][category] == 0 and current["sensitive_violations"][category] > 0
    }
    counts = {
        "failed_increased": 1 if current["failed"] > baseline["failed"] else 0,
    }
    versions = {
        "schema_version_changed": 1 if current["schema_version"] != baseline["schema_version"] else 0,
        "suite_version_changed": 1 if current["suite_version"] != baseline["suite_version"] else 0,
        "fixture_version_changed": 1 if current["fixture_version"] != baseline["fixture_version"] else 0,
    }
    reasons: set[str] = set()
    if coverage_reduced:
        reasons.add("coverage_reduced")
    if sensitive_categories:
        reasons.add("new_sensitive_category")
    if counts["failed_increased"]:
        reasons.add("assertion_failures_increased")
    if any(versions.values()):
        reasons.add("schema_or_fixture_changed")
    return {
        "status": "failed" if reasons - {"schema_or_fixture_changed"} else "no_regression",
        "reasons": sorted(reasons),
        "coverage_reduced": coverage_reduced,
        "sensitive_categories": sensitive_categories,
        "counts": counts,
        "versions": versions,
    }



def validate_manifest(
    manifest: Mapping[str, Any], old_summary: Mapping[str, Any], new_summary: Mapping[str, Any]
) -> dict[str, str]:
    """Validate an explicit, synthetic approval marker for a real summary change.

    This only verifies fields supplied by a caller; it never approves or updates a baseline.
    """
    if not verify_summary(old_summary) or not verify_summary(new_summary):
        raise ValueError("invalid summary")
    if old_summary == new_summary:
        raise ValueError("manifest requires a summary change")
    try:
        if set(manifest) != _MANIFEST_FIELDS:
            raise ValueError("invalid manifest")
        if manifest["schema_version"] != _MANIFEST_SCHEMA_VERSION:
            raise ValueError("invalid manifest")
        if not all(isinstance(manifest[key], str) and re.fullmatch(r"[0-9a-f]{64}", manifest[key])
                   for key in ("old_integrity", "new_integrity")):
            raise ValueError("invalid manifest")
        if (manifest["old_integrity"] != old_summary["integrity"]["sha256"] or
                manifest["new_integrity"] != new_summary["integrity"]["sha256"]):
            raise ValueError("invalid manifest")
        change_types = manifest["change_types"]
        scopes = manifest["impact_scopes"]
        if (not isinstance(change_types, Sequence) or isinstance(change_types, (str, bytes)) or
                not change_types or len(set(change_types)) != len(change_types) or
                not set(change_types) <= _MANIFEST_CHANGE_TYPES):
            raise ValueError("invalid manifest")
        if (not isinstance(scopes, Sequence) or isinstance(scopes, (str, bytes)) or
                len(set(scopes)) != len(scopes) or not set(scopes) <= _SCENARIOS):
            raise ValueError("invalid manifest")
        if manifest["reason_code"] not in _MANIFEST_REASON_CODES:
            raise ValueError("invalid manifest")
        if manifest["external_requests"] != 0 or manifest["no_sensitive_data_in_manifest"] is not True:
            raise ValueError("invalid manifest")
        if (manifest["human_approval_required"] is not True or manifest["approval_state"] != "approved" or
                manifest["approved_by_role"] != "maintainer"):
            raise ValueError("invalid manifest")
        _parse_utc(manifest["approved_at_utc"])
        _parse_utc(manifest["approval_valid_until_utc"])
        if not isinstance(manifest["approved_change_digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", manifest["approved_change_digest"]):
            raise ValueError("invalid manifest")
        changed_scopes = {name for name in _SCENARIOS if old_summary["coverage"][name] != new_summary["coverage"][name]}
        if set(scopes) != changed_scopes:
            raise ValueError("invalid manifest")
        derived_types: set[str] = set()
        if any(old_summary[field] != new_summary[field]
               for field in ("schema_version", "suite_version", "fixture_version")):
            derived_types.add("schema_changed")
        if (any(old_summary[field] != new_summary[field]
                for field in ("passed", "failed", "sensitive_violations")) or changed_scopes):
            derived_types.add("assertion_changed")
        if set(change_types) != derived_types:
            raise ValueError("invalid manifest")
    except (KeyError, TypeError, ValueError):
        raise ValueError("invalid manifest") from None
    return {"status": "validated"}


def approval_change_digest(
    manifest: Mapping[str, Any], old_summary: Mapping[str, Any], new_summary: Mapping[str, Any],
    provenance_envelope: Mapping[str, Any] | None = None,
) -> str:
    """Compute the fixed, non-sensitive binding digest for an explicit approval."""
    payload: dict[str, Any] = {
        "old_integrity": old_summary["integrity"]["sha256"],
        "new_integrity": new_summary["integrity"]["sha256"],
        "change_types": sorted(manifest["change_types"]),
        "impact_scopes": sorted(manifest["impact_scopes"]),
        "reason_code": manifest["reason_code"],
        "schema_version": new_summary["schema_version"],
        "suite_version": new_summary["suite_version"],
        "fixture_version": new_summary["fixture_version"],
    }
    if provenance_envelope is not None:
        payload["provenance"] = {
            key: provenance_envelope[key]
            for key in ("fixture_digest", "contract_version", "summary_schema_version")
        }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def validate_approval_freshness(
    manifest: Mapping[str, Any], old_summary: Mapping[str, Any], new_summary: Mapping[str, Any], now_utc: str,
    provenance_envelope: Mapping[str, Any] | None = None,
    *,
    artifact_envelopes: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, str]:
    """Verify only an explicit synthetic approval's freshness and aggregate binding."""
    try:
        _parse_utc(now_utc)
        if (not verify_summary(old_summary) or not verify_summary(new_summary) or
                not isinstance(manifest, Mapping) or set(manifest) != _MANIFEST_FIELDS):
            return {"status": "rejected", "reason": "invalid_approval"}
        if (manifest["old_integrity"] != old_summary["integrity"]["sha256"] or
                manifest["new_integrity"] != new_summary["integrity"]["sha256"]):
            return {"status": "rejected", "reason": "reapproval_required"}
        validate_manifest(manifest, old_summary, new_summary)
        if provenance_envelope is not None:
            if not _valid_provenance_envelope(provenance_envelope) or artifact_envelopes is None:
                return {"status": "rejected", "reason": "reapproval_required"}
            provenance_result = validate_provenance_link(
                new_summary, compare_baseline(new_summary, old_summary), manifest, provenance_envelope,
                baseline_summary=old_summary, artifact_envelopes=artifact_envelopes,
            )
            if provenance_result != {"status": "linked"}:
                return {"status": "rejected", "reason": "reapproval_required"}
            if (provenance_envelope["baseline_before"] != old_summary["integrity"]["sha256"] or
                    provenance_envelope["baseline_after"] != new_summary["integrity"]["sha256"] or
                    provenance_envelope["baseline_before"] != manifest["old_integrity"] or
                    provenance_envelope["baseline_after"] != manifest["new_integrity"]):
                return {"status": "rejected", "reason": "reapproval_required"}
        elif artifact_envelopes is not None:
            return {"status": "rejected", "reason": "reapproval_required"}
        approved_at = datetime.strptime(manifest["approved_at_utc"], "%Y-%m-%dT%H:%M:%SZ")
        valid_until = datetime.strptime(manifest["approval_valid_until_utc"], "%Y-%m-%dT%H:%M:%SZ")
        now = datetime.strptime(now_utc, "%Y-%m-%dT%H:%M:%SZ")
    except (KeyError, TypeError, ValueError):
        return {"status": "rejected", "reason": "invalid_approval"}
    if approved_at > valid_until:
        return {"status": "rejected", "reason": "invalid_approval"}
    if now < approved_at:
        return {"status": "rejected", "reason": "approval_not_yet_valid"}
    if now > valid_until:
        return {"status": "rejected", "reason": "approval_expired"}
    if manifest["approved_change_digest"] != approval_change_digest(manifest, old_summary, new_summary, provenance_envelope):
        return {"status": "rejected", "reason": "approval_digest_mismatch"}
    return {"status": "approved_current"}

def validate_provenance_link(
    summary: Mapping[str, Any],
    diff: Mapping[str, Any],
    manifest_or_none: Mapping[str, Any] | None,
    envelope: Mapping[str, Any],
    *,
    baseline_summary: Mapping[str, Any] | None = None,
    artifact_envelopes: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, str]:
    """Link explicitly supplied aggregate artifacts without modifying their schemas.

    Provenance values exist only in this call. They are never persisted into Summary,
    Diff, or Manifest and do not constitute a real approval.
    """
    if not verify_summary(summary) or not _verify_diff(diff):
        return {"status": "rejected", "reason": "missing_artifact"}
    if not isinstance(envelope, Mapping) or not _valid_provenance_envelope(envelope):
        return {"status": "rejected", "reason": "invalid_artifact"}
    if not _valid_provenance_envelope(envelope):
        return {"status": "rejected", "reason": "fixture_or_contract_mismatch"}
    if envelope["summary_schema_version"] != _SCHEMA_VERSION:
        return {"status": "rejected", "reason": "schema_mismatch"}
    if artifact_envelopes is not None:
        if not isinstance(artifact_envelopes, Mapping) or set(artifact_envelopes) != {"summary", "diff", "manifest"}:
            return {"status": "rejected", "reason": "invalid_artifact"}
        values = tuple(artifact_envelopes.values())
        if any(not isinstance(value, Mapping) or not _valid_provenance_envelope(value) for value in values):
            return {"status": "rejected", "reason": "invalid_artifact"}
        if any(value != envelope for value in values):
            return {"status": "rejected", "reason": "baseline_mismatch"}
    if manifest_or_none is None:
        if baseline_summary is not None or envelope["baseline_before"] or envelope["baseline_after"]:
            return {"status": "rejected", "reason": "baseline_mismatch"}
        return {"status": "linked"}
    if baseline_summary is None or not verify_summary(baseline_summary):
        return {"status": "rejected", "reason": "missing_artifact"}
    try:
        validate_manifest(manifest_or_none, baseline_summary, summary)
    except ValueError:
        return {"status": "rejected", "reason": "baseline_mismatch"}
    if (envelope["baseline_before"] != baseline_summary["integrity"]["sha256"] or
            envelope["baseline_after"] != summary["integrity"]["sha256"] or
            manifest_or_none["old_integrity"] != envelope["baseline_before"] or
            manifest_or_none["new_integrity"] != envelope["baseline_after"]):
        return {"status": "rejected", "reason": "baseline_mismatch"}
    expected_diff = compare_baseline(summary, baseline_summary)
    if diff != expected_diff:
        return {"status": "rejected", "reason": "baseline_mismatch"}
    return {"status": "linked"}


def _valid_provenance_envelope(envelope: Mapping[str, Any]) -> bool:
    if not isinstance(envelope, Mapping) or set(envelope) != _PROVENANCE_FIELDS:
        return False
    try:
        run_id = envelope["run_id"]
        fixture_digest = envelope["fixture_digest"]
        contract_version = envelope["contract_version"]
        before = envelope["baseline_before"]
        after = envelope["baseline_after"]
    except (KeyError, TypeError):
        return False
    if not isinstance(run_id, str) or not (re.fullmatch(r"[0-9a-f]{32}", run_id) or re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", run_id)):
        return False
    if not isinstance(fixture_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", fixture_digest):
        return False
    if not isinstance(contract_version, str) or not re.fullmatch(r"(?:v\d+|\d+\.\d+\.\d+)", contract_version):
        return False
    if envelope["summary_schema_version"] != _SCHEMA_VERSION:
        return False
    return all(isinstance(value, str) and (not value or re.fullmatch(r"[0-9a-f]{64}", value)) for value in (before, after))


def _verify_diff(diff: Mapping[str, Any]) -> bool:
    if not isinstance(diff, Mapping) or set(diff) != _DIFF_FIELDS:
        return False
    try:
        reasons = diff["reasons"]
        if (not isinstance(reasons, list) or len(set(reasons)) != len(reasons) or
                not set(reasons) <= _DIFF_REASONS):
            return False
        coverage = diff["coverage_reduced"]
        categories = diff["sensitive_categories"]
        counts = diff["counts"]
        versions = diff["versions"]
        if not isinstance(coverage, Mapping) or not isinstance(categories, Mapping):
            return False
        if not set(coverage) <= _SCENARIOS or not set(categories) <= _VIOLATION_CATEGORIES:
            return False
        if any(value != 1 for value in coverage.values()) or any(value != 1 for value in categories.values()):
            return False
        if set(counts) != {"failed_increased"} or counts["failed_increased"] not in (0, 1):
            return False
        if set(versions) != _DIFF_VERSION_FIELDS or any(value not in (0, 1) for value in versions.values()):
            return False
        expected_reasons = set()
        if coverage:
            expected_reasons.add("coverage_reduced")
        if categories:
            expected_reasons.add("new_sensitive_category")
        if counts["failed_increased"]:
            expected_reasons.add("assertion_failures_increased")
        if any(versions.values()):
            expected_reasons.add("schema_or_fixture_changed")
        return set(reasons) == expected_reasons and diff["status"] == (
            "failed" if expected_reasons - {"schema_or_fixture_changed"} else "no_regression"
        )
    except (KeyError, TypeError):
        return False
    if not isinstance(value, str):
        raise ValueError("invalid UTC time")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ValueError("invalid UTC time") from None
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ValueError("invalid UTC time")


def _parse_utc(value: object) -> None:
    if not isinstance(value, str):
        raise ValueError("invalid UTC time")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ValueError("invalid UTC time") from None
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ValueError("invalid UTC time")


def verify_summary(summary: Mapping[str, Any]) -> bool:
    """Verify exact shape and canonical SHA-256 without exposing malformed content."""
    try:
        if set(summary) != _TOP_LEVEL_FIELDS or not isinstance(summary["integrity"], Mapping):
            return False
        integrity = summary["integrity"]
        if set(integrity) != {"sha256"} or not isinstance(integrity["sha256"], str):
            return False
        payload = dict(summary)
        digest = payload.pop("integrity")["sha256"]
        rebuilt = build_summary(
            run_at_utc=payload["run_at_utc"], coverage=payload["coverage"], passed=payload["passed"],
            failed=payload["failed"], sensitive_violations=payload["sensitive_violations"],
            external_requests=payload["external_requests"], schema_version=payload["schema_version"],
            suite_version=payload["suite_version"], fixture_version=payload["fixture_version"],
        )
        return payload == {key: value for key, value in rebuilt.items() if key != "integrity"} and digest == rebuilt["integrity"]["sha256"]
    except (KeyError, TypeError, ValueError):
        return False
