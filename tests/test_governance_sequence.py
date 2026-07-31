"""Offline tests for the synthetic governance event sequence contract."""
from __future__ import annotations

import copy
import unittest

try:
    from tests.governance_sequence import validate_governance_sequence
except ModuleNotFoundError:  # unittest discovery loads modules directly from tests/.
    from governance_sequence import validate_governance_sequence  # type: ignore[no-redef]


class GovernanceSequenceTests(unittest.TestCase):
    @staticmethod
    def _trace(*events: str) -> list[dict[str, object]]:
        return [{"sequence": index, "event": event} for index, event in enumerate(events, start=1)]

    def test_accepts_normal_minimal_closure_with_manifest(self) -> None:
        trace = self._trace(
            "purpose_confirmed", "second_confirmation_passed", "allowed_external_action",
            "tls_verified", "result_classified", "success_classified", "terminal_policy_assigned",
            "summary_generated", "provenance_link_verified", "approval_freshness_verified", "manifest_adoptable",
        )
        before = copy.deepcopy(trace)
        self.assertEqual(validate_governance_sequence(trace), {"status": "valid"})
        self.assertEqual(trace, before)

    def test_accepts_no_manifest_closure_and_terminal_minimum(self) -> None:
        self.assertEqual(
            validate_governance_sequence(self._trace("purpose_confirmed", "result_classified", "terminal_policy_assigned", "summary_generated")),
            {"status": "valid"},
        )
        self.assertEqual(validate_governance_sequence(self._trace("precheck_blocked")), {"status": "valid"})
        self.assertEqual(
            validate_governance_sequence(self._trace("provenance_link_verified", "approval_freshness_verified", "manifest_adoptable")),
            {"status": "valid"},
        )

    def test_rejects_missing_or_inverted_preconditions(self) -> None:
        cases = (
            (self._trace("tls_verified", "result_classified"), "purpose_before_result"),
            (self._trace("purpose_confirmed", "result_classified", "success_classified"), "tls_before_success"),
            (self._trace("purpose_confirmed", "allowed_external_action"), "invalid_trace"),
            (self._trace("purpose_confirmed", "result_classified", "manifest_adoptable"), "approval_before_manifest"),
            (self._trace("approval_freshness_verified"), "approval_before_manifest"),
            (self._trace("approval_freshness_verified", "provenance_link_verified", "manifest_adoptable"), "approval_before_manifest"),
        )
        for trace, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(validate_governance_sequence(trace), {"status": "rejected", "reason": reason})

    def test_rejects_post_terminal_processing_and_mixed_traces(self) -> None:
        for event in ("success_classified", "review_sample_created", "summary_generated", "manifest_adoptable"):
            with self.subTest(event=event):
                trace = self._trace("precheck_blocked", event)
                self.assertEqual(
                    validate_governance_sequence(trace),
                    {"status": "rejected", "reason": "terminal_after_block"},
                )

    def test_rejects_invalid_shape_unknown_duplicate_and_non_monotonic_sequences(self) -> None:
        cases = (
            [{"sequence": 1, "event": "purpose_confirmed", "extra": True}],
            [{"sequence": 1, "event": "unknown"}],
            [{"sequence": 1, "event": "purpose_confirmed"}, {"sequence": 1, "event": "result_classified"}],
            [{"sequence": 1, "event": "purpose_confirmed"}, {"sequence": 3, "event": "result_classified"}],
            self._trace("purpose_confirmed", "purpose_confirmed"),
            [{"sequence": 1, "event": "purpose_confirmed"}, "not-a-mapping"],  # type: ignore[list-item]
        )
        for trace in cases:
            with self.subTest(trace_type=type(trace).__name__):
                result = validate_governance_sequence(trace)
                self.assertEqual(result, {"status": "rejected", "reason": "invalid_trace"})
                self.assertNotIn("secret", repr(result))


if __name__ == "__main__":
    unittest.main()
