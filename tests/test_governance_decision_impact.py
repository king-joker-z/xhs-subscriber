"""Offline regression tests for synthetic governance decision impact analysis."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

try:
    from tests.governance_decision_impact import analyze_decision_impact
except ModuleNotFoundError:
    from governance_decision_impact import analyze_decision_impact  # type: ignore[no-redef]

_DIGEST = "a" * 64
_CONTRACT = "contract/v1"
_VERSION = "governance-decision-matrix/v1"


class GovernanceDecisionImpactTests(unittest.TestCase):
    @staticmethod
    def _item(scenario: str, outcome: str, actions: list[str], retention: str, terminal: bool = False, **extra: object) -> dict[str, object]:
        item: dict[str, object] = {"scenario_id": scenario, "outcome": outcome, "allowed_actions": actions, "retention_level": retention, "terminal": terminal, "matrix_version": _VERSION, "fixture_digest": _DIGEST, "contract_version": _CONTRACT}
        item.update(extra)
        return item

    def _baseline(self) -> list[dict[str, object]]:
        return [
            self._item("public_single_work", "accepted_public_single_work", ["continue_processing", "quality_guidance_shown"], "standard"),
            self._item("quality_degraded", "quality_degraded", ["quality_guidance_shown"], "minimal"),
            self._item("review_required", "review_required", ["review_sample_created"], "minimal"),
            self._item("tls_failure", "tls_failure", [], "none", True),
        ]

    def test_accepts_equal_or_tighter_actions_and_reports_only_aggregate_counts(self) -> None:
        before = self._baseline()
        after = copy.deepcopy(before)
        after[0]["allowed_actions"] = ["quality_guidance_shown"]
        after[0]["retention_level"] = "minimal"
        report = analyze_decision_impact(before, after, _DIGEST, _CONTRACT)
        self.assertEqual(report, {"status": "valid", "reason": "impact_tightened_or_equal", "matrix_version_before": _VERSION, "matrix_version_after": _VERSION, "scenario_count": 4, "outcome_tightened_count": 0, "actions_reduced_count": 1, "retention_tightened_count": 1})
        self.assertNotIn("allowed_actions", report)

    def test_rejects_outcome_actions_and_retention_weakening(self) -> None:
        cases = []
        outcome = self._baseline(); outcome[1]["outcome"] = "accepted_public_single_work"; cases.append((outcome, "decision_impact_terminal_weakened"))
        review = self._baseline(); review[2]["outcome"] = "accepted_public_single_work"; cases.append((review, "decision_impact_terminal_weakened"))
        tls = self._baseline(); tls[3]["outcome"] = "accepted_public_single_work"; tls[3]["terminal"] = False; tls[3]["retention_level"] = "minimal"; cases.append((tls, "decision_impact_terminal_weakened"))
        actions = self._baseline(); actions[0]["allowed_actions"].append("quality_guarantee"); cases.append((actions, "decision_impact_actions_weakened"))  # type: ignore[union-attr]
        retention = self._baseline(); retention[1]["retention_level"] = "standard"; cases.append((retention, "invalid_impact"))
        for after, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(analyze_decision_impact(self._baseline(), after, _DIGEST, _CONTRACT), {"status": "rejected", "reason": reason})

    def test_rejects_version_mismatch_terminal_weakening_and_unsafe_outcomes(self) -> None:
        baseline = self._baseline()
        v2 = copy.deepcopy(baseline)
        for item in v2:
            item["matrix_version"] = "governance-decision-matrix/v2"
        terminal_weakened = copy.deepcopy(baseline)
        terminal_weakened[3]["terminal"] = False
        terminal_weakened[3]["outcome"] = "block"
        bad_block_actions = copy.deepcopy(baseline)
        bad_block_actions[0].update({"outcome": "block", "allowed_actions": ["continue_processing"], "retention_level": "none", "terminal": True})
        bad_block_retention = copy.deepcopy(baseline)
        bad_block_retention[0].update({"outcome": "block", "allowed_actions": [], "retention_level": "standard", "terminal": True})
        bad_block_terminal = copy.deepcopy(baseline)
        bad_block_terminal[0].update({"outcome": "block", "allowed_actions": [], "retention_level": "none", "terminal": False})
        bad_review = copy.deepcopy(baseline)
        bad_review[2]["allowed_actions"] = ["continue_processing"]
        bad_quality = copy.deepcopy(baseline)
        bad_quality[1]["allowed_actions"] = ["quality_guarantee"]
        cases = ((v2, "version_mismatch"), (terminal_weakened, "decision_impact_terminal_weakened"), (bad_block_actions, "invalid_impact"), (bad_block_retention, "invalid_impact"), (bad_block_terminal, "invalid_impact"), (bad_review, "invalid_impact"), (bad_quality, "invalid_impact"))
        for after, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(analyze_decision_impact(baseline, after, _DIGEST, _CONTRACT), {"status": "rejected", "reason": reason})

        baseline = self._baseline()
        missing = baseline[:-1]
        added = baseline + [self._item("access_restricted", "access_restricted", [], "none", True)]
        digest = copy.deepcopy(baseline); digest[0]["fixture_digest"] = "b" * 64
        version = copy.deepcopy(baseline); version[0]["matrix_version"] = "governance-decision-matrix/v2"
        contract = copy.deepcopy(baseline); contract[0]["contract_version"] = "old"
        terminal = copy.deepcopy(baseline); terminal[3]["allowed_actions"] = ["continue_processing"]
        cases = ((missing, "decision_impact_coverage_missing"), (added, "decision_impact_coverage_missing"), (digest, "invalid_impact"), (version, "version_mismatch"), (contract, "invalid_impact"), (terminal, "invalid_impact"))
        for after, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(analyze_decision_impact(baseline, after, _DIGEST, _CONTRACT), {"status": "rejected", "reason": reason})

    def test_rejects_extra_unknown_duplicate_and_wrong_expected_digest(self) -> None:
        baseline = self._baseline()
        extra = copy.deepcopy(baseline); extra[0]["url"] = "sensitive"
        unknown = copy.deepcopy(baseline); unknown[0]["scenario_id"] = "unknown"
        duplicate = copy.deepcopy(baseline); duplicate[1]["scenario_id"] = "public_single_work"
        for after in (extra, unknown, duplicate):
            self.assertEqual(analyze_decision_impact(baseline, after, _DIGEST, _CONTRACT), {"status": "rejected", "reason": "invalid_impact"})
        self.assertEqual(analyze_decision_impact(baseline, baseline, "bad", _CONTRACT), {"status": "rejected", "reason": "invalid_impact"})

    def test_input_is_unchanged_and_no_io_or_network_is_used(self) -> None:
        before, after = self._baseline(), self._baseline()
        original_before, original_after = copy.deepcopy(before), copy.deepcopy(after)
        with patch("builtins.open", side_effect=AssertionError("no file I/O")), patch("socket.socket", side_effect=AssertionError("no network")):
            self.assertEqual(analyze_decision_impact(before, after, _DIGEST, _CONTRACT)["status"], "valid")
        self.assertEqual(before, original_before)
        self.assertEqual(after, original_after)


if __name__ == "__main__":
    unittest.main()
