"""Terrynce Curve controller proposals with shadow-first activation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cole_portable_core.canonical import sign_object, verify_signed_object
from cole_portable_core.receipt import validate_measurement_profile

from .calibration import METRICS, verify_calibration_profile
from .outcome import verify_outcome_receipt


PROPOSAL_FIELDS = {
    "kind", "receipt_version", "algorithm_id", "canonicalization_id", "spec_uri", "attestation",
    "mode", "action", "input_receipt_hash", "measurement_receipt_hash", "outcome_receipt_hash",
    "calibration_profile_hash", "previous_proposal_hash", "reasons", "payload_hash", "signature",
}


@dataclass(frozen=True)
class ControllerProposal:
    receipt: dict[str, Any]

    @property
    def action(self) -> str:
        return self.receipt["action"]


def propose(
    measurement_receipt: dict[str, Any] | None,
    outcome_receipt: dict[str, Any],
    input_receipt: dict[str, Any],
    key: Ed25519PrivateKey,
    *,
    expected_witness_key: str,
    calibration_profile: dict[str, Any] | None = None,
    mode: str = "shadow",
    previous_proposal_hash: str | None = None,
) -> ControllerProposal:
    if mode not in {"shadow", "active"}:
        raise ValueError("controller mode must be shadow or active")
    if not verify_outcome_receipt(outcome_receipt, input_receipt, expected_witness_key):
        raise ValueError("outcome receipt is not valid for this input")
    if measurement_receipt is not None:
        try:
            validate_measurement_profile(measurement_receipt)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("measurement receipt profile is invalid") from exc
        if not verify_signed_object(measurement_receipt):
            raise ValueError("measurement receipt signature is invalid")
        if (
            measurement_receipt["input_receipt_hash"] != input_receipt["payload_hash"]
            or measurement_receipt["input_trace_id"] != input_receipt["trace_id"]
        ):
            raise ValueError("measurement receipt is bound to a different input")
    if calibration_profile is not None and not verify_calibration_profile(calibration_profile):
        raise ValueError("calibration profile is invalid")
    if mode == "active" and (calibration_profile is None or calibration_profile["activation_status"] != "eligible_for_activation"):
        raise ValueError("active mode requires an eligible calibration profile")

    label = outcome_receipt["label"]
    reasons: list[str] = []
    if label == "review":
        action = "human_review"
        reasons.append("witness_requested_review")
    elif label == "fail":
        action = "retry"
        reasons.append("orthogonal_outcome_failed")
    else:
        action = "accept"
        reasons.append("orthogonal_outcome_passed")

    if measurement_receipt is not None and calibration_profile is not None:
        digest = measurement_receipt["measurement"]["digest"]
        thresholds = calibration_profile["thresholds"]
        crossed = [metric for metric in METRICS if digest.get(metric) is None or digest[metric] >= thresholds[metric]]
        for metric in crossed:
            reasons.append(f"{metric}_threshold")
        metric_action = "human_review" if any(digest.get(metric) is None for metric in METRICS) else ("retry" if crossed else "accept")
        if metric_action != action:
            reasons.append("orthogonal_witness_disagreement")
            action = "human_review"
        else:
            action = metric_action

    body = {
        "kind": "tc_controller_proposal_receipt",
        "receipt_version": "0.1-draft",
        "algorithm_id": "tc-controller-0.1-draft",
        "canonicalization_id": "olp-canonical-json-int-v1",
        "spec_uri": "https://github.com/terryncew/openline-agents",
        "attestation": "self",
        "mode": mode,
        "action": action,
        "input_receipt_hash": input_receipt["payload_hash"],
        "measurement_receipt_hash": None if measurement_receipt is None else measurement_receipt["payload_hash"],
        "outcome_receipt_hash": outcome_receipt["payload_hash"],
        "calibration_profile_hash": None if calibration_profile is None else calibration_profile["payload_hash"],
        "previous_proposal_hash": previous_proposal_hash,
        "reasons": sorted(set(reasons)),
    }
    return ControllerProposal(sign_object(body, key))


def verify_proposal(receipt: dict[str, Any]) -> bool:
    try:
        if set(receipt) != PROPOSAL_FIELDS or not verify_signed_object(receipt):
            return False
        if (
            receipt["kind"] != "tc_controller_proposal_receipt"
            or receipt["receipt_version"] != "0.1-draft"
            or receipt["algorithm_id"] != "tc-controller-0.1-draft"
            or receipt["canonicalization_id"] != "olp-canonical-json-int-v1"
            or receipt["attestation"] != "self"
        ):
            return False
        if receipt["mode"] not in {"shadow", "active"} or receipt["action"] not in {"accept", "retry", "human_review"}:
            return False
        for field in ("input_receipt_hash", "outcome_receipt_hash"):
            if not isinstance(receipt[field], str) or len(receipt[field]) != 64 or any(char not in "0123456789abcdef" for char in receipt[field]):
                return False
        for field in ("measurement_receipt_hash", "calibration_profile_hash", "previous_proposal_hash"):
            value = receipt[field]
            if value is not None and (not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value)):
                return False
        if (
            not isinstance(receipt["reasons"], list)
            or not all(isinstance(reason, str) and reason.isascii() and reason for reason in receipt["reasons"])
            or receipt["reasons"] != sorted(set(receipt["reasons"]))
        ):
            return False
        return True
    except (KeyError, TypeError, ValueError):
        return False
