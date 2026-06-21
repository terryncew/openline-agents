"""Deterministic self-service calibration from verified outcomes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cole_portable_core.canonical import MAX_SAFE_INTEGER, sha256_canonical, sign_object, verify_signed_object
from cole_portable_core.receipt import verify_measurement_receipt

from .outcome import verify_outcome_receipt


METRICS = ("kappa_micros", "epsilon_micros", "delta_hol_micros")
PROFILE_FIELDS = {
    "kind", "receipt_version", "algorithm_id", "canonicalization_id", "spec_uri", "attestation",
    "profile_id", "measurement_algorithm_id", "fit_method_id", "thresholds", "training_corpus_hash",
    "holdout_corpus_hash", "training_sample_count", "holdout_sample_count", "criteria", "validation",
    "activation_status", "payload_hash", "signature",
}


@dataclass(frozen=True)
class CalibrationRecord:
    input_receipt_hash: str
    measurement_receipt_hash: str
    outcome_receipt_hash: str
    kappa_micros: int
    epsilon_micros: int
    delta_hol_micros: int
    label: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CalibrationCriteria:
    min_total_samples: int
    min_holdout_samples: int
    max_false_accept_micros: int
    max_false_retry_micros: int
    false_accept_weight: int
    false_retry_weight: int

    def validate(self) -> None:
        values = asdict(self)
        if any(not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_SAFE_INTEGER for value in values.values()):
            raise ValueError("calibration criteria must contain nonnegative interoperable integers")
        if self.min_total_samples < 500:
            raise ValueError("activation requires at least 500 labeled samples")
        if self.min_holdout_samples < 1:
            raise ValueError("at least one held-out sample is required")
        if self.max_false_accept_micros > 1_000_000 or self.max_false_retry_micros > 1_000_000:
            raise ValueError("error-rate gates must be integer micros in [0, 1000000]")
        if self.false_accept_weight < 1 or self.false_retry_weight < 1:
            raise ValueError("classification weights must be positive")


def verified_record(
    input_receipt: dict[str, Any],
    disclosure: dict[str, Any],
    measurement_receipt: dict[str, Any],
    outcome_receipt: dict[str, Any],
    *,
    previous_input_receipt: dict[str, Any] | None = None,
    previous_disclosure: dict[str, Any] | None = None,
    expected_measurement_key: str | None = None,
    expected_witness_key: str | None = None,
) -> CalibrationRecord:
    if not verify_measurement_receipt(
        measurement_receipt,
        input_receipt,
        disclosure,
        previous_input_receipt=previous_input_receipt,
        previous_disclosure=previous_disclosure,
        expected_public_key=expected_measurement_key,
    ):
        raise ValueError("measurement receipt failed recomputation")
    if not verify_outcome_receipt(outcome_receipt, input_receipt, expected_witness_key):
        raise ValueError("outcome receipt failed witness verification")
    digest = measurement_receipt["measurement"]["digest"]
    values = [digest[name] for name in METRICS]
    if any(value is None for value in values):
        raise ValueError("calibration requires complete kappa, epsilon, and delta_hol")
    if outcome_receipt["label"] not in {"pass", "fail"}:
        raise ValueError("review outcomes cannot train a binary controller")
    return CalibrationRecord(
        input_receipt["payload_hash"],
        measurement_receipt["payload_hash"],
        outcome_receipt["payload_hash"],
        values[0], values[1], values[2], outcome_receipt["label"],
    )


def _records_hash(records: Iterable[CalibrationRecord]) -> str:
    ordered = sorted((record.as_dict() for record in records), key=lambda item: (item["input_receipt_hash"], item["outcome_receipt_hash"]))
    return sha256_canonical(ordered)


def _fit_threshold(records: list[CalibrationRecord], metric: str, criteria: CalibrationCriteria) -> int:
    values = sorted({getattr(record, metric) for record in records})
    if not values:
        raise ValueError("cannot fit an empty training set")
    candidates = values + ([values[-1] + 1] if values[-1] < MAX_SAFE_INTEGER else [])
    best: tuple[int, int, int, int] | None = None
    for threshold in candidates:
        false_accept = sum(record.label == "fail" and getattr(record, metric) < threshold for record in records)
        false_retry = sum(record.label == "pass" and getattr(record, metric) >= threshold for record in records)
        cost = criteria.false_accept_weight * false_accept + criteria.false_retry_weight * false_retry
        candidate = (cost, false_accept, false_retry, threshold)
        if best is None or candidate < best:
            best = candidate
    assert best is not None
    return best[3]


def policy_action(record: CalibrationRecord, thresholds: dict[str, int]) -> str:
    return "retry" if any(getattr(record, metric) >= thresholds[metric] for metric in METRICS) else "accept"


def validation_report(records: list[CalibrationRecord], thresholds: dict[str, int]) -> dict[str, Any]:
    failed = [record for record in records if record.label == "fail"]
    passed = [record for record in records if record.label == "pass"]
    false_accept = sum(policy_action(record, thresholds) == "accept" for record in failed)
    false_retry = sum(policy_action(record, thresholds) == "retry" for record in passed)
    return {
        "failed_count": len(failed),
        "passed_count": len(passed),
        "false_accept_count": false_accept,
        "false_retry_count": false_retry,
        "false_accept_micros": None if not failed else false_accept * 1_000_000 // len(failed),
        "false_retry_micros": None if not passed else false_retry * 1_000_000 // len(passed),
    }


def issue_calibration_profile(
    profile_id: str,
    training_records: list[CalibrationRecord],
    holdout_records: list[CalibrationRecord],
    criteria: CalibrationCriteria,
    key: Ed25519PrivateKey,
) -> dict[str, Any]:
    criteria.validate()
    if not isinstance(profile_id, str) or not profile_id.isascii() or not profile_id:
        raise ValueError("profile_id must be non-empty ASCII")
    if not training_records:
        raise ValueError("training records are required")
    training_ids = [record.input_receipt_hash for record in training_records]
    holdout_ids = [record.input_receipt_hash for record in holdout_records]
    if len(training_ids) != len(set(training_ids)) or len(holdout_ids) != len(set(holdout_ids)):
        raise ValueError("calibration corpora cannot contain duplicate input receipts")
    if set(training_ids) & set(holdout_ids):
        raise ValueError("training and holdout corpora must be disjoint")
    thresholds = {metric: _fit_threshold(training_records, metric, criteria) for metric in METRICS}
    report = validation_report(holdout_records, thresholds)
    total = len(training_records) + len(holdout_records)
    rates_available = report["false_accept_micros"] is not None and report["false_retry_micros"] is not None
    gates_pass = (
        total >= criteria.min_total_samples
        and len(holdout_records) >= criteria.min_holdout_samples
        and rates_available
        and report["false_accept_micros"] <= criteria.max_false_accept_micros
        and report["false_retry_micros"] <= criteria.max_false_retry_micros
    )
    body = {
        "kind": "tc_calibration_profile_receipt",
        "receipt_version": "0.1-draft",
        "algorithm_id": "tc-threshold-calibration-0.1-draft",
        "canonicalization_id": "olp-canonical-json-int-v1",
        "spec_uri": "https://github.com/terryncew/openline-agents",
        "attestation": "self",
        "profile_id": profile_id,
        "measurement_algorithm_id": "cole-portable-core-2.1-draft",
        "fit_method_id": "per-metric-weighted-error-threshold-or-policy-v1",
        "thresholds": thresholds,
        "training_corpus_hash": _records_hash(training_records),
        "holdout_corpus_hash": _records_hash(holdout_records),
        "training_sample_count": len(training_records),
        "holdout_sample_count": len(holdout_records),
        "criteria": asdict(criteria),
        "validation": report,
        "activation_status": "eligible_for_activation" if gates_pass else "shadow_only",
    }
    return sign_object(body, key)


def verify_calibration_profile(receipt: dict[str, Any]) -> bool:
    try:
        if set(receipt) != PROFILE_FIELDS or not verify_signed_object(receipt):
            return False
        if (
            receipt["kind"] != "tc_calibration_profile_receipt"
            or receipt["receipt_version"] != "0.1-draft"
            or receipt["algorithm_id"] != "tc-threshold-calibration-0.1-draft"
            or receipt["canonicalization_id"] != "olp-canonical-json-int-v1"
            or receipt["attestation"] != "self"
            or receipt["measurement_algorithm_id"] != "cole-portable-core-2.1-draft"
            or receipt["fit_method_id"] != "per-metric-weighted-error-threshold-or-policy-v1"
        ):
            return False
        if not isinstance(receipt["profile_id"], str) or not receipt["profile_id"].isascii() or not receipt["profile_id"]:
            return False
        if any(not isinstance(receipt[name], str) or len(receipt[name]) != 64 for name in ("training_corpus_hash", "holdout_corpus_hash")):
            return False
        criteria = CalibrationCriteria(**receipt["criteria"])
        criteria.validate()
        if set(receipt["criteria"]) != set(asdict(criteria)):
            return False
        if set(receipt["thresholds"]) != set(METRICS) or any(
            not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_SAFE_INTEGER
            for value in receipt["thresholds"].values()
        ):
            return False
        if set(receipt["validation"]) != {"failed_count", "passed_count", "false_accept_count", "false_retry_count", "false_accept_micros", "false_retry_micros"}:
            return False
        if not all(
            isinstance(receipt[field], int) and not isinstance(receipt[field], bool) and 0 <= receipt[field] <= MAX_SAFE_INTEGER
            for field in ("training_sample_count", "holdout_sample_count")
        ):
            return False
        validation = receipt["validation"]
        count_fields = ("failed_count", "passed_count", "false_accept_count", "false_retry_count")
        if any(not isinstance(validation[field], int) or isinstance(validation[field], bool) or validation[field] < 0 for field in count_fields):
            return False
        for field in ("false_accept_micros", "false_retry_micros"):
            if validation[field] is not None and (
                not isinstance(validation[field], int) or isinstance(validation[field], bool) or not 0 <= validation[field] <= 1_000_000
            ):
                return False
        if validation["failed_count"] + validation["passed_count"] != receipt["holdout_sample_count"]:
            return False
        if validation["false_accept_count"] > validation["failed_count"] or validation["false_retry_count"] > validation["passed_count"]:
            return False
        if receipt["activation_status"] not in {"shadow_only", "eligible_for_activation"}:
            return False
        eligible = (
            receipt["training_sample_count"] + receipt["holdout_sample_count"] >= criteria.min_total_samples
            and receipt["holdout_sample_count"] >= criteria.min_holdout_samples
            and receipt["validation"]["false_accept_micros"] is not None
            and receipt["validation"]["false_retry_micros"] is not None
            and receipt["validation"]["false_accept_micros"] <= criteria.max_false_accept_micros
            and receipt["validation"]["false_retry_micros"] <= criteria.max_false_retry_micros
        )
        return (receipt["activation_status"] == "eligible_for_activation") is eligible
    except (KeyError, TypeError, ValueError):
        return False
