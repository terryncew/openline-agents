"""Native OpenAI Agents SDK trace processor producing OLP Wire Canon receipts."""

from __future__ import annotations

import hashlib
import math
import queue
import struct
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cole_portable_core.canon import validate_semantic_graph
from cole_portable_core.canonical import canonical_json, sha256_canonical, sign_object

try:  # The deterministic suite runs without importing the network-facing SDK.
    from agents.tracing import TracingProcessor
except ImportError:  # pragma: no cover - the real-SDK gate covers the import path
    class TracingProcessor:  # type: ignore[no-redef]
        pass


ALGORITHM_ID = "olp-openai-agents-receipt-0.1-draft"
SPEC_URI = "https://github.com/terryncew/openline-agents"
SEMCONV_SCHEMA_ID = "openai-agents-sdk-tracing-0.17"
OLP_EVENT_NAMES = frozenset({"olp.claim", "olp.evidence", "olp.relation", "olp.signal"})
MAX_SAFE_INTEGER = (1 << 53) - 1


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value if abs(value) <= MAX_SAFE_INTEGER else {"$int": str(value)}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite trace value")
        return {"$f64": struct.pack(">d", value).hex()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("trace object keys must be strings")
        return {key: _normalize(item) for key, item in sorted(value.items())}
    raise ValueError(f"unsupported trace value type: {type(value).__name__}")


def _merkle_root(records: list[dict[str, Any]]) -> str:
    if not records:
        return hashlib.sha256(b"").hexdigest()
    level = [hashlib.sha256(b"\x00" + canonical_json(record)).digest() for record in records]
    while len(level) > 1:
        next_level = []
        for index in range(0, len(level), 2):
            if index + 1 == len(level):
                next_level.append(level[index])
            else:
                next_level.append(hashlib.sha256(b"\x01" + level[index] + level[index + 1]).digest())
        level = next_level
    return level[0].hex()


def _wire_trace_id(agent_trace_id: str) -> str:
    return hashlib.sha256(agent_trace_id.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class CaptureBundle:
    agent_trace_id: str
    receipt: dict[str, Any]
    disclosure: dict[str, Any] | None
    span_records: tuple[dict[str, Any], ...]


class BundleStore:
    def __init__(self) -> None:
        self._items: list[CaptureBundle] = []
        self._condition = threading.Condition()

    def emit(self, bundle: CaptureBundle) -> None:
        with self._condition:
            self._items.append(bundle)
            self._condition.notify_all()

    def all(self) -> list[CaptureBundle]:
        with self._condition:
            return list(self._items)

    def wait_for(self, predicate: Callable[[CaptureBundle], bool], timeout: float = 5) -> CaptureBundle:
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                for item in self._items:
                    if predicate(item):
                        return item
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("capture bundle was not emitted")
                self._condition.wait(remaining)


class OpenLineTraceProcessor(TracingProcessor):
    """Non-blocking processor attached with ``agents.add_trace_processor``."""

    def __init__(self, signing_key: Ed25519PrivateKey, *, store: BundleStore | None = None) -> None:
        self._key = signing_key
        self._store = store or BundleStore()
        self._queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        self._spans: dict[str, list[dict[str, Any]]] = {}
        self._closed = False
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._run, name="openline-agents", daemon=True)
        self._worker.start()

    @property
    def store(self) -> BundleStore:
        return self._store

    def on_trace_start(self, trace: Any) -> None:
        return None

    def on_trace_end(self, trace: Any) -> None:
        exported = trace.export()
        if isinstance(exported, Mapping):
            self._queue.put(("trace", dict(exported)))

    def on_span_start(self, span: Any) -> None:
        return None

    def on_span_end(self, span: Any) -> None:
        exported = span.export()
        if isinstance(exported, Mapping):
            self._queue.put(("span", dict(exported)))

    def _run(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            try:
                kind, value = self._queue.get(timeout=0.02)
            except queue.Empty:
                continue
            try:
                if kind == "span":
                    trace_id = value.get("trace_id")
                    if isinstance(trace_id, str):
                        self._spans.setdefault(trace_id, []).append(value)
                else:
                    trace_id = value.get("id") or value.get("trace_id")
                    if isinstance(trace_id, str):
                        self._seal(trace_id, value, self._spans.pop(trace_id, []))
            finally:
                self._queue.task_done()

    @staticmethod
    def _typed_input(spans: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], str | None] | None:
        claims: dict[str, dict[str, Any]] = {}
        evidence: dict[str, dict[str, Any]] = {}
        relations: list[dict[str, Any]] = []
        signals: dict[int, dict[str, Any]] = {}
        schemas: set[str] = set()
        saw_event = False

        def exact(value: Mapping[str, Any], fields: set[str]) -> None:
            if set(value) != fields:
                raise ValueError(f"typed event fields mismatch: expected {sorted(fields)}")

        for span in spans:
            span_data = span.get("span_data")
            if not isinstance(span_data, Mapping) or span_data.get("type") != "custom":
                continue
            name = span_data.get("name")
            if name not in OLP_EVENT_NAMES:
                continue
            saw_event = True
            data = span_data.get("data")
            if not isinstance(data, Mapping):
                raise ValueError("OLP custom span data must be an object")
            attrs = dict(data)
            if name == "olp.claim":
                exact(attrs, {"id", "content_hash", "material"})
                if attrs["id"] in claims:
                    raise ValueError("duplicate claim id")
                claims[attrs["id"]] = attrs
            elif name == "olp.evidence":
                exact(attrs, {"id", "content_hash", "observed"})
                if attrs["id"] in evidence:
                    raise ValueError("duplicate evidence id")
                evidence[attrs["id"]] = attrs
            elif name == "olp.relation":
                exact(attrs, {"src", "dst", "relation_type"})
                relations.append(attrs)
            else:
                exact(attrs, {"sequence", "value_micros", "signal_schema_id"})
                sequence = attrs["sequence"]
                if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0 or sequence in signals:
                    raise ValueError("signal sequence must be a unique nonnegative integer")
                if not isinstance(attrs["value_micros"], int) or isinstance(attrs["value_micros"], bool):
                    raise ValueError("signal value must be integer micros")
                if not isinstance(attrs["signal_schema_id"], str) or not attrs["signal_schema_id"]:
                    raise ValueError("signal schema is required")
                schemas.add(attrs["signal_schema_id"])
                signals[sequence] = attrs
        if not saw_event:
            return None
        if len(schemas) > 1:
            raise ValueError("signal schema must be uniform")
        ordered = sorted(signals)
        if ordered != list(range(len(ordered))):
            raise ValueError("signal sequence must be contiguous and zero-based")
        graph = {
            "claims": [claims[key] for key in sorted(claims)],
            "evidence": [evidence[key] for key in sorted(evidence)],
            "relations": sorted(relations, key=lambda item: (item["src"], item["dst"], item["relation_type"])),
        }
        validate_semantic_graph(graph)
        signal_items = [signals[key] for key in ordered]
        schema = signal_items[0]["signal_schema_id"] if signal_items else None
        return graph, signal_items, schema

    def _seal(self, agent_trace_id: str, trace: dict[str, Any], spans: list[dict[str, Any]]) -> None:
        normalized = []
        dropped_span_count = 0
        for span in spans:
            try:
                normalized.append(_normalize(span))
            except ValueError:
                dropped_span_count += 1
        normalized.sort(key=lambda item: (item.get("started_at") or "", item.get("id") or ""))
        wire_trace_id = _wire_trace_id(agent_trace_id)
        base = {
            "kind": "trace_receipt",
            "receipt_version": "0.1",
            "algorithm_id": ALGORITHM_ID,
            "canonicalization_id": "olp-canonical-json-int-v1",
            "spec_uri": SPEC_URI,
            "attestation": "self",
            "capture_status": "provisional",
            "trace_id": wire_trace_id,
            "capture_loss": dropped_span_count > 0,
            "dropped_span_count": dropped_span_count,
            "observed_span_count": len(spans),
            "trace_root": _merkle_root(normalized),
            "tree_algorithm": "rfc6962-mth-sha256-promote-odd-v1",
            "completion_policy": {"type": "root_close_plus_grace", "grace_millis": 0, "semconv_schema_id": SEMCONV_SCHEMA_ID},
            "seal_reason": "grace_elapsed",
        }
        disclosure = None
        try:
            typed = self._typed_input(spans)
        except (KeyError, TypeError, ValueError) as exc:
            base.update({"semantic_claims": False, "typed_event_status": "invalid", "typed_event_error": str(exc)})
        else:
            if typed is None:
                base["semantic_claims"] = False
            else:
                graph, signals, schema = typed
                base.update({
                    "kind": "coherence_input_receipt",
                    "semantic_claims": True,
                    "typed_event_status": "valid",
                    "semantic_graph_hash": sha256_canonical(graph),
                    "signal_schema_id": schema,
                    "signal_points_micros": [item["value_micros"] for item in signals],
                    "state_cap": "white",
                })
                disclosure = {
                    "kind": "coherence_input_disclosure",
                    "disclosure_version": "0.1",
                    "trace_id": wire_trace_id,
                    "semantic_graph": graph,
                    "signal_schema_id": schema,
                    "signals": [{"sequence": index, "value_micros": item["value_micros"]} for index, item in enumerate(signals)],
                }
        receipt = sign_object(base, self._key)
        self._store.emit(CaptureBundle(agent_trace_id, receipt, disclosure, tuple(normalized)))

    def force_flush(self) -> None:
        self._queue.join()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.force_flush()
        self._stop.set()
        self._worker.join(timeout=2)
