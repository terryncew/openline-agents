from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest


EXAMPLE = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "agents_api_receiver_boundary.py"
)
spec = importlib.util.spec_from_file_location("agents_api_receiver_boundary", EXAMPLE)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def action(environment: str = "staging") -> dict:
    return {
        "type": "function_call",
        "turn_id": "turn_123",
        "call_id": "call_456",
        "name": "deploy_release",
        "arguments": {
            "service": "checkout",
            "version": "2026.09.11",
            "environment": environment,
        },
    }


class EventSink:
    def __init__(self) -> None:
        self.calls = []

    def create(self, session_id, *, events, idempotency_key):
        self.calls.append(
            {
                "session_id": session_id,
                "events": events,
                "idempotency_key": idempotency_key,
            }
        )


class ReceiverBoundaryTests(unittest.TestCase):
    def test_commit_is_the_only_path_that_executes(self):
        seen = {}
        executions = []

        def gate(proposal):
            seen["proposal"] = proposal
            return module.GateDecision("COMMIT", "allowed", "receipt:1")

        def execute(arguments):
            executions.append(arguments)
            return {"ok": True}

        result = module.handle_function_action(
            "sess_1",
            action(),
            gate,
            execute,
        )

        self.assertTrue(result.executed)
        self.assertEqual(len(executions), 1)
        self.assertEqual(
            dict(seen["proposal"].arguments),
            action()["arguments"],
        )
        self.assertEqual(seen["proposal"].session_id, "sess_1")
        self.assertEqual(seen["proposal"].turn_id, "turn_123")
        self.assertEqual(seen["proposal"].call_id, "call_456")
        self.assertEqual(result.tool_result["turn_id"], "turn_123")
        self.assertEqual(result.tool_result["call_id"], "call_456")
        self.assertTrue(result.tool_result["success"])
        self.assertEqual(result.tool_result["output"], '{"ok":true}')

    def test_quarantine_never_executes(self):
        executions = []

        result = module.handle_function_action(
            "sess_1",
            action("production"),
            lambda proposal: module.GateDecision(
                "QUARANTINE",
                "human review required",
                "receipt:2",
            ),
            lambda arguments: executions.append(arguments),
        )

        self.assertFalse(result.executed)
        self.assertEqual(executions, [])
        self.assertFalse(result.tool_result["success"])
        self.assertIn("OpenLine QUARANTINE", result.tool_result["error"])

    def test_deny_never_executes(self):
        executions = []

        result = module.handle_function_action(
            "sess_1",
            action(),
            lambda proposal: module.GateDecision(
                "DENY",
                "authority absent",
                "receipt:3",
            ),
            lambda arguments: executions.append(arguments),
        )

        self.assertFalse(result.executed)
        self.assertEqual(executions, [])
        self.assertFalse(result.tool_result["success"])
        self.assertIn("OpenLine DENY", result.tool_result["error"])

    def test_submit_preserves_call_identity_and_uses_event_idempotency(self):
        sink = EventSink()
        client = SimpleNamespace(
            beta=SimpleNamespace(
                agents=SimpleNamespace(
                    sessions=SimpleNamespace(
                        events=sink,
                    )
                )
            )
        )
        session = SimpleNamespace(
            id="sess_1",
            status="requires_action",
            required_actions=[action()],
        )

        results = module.submit_required_actions(
            client,
            session,
            lambda proposal: module.GateDecision("COMMIT", "allowed"),
            lambda arguments: {"deployed": arguments["version"]},
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(len(sink.calls), 1)
        submitted = sink.calls[0]
        self.assertEqual(submitted["session_id"], "sess_1")
        self.assertTrue(submitted["idempotency_key"].startswith("openline-tool-result-"))
        tool_result = submitted["events"][0]
        self.assertEqual(tool_result["turn_id"], "turn_123")
        self.assertEqual(tool_result["call_id"], "call_456")
        self.assertTrue(tool_result["success"])

    def test_unknown_function_fails_closed_before_gate_or_effect(self):
        gate_calls = []
        executions = []
        proposed = action()
        proposed["name"] = "unexpected_tool"

        result = module.handle_function_action(
            "sess_1",
            proposed,
            lambda proposal: gate_calls.append(proposal),
            lambda arguments: executions.append(arguments),
        )

        self.assertFalse(result.executed)
        self.assertEqual(gate_calls, [])
        self.assertEqual(executions, [])
        self.assertFalse(result.tool_result["success"])
        self.assertIn("unsupported function", result.tool_result["error"])


if __name__ == "__main__":
    unittest.main()
