"""Offline tests for the anonymous compliance-contract summary helper."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from tests.compliance_summary import (
        approval_change_digest, build_summary, canonical_json_bytes, compare_baseline, scan_synthetic_values,
        validate_approval_freshness, validate_manifest,
        validate_provenance_link, verify_summary,
    )
except ModuleNotFoundError:  # unittest discovery loads this module directly from tests/.
    from compliance_summary import (  # type: ignore[no-redef]
        approval_change_digest, build_summary, canonical_json_bytes, compare_baseline, scan_synthetic_values,
        validate_approval_freshness, validate_manifest,
        validate_provenance_link, verify_summary,
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

    def _manifest(self, old: dict[str, object], new: dict[str, object], **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "schema_version": "baseline-change-manifest/v1",
            "old_integrity": old["integrity"]["sha256"],
            "new_integrity": new["integrity"]["sha256"],
            "change_types": ["assertion_changed"],
            "impact_scopes": [],
            "reason_code": "assertion_maintenance",
            "external_requests": 0,
            "no_sensitive_data_in_manifest": True,
            "human_approval_required": True,
            "approval_state": "approved",
            "approved_at_utc": _RUN_AT,
            "approval_valid_until_utc": "2026-07-31T08:03:22Z",
            "approved_change_digest": "0" * 64,
            "approved_by_role": "maintainer",
        }
        values.update(overrides)
        if values["approved_change_digest"] == "0" * 64:
            values["approved_change_digest"] = approval_change_digest(values, old, new)
        return values

    def _envelope(self, **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "run_id": "0123456789abcdef0123456789abcdef",
            "fixture_digest": "a" * 64,
            "contract_version": "v1",
            "summary_schema_version": "compliance-summary/v1",
            "baseline_before": "",
            "baseline_after": "",
        }
        values.update(overrides)
        return values

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

    def test_approval_freshness_binds_approved_manifest_to_time_and_change_summary(self) -> None:
        old = self._summary()
        new = self._summary(failed=1)
        manifest = self._manifest(old, new)
        self.assertEqual(
            validate_approval_freshness(manifest, old, new, "2026-07-30T09:00:00Z"),
            {"status": "approved_current"},
        )
        self.assertEqual(
            validate_approval_freshness(manifest, old, new, "2026-07-30T08:00:00Z"),
            {"status": "rejected", "reason": "approval_not_yet_valid"},
        )
        self.assertEqual(
            validate_approval_freshness(manifest, old, new, "2026-08-01T00:00:00Z"),
            {"status": "rejected", "reason": "approval_expired"},
        )
        changed = dict(manifest, approved_change_digest="f" * 64)
        self.assertEqual(
            validate_approval_freshness(changed, old, new, "2026-07-30T09:00:00Z"),
            {"status": "rejected", "reason": "approval_digest_mismatch"},
        )
        changed_summary = self._summary(failed=2)
        self.assertEqual(
            validate_approval_freshness(manifest, old, changed_summary, "2026-07-30T09:00:00Z"),
            {"status": "rejected", "reason": "reapproval_required"},
        )
        digest_envelope = self._envelope(
            baseline_before=old["integrity"]["sha256"], baseline_after=new["integrity"]["sha256"],
        )
        self.assertEqual(
            validate_approval_freshness(manifest, old, new, "2026-07-30T09:00:00Z", digest_envelope),
            {"status": "rejected", "reason": "reapproval_required"},
        )

        approved_envelope = self._envelope(
            baseline_before=old["integrity"]["sha256"], baseline_after=new["integrity"]["sha256"],
        )
        manifest_with_provenance = self._manifest(
            old, new, approved_change_digest=approval_change_digest(self._manifest(old, new), old, new, approved_envelope),
        )
        approved_artifacts = {"summary": dict(approved_envelope), "diff": dict(approved_envelope), "manifest": dict(approved_envelope)}
        self.assertEqual(
            validate_approval_freshness(
                manifest_with_provenance, old, new, "2026-07-30T09:00:00Z", approved_envelope,
                artifact_envelopes=approved_artifacts,
            ),
            {"status": "approved_current"},
        )
        self.assertEqual(
            validate_approval_freshness(manifest_with_provenance, old, new, "2026-07-30T09:00:00Z", approved_envelope),
            {"status": "rejected", "reason": "reapproval_required"},
        )
        for field, value in (("baseline_before", ""), ("baseline_after", ""), ("baseline_before", "0" * 64), ("baseline_after", "1" * 64)):
            stale = dict(approved_envelope, **{field: value})
            rebound = self._manifest(
                old, new, approved_change_digest=approval_change_digest(self._manifest(old, new), old, new, stale),
            )
            with self.subTest(provenance_field=field, value=value):
                self.assertEqual(
                    validate_approval_freshness(rebound, old, new, "2026-07-30T09:00:00Z", stale),
                    {"status": "rejected", "reason": "reapproval_required"},
                )
        inverted = self._manifest(old, new, approved_at_utc="2026-08-01T00:00:00Z")
        self.assertEqual(
            validate_approval_freshness(inverted, old, new, "2026-07-30T09:00:00Z"),
            {"status": "rejected", "reason": "invalid_approval"},
        )

        old = self._summary()
        new = self._summary(failed=1)
        manifest = self._manifest(old, new)
        cases = (
            {key: value for key, value in manifest.items() if key != "approval_valid_until_utc"},
            dict(manifest, approval_valid_until_utc="2026-02-30T08:03:22Z"),
            dict(manifest, approved_change_digest="token=secret"),
            {**manifest, "raw_log": "token=secret"},
        )
        for candidate in cases:
            result = validate_approval_freshness(candidate, old, new, "2026-07-30T09:00:00Z")
            self.assertEqual(result, {"status": "rejected", "reason": "invalid_approval"})
            self.assertNotIn("secret", canonical_json_bytes(result).decode("ascii"))

        summary = self._summary()
        diff = compare_baseline(summary, summary)
        envelope = self._envelope()
        before = (canonical_json_bytes(summary), canonical_json_bytes(diff), canonical_json_bytes(envelope))
        self.assertEqual(validate_provenance_link(summary, diff, None, envelope), {"status": "linked"})
        self.assertEqual((canonical_json_bytes(summary), canonical_json_bytes(diff), canonical_json_bytes(envelope)), before)

        old = self._summary()
        new = self._summary(failed=1)
        manifest = self._manifest(old, new)
        linked_envelope = self._envelope(
            baseline_before=old["integrity"]["sha256"], baseline_after=new["integrity"]["sha256"],
        )
        self.assertEqual(
            validate_provenance_link(new, compare_baseline(new, old), manifest, linked_envelope, baseline_summary=old),
            {"status": "linked"},
        )

    def test_approval_freshness_requires_complete_artifacts_for_provenance(self) -> None:
        old = self._summary()
        new = self._summary(failed=1)
        envelope = self._envelope(baseline_before=old["integrity"]["sha256"], baseline_after=new["integrity"]["sha256"])
        manifest = self._manifest(old, new, approved_change_digest=approval_change_digest(self._manifest(old, new), old, new, envelope))
        artifacts = {"summary": dict(envelope), "diff": dict(envelope), "manifest": dict(envelope)}
        for candidate in (None, {}, {"summary": dict(envelope)}, {**artifacts, "extra": dict(envelope)}):
            with self.subTest(kind=type(candidate).__name__):
                self.assertEqual(
                    validate_approval_freshness(manifest, old, new, "2026-07-30T09:00:00Z", envelope,
                                                artifact_envelopes=candidate),
                    {"status": "rejected", "reason": "reapproval_required"},
                )
        for field, value in (("run_id", "fedcba9876543210fedcba9876543210"), ("fixture_digest", "b" * 64),
                             ("contract_version", "v2"), ("summary_schema_version", "wrong/v1"),
                             ("baseline_before", "0" * 64), ("baseline_after", "1" * 64)):
            candidate = {key: dict(item) for key, item in artifacts.items()}
            candidate["diff"][field] = value
            with self.subTest(field=field):
                self.assertEqual(
                    validate_approval_freshness(manifest, old, new, "2026-07-30T09:00:00Z", envelope,
                                                artifact_envelopes=candidate),
                    {"status": "rejected", "reason": "reapproval_required"},
                )

    def test_provenance_link_rejects_historical_run_and_metadata_mixing(self) -> None:
        summary = self._summary()
        diff = compare_baseline(summary, summary)
        envelope = self._envelope()
        artifacts = {"summary": dict(envelope), "diff": dict(envelope), "manifest": dict(envelope)}
        self.assertEqual(validate_provenance_link(summary, diff, None, envelope, artifact_envelopes=artifacts), {"status": "linked"})
        artifacts["diff"]["run_id"] = "fedcba9876543210fedcba9876543210"
        self.assertEqual(
            validate_provenance_link(summary, diff, None, envelope, artifact_envelopes=artifacts),
            {"status": "rejected", "reason": "baseline_mismatch"},
        )
        artifacts["diff"] = dict(envelope, fixture_digest="b" * 64)
        self.assertEqual(
            validate_provenance_link(summary, diff, None, envelope, artifact_envelopes=artifacts),
            {"status": "rejected", "reason": "baseline_mismatch"},
        )

    def test_provenance_link_rejects_malformed_main_and_artifact_envelopes_safely(self) -> None:
        summary = self._summary()
        diff = compare_baseline(summary, summary)
        envelope = self._envelope()
        for key in tuple(envelope):
            malformed = dict(envelope)
            malformed.pop(key)
            with self.subTest(main_missing=key):
                self.assertEqual(
                    validate_provenance_link(summary, diff, None, malformed),
                    {"status": "rejected", "reason": "invalid_artifact"},
                )
        for malformed in (None, [], {**envelope, "unknown": "x"}, dict(envelope, run_id=1)):
            with self.subTest(main_type=type(malformed).__name__):
                self.assertEqual(
                    validate_provenance_link(summary, diff, None, malformed),
                    {"status": "rejected", "reason": "invalid_artifact"},
                )
        for invalid_version in ("wrong/v1", "", 1, "compliance-summary/v2"):
            malformed = dict(envelope, summary_schema_version=invalid_version)
            with self.subTest(main_schema_version=repr(invalid_version)):
                self.assertEqual(
                    validate_provenance_link(summary, diff, None, malformed),
                    {"status": "rejected", "reason": "invalid_artifact"},
                )
        artifacts = {"summary": dict(envelope), "diff": dict(envelope), "manifest": dict(envelope)}
        for artifact_name in artifacts:
            for invalid_version in ("wrong/v1", "", 1, "compliance-summary/v2"):
                candidate = {key: dict(value) for key, value in artifacts.items()}
                candidate[artifact_name]["summary_schema_version"] = invalid_version
                with self.subTest(artifact=artifact_name, schema_version=repr(invalid_version)):
                    self.assertEqual(
                        validate_provenance_link(summary, diff, None, envelope, artifact_envelopes=candidate),
                        {"status": "rejected", "reason": "invalid_artifact"},
                    )
        missing = {key: dict(value) for key, value in artifacts.items()}
        missing["diff"].pop("baseline_after")
        result = validate_provenance_link(summary, diff, None, envelope, artifact_envelopes=missing)
        self.assertEqual(result, {"status": "rejected", "reason": "invalid_artifact"})
        self.assertNotIn("baseline_after", canonical_json_bytes(result).decode("ascii"))

        old = self._summary()
        new = self._summary(failed=1)
        manifest = self._manifest(old, new)
        envelope = self._envelope(baseline_before=old["integrity"]["sha256"], baseline_after=new["integrity"]["sha256"])
        artifacts = {"summary": dict(envelope), "diff": dict(envelope), "manifest": dict(envelope)}
        for name in artifacts:
            for field, value in (("baseline_before", "0" * 64), ("baseline_after", "1" * 64)):
                candidate = {key: dict(item) for key, item in artifacts.items()}
                candidate[name][field] = value
                with self.subTest(artifact=name, field=field):
                    self.assertEqual(
                        validate_provenance_link(
                            new, compare_baseline(new, old), manifest, envelope, baseline_summary=old,
                            artifact_envelopes=candidate,
                        ),
                        {"status": "rejected", "reason": "baseline_mismatch"},
                    )
        no_manifest = self._envelope(baseline_before="0" * 64)
        no_manifest_artifacts = {"summary": dict(no_manifest), "diff": dict(no_manifest), "manifest": dict(no_manifest)}
        self.assertEqual(
            validate_provenance_link(self._summary(), compare_baseline(self._summary(), self._summary()), None, no_manifest,
                                     artifact_envelopes=no_manifest_artifacts),
            {"status": "rejected", "reason": "baseline_mismatch"},
        )

        old = self._summary()
        new = self._summary(failed=1)
        manifest = self._manifest(old, new)
        diff = compare_baseline(new, old)
        good = self._envelope(baseline_before=old["integrity"]["sha256"], baseline_after=new["integrity"]["sha256"])
        cases = (
            (new, diff, manifest, self._envelope(), old),
            (new, diff, manifest, self._envelope(run_id="historical-run", baseline_before=old["integrity"]["sha256"], baseline_after=new["integrity"]["sha256"]), old),
            (new, diff, manifest, self._envelope(contract_version="/private/path", baseline_before=old["integrity"]["sha256"], baseline_after=new["integrity"]["sha256"]), old),
            (new, diff, manifest, self._envelope(summary_schema_version="wrong/v1", baseline_before=old["integrity"]["sha256"], baseline_after=new["integrity"]["sha256"]), old),
            (new, diff, manifest, self._envelope(baseline_before="0" * 64, baseline_after=new["integrity"]["sha256"]), old),
            (new, diff, None, good, old),
            ({**new, "passed": 99}, diff, manifest, good, old),
            (new, {**diff, "raw_log": "token=secret"}, manifest, good, old),
            (new, diff, {**manifest, "approval_state": "pending"}, good, old),
        )
        for summary, candidate_diff, candidate_manifest, envelope, baseline in cases:
            with self.subTest(case=type(candidate_manifest).__name__):
                result = validate_provenance_link(summary, candidate_diff, candidate_manifest, envelope, baseline_summary=baseline)
                self.assertEqual(result["status"], "rejected")
                self.assertNotIn("secret", canonical_json_bytes(result).decode("ascii"))

    def test_manifest_validates_explicit_approved_aggregate_change_without_input_mutation(self) -> None:
        old = self._summary()
        coverage = dict(_COVERAGE, preflight=0)
        new = self._summary(coverage=coverage, failed=1)
        manifest = self._manifest(old, new, impact_scopes=["preflight"])
        old_bytes, new_bytes, manifest_bytes = map(canonical_json_bytes, (old, new, manifest))
        self.assertEqual(validate_manifest(manifest, old, new), {"status": "validated"})
        self.assertEqual((canonical_json_bytes(old), canonical_json_bytes(new), canonical_json_bytes(manifest)),
                         (old_bytes, new_bytes, manifest_bytes))

    def test_manifest_derives_exact_types_and_scopes(self) -> None:
        old = self._summary()
        assertion_only = self._summary(failed=1)
        self.assertEqual(validate_manifest(self._manifest(old, assertion_only), old, assertion_only), {"status": "validated"})

        version_only = self._summary(fixture_version="offline-fixtures/v2")
        version_manifest = self._manifest(old, version_only, change_types=["schema_changed"])
        self.assertEqual(validate_manifest(version_manifest, old, version_only), {"status": "validated"})

        coverage = self._summary(coverage=dict(_COVERAGE, tls=0))
        coverage_manifest = self._manifest(old, coverage, impact_scopes=["tls"])
        self.assertEqual(validate_manifest(coverage_manifest, old, coverage), {"status": "validated"})

        mixed = self._summary(coverage=dict(_COVERAGE, review=0), failed=1, fixture_version="offline-fixtures/v2")
        mixed_manifest = self._manifest(
            old, mixed, change_types=["schema_changed", "assertion_changed"], impact_scopes=["review"],
        )
        self.assertEqual(validate_manifest(mixed_manifest, old, mixed), {"status": "validated"})

    def test_manifest_rejects_non_exact_types_and_scopes(self) -> None:
        old = self._summary()
        assertion_only = self._summary(failed=1)
        version_only = self._summary(fixture_version="offline-fixtures/v2")
        coverage = self._summary(coverage=dict(_COVERAGE, tls=0))
        cases = (
            self._manifest(old, assertion_only, change_types=["assertion_changed", "schema_changed"]),
            self._manifest(old, version_only, change_types=["schema_changed", "assertion_changed"]),
            self._manifest(old, assertion_only, impact_scopes=["preflight"]),
            self._manifest(old, coverage, impact_scopes=[]),
            self._manifest(old, coverage, impact_scopes=["preflight"]),
            self._manifest(old, assertion_only, change_types=["fixture_added"]),
            self._manifest(old, assertion_only, change_types=["approved_policy_change"]),
        )
        for manifest, new in zip(cases, (assertion_only, version_only, assertion_only, coverage, coverage, assertion_only, assertion_only)):
            with self.subTest(manifest=manifest["change_types"]):
                with self.assertRaisesRegex(ValueError, "invalid manifest"):
                    validate_manifest(manifest, old, new)

        old = self._summary()
        new = self._summary(coverage=dict(_COVERAGE, tls=0), failed=1)
        cases = (
            self._manifest(old, new, approval_state="pending"),
            self._manifest(old, new, old_integrity="0" * 64),
            self._manifest(old, new, impact_scopes=["preflight"]),
            self._manifest(old, new, approved_at_utc="2026-02-30T08:03:22Z"),
            self._manifest(old, new, external_requests=1),
            self._manifest(old, new, no_sensitive_data_in_manifest=False),
            self._manifest(old, new, unknown="forbidden"),
        )
        for manifest in cases:
            with self.subTest(manifest=sorted(manifest)):
                with self.assertRaisesRegex(ValueError, "invalid manifest") as error:
                    validate_manifest(manifest, old, new)
                self.assertNotIn("forbidden", str(error.exception))

    def test_manifest_rejects_sensitive_or_unrelated_changes_and_no_change(self) -> None:
        old = self._summary()
        new = self._summary(coverage=dict(_COVERAGE, review=0), failed=1)
        with self.assertRaises(ValueError):
            validate_manifest(self._manifest(old, new, impact_scopes=["preflight"]), old, new)
        with self.assertRaises(ValueError):
            validate_manifest(self._manifest(old, old), old, old)
        sensitive = self._manifest(old, new, reason_code="https://example.invalid/?token=secret")
        with self.assertRaisesRegex(ValueError, "invalid manifest") as error:
            validate_manifest(sensitive, old, new)
        self.assertNotIn("secret", str(error.exception))

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
