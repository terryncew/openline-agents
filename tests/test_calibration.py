import copy
import unittest

from openline_agents.calibration import (
    CalibrationCriteria,
    CalibrationRecord,
    issue_calibration_profile,
    verify_calibration_profile,
)
from tests.helpers import CALIBRATION_KEY, h


def record(index: int, label: str, value: int) -> CalibrationRecord:
    return CalibrationRecord(h(f"input:{index}"), h(f"measurement:{index}"), h(f"outcome:{index}"), value, value, value, label)


CRITERIA = CalibrationCriteria(500, 100, 0, 0, 2, 1)


class CalibrationTests(unittest.TestCase):
    def test_separable_500_sample_corpus_becomes_eligible(self):
        train = [record(i, "pass", 100_000) for i in range(200)] + [record(i + 200, "fail", 900_000) for i in range(200)]
        holdout = [record(i + 400, "pass", 100_000) for i in range(50)] + [record(i + 450, "fail", 900_000) for i in range(50)]
        profile = issue_calibration_profile("test-profile", train, holdout, CRITERIA, CALIBRATION_KEY)
        self.assertEqual(profile["activation_status"], "eligible_for_activation")
        self.assertTrue(verify_calibration_profile(profile))

    def test_small_corpus_stays_shadow_only(self):
        profile = issue_calibration_profile("small", [record(1, "pass", 100_000), record(2, "fail", 900_000)], [record(3, "pass", 100_000), record(4, "fail", 900_000)], CRITERIA, CALIBRATION_KEY)
        self.assertEqual(profile["activation_status"], "shadow_only")
        self.assertTrue(verify_calibration_profile(profile))

    def test_failed_holdout_stays_shadow_only(self):
        train = [record(i, "pass", 100_000) for i in range(200)] + [record(i + 200, "fail", 900_000) for i in range(200)]
        holdout = [record(i + 400, "pass", 900_000) for i in range(50)] + [record(i + 450, "fail", 100_000) for i in range(50)]
        profile = issue_calibration_profile("bad-holdout", train, holdout, CRITERIA, CALIBRATION_KEY)
        self.assertEqual(profile["activation_status"], "shadow_only")

    def test_profile_tampering_fails(self):
        profile = issue_calibration_profile("small", [record(1, "pass", 100_000)], [record(2, "fail", 900_000)], CRITERIA, CALIBRATION_KEY)
        changed = copy.deepcopy(profile)
        changed["thresholds"]["kappa_micros"] += 1
        self.assertFalse(verify_calibration_profile(changed))

    def test_duplicate_runs_cannot_fake_sample_count(self):
        duplicated = [record(1, "pass", 100_000)] * 500
        with self.assertRaises(ValueError):
            issue_calibration_profile("duplicates", duplicated, [record(2, "fail", 900_000)], CRITERIA, CALIBRATION_KEY)

    def test_training_and_holdout_cannot_overlap(self):
        shared = record(1, "pass", 100_000)
        with self.assertRaises(ValueError):
            issue_calibration_profile("leakage", [shared], [shared], CRITERIA, CALIBRATION_KEY)

    def test_unknown_profile_field_is_rejected(self):
        profile = issue_calibration_profile("small", [record(1, "pass", 100_000)], [record(2, "fail", 900_000)], CRITERIA, CALIBRATION_KEY)
        profile["surprise"] = True
        self.assertFalse(verify_calibration_profile(profile))


if __name__ == "__main__":
    unittest.main()
