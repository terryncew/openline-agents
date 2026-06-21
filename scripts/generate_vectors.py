#!/usr/bin/env python3
"""Generate deterministic signed cross-runtime conformance vectors."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cole_portable_core.canonical import sign_object
from openline_agents.calibration import CalibrationCriteria, CalibrationRecord, issue_calibration_profile
from openline_agents.controller import propose
from openline_agents.outcome import Outcome, issue_outcome_receipt


ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "vectors"


def key(byte: int) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes([byte]) * 32)


def digest(label: str) -> str:
    import hashlib
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def write(name: str, value: object) -> None:
    VECTORS.mkdir(exist_ok=True)
    (VECTORS / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="ascii")


def main() -> None:
    input_receipt = sign_object({
        "kind": "trace_receipt",
        "receipt_version": "0.1",
        "algorithm_id": "openline-agents-vector-input-v1",
        "canonicalization_id": "olp-canonical-json-int-v1",
        "spec_uri": "https://github.com/terryncew/openline-agents",
        "attestation": "self",
        "trace_id": "0123456789abcdef0123456789abcdef",
    }, key(1))
    outcome = issue_outcome_receipt(
        input_receipt,
        Outcome("pass", 1_000_000, "conformance.pass-fail.v1", digest("test output"), "conformance-suite", 1_780_000_000_000_000),
        key(2),
    )
    train = [CalibrationRecord(digest(f"input:{i}"), digest(f"measurement:{i}"), digest(f"outcome:{i}"), 100_000, 100_000, 100_000, "pass") for i in range(250)]
    train += [CalibrationRecord(digest(f"input:{i}"), digest(f"measurement:{i}"), digest(f"outcome:{i}"), 900_000, 900_000, 900_000, "fail") for i in range(250, 400)]
    holdout = [CalibrationRecord(digest(f"input:{i}"), digest(f"measurement:{i}"), digest(f"outcome:{i}"), 100_000, 100_000, 100_000, "pass") for i in range(400, 450)]
    holdout += [CalibrationRecord(digest(f"input:{i}"), digest(f"measurement:{i}"), digest(f"outcome:{i}"), 900_000, 900_000, 900_000, "fail") for i in range(450, 500)]
    profile = issue_calibration_profile(
        "conformance-profile",
        train,
        holdout,
        CalibrationCriteria(500, 100, 0, 0, 2, 1),
        key(3),
    )
    proposal = propose(None, outcome, input_receipt, key(4)).receipt
    tampered = copy.deepcopy(proposal)
    tampered["action"] = "retry"
    write("input-receipt.json", input_receipt)
    write("outcome-receipt.json", outcome)
    write("calibration-profile-receipt.json", profile)
    write("controller-proposal-receipt.json", proposal)
    write("invalid-tampered-controller-proposal.json", tampered)


if __name__ == "__main__":
    main()
