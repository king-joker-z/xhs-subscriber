"""Pure-memory freshness tests for synthetic governance rule evidence."""
from __future__ import annotations

import copy
import unittest

try:
    from tests.governance_rule_coverage import canonical_evidence_digest, validate_rule_evidence_freshness
except ModuleNotFoundError:
    from governance_rule_coverage import canonical_evidence_digest, validate_rule_evidence_freshness  # type: ignore[no-redef]

_CONTRACT, _FIXTURE, _NOW, _DIGEST = "governance-contract/v1", "offline-fixture/v1", "2026-07-31T06:00:00Z", "a" * 64
_RULES = (("purpose_before_result", "purpose_guard", "purpose_before_result"), ("tls_before_success", "tls_guard", "tls_before_success"), ("terminal_after_block", "terminal_guard", "terminal_after_block"), ("baseline_provenance_approval", "approval_guard", "reapproval_required"), ("governance_sequence", "sequence_guard", "invalid_trace"))


class GovernanceRuleEvidenceFreshnessTests(unittest.TestCase):
    def _case(self, rule_id: str, outcome: str, *, negative: bool = False) -> dict[str, str]:
        case = {"fixture_digest": _DIGEST, "replay_outcome": outcome, "verified_contract_version": _CONTRACT, "verified_fixture_version": _FIXTURE, "verified_schema_version": "governance-rule-evidence/v1", "verified_at_utc": "2026-07-31T05:00:00Z", "valid_until_utc": "2026-07-31T07:00:00Z"}
        case["replay_digest"] = canonical_evidence_digest({"rule_id": rule_id, "fixture_digest": _DIGEST, "replay_outcome": outcome, "contract_version": _CONTRACT, "fixture_version": _FIXTURE, "schema_version": "governance-rule-evidence/v1"})
        if negative: case["expected_rejection"] = outcome
        return case

    def _manifest(self) -> dict[str, object]:
        rules = [{"rule_id": rule, "assertion_id": assertion, "positive": self._case(rule, "valid"), "negative": self._case(rule, reason, negative=True)} for rule, assertion, reason in _RULES]
        manifest: dict[str, object] = {"schema_version": "governance-rule-evidence/v1", "contract_version": _CONTRACT, "fixture_version": _FIXTURE, "rules": rules, "coverage_evidence_digest": ""}
        manifest["coverage_evidence_digest"] = canonical_evidence_digest({"schema_version": manifest["schema_version"], "contract_version": _CONTRACT, "fixture_version": _FIXTURE, "rules": rules})
        return manifest

    def test_accepts_current_replayable_evidence_without_mutation(self) -> None:
        manifest = self._manifest(); before = copy.deepcopy(manifest)
        self.assertEqual(validate_rule_evidence_freshness(manifest, _CONTRACT, _FIXTURE, _NOW, _DIGEST), {"status": "valid"})
        self.assertEqual(manifest, before)

    def test_rejects_missing_or_ineffective_negative_evidence(self) -> None:
        missing = self._manifest(); missing["rules"][0]["negative"] = None  # type: ignore[index]
        self.assertEqual(validate_rule_evidence_freshness(missing, _CONTRACT, _FIXTURE, _NOW, _DIGEST), {"status": "rejected", "reason": "coverage_negative_not_effective"})
        generic = self._manifest(); generic["rules"][0]["negative"]["replay_outcome"] = "invalid_trace"  # type: ignore[index]
        self.assertEqual(validate_rule_evidence_freshness(generic, _CONTRACT, _FIXTURE, _NOW, _DIGEST), {"status": "rejected", "reason": "coverage_negative_not_effective"})

    def test_rejects_stale_replay_and_time_windows(self) -> None:
        stale = self._manifest(); stale["rules"][0]["positive"]["verified_fixture_version"] = "old-fixture/v1"  # type: ignore[index]
        self.assertEqual(validate_rule_evidence_freshness(stale, _CONTRACT, _FIXTURE, _NOW, _DIGEST), {"status": "rejected", "reason": "coverage_evidence_stale"})
        tampered = self._manifest(); tampered["rules"][0]["positive"]["replay_digest"] = "b" * 64  # type: ignore[index]
        self.assertEqual(validate_rule_evidence_freshness(tampered, _CONTRACT, _FIXTURE, _NOW, _DIGEST), {"status": "rejected", "reason": "replay_mismatch"})
        future = self._manifest(); future["rules"][0]["positive"]["verified_at_utc"] = "2026-07-31T06:30:00Z"  # type: ignore[index]
        self.assertEqual(validate_rule_evidence_freshness(future, _CONTRACT, _FIXTURE, _NOW, _DIGEST), {"status": "rejected", "reason": "coverage_evidence_not_yet_valid"})
        expired = self._manifest(); expired["rules"][0]["positive"]["valid_until_utc"] = "2026-07-31T05:30:00Z"  # type: ignore[index]
        self.assertEqual(validate_rule_evidence_freshness(expired, _CONTRACT, _FIXTURE, _NOW, _DIGEST), {"status": "rejected", "reason": "coverage_evidence_expired"})

    def test_rejects_untrusted_fixture_replacement_even_when_digests_are_recomputed(self) -> None:
        replacement = "b" * 64
        for case_name in ("positive", "negative"):
            candidate = self._manifest()
            candidate["rules"][0][case_name]["fixture_digest"] = replacement  # type: ignore[index]
            case = candidate["rules"][0][case_name]  # type: ignore[index]
            outcome = case["replay_outcome"]
            case["replay_digest"] = canonical_evidence_digest({"rule_id": "purpose_before_result", "fixture_digest": replacement, "replay_outcome": outcome, "contract_version": _CONTRACT, "fixture_version": _FIXTURE, "schema_version": "governance-rule-evidence/v1"})
            candidate["coverage_evidence_digest"] = canonical_evidence_digest({"schema_version": candidate["schema_version"], "contract_version": _CONTRACT, "fixture_version": _FIXTURE, "rules": candidate["rules"]})
            with self.subTest(case=case_name):
                self.assertEqual(validate_rule_evidence_freshness(candidate, _CONTRACT, _FIXTURE, _NOW, _DIGEST), {"status": "rejected", "reason": "coverage_evidence_stale"})
        self.assertEqual(validate_rule_evidence_freshness(self._manifest(), _CONTRACT, _FIXTURE, _NOW, "bad"), {"status": "rejected", "reason": "invalid_evidence"})

        for mutate in (lambda m: m["rules"][0].update({"assertion_id": "sequence_guard"}), lambda m: m["rules"][0]["positive"].update({"token": "secret"}), lambda m: m.update({"extra": "secret"}), lambda m: m.update({"coverage_evidence_digest": "bad"})):
            manifest = self._manifest(); mutate(manifest)
            result = validate_rule_evidence_freshness(manifest, _CONTRACT, _FIXTURE, _NOW, _DIGEST)
            self.assertIn(result["reason"], {"invalid_evidence", "replay_mismatch"})
            self.assertNotIn("secret", repr(result))


if __name__ == "__main__": unittest.main()
