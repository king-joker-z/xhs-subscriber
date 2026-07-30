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
