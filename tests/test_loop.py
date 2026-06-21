import unittest

from cole_portable_core.receipt import issue_measurement_receipt
from openline_agents.calibration import CalibrationCriteria, CalibrationRecord, issue_calibration_profile
from openline_agents.controller import propose, verify_proposal
from openline_agents.loop import ExecutionResult, VerifiedLoop
from openline_agents.outcome import Outcome, issue_outcome_receipt
from tests.helpers import CALIBRATION_KEY, CONTROLLER_KEY, MEASUREMENT_KEY, WITNESS_KEY, h, make_bundle


class SequenceWitness:
    def __init__(self):
        self.count = 0

    def evaluate(self, output):
        self.count += 1
        label = "fail" if self.count == 1 else "pass"
        return Outcome(label, 0 if label == "fail" else 1_000_000, "test.pass-fail.v1", h(str(output)), "test-suite", 1_780_000_000_000_000 + self.count)


class LoopTests(unittest.TestCase):
    def test_shadow_retry_requires_caller_approval_and_chains_measurement(self):
        bundles = [make_bundle("trace_loop_1"), make_bundle("trace_loop_2", changed=True)]

        def executor(prompt, attempt):
            return ExecutionResult(f"output-{attempt}", bundles[attempt - 1])

        loop = VerifiedLoop(
            executor,
            SequenceWitness(),
            measurement_key=MEASUREMENT_KEY,
            witness_key=WITNESS_KEY,
            controller_key=CONTROLLER_KEY,
            max_attempts=2,
            approve_retry=lambda proposal: proposal.action == "retry",
            revise=lambda prompt, proposal, result: prompt + " corrected",
        )
        result = loop.run("solve")
        self.assertEqual(len(result.attempts), 2)
        self.assertEqual(result.attempts[0].controller_proposal["mode"], "shadow")
        self.assertEqual(result.attempts[0].controller_proposal["action"], "retry")
        self.assertTrue(verify_proposal(result.attempts[0].controller_proposal))
        self.assertEqual(result.final.controller_proposal["action"], "accept")
        self.assertEqual(
            result.final.measurement_receipt["previous_input_receipt_hash"],
            result.attempts[0].bundle.receipt["payload_hash"],
        )

    def test_shadow_proposal_does_not_retry_without_approval(self):
        bundle = make_bundle("trace_no_retry")
        loop = VerifiedLoop(
            lambda prompt, attempt: ExecutionResult("failed", bundle),
            SequenceWitness(),
            measurement_key=MEASUREMENT_KEY,
            witness_key=WITNESS_KEY,
            controller_key=CONTROLLER_KEY,
            max_attempts=3,
        )
        self.assertEqual(len(loop.run("solve").attempts), 1)

    def test_active_mode_rejects_shadow_only_profile(self):
        criteria = CalibrationCriteria(500, 100, 0, 0, 2, 1)
        item = CalibrationRecord(h("i"), h("m"), h("o"), 100_000, 100_000, 100_000, "pass")
        other = CalibrationRecord(h("i2"), h("m2"), h("o2"), 900_000, 900_000, 900_000, "fail")
        profile = issue_calibration_profile("small", [item], [other], criteria, CALIBRATION_KEY)
        bundle = make_bundle("trace_active_rejected")
        outcome = issue_outcome_receipt(bundle.receipt, Outcome("pass", 1_000_000, "test.v1", h("ok"), "test", 1), WITNESS_KEY)
        with self.assertRaises(ValueError):
            propose(
                None, outcome, bundle.receipt, CONTROLLER_KEY,
                expected_witness_key=outcome["signature"]["public_key"],
                calibration_profile=profile, mode="active",
            )

    def test_controller_rejects_measurement_from_another_input(self):
        first = make_bundle("trace_measurement_first")
        second = make_bundle("trace_measurement_second")
        measurement = issue_measurement_receipt(first.receipt, first.disclosure, MEASUREMENT_KEY)
        outcome = issue_outcome_receipt(second.receipt, Outcome("pass", 1_000_000, "test.v1", h("ok"), "test", 1), WITNESS_KEY)
        with self.assertRaises(ValueError):
            propose(
                measurement, outcome, second.receipt, CONTROLLER_KEY,
                expected_witness_key=outcome["signature"]["public_key"],
            )

    def test_controller_rejects_valid_but_untrusted_witness(self):
        bundle = make_bundle("trace_untrusted_witness")
        outcome = issue_outcome_receipt(bundle.receipt, Outcome("pass", 1_000_000, "test.v1", h("ok"), "test", 1), WITNESS_KEY)
        with self.assertRaises(ValueError):
            propose(
                None, outcome, bundle.receipt, CONTROLLER_KEY,
                expected_witness_key="00" * 32,
            )


if __name__ == "__main__":
    unittest.main()
