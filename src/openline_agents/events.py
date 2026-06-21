"""Explicit typed OLP custom spans for the OpenAI Agents SDK."""

from __future__ import annotations

import hashlib
from typing import Any


def content_hash(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def _custom_span(name: str, data: dict[str, Any]):
    try:
        from agents.tracing import custom_span
    except ImportError as exc:  # pragma: no cover - exercised by real-SDK gate
        raise RuntimeError("install the openai-agents package to emit native custom spans") from exc
    return custom_span(name, data)


def claim(node_id: str, content: str | bytes, *, material: bool = True):
    return _custom_span("olp.claim", {"id": node_id, "content_hash": content_hash(content), "material": material})


def evidence(node_id: str, content: str | bytes, *, observed: bool = True):
    return _custom_span("olp.evidence", {"id": node_id, "content_hash": content_hash(content), "observed": observed})


def relation(src: str, dst: str, relation_type: str):
    return _custom_span("olp.relation", {"src": src, "dst": dst, "relation_type": relation_type})


def signal(sequence: int, value_micros: int, signal_schema_id: str):
    return _custom_span("olp.signal", {"sequence": sequence, "value_micros": value_micros, "signal_schema_id": signal_schema_id})
