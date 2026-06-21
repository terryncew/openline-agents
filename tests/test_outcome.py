import copy
import unittest

from openline_agents.outcome import Outcome, issue_outcome_receipt, verify_outcome_receipt
from tests.helpers import WITNESS_KEY, h, make_bundle


class OutcomeTests(unittest.TestCase):
    def test_external_outcome_is_bound_to_input(self):
        bundle = make_bundle("trace_outcome")
        outcome = Outcome("pass", 1_000_000, "test.pass-fail.v1", h("tests passed"), "ci", 1_780_000_000_000_000)
        receipt = issue_outcome_receipt(bundle.receipt, outcome, WITNESS_KEY)
        self.assertTrue(verify_outcome_receipt(receipt, bundle.receipt))

    def test_tampering_fails(self):
        bundle = make_bundle("trace_tamper")
        outcome = Outcome("fail", 0, "test.pass-fail.v1", h("tests failed"), "ci", 1_780_000_000_000_000)
        receipt = issue_outcome_receipt(bundle.receipt, outcome, WITNESS_KEY)
        changed = copy.deepcopy(receipt)
        changed["label"] = "pass"
        self.assertFalse(verify_outcome_receipt(changed, bundle.receipt))


if __name__ == "__main__":
    unittest.main()
