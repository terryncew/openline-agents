import unittest

from cole_portable_core.canon import validate_disclosure
from cole_portable_core.canonical import verify_signed_object

from openline_agents.capture import OpenLineTraceProcessor
from tests.helpers import CAPTURE_KEY, FakeItem, custom, h, span


class CaptureTests(unittest.TestCase):
    def make_processor(self):
        processor = OpenLineTraceProcessor(CAPTURE_KEY)
        self.addCleanup(processor.shutdown)
        return processor

    def test_ordinary_sdk_span_stays_structural(self):
        processor = self.make_processor()
        trace_id = "trace_ordinary"
        processor.on_span_end(span(trace_id, "span_1", {"type": "generation", "model": "example", "temperature": 0.1}))
        processor.on_trace_end(FakeItem({"object": "trace", "id": trace_id, "workflow_name": "ordinary", "group_id": None, "metadata": None}))
        bundle = processor.store.wait_for(lambda item: item.agent_trace_id == trace_id)
        self.assertEqual(bundle.receipt["kind"], "trace_receipt")
        self.assertFalse(bundle.receipt["semantic_claims"])
        self.assertIsNone(bundle.disclosure)
        self.assertEqual(bundle.span_records[0]["span_data"]["temperature"], {"$f64": "3fb999999999999a"})
        self.assertTrue(verify_signed_object(bundle.receipt))

    def test_explicit_custom_spans_produce_bound_disclosure(self):
        processor = self.make_processor()
        trace_id = "trace_typed"
        items = [
            custom(trace_id, "1", "olp.claim", {"id": "c1", "content_hash": h("claim"), "material": True}),
            custom(trace_id, "2", "olp.evidence", {"id": "e1", "content_hash": h("evidence"), "observed": True}),
            custom(trace_id, "3", "olp.relation", {"src": "e1", "dst": "c1", "relation_type": "supports"}),
            custom(trace_id, "4", "olp.signal", {"sequence": 0, "value_micros": 500_000, "signal_schema_id": "test.signal.v1"}),
        ]
        for item in items:
            processor.on_span_end(item)
        processor.on_trace_end(FakeItem({"object": "trace", "id": trace_id, "workflow_name": "typed", "group_id": None, "metadata": None}))
        bundle = processor.store.wait_for(lambda item: item.agent_trace_id == trace_id)
        self.assertEqual(bundle.receipt["kind"], "coherence_input_receipt")
        self.assertIsNotNone(bundle.disclosure)
        validate_disclosure(bundle.disclosure, bundle.receipt)

    def test_invalid_typed_event_downgrades_with_signed_error(self):
        processor = self.make_processor()
        trace_id = "trace_invalid"
        processor.on_span_end(custom(trace_id, "1", "olp.claim", {"id": "c1", "content_hash": h("claim"), "material": True}))
        processor.on_span_end(custom(trace_id, "2", "olp.claim", {"id": "c1", "content_hash": h("other"), "material": True}))
        processor.on_trace_end(FakeItem({"object": "trace", "id": trace_id, "workflow_name": "invalid", "group_id": None, "metadata": None}))
        receipt = processor.store.wait_for(lambda item: item.agent_trace_id == trace_id).receipt
        self.assertEqual(receipt["kind"], "trace_receipt")
        self.assertEqual(receipt["typed_event_status"], "invalid")
        self.assertTrue(verify_signed_object(receipt))

    def test_unsupported_custom_value_becomes_signed_capture_loss(self):
        processor = self.make_processor()
        trace_id = "trace_capture_loss"
        processor.on_span_end(FakeItem({
            "object": "trace.span",
            "id": "span_bad",
            "trace_id": trace_id,
            "started_at": "2026-06-21T00:00:00Z",
            "span_data": {"type": "custom", "name": "third.party", "data": {"bad": object()}},
        }))
        processor.on_trace_end(FakeItem({"object": "trace", "id": trace_id, "workflow_name": "loss", "group_id": None, "metadata": None}))
        receipt = processor.store.wait_for(lambda item: item.agent_trace_id == trace_id).receipt
        self.assertTrue(receipt["capture_loss"])
        self.assertEqual(receipt["dropped_span_count"], 1)
        self.assertEqual(receipt["observed_span_count"], 1)
        self.assertTrue(verify_signed_object(receipt))


if __name__ == "__main__":
    unittest.main()
