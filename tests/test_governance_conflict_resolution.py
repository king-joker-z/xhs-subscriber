"""Offline tests for pure-memory synthetic governance conflict resolution."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

try:
    from tests.governance_conflict_resolution import resolve_governance_conflict
except ModuleNotFoundError:  # unittest discovery loads modules directly from tests/.
    from governance_conflict_resolution import resolve_governance_conflict  # type: ignore[no-redef]


class GovernanceConflictResolutionTests(unittest.TestCase):
    @staticmethod
    def _decision(rule_id: str, outcome: str, actions: list[str], retention: str, terminal: bool = False) -> dict[str, object]:
        return {"rule_id": rule_id, "outcome": outcome, "allowed_actions": actions, "retention_level": retention, "terminal": terminal}

    def test_known_conflicts_choose_stricter_outcome_and_minimal_retention(self) -> None:
        quality = [
            self._decision("purpose_before_result", "accepted_public_single_work", ["quality_guidance_shown"], "standard"),
            self._decision("governance_sequence", "quality_degraded", ["quality_guidance_shown"], "minimal"),
        ]
        review = [
            self._decision("purpose_before_result", "accepted_public_single_work", ["review_sample_created"], "standard"),
            self._decision("baseline_provenance_approval", "review_required", ["review_sample_created"], "minimal"),
        ]
        tls = [
            self._decision("purpose_before_result", "accepted_public_single_work", [], "minimal"),
            self._decision("tls_before_success", "tls_failure", [], "none", True),
        ]
        self.assertEqual(resolve_governance_conflict(quality), {"status": "valid", "reason": "resolved", "outcome": "quality_degraded", "allowed_actions": ["quality_guidance_shown"], "retention_level": "minimal", "terminal": False})
        self.assertEqual(resolve_governance_conflict(review), {"status": "valid", "reason": "resolved", "outcome": "review_required", "allowed_actions": ["review_sample_created"], "retention_level": "minimal", "terminal": False})
        self.assertEqual(resolve_governance_conflict(tls), {"status": "valid", "reason": "resolved", "outcome": "block", "allowed_actions": [], "retention_level": "none", "terminal": True})

    def test_three_way_conflict_prefers_access_restricted(self) -> None:
        decisions = [
            self._decision("purpose_before_result", "accepted_public_single_work", [], "minimal"),
            self._decision("tls_before_success", "tls_failure", [], "none"),
            self._decision("baseline_provenance_approval", "access_restricted", [], "none"),
        ]
        self.assertEqual(resolve_governance_conflict(decisions), {"status": "valid", "reason": "resolved", "outcome": "access_restricted", "allowed_actions": [], "retention_level": "none", "terminal": False})

    def test_quality_and_review_outputs_are_safely_constrained(self) -> None:
        quality = [
            self._decision("purpose_before_result", "accepted_public_single_work", ["continue_processing", "quality_guidance_shown"], "minimal"),
            self._decision("governance_sequence", "quality_degraded", ["continue_processing", "quality_guidance_shown"], "minimal"),
        ]
        review = [
            self._decision("purpose_before_result", "accepted_public_single_work", ["continue_processing", "review_sample_created"], "minimal"),
            self._decision("baseline_provenance_approval", "review_required", ["continue_processing", "review_sample_created"], "minimal"),
        ]
        self.assertEqual(resolve_governance_conflict(quality), {"status": "valid", "reason": "resolved", "outcome": "quality_degraded", "allowed_actions": ["quality_guidance_shown"], "retention_level": "minimal", "terminal": False})
        self.assertEqual(resolve_governance_conflict(review), {"status": "valid", "reason": "resolved", "outcome": "review_required", "allowed_actions": ["review_sample_created"], "retention_level": "minimal", "terminal": False})
        invalid = {"status": "rejected", "reason": "invalid_decision", "outcome": "block", "allowed_actions": [], "retention_level": "none", "terminal": True}
        self.assertEqual(resolve_governance_conflict([self._decision("governance_sequence", "quality_degraded", ["quality_guarantee"], "minimal")]), invalid)
        self.assertEqual(resolve_governance_conflict([self._decision("governance_sequence", "quality_degraded", ["download"], "minimal")]), invalid)

    def test_terminal_input_always_upgrades_to_safe_block(self) -> None:
        accepted_terminal = [self._decision("purpose_before_result", "accepted_public_single_work", ["continue_processing"], "minimal", True)]
        three_way = [
            self._decision("purpose_before_result", "accepted_public_single_work", ["continue_processing"], "minimal"),
            self._decision("governance_sequence", "quality_degraded", ["continue_processing", "quality_guidance_shown"], "minimal"),
            self._decision("baseline_provenance_approval", "review_required", ["continue_processing", "review_sample_created"], "minimal", True),
        ]
        expected = {"status": "valid", "reason": "resolved", "outcome": "block", "allowed_actions": [], "retention_level": "none", "terminal": True}
        self.assertEqual(resolve_governance_conflict(accepted_terminal), expected)
        self.assertEqual(resolve_governance_conflict(three_way), expected)

        decisions = [
            self._decision("purpose_before_result", "accepted_public_single_work", ["continue_processing"], "minimal"),
            self._decision("governance_sequence", "quality_degraded", ["quality_guidance_shown"], "minimal"),
        ]
        default = {"status": "rejected", "reason": "default_deny", "outcome": "block", "allowed_actions": [], "retention_level": "none", "terminal": True}
        self.assertEqual(resolve_governance_conflict(decisions), default)
        self.assertEqual(resolve_governance_conflict([]), default)
        self.assertEqual(resolve_governance_conflict([self._decision("unknown", "block", [], "none", True)]), {**default, "reason": "invalid_decision"})

    def test_rejects_duplicates_unregistered_combinations_extra_and_strict_types(self) -> None:
        valid = self._decision("purpose_before_result", "accepted_public_single_work", ["continue_processing"], "minimal")
        cases = (
            [valid, copy.deepcopy(valid)],
            [self._decision("purpose_before_result", "tls_failure", [], "none", True)],
            [{**valid, "url": "sensitive"}],
            ["not-a-mapping"],  # type: ignore[list-item]
            [self._decision("purpose_before_result", "accepted_public_single_work", "continue_processing", "minimal")],  # type: ignore[arg-type]
            [self._decision("purpose_before_result", "accepted_public_single_work", ["continue_processing", "continue_processing"], "minimal")],
            [self._decision("purpose_before_result", "accepted_public_single_work", ["unknown_action"], "minimal")],
            [self._decision("purpose_before_result", "accepted_public_single_work", ["continue_processing"], "minimal", 1)],  # type: ignore[arg-type]
        )
        expected = {"status": "rejected", "reason": "invalid_decision", "outcome": "block", "allowed_actions": [], "retention_level": "none", "terminal": True}
        for decisions in cases:
            with self.subTest(case=repr(decisions)):
                result = resolve_governance_conflict(decisions)
                self.assertEqual(result, expected)
                self.assertNotIn("sensitive", repr(result))

    def test_input_is_unchanged_and_has_no_io_or_network_path(self) -> None:
        decisions = [
            self._decision("purpose_before_result", "accepted_public_single_work", ["continue_processing"], "minimal"),
        ]
        before = copy.deepcopy(decisions)
        with patch("builtins.open", side_effect=AssertionError("no file I/O")), patch("socket.socket", side_effect=AssertionError("no network")):
            self.assertEqual(resolve_governance_conflict(decisions)["status"], "valid")
        self.assertEqual(decisions, before)


if __name__ == "__main__":
    unittest.main()
