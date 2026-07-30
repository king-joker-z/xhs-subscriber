"""Offline tests for the anonymous compliance-contract summary helper."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.compliance_summary import (
    build_summary, canonical_json_bytes, compare_baseline, scan_synthetic_values, verify_summary,
)


_COVERAGE = {
    "preflight": 1, "dual_confirmation": 1, "tls": 1, "platform_rejected": 1,
    "active_delete": 1, "expiry_delete": 1, "review": 1, "ab_guidance": 1,
}
_EMPTY_VIOLATIONS = {
    "token_like": 0, "cookie_like": 0, "signature_like": 0, "url_like": 0, "absolute_path_like": 0,
}
_RUN_AT = "2026-07-30T08:03:22Z"


class ComplianceSummaryTests(unittest.TestCase):
    def _summary(self, **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "run_at_utc": _RUN_AT, "coverage": _COVERAGE, "passed": 8,
            "failed": 0, "sensitive_violations": _EMPTY_VIOLATIONS,
        }
        values.update(overrides)
        return build_summary(**values)  # type: ignore[arg-type]

    def test_canonical_summary_is_stable_and_can_be_written_only_to_tempdir(self) -> None:
        first = self._summary()
        second = self._summary()
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
        self.assertTrue(verify_summary(first))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "summary.json"
            output.write_bytes(canonical_json_bytes(first))
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), first)

    def test_summary_has_only_fixed_aggregate_fields_and_failed_status(self) -> None:
        summary = self._summary(failed=1)
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["external_requests"], 0)
        self.assertEqual(set(summary), {
            "schema_version", "suite_version", "fixture_version", "run_at_utc", "coverage",
            "passed", "failed", "external_requests", "sensitive_violations", "status", "integrity",
        })
        self.assertEqual(set(summary["coverage"]), set(_COVERAGE))
        self.assertEqual(set(summary["sensitive_violations"]), set(_EMPTY_VIOLATIONS))
        self.assertEqual(summary["external_requests"], 0)

    def test_version_metadata_is_not_classified_as_sensitive(self) -> None:
        counts = scan_synthetic_values((
            "schema_version=v1", "suite_version=v1", "fixture_version=v1",
            "signature_version=v1", "token_version=v1", "cookie_version=v1", "xsec_version=v1",
        ))
        self.assertEqual(counts, _EMPTY_VIOLATIONS)

        values = (
            "https://example.invalid/work?token=synthetic", "cookie=session-synthetic",
            "signature=synthetic", "/synthetic/private/file", "ordinary-label",
        )
        counts = scan_synthetic_values(values)
        self.assertEqual(counts, {
            "absolute_path_like": 1, "cookie_like": 1, "signature_like": 1, "token_like": 1, "url_like": 1,
        })
        summary = self._summary(sensitive_violations=counts)
        observed = canonical_json_bytes(summary).decode("ascii")
        for value in values:
            self.assertNotIn(value, observed)
        self.assertNotIn("example.invalid", observed)
        self.assertNotIn("synthetic", observed)

    def test_unknown_fields_categories_and_external_requests_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._summary(coverage={**_COVERAGE, "unknown": 1})
        with self.assertRaises(ValueError):
            self._summary(sensitive_violations={**_EMPTY_VIOLATIONS, "unknown": 1})
        with self.assertRaises(ValueError):
            self._summary(external_requests=1)
        with self.assertRaises(ValueError):
            self._summary(external_requests=-1)
        with self.assertRaises(ValueError):
            self._summary(run_at_utc="2026-07-30")
        for invalid_time in (
            "2026-02-30T08:03:22Z", "2026-07-30T24:03:22Z",
            "2026-07-30T08:60:22Z", "2026-07-30T08:03:60Z",
        ):
            with self.subTest(run_at_utc=invalid_time), self.assertRaises(ValueError):
                self._summary(run_at_utc=invalid_time)

    def test_baseline_diff_is_deterministic_and_no_regression_for_same_input(self) -> None:
        baseline = self._summary()
        first = compare_baseline(baseline, baseline)
        second = compare_baseline(self._summary(), baseline)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "no_regression")
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
        self.assertEqual(first["reasons"], [])

    def test_baseline_diff_detects_aggregate_regressions_without_sensitive_values(self) -> None:
        baseline = self._summary()
        coverage = dict(_COVERAGE)
        coverage["preflight"] = 0
        coverage["tls"] = 0
        coverage["active_delete"] = 0
        coverage["ab_guidance"] = 0
        violations = dict(_EMPTY_VIOLATIONS, token_like=1, cookie_like=1)
        current = self._summary(coverage=coverage, failed=1, sensitive_violations=violations)
        diff = compare_baseline(current, baseline)
        self.assertEqual(diff["status"], "failed")
        self.assertEqual(set(diff["reasons"]), {
            "coverage_reduced", "new_sensitive_category", "assertion_failures_increased",
        })
        self.assertEqual(diff["coverage_reduced"], {"ab_guidance": 1, "active_delete": 1, "preflight": 1, "tls": 1})
        self.assertEqual(diff["sensitive_categories"], {"cookie_like": 1, "token_like": 1})
        self.assertEqual(diff["counts"], {"failed_increased": 1})
        observed = canonical_json_bytes(diff).decode("ascii")
        for forbidden in ("https://", "token=", "cookie=", "task", "path", "exception"):
            self.assertNotIn(forbidden, observed)

    def test_nonzero_external_requests_are_invalid_before_baseline_diff(self) -> None:
        baseline = self._summary()
        for count in (1, -1):
            with self.subTest(external_requests=count), self.assertRaises(ValueError):
                self._summary(external_requests=count)
        forged = dict(baseline)
        forged["external_requests"] = 1
        forged["integrity"] = {"sha256": "0" * 64}
        self.assertFalse(verify_summary(forged))
        with self.assertRaises(ValueError):
            compare_baseline(forged, baseline)

        baseline = self._summary()
        current = build_summary(
            run_at_utc=_RUN_AT, coverage=_COVERAGE, passed=8, failed=0,
            sensitive_violations=_EMPTY_VIOLATIONS, fixture_version="offline-fixtures/v2",
        )
        before = canonical_json_bytes(baseline)
        diff = compare_baseline(current, baseline)
        self.assertEqual(diff["status"], "no_regression")
        self.assertEqual(diff["reasons"], ["schema_or_fixture_changed"])
        self.assertEqual(diff["versions"], {
            "schema_version_changed": 0, "suite_version_changed": 0, "fixture_version_changed": 1,
        })
        self.assertEqual(canonical_json_bytes(baseline), before)

    def test_baseline_diff_rejects_tampered_unknown_and_invalid_summary_inputs(self) -> None:
        baseline = self._summary()
        tampered = dict(baseline)
        tampered["passed"] = 99
        unknown = dict(baseline)
        unknown["raw_summary"] = "forbidden"
        for invalid in (tampered, unknown, {"coverage": {}}):
            with self.subTest(invalid=type(invalid).__name__), self.assertRaises(ValueError):
                compare_baseline(baseline, invalid)

        summary = self._summary()
        self.assertTrue(verify_summary(summary))
        altered = dict(summary)
        altered["passed"] = 9
        self.assertFalse(verify_summary(altered))
        extra = dict(summary)
        extra["task_detail"] = "forbidden"
        self.assertFalse(verify_summary(extra))


if __name__ == "__main__":
    unittest.main()
