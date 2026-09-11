# openline-agents

Receiver-owned control for OpenAI agents.

Use OpenLine with the OpenAI Agents SDK or the managed Agents API. The agent can propose a tool call. Your application decides whether that exact action is authorized before the effect occurs.

There are two integration paths:

- **Managed Agents API:** put OpenLine Receipt Gate in the custom-function handler or in an MCP receiver you control. OpenAI manages the session; your receiver decides whether the proposed effect may happen.
- **OpenAI Agents SDK:** keep using the existing `OpenLineTraceProcessor` to capture portable signed receipts from SDK traces.

The existing SDK integration is unchanged. The managed Agents API path is an application-side receiver pattern, not a replacement for the SDK trace processor.

## Agents API Receiver Boundary

The managed Agents API can pause a session in `requires_action` and expose pending function calls. That is the receiver boundary.

```text
OpenAI Agents API
        |
  proposed tool call
        |
        v
OpenLine Receipt Gate
        |
 COMMIT / QUARANTINE / DENY
        |
        v
 consequential function
        |
 tool result -> Agents API
```

OpenAI owns the managed session mechanics. OpenLine belongs immediately before the effect your application controls.

For a custom function call, the receiver gets the proposed `turn_id`, `call_id`, function name, and JSON arguments. Send that exact proposal through Receipt Gate.

- `COMMIT` -> execute the consequential function, then submit a successful `agent.session.input.tool_result`.
- `QUARANTINE` -> do not execute the function; submit a failed tool result explaining that receiver review is required.
- `DENY` -> do not execute the function; submit a failed tool result explaining that the receiver refused the action.

The tool result copies the original `turn_id` and `call_id` back to the managed session.

A complete example lives at:

```text
examples/agents_api_receiver_boundary.py
```

It defines one custom function tool, `deploy_release`, creates a managed session, waits for `requires_action`, routes the exact proposal through an injected Receipt Gate callback, executes only on `COMMIT`, and submits the result through:

```python
client.beta.agents.sessions.events.create(
    session_id,
    events=[tool_result],
    idempotency_key=...,
)
```

The example uses a safe demo gate and a simulated deployment. Replace those two functions with your real OpenLine Receipt Gate adapter and your real effect.

For real side effects, persist or reconcile `(session_id, turn_id, call_id)` at the receiver. The Agents API idempotency key can deduplicate event submission; it does not prove that an external side effect did or did not already happen.

### Run the managed API example

Install a current OpenAI Python client, set your API key and a model available to your project, then run:

```bash
python -m pip install -U openai
export OPENAI_API_KEY=...
export OPENAI_AGENT_MODEL=...
python examples/agents_api_receiver_boundary.py
```

The example deliberately does not add the managed Agents API client as a package dependency. `openline-agents` still supports its existing Agents SDK integration without forcing SDK users onto a different runtime.

### MCP receiver path

The same boundary applies when you own the MCP receiver:

```text
Agents API -> MCP call -> your MCP server -> Receipt Gate -> effect
```

Gate the exact call before your MCP server causes the consequential effect.

This repo does not claim to intercept hosted tools or effects that your application does not mediate.

## Agents SDK trace capture

For applications running the OpenAI Agents SDK directly, the existing trace-processor path remains available.

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from agents import add_trace_processor
from openline_agents import OpenLineTraceProcessor

processor = OpenLineTraceProcessor(Ed25519PrivateKey.generate())
add_trace_processor(processor)
```

Adding the processor preserves the SDK's default OpenAI trace exporter.

Use `set_trace_processors([processor])` only when you intend to replace it.

Ordinary generations, tool calls, handoffs, and guardrails produce a structural `trace_receipt`. Explicit `olp.*` custom spans can produce the older coherence-research artifacts described below.

The package never infers claims or evidence from ordinary model text. Raw evidence can stay local. The receipt preserves what crossed the boundary.

## Portable receipts

A log stays inside a stack. A receipt can travel with the user.

OpenLine receipts are intended to preserve the evidence needed at a handoff: what was proposed, what was accepted, what happened, who issued the record, and what earlier record it depends on.

A minimal handoff receipt lives at:

```text
examples/simple-handoff.receipt.json
```

The Agents API receiver example is different: it shows where to make the consequential decision before a custom function runs.

## Existing SDK integration

The existing Agents SDK trace processor remains in the repository unchanged. It still uses the legacy `cole-portable-core` dependency that backed the original signed-capture and calibration work.

That dependency is separate from the managed Agents API receiver example above. The managed example does not import `openline_agents` or require COLE; it only needs a current OpenAI Python client.

If your environment already has access to the legacy COLE dependency, the existing SDK trace-processor path remains available. This update does not repackage or replace that older dependency.

## Experimental research surface

The COLE/calibration and shadow-controller work remains in the repository, but it is not the product front door.

That experimental surface includes:

- explicit `olp.*` custom spans for claims, evidence, relations, and signals
- outcome receipts from an orthogonal witness
- deterministic calibration profiles
- shadow controller proposals such as `accept`, `retry`, or `human_review`
- caller-approved context revision

Those components are retained for research and compatibility. They do not replace receiver-owned authorization at the effect boundary.

Use these helpers inside an Agents SDK trace when you are intentionally working with the research surface:

```python
from openline_agents import claim, evidence, relation, signal

with claim("claim_1", "The tool completed the requested change"):
    pass

with evidence("evidence_1", test_output_bytes):
    pass

with relation("evidence_1", "claim_1", "supports"):
    pass

with signal(0, 240_000, "my-agent.normalized-signal.v1"):
    pass
```

Only content hashes enter that portable graph. Raw evidence remains local.

Calibration labels come from a separate witness such as tests, a human decision, a schema check, or an observed environment result. The agent cannot sign its own outcome as an external witness.

`verified_record(...)`, `issue_calibration_profile(...)`, and the shadow controller remain available for that experimental work. See [`SPEC.md`](./SPEC.md) for the signed artifacts and activation rules.

## Verify

```bash
python -m unittest discover -s tests -v
python scripts/generate_vectors.py
node verify-node.mjs
```

The Agents API receiver tests specifically prove that:

- the gate sees the exact proposed function arguments and call identity
- `COMMIT` is the only disposition that invokes the consequential function
- `QUARANTINE` and `DENY` return tool-result failures without invoking the function
- the submitted tool result preserves the managed session's `turn_id` and `call_id`

## License

MIT
