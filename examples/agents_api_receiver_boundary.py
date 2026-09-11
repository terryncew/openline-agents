"""OpenLine receiver boundary for the managed OpenAI Agents API.

The Agents API owns the managed session. This application owns the custom
function side effect. OpenLine Receipt Gate belongs between the proposed call
and that effect.

This file intentionally has no import-time dependency on the OpenAI client so
its boundary behavior can be tested without network access.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import time
from typing import Any, Callable, Literal, Mapping, Protocol

Disposition = Literal["COMMIT", "QUARANTINE", "DENY"]

DEPLOY_RELEASE_TOOL = {
    "type": "function",
    "name": "deploy_release",
    "description": "Deploy one service version to a named environment.",
    "parameters": {
        "type": "object",
        "properties": {
            "service": {"type": "string"},
            "version": {"type": "string"},
            "environment": {
                "type": "string",
                "enum": ["staging", "production"],
            },
        },
        "required": ["service", "version", "environment"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class ToolProposal:
    session_id: str
    turn_id: str
    call_id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class GateDecision:
    disposition: Disposition
    reason: str
    receipt_ref: str | None = None


@dataclass(frozen=True)
class BoundaryResult:
    decision: GateDecision
    tool_result: dict[str, Any]
    executed: bool


class ReceiptGate(Protocol):
    def __call__(self, proposal: ToolProposal) -> GateDecision: ...


ToolExecutor = Callable[[Mapping[str, Any]], Any]


def _as_dict(action: Any) -> dict[str, Any]:
    if hasattr(action, "to_dict"):
        value = action.to_dict()
    elif isinstance(action, dict):
        value = action
    else:
        raise TypeError("required action must be a dict-like Agents API action")
    if not isinstance(value, dict):
        raise TypeError("required action did not convert to a dict")
    return value


def _failure_result(
    action: Mapping[str, Any],
    *,
    disposition: Disposition,
    reason: str,
) -> BoundaryResult:
    decision = GateDecision(disposition=disposition, reason=reason)
    return BoundaryResult(
        decision=decision,
        executed=False,
        tool_result={
            "type": "agent.session.input.tool_result",
            "turn_id": action.get("turn_id", ""),
            "call_id": action.get("call_id", ""),
            "success": False,
            "error": f"OpenLine {disposition}: {reason}",
        },
    )


def handle_function_action(
    session_id: str,
    raw_action: Any,
    receipt_gate: ReceiptGate,
    execute_tool: ToolExecutor,
) -> BoundaryResult:
    """Gate one Agents API required action before any application effect."""
    action = _as_dict(raw_action)

    if action.get("type") != "function_call":
        return _failure_result(
            action,
            disposition="DENY",
            reason="unsupported required-action type",
        )

    if action.get("name") != DEPLOY_RELEASE_TOOL["name"]:
        return _failure_result(
            action,
            disposition="DENY",
            reason="unsupported function",
        )

    arguments = action.get("arguments")
    if not isinstance(arguments, dict):
        return _failure_result(
            action,
            disposition="DENY",
            reason="function arguments must be a JSON object",
        )

    proposal = ToolProposal(
        session_id=session_id,
        turn_id=str(action["turn_id"]),
        call_id=str(action["call_id"]),
        name=str(action["name"]),
        arguments=arguments,
    )
    decision = receipt_gate(proposal)

    if decision.disposition not in {"COMMIT", "QUARANTINE", "DENY"}:
        return _failure_result(
            action,
            disposition="DENY",
            reason="unknown gate disposition",
        )

    if decision.disposition != "COMMIT":
        return BoundaryResult(
            decision=decision,
            executed=False,
            tool_result={
                "type": "agent.session.input.tool_result",
                "turn_id": proposal.turn_id,
                "call_id": proposal.call_id,
                "success": False,
                "error": f"OpenLine {decision.disposition}: {decision.reason}",
            },
        )

    try:
        output = execute_tool(proposal.arguments)
    except Exception as exc:  # no automatic retry after an ambiguous side effect
        return BoundaryResult(
            decision=decision,
            executed=True,
            tool_result={
                "type": "agent.session.input.tool_result",
                "turn_id": proposal.turn_id,
                "call_id": proposal.call_id,
                "success": False,
                "error": f"Tool execution failed: {exc}",
            },
        )

    return BoundaryResult(
        decision=decision,
        executed=True,
        tool_result={
            "type": "agent.session.input.tool_result",
            "turn_id": proposal.turn_id,
            "call_id": proposal.call_id,
            "success": True,
            "output": json.dumps(
                output,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        },
    )


def _event_idempotency_key(session_id: str, turn_id: str, call_id: str) -> str:
    material = f"{session_id}\0{turn_id}\0{call_id}".encode("utf-8")
    return "openline-tool-result-" + hashlib.sha256(material).hexdigest()


def submit_required_actions(
    client: Any,
    session: Any,
    receipt_gate: ReceiptGate,
    execute_tool: ToolExecutor,
) -> list[BoundaryResult]:
    """Handle and submit all currently pending function actions.

    Event-submission idempotency does not make the external side effect
    exactly-once. Real effectors should durably reconcile session/turn/call IDs.
    """
    if session.status != "requires_action":
        return []

    results: list[BoundaryResult] = []
    for raw_action in session.required_actions:
        result = handle_function_action(
            session.id,
            raw_action,
            receipt_gate,
            execute_tool,
        )
        action = _as_dict(raw_action)
        client.beta.agents.sessions.events.create(
            session.id,
            events=[result.tool_result],
            idempotency_key=_event_idempotency_key(
                session.id,
                str(action.get("turn_id", "")),
                str(action.get("call_id", "")),
            ),
        )
        results.append(result)
    return results


def demo_receipt_gate(proposal: ToolProposal) -> GateDecision:
    """Safe demo policy. Replace this with your real Receipt Gate adapter."""
    environment = proposal.arguments.get("environment")
    if environment == "staging":
        return GateDecision(
            "COMMIT",
            "demo policy permits staging only",
            receipt_ref=f"demo:{proposal.call_id}",
        )
    if environment == "production":
        return GateDecision(
            "QUARANTINE",
            "production deployment requires receiver review",
            receipt_ref=f"demo:{proposal.call_id}",
        )
    return GateDecision(
        "DENY",
        "environment is outside the demo policy",
        receipt_ref=f"demo:{proposal.call_id}",
    )


def demo_deploy(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Simulated effect. Replace this function with your consequential action."""
    return {
        "status": "simulated_deployment",
        "service": arguments["service"],
        "version": arguments["version"],
        "environment": arguments["environment"],
    }


def _wait_for_boundary(client: Any, session_id: str, timeout_seconds: float = 60.0) -> Any:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        session = client.beta.agents.sessions.retrieve(session_id)
        if session.status in {"requires_action", "idle", "failed"}:
            return session
        time.sleep(0.5)
    raise TimeoutError(f"session {session_id} did not reach a receiver boundary")


def main() -> int:
    from openai import OpenAI

    model = os.environ.get("OPENAI_AGENT_MODEL")
    if not model:
        raise SystemExit("Set OPENAI_AGENT_MODEL to a model available to your project.")

    client = OpenAI()
    session = client.beta.agents.sessions.create(
        environment={"type": "none"},
        agent={
            "model": model,
            "instructions": (
                "You manage release requests. Use deploy_release when a deployment "
                "is required. Do not claim a deployment succeeded until the tool result returns."
            ),
            "tools": [DEPLOY_RELEASE_TOOL],
        },
        input="Deploy checkout version 2026.09.11 to staging.",
    )

    session = _wait_for_boundary(client, session.id)
    if session.status == "requires_action":
        results = submit_required_actions(
            client,
            session,
            demo_receipt_gate,
            demo_deploy,
        )
        for result in results:
            print(
                result.decision.disposition,
                result.decision.receipt_ref,
                result.tool_result,
            )
        session = _wait_for_boundary(client, session.id)

    print(f"session={session.id} status={session.status}")
    if session.status == "failed":
        print(f"error={session.error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
