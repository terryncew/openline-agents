from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from openline_agents.capture import CaptureBundle, OpenLineTraceProcessor


CAPTURE_KEY = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("11" * 32))
MEASUREMENT_KEY = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("22" * 32))
WITNESS_KEY = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("33" * 32))
CONTROLLER_KEY = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("44" * 32))
CALIBRATION_KEY = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("55" * 32))


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass
class FakeItem:
    value: dict[str, Any]

    def export(self):
        return self.value


def span(trace_id: str, span_id: str, data: dict[str, Any], *, parent_id: str | None = None, start: str = "2026-06-21T00:00:00Z") -> FakeItem:
    return FakeItem({
        "object": "trace.span",
        "id": span_id,
        "trace_id": trace_id,
        "parent_id": parent_id,
        "started_at": start,
        "ended_at": "2026-06-21T00:00:01Z",
        "span_data": data,
        "error": None,
    })


def custom(trace_id: str, span_id: str, name: str, data: dict[str, Any]) -> FakeItem:
    return span(trace_id, span_id, {"type": "custom", "name": name, "data": data})


def make_bundle(trace_id: str, *, changed: bool = False, signals: list[int] | None = None) -> CaptureBundle:
    values = signals or [400_000, 500_000, 400_000]
    processor = OpenLineTraceProcessor(CAPTURE_KEY)
    claim_text = "claim changed" if changed else "claim"
    items = [
        custom(trace_id, "span_claim", "olp.claim", {"id": "claim_1", "content_hash": h(claim_text), "material": True}),
        custom(trace_id, "span_evidence", "olp.evidence", {"id": "evidence_1", "content_hash": h("evidence"), "observed": True}),
        custom(trace_id, "span_relation", "olp.relation", {"src": "evidence_1", "dst": "claim_1", "relation_type": "supports"}),
    ]
    items.extend(custom(trace_id, f"span_signal_{index}", "olp.signal", {"sequence": index, "value_micros": value, "signal_schema_id": "test.normalized-signal.v1"}) for index, value in enumerate(values))
    for item in items:
        processor.on_span_end(item)
    processor.on_trace_end(FakeItem({"object": "trace", "id": trace_id, "workflow_name": "test", "group_id": None, "metadata": None}))
    bundle = processor.store.wait_for(lambda candidate: candidate.agent_trace_id == trace_id)
    processor.shutdown()
    return bundle
