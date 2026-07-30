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
    payload: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "suite_version": _SUITE_VERSION,
        "fixture_version": _FIXTURE_VERSION,
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
            external_requests=payload["external_requests"],
        )
        return payload == {key: value for key, value in rebuilt.items() if key != "integrity"} and digest == rebuilt["integrity"]["sha256"]
    except (KeyError, TypeError, ValueError):
        return False
