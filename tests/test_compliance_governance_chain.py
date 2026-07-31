"""End-to-end, pure-memory contract tests for the compliance governance chain."""
from __future__ import annotations

import copy
import unittest

try:
    from tests.compliance_summary import (
        approval_change_digest,
        build_summary,
        canonical_json_bytes,
        compare_baseline,
        validate_approval_freshness,
        validate_manifest,
        validate_provenance_link,
    )
except ModuleNotFoundError:  # unittest discovery loads modules directly from tests/.
    from compliance_summary import (  # type: ignore[no-redef]
        approval_change_digest,
        build_summary,
        canonical_json_bytes,
        compare_baseline,
        validate_approval_freshness,
        validate_manifest,
        validate_provenance_link,
    )


_RUN_AT = "2026-07-31T02:00:00Z"
_NOW = "2026-07-31T02:30:00Z"
_COVERAGE = {
    "preflight": 1, "dual_confirmation": 1, "tls": 1, "platform_rejected": 1,
    "active_delete": 1, "expiry_delete": 1, "review": 1, "ab_guidance": 1,
}
_SENSITIVE = {
    "token_like": 0, "cookie_like": 0, "signature_like": 0, "url_like": 0, "absolute_path_like": 0,
}


class ComplianceGovernanceChainTests(unittest.TestCase):
    """Exercise the real test-only helpers without I/O, current time, or platform calls."""

    def _summary(self, **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "run_at_utc": _RUN_AT,
            "coverage": dict(_COVERAGE),
            "passed": 8,
            "failed": 0,
            "sensitive_violations": dict(_SENSITIVE),
        }
        values.update(overrides)
        return build_summary(**values)  # type: ignore[arg-type]

    def _envelope(self, old: dict[str, object], new: dict[str, object]) -> dict[str, str]:
        return {
            "run_id": "123e4567-e89b-42d3-a456-426614174000",
            "fixture_digest": "a" * 64,
            "contract_version": "v1",
            "summary_schema_version": "compliance-summary/v1",
            "baseline_before": old["integrity"]["sha256"],  # type: ignore[index]
            "baseline_after": new["integrity"]["sha256"],  # type: ignore[index]
        }

    def _manifest(self, old: dict[str, object], new: dict[str, object], envelope: dict[str, str]) -> dict[str, object]:
        changed_scopes = sorted(name for name in _COVERAGE if old["coverage"][name] != new["coverage"][name])  # type: ignore[index]
        types: list[str] = []
        if any(old[key] != new[key] for key in ("schema_version", "suite_version", "fixture_version")):
            types.append("schema_changed")
        if (any(old[key] != new[key] for key in ("passed", "failed", "sensitive_violations")) or changed_scopes):
            types.append("assertion_changed")
        manifest: dict[str, object] = {
            "schema_version": "baseline-change-manifest/v1",
            "old_integrity": old["integrity"]["sha256"],  # type: ignore[index]
            "new_integrity": new["integrity"]["sha256"],  # type: ignore[index]
            "change_types": types,
            "impact_scopes": changed_scopes,
            "reason_code": "assertion_maintenance",
            "external_requests": 0,
            "no_sensitive_data_in_manifest": True,
            "human_approval_required": True,
            "approval_state": "approved",
            "approved_at_utc": _RUN_AT,
            "approval_valid_until_utc": "2026-07-31T03:00:00Z",
            "approved_change_digest": "0" * 64,
            "approved_by_role": "maintainer",
        }
        manifest["approved_change_digest"] = approval_change_digest(manifest, old, new, envelope)
        return manifest

    @staticmethod
    def _artifacts(envelope: dict[str, str]) -> dict[str, dict[str, str]]:
        return {"summary": dict(envelope), "diff": dict(envelope), "manifest": dict(envelope)}

    def test_complete_chain_accepts_only_one_explicit_bound_path_without_mutation(self) -> None:
        old = self._summary()
        new = self._summary(failed=1)
        diff = compare_baseline(new, old)
        envelope = self._envelope(old, new)
        manifest = self._manifest(old, new, envelope)
        artifacts = self._artifacts(envelope)
        originals = tuple(canonical_json_bytes(value) for value in (old, new, diff, manifest, envelope, artifacts))

        self.assertEqual(validate_manifest(manifest, old, new), {"status": "validated"})
        self.assertEqual(
            validate_provenance_link(new, diff, manifest, envelope, baseline_summary=old, artifact_envelopes=artifacts),
            {"status": "linked"},
        )
        self.assertEqual(
            validate_approval_freshness(manifest, old, new, _NOW, envelope, artifact_envelopes=artifacts),
            {"status": "approved_current"},
        )
        self.assertEqual(tuple(canonical_json_bytes(value) for value in (old, new, diff, manifest, envelope, artifacts)), originals)

    def test_diff_regressions_and_manifest_mutations_cannot_be_approved_or_echoed(self) -> None:
        old = self._summary()
        coverage = dict(_COVERAGE, review=0)
        sensitive = dict(_SENSITIVE, token_like=1)
        for changed, reason in (
            (self._summary(coverage=coverage), "coverage_reduced"),
            (self._summary(sensitive_violations=sensitive), "new_sensitive_category"),
            (self._summary(failed=1), "assertion_failures_increased"),
        ):
            with self.subTest(reason=reason):
                self.assertIn(reason, compare_baseline(changed, old)["reasons"])

        new = self._summary(failed=1)
        envelope = self._envelope(old, new)
        manifest = self._manifest(old, new, envelope)
        for field, value in (("change_types", ["schema_changed"]), ("impact_scopes", ["review"]),
                             ("new_integrity", "b" * 64)):
            candidate = dict(manifest, **{field: value})
            result = validate_approval_freshness(candidate, old, new, _NOW)
            with self.subTest(field=field):
                self.assertEqual(result["status"], "rejected")
                self.assertNotIn("redacted-value", canonical_json_bytes(result).decode("ascii"))

    def test_provenance_and_freshness_bypasses_are_rejected_with_fixed_results(self) -> None:
        old = self._summary()
        new = self._summary(failed=1)
        diff = compare_baseline(new, old)
        envelope = self._envelope(old, new)
        manifest = self._manifest(old, new, envelope)
        artifacts = self._artifacts(envelope)
        rejected = {"status": "rejected", "reason": "reapproval_required"}

        self.assertEqual(validate_approval_freshness(manifest, old, new, _NOW, envelope), rejected)
        self.assertEqual(validate_approval_freshness(manifest, old, new, "2026-07-31T03:00:01Z", envelope,
                                                     artifact_envelopes=artifacts),
                         {"status": "rejected", "reason": "approval_expired"})
        digest_tampered = dict(manifest, approved_change_digest="c" * 64)
        self.assertEqual(validate_approval_freshness(digest_tampered, old, new, _NOW, envelope,
                                                     artifact_envelopes=artifacts),
                         {"status": "rejected", "reason": "approval_digest_mismatch"})

        mixed = self._artifacts(envelope)
        mixed["diff"]["fixture_digest"] = "d" * 64
        self.assertEqual(validate_provenance_link(new, diff, manifest, envelope, baseline_summary=old,
                                                  artifact_envelopes=mixed)["status"], "rejected")
        self.assertEqual(validate_approval_freshness(manifest, old, new, _NOW, envelope, artifact_envelopes=mixed), rejected)

    def test_old_approval_cannot_be_reused_and_legacy_path_is_explicitly_limited(self) -> None:
        old = self._summary()
        new = self._summary(failed=1)
        envelope = self._envelope(old, new)
        manifest = self._manifest(old, new, envelope)
        artifacts = self._artifacts(envelope)
        newer = self._summary(failed=2)

        reused = copy.deepcopy(manifest)
        reused["new_integrity"] = newer["integrity"]["sha256"]  # type: ignore[index]
        reused["approved_change_digest"] = approval_change_digest(reused, old, newer, envelope)
        result = validate_approval_freshness(reused, old, newer, _NOW, envelope, artifact_envelopes=artifacts)
        self.assertEqual(result, {"status": "rejected", "reason": "reapproval_required"})
        self.assertNotIn("redacted-value", canonical_json_bytes(result).decode("ascii"))

        # The legacy path has no provenance and is deliberately tested separately.
        legacy = self._manifest(old, new, envelope)
        legacy["approved_change_digest"] = approval_change_digest(legacy, old, new)
        self.assertEqual(validate_approval_freshness(legacy, old, new, _NOW), {"status": "approved_current"})
        self.assertNotEqual(
            validate_approval_freshness(legacy, old, new, _NOW, envelope, artifact_envelopes=artifacts),
            {"status": "approved_current"},
        )


if __name__ == "__main__":
    unittest.main()
