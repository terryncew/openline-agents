"""A bounded, receipt-producing agent improvement loop."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cole_portable_core.receipt import issue_measurement_receipt

from .capture import CaptureBundle, OpenLineTraceProcessor
from .controller import ControllerProposal, propose
from .outcome import Witness, issue_outcome_receipt


@dataclass(frozen=True)
class ExecutionResult:
    output: Any
    bundle: CaptureBundle


class Executor(Protocol):
    def __call__(self, prompt: str, attempt: int) -> ExecutionResult: ...


class AsyncExecutor(Protocol):
    async def run(self, prompt: str, attempt: int) -> ExecutionResult: ...


@dataclass(frozen=True)
class Attempt:
    number: int
    prompt: str
    output: Any
    bundle: CaptureBundle
    measurement_receipt: dict[str, Any] | None
    outcome_receipt: dict[str, Any]
    controller_proposal: dict[str, Any]


@dataclass(frozen=True)
class LoopResult:
    attempts: tuple[Attempt, ...]

    @property
    def final(self) -> Attempt:
        return self.attempts[-1]


class VerifiedLoop:
    """Runs only the retries explicitly approved by the caller."""

    def __init__(
        self,
        executor: Executor,
        witness: Witness,
        *,
        measurement_key: Ed25519PrivateKey,
        witness_key: Ed25519PrivateKey,
        controller_key: Ed25519PrivateKey,
        max_attempts: int,
        mode: str = "shadow",
        calibration_profile: dict[str, Any] | None = None,
        core_profile: dict[str, Any] | None = None,
        approve_retry: Callable[[ControllerProposal], bool] | None = None,
        revise: Callable[[str, ControllerProposal, ExecutionResult], str] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.executor = executor
        self.witness = witness
        self.measurement_key = measurement_key
        self.witness_key = witness_key
        self.controller_key = controller_key
        self.max_attempts = max_attempts
        self.mode = mode
        self.calibration_profile = calibration_profile
        self.core_profile = core_profile
        self.approve_retry = approve_retry or (lambda _: False)
        self.revise = revise

    def run(self, prompt: str) -> LoopResult:
        attempts: list[Attempt] = []
        previous_bundle: CaptureBundle | None = None
        previous_proposal_hash: str | None = None
        current_prompt = prompt
        for number in range(1, self.max_attempts + 1):
            executed = self.executor(current_prompt, number)
            bundle = executed.bundle
            outcome = self.witness.evaluate(executed.output)
            outcome_receipt = issue_outcome_receipt(bundle.receipt, outcome, self.witness_key)
            measurement = None
            if bundle.disclosure is not None:
                kwargs: dict[str, Any] = {}
                if previous_bundle is not None and previous_bundle.disclosure is not None:
                    kwargs.update(previous_input_receipt=previous_bundle.receipt, previous_disclosure=previous_bundle.disclosure)
                if self.core_profile is not None:
                    kwargs["profile"] = self.core_profile
                measurement = issue_measurement_receipt(bundle.receipt, bundle.disclosure, self.measurement_key, **kwargs)
            proposal = propose(
                measurement,
                outcome_receipt,
                bundle.receipt,
                self.controller_key,
                calibration_profile=self.calibration_profile,
                mode=self.mode,
                previous_proposal_hash=previous_proposal_hash,
            )
            attempt = Attempt(number, current_prompt, executed.output, bundle, measurement, outcome_receipt, proposal.receipt)
            attempts.append(attempt)
            previous_bundle = bundle
            previous_proposal_hash = proposal.receipt["payload_hash"]
            if proposal.action != "retry" or number == self.max_attempts or not self.approve_retry(proposal):
                break
            if self.revise is None:
                raise ValueError("an approved retry requires a caller-supplied revision function")
            current_prompt = self.revise(current_prompt, proposal, executed)
        return LoopResult(tuple(attempts))


class OpenAIAgentsExecutor:
    """Single-flight async adapter around ``agents.Runner.run``."""

    def __init__(self, agent: Any, processor: OpenLineTraceProcessor, *, workflow_name: str = "OpenLine agent loop") -> None:
        try:
            from agents import add_trace_processor
        except ImportError as exc:  # pragma: no cover - real SDK gate covers this path
            raise RuntimeError("install openai-agents to use OpenAIAgentsExecutor") from exc
        self.agent = agent
        self.processor = processor
        self.workflow_name = workflow_name
        self._lock = asyncio.Lock()
        add_trace_processor(processor)

    async def run(self, prompt: str, attempt: int = 1) -> ExecutionResult:
        from agents import Runner, trace

        async with self._lock:
            before = {item.agent_trace_id for item in self.processor.store.all()}
            with trace(self.workflow_name, metadata={"openline.attempt": attempt}):
                result = await Runner.run(self.agent, prompt)
            self.processor.force_flush()
            created = [item for item in self.processor.store.all() if item.agent_trace_id not in before]
            if len(created) != 1:
                raise RuntimeError(f"expected one completed trace, received {len(created)}")
            return ExecutionResult(result.final_output, created[0])


class AsyncVerifiedLoop:
    """Async counterpart used with ``OpenAIAgentsExecutor``."""

    def __init__(
        self,
        executor: AsyncExecutor,
        witness: Witness,
        *,
        measurement_key: Ed25519PrivateKey,
        witness_key: Ed25519PrivateKey,
        controller_key: Ed25519PrivateKey,
        max_attempts: int,
        mode: str = "shadow",
        calibration_profile: dict[str, Any] | None = None,
        core_profile: dict[str, Any] | None = None,
        approve_retry: Callable[[ControllerProposal], bool] | None = None,
        revise: Callable[[str, ControllerProposal, ExecutionResult], str] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.executor = executor
        self.witness = witness
        self.measurement_key = measurement_key
        self.witness_key = witness_key
        self.controller_key = controller_key
        self.max_attempts = max_attempts
        self.mode = mode
        self.calibration_profile = calibration_profile
        self.core_profile = core_profile
        self.approve_retry = approve_retry or (lambda _: False)
        self.revise = revise

    async def run(self, prompt: str) -> LoopResult:
        attempts: list[Attempt] = []
        previous_bundle: CaptureBundle | None = None
        previous_proposal_hash: str | None = None
        current_prompt = prompt
        for number in range(1, self.max_attempts + 1):
            executed = await self.executor.run(current_prompt, number)
            bundle = executed.bundle
            outcome_receipt = issue_outcome_receipt(bundle.receipt, self.witness.evaluate(executed.output), self.witness_key)
            measurement = None
            if bundle.disclosure is not None:
                kwargs: dict[str, Any] = {}
                if previous_bundle is not None and previous_bundle.disclosure is not None:
                    kwargs.update(previous_input_receipt=previous_bundle.receipt, previous_disclosure=previous_bundle.disclosure)
                if self.core_profile is not None:
                    kwargs["profile"] = self.core_profile
                measurement = issue_measurement_receipt(bundle.receipt, bundle.disclosure, self.measurement_key, **kwargs)
            proposal = propose(
                measurement, outcome_receipt, bundle.receipt, self.controller_key,
                calibration_profile=self.calibration_profile, mode=self.mode,
                previous_proposal_hash=previous_proposal_hash,
            )
            attempts.append(Attempt(number, current_prompt, executed.output, bundle, measurement, outcome_receipt, proposal.receipt))
            previous_bundle = bundle
            previous_proposal_hash = proposal.receipt["payload_hash"]
            if proposal.action != "retry" or number == self.max_attempts or not self.approve_retry(proposal):
                break
            if self.revise is None:
                raise ValueError("an approved retry requires a caller-supplied revision function")
            current_prompt = self.revise(current_prompt, proposal, executed)
        return LoopResult(tuple(attempts))
