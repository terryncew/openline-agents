"""Minimal OpenAI Agents SDK workflow with an external witness and shadow retry."""

from __future__ import annotations

import asyncio
import hashlib
import time

from agents import Agent, function_tool
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from openline_agents import (
    AsyncVerifiedLoop,
    OpenAIAgentsExecutor,
    OpenLineTraceProcessor,
    Outcome,
    claim,
    evidence,
    relation,
    signal,
)


@function_tool
def deterministic_check(candidate: str) -> str:
    """Return PASS only when the candidate contains the required token."""
    result = "PASS" if "OPENLINE" in candidate.upper() else "FAIL"
    with claim("claim_check", "The deterministic check passed", material=True):
        pass
    with evidence("evidence_check", result, observed=True):
        pass
    with relation("evidence_check", "claim_check", "supports"):
        pass
    for index, value in enumerate((100_000, 120_000, 110_000, 115_000, 105_000)):
        with signal(index, value, "example.normalized-signal.v1"):
            pass
    return result


class CheckWitness:
    """A deterministic result source separate from the agent's self-report."""

    def evaluate(self, output: object) -> Outcome:
        text = str(output)
        passed = "PASS" in text.upper()
        return Outcome(
            label="pass" if passed else "fail",
            score_micros=1_000_000 if passed else 0,
            label_schema_id="example.check.pass-fail.v1",
            evidence_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            witness_id="deterministic-check",
            observed_at_unix_micros=time.time_ns() // 1_000,
        )


async def main() -> None:
    processor = OpenLineTraceProcessor(Ed25519PrivateKey.generate())
    agent = Agent(
        name="OpenLine example",
        instructions="Use deterministic_check. Return its exact result.",
        tools=[deterministic_check],
    )
    loop = AsyncVerifiedLoop(
        OpenAIAgentsExecutor(agent, processor),
        CheckWitness(),
        measurement_key=Ed25519PrivateKey.generate(),
        witness_key=Ed25519PrivateKey.generate(),
        controller_key=Ed25519PrivateKey.generate(),
        max_attempts=2,
        mode="shadow",
        approve_retry=lambda proposal: proposal.action == "retry",
        revise=lambda prompt, proposal, result: f"{prompt}\nPrevious external check failed. Include OPENLINE.",
    )
    result = await loop.run("Run the deterministic check on: openline")
    for attempt in result.attempts:
        print(attempt.number, attempt.controller_proposal["action"], attempt.bundle.receipt["payload_hash"])
    processor.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
