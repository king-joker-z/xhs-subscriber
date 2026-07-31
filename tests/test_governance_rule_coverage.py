"""Offline tests for synthetic governance rule-to-evidence coverage declarations."""
from __future__ import annotations

import copy
import unittest

try:
    from tests.governance_rule_coverage import validate_rule_coverage
except ModuleNotFoundError:  # unittest discovery loads modules directly from tests/.
    from governance_rule_coverage import validate_rule_coverage  # type: ignore[no-redef]


_CONTRACT = "governance-contract/v1"
_FIXTURE = "offline-fixture/v1"
_DIGEST = "a" * 64
_RULES = (
    ("purpose_before_result", "purpose_guard", "purpose_before_result"),
    ("tls_before_success", "tls_guard", "tls_before_success"),
    ("terminal_after_block", "terminal_guard", "terminal_after_block"),
    ("baseline_provenance_approval", "approval_guard", "reapproval_required"),
    ("governance_sequence", "sequence_guard", "invalid_trace"),
)


class GovernanceRuleCoverageTests(unittest.TestCase):
    @staticmethod
    def _case(assertion_id: str, passed: bool, reason: str | None = None) -> dict[str, object]:
        result: dict[str, object] = {"fixture_digest": _DIGEST, "assertion_id": assertion_id, "passed": passed}
        if reason is not None:
            result["expected_rejection"] = reason
        return result

    def _manifest(self) -> dict[str, object]:
        return {
            "schema_version": "rule_coverage_contract/v1",
            "contract_version": _CONTRACT,
            "fixture_version": _FIXTURE,
            "rules": [
                {
                    "rule_id": rule_id,
                    "severity": "required",
                    "positive_case": self._case(assertion_id, True),
                    "negative_case": self._case(assertion_id, True, reason),
                }
                for rule_id, assertion_id, reason in _RULES
            ],
        }

    def test_accepts_complete_explicit_synthetic_evidence_without_mutation(self) -> None:
        manifest = self._manifest()
        before = copy.deepcopy(manifest)
        self.assertEqual(validate_rule_coverage(manifest, _CONTRACT, _FIXTURE), {"status": "valid"})
        self.assertEqual(manifest, before)

    def test_rejects_missing_positive_or_negative_evidence(self) -> None:
        for field, reason in (("positive_case", "coverage_missing_positive_case"),
                              ("negative_case", "coverage_missing_negative_case")):
            manifest = self._manifest()
            manifest["rules"][0][field] = None  # type: ignore[index]
            with self.subTest(field=field):
                self.assertEqual(
                    validate_rule_coverage(manifest, _CONTRACT, _FIXTURE),
                    {"status": "rejected", "reason": reason},
                )

    def test_rejects_ineffective_negative_evidence_and_version_mismatch(self) -> None:
        manifest = self._manifest()
        manifest["rules"][0]["negative_case"]["expected_rejection"] = "invalid_trace"  # type: ignore[index]
        self.assertEqual(
            validate_rule_coverage(manifest, _CONTRACT, _FIXTURE),
            {"status": "rejected", "reason": "negative_case_not_effective"},
        )
        manifest = self._manifest()
        manifest["rules"][0]["negative_case"]["passed"] = False  # type: ignore[index]
        self.assertEqual(
            validate_rule_coverage(manifest, _CONTRACT, _FIXTURE),
            {"status": "rejected", "reason": "negative_case_not_effective"},
        )
        for contract, fixture in (("old-contract/v1", _FIXTURE), (_CONTRACT, "old-fixture/v1")):
            with self.subTest(contract=contract, fixture=fixture):
                self.assertEqual(
                    validate_rule_coverage(self._manifest(), contract, fixture),
                    {"status": "rejected", "reason": "version_mismatch"},
                )

    def test_rejects_cross_rule_assertions_and_info_severity(self) -> None:
        for index, (rule_id, assertion_id, _) in enumerate(_RULES):
            wrong_assertion = _RULES[(index + 1) % len(_RULES)][1]
            for case_name in ("positive_case", "negative_case"):
                manifest = self._manifest()
                manifest["rules"][index][case_name]["assertion_id"] = wrong_assertion  # type: ignore[index]
                with self.subTest(rule_id=rule_id, case=case_name):
                    self.assertEqual(
                        validate_rule_coverage(manifest, _CONTRACT, _FIXTURE),
                        {"status": "rejected", "reason": "invalid_coverage"},
                    )
        for severity in ("info", 1, True):
            manifest = self._manifest()
            manifest["rules"][0]["severity"] = severity  # type: ignore[index]
            with self.subTest(severity=repr(severity)):
                self.assertEqual(
                    validate_rule_coverage(manifest, _CONTRACT, _FIXTURE),
                    {"status": "rejected", "reason": "invalid_coverage"},
                )

        cases: list[object] = []
        duplicate = self._manifest()
        duplicate["rules"].append(copy.deepcopy(duplicate["rules"][0]))  # type: ignore[index]
        cases.append(duplicate)
        unknown = self._manifest()
        unknown["rules"][0]["rule_id"] = "unknown_rule"  # type: ignore[index]
        cases.append(unknown)
        extra = self._manifest()
        extra["rules"][0]["positive_case"]["token"] = "secret"  # type: ignore[index]
        cases.append(extra)
        bad_digest = self._manifest()
        bad_digest["rules"][0]["positive_case"]["fixture_digest"] = "not-a-hash"  # type: ignore[index]
        cases.append(bad_digest)
        cases.extend(({"schema_version": "rule_coverage_contract/v1"}, "not-a-mapping"))
        for candidate in cases:
            with self.subTest(candidate_type=type(candidate).__name__):
                result = validate_rule_coverage(candidate, _CONTRACT, _FIXTURE)  # type: ignore[arg-type]
                self.assertEqual(result, {"status": "rejected", "reason": "invalid_coverage"})
                self.assertNotIn("secret", repr(result))


if __name__ == "__main__":
    unittest.main()
