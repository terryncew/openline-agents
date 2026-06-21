"""Native Agents SDK gate. No model call or API key is required."""

import hashlib
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

try:
    from agents.tracing import custom_span, set_trace_processors, trace
except ImportError as exc:  # pragma: no cover - CI installs the real SDK
    SDK_IMPORT_ERROR = exc
else:
    SDK_IMPORT_ERROR = None

from cole_portable_core.canon import validate_disclosure
from openline_agents.capture import OpenLineTraceProcessor


def h(value):
    return hashlib.sha256(value.encode()).hexdigest()


@unittest.skipIf(SDK_IMPORT_ERROR is not None, f"real OpenAI Agents SDK unavailable: {SDK_IMPORT_ERROR}")
class RealSdkIntegrationTests(unittest.TestCase):
    def test_native_custom_spans_produce_canon_input(self):
        processor = OpenLineTraceProcessor(Ed25519PrivateKey.from_private_bytes(bytes.fromhex("66" * 32)))
        self.addCleanup(processor.shutdown)
        set_trace_processors([processor])
        with trace("OpenLine native SDK gate"):
            with custom_span("olp.claim", {"id": "c1", "content_hash": h("claim"), "material": True}):
                pass
            with custom_span("olp.evidence", {"id": "e1", "content_hash": h("evidence"), "observed": True}):
                pass
            with custom_span("olp.relation", {"src": "e1", "dst": "c1", "relation_type": "supports"}):
                pass
            with custom_span("olp.signal", {"sequence": 0, "value_micros": 500_000, "signal_schema_id": "test.signal.v1"}):
                pass
        processor.force_flush()
        bundle = processor.store.all()[-1]
        self.assertEqual(bundle.receipt["kind"], "coherence_input_receipt")
        validate_disclosure(bundle.disclosure, bundle.receipt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
