"""Signed outcomes supplied by an orthogonal witness."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cole_portable_core.canonical import MAX_SAFE_INTEGER, sign_object, verify_signed_object


HASH256 = re.compile(r"^[0-9a-f]{64}$")
LABELS = frozenset({"pass", "fail", "review"})


@dataclass(frozen=True)
class Outcome:
    label: str
    score_micros: int | None
    label_schema_id: str
    evidence_hash: str
    witness_id: str
    observed_at_unix_micros: int

    def validate(self) -> None:
        if self.label not in LABELS:
            raise ValueError("outcome label must be pass, fail, or review")
        if self.score_micros is not None and (not isinstance(self.score_micros, int) or isinstance(self.score_micros, bool) or not 0 <= self.score_micros <= 1_000_000):
            raise ValueError("outcome score must be null or integer micros in [0, 1000000]")
        if not isinstance(self.label_schema_id, str) or not self.label_schema_id:
            raise ValueError("label_schema_id is required")
        if not isinstance(self.witness_id, str) or not self.witness_id.isascii() or not self.witness_id:
            raise ValueError("witness_id must be non-empty ASCII")
        if not HASH256.fullmatch(self.evidence_hash):
            raise ValueError("evidence_hash must be lowercase SHA-256 hex")
        if not isinstance(self.observed_at_unix_micros, int) or isinstance(self.observed_at_unix_micros, bool) or not 0 <= self.observed_at_unix_micros <= MAX_SAFE_INTEGER:
            raise ValueError("observed timestamp must be an interoperable nonnegative integer")


class Witness(Protocol):
    def evaluate(self, output: Any) -> Outcome: ...


def issue_outcome_receipt(input_receipt: dict[str, Any], outcome: Outcome, key: Ed25519PrivateKey) -> dict[str, Any]:
    outcome.validate()
    body = {
        "kind": "outcome_receipt",
        "receipt_version": "0.1-draft",
        "algorithm_id": "openline-orthogonal-outcome-0.1-draft",
        "canonicalization_id": "olp-canonical-json-int-v1",
        "spec_uri": "https://github.com/terryncew/openline-agents",
        "attestation": "witness_signed",
        "input_receipt_hash": input_receipt["payload_hash"],
        "input_trace_id": input_receipt["trace_id"],
        "label": outcome.label,
        "score_micros": outcome.score_micros,
        "label_schema_id": outcome.label_schema_id,
        "evidence_hash": outcome.evidence_hash,
        "witness_id": outcome.witness_id,
        "observed_at_unix_micros": outcome.observed_at_unix_micros,
    }
    return sign_object(body, key)


def verify_outcome_receipt(receipt: dict[str, Any], input_receipt: dict[str, Any], expected_public_key: str | None = None) -> bool:
    fields = {
        "kind", "receipt_version", "algorithm_id", "canonicalization_id", "spec_uri", "attestation",
        "input_receipt_hash", "input_trace_id", "label", "score_micros", "label_schema_id",
        "evidence_hash", "witness_id", "observed_at_unix_micros", "payload_hash", "signature",
    }
    try:
        if set(receipt) != fields or not verify_signed_object(receipt):
            return False
        if (
            receipt["kind"] != "outcome_receipt"
            or receipt["receipt_version"] != "0.1-draft"
            or receipt["algorithm_id"] != "openline-orthogonal-outcome-0.1-draft"
            or receipt["canonicalization_id"] != "olp-canonical-json-int-v1"
            or receipt["attestation"] != "witness_signed"
        ):
            return False
        if receipt["input_receipt_hash"] != input_receipt["payload_hash"] or receipt["input_trace_id"] != input_receipt["trace_id"]:
            return False
        if expected_public_key is not None and receipt["signature"]["public_key"] != expected_public_key:
            return False
        Outcome(
            receipt["label"], receipt["score_micros"], receipt["label_schema_id"], receipt["evidence_hash"],
            receipt["witness_id"], receipt["observed_at_unix_micros"],
        ).validate()
        return True
    except (KeyError, TypeError, ValueError):
        return False
