# openline-agents

Signed OLP capture, outcome-grounded calibration, and shadow control for the OpenAI Agents SDK.

> **Builders wanted:** OpenLine needs its first useful surfaces: a receipt viewer, GitHub issue/PR exporter, discovery UI, or agent wrapper. Build one small connector and own the surface. Start here: [Build OpenLine Connectors](https://github.com/terryncew/openline-agents/issues/1).

OpenLine is for portable proof across AI handoffs.

A log stays inside the stack. A receipt travels with the user.

`openline-agents` attaches through the OpenAI Agents SDK trace processor interface. Ordinary generations, tool calls, handoffs, and guardrails produce a structural `trace_receipt`. Explicit `olp.*` custom spans produce a hash-bound `coherence_input_receipt` and disclosure that COLE Portable Core can measure.

The package never infers claims or evidence from ordinary model text. Raw evidence can stay local. The receipt preserves what crossed the boundary.

## Why this exists

AI agents are starting to act across tools, teams, vendors, and institutions.

That creates a simple problem: the important part of the run often disappears at the handoff.

Who made the claim? What evidence supported it? Which tool call mattered? What outcome came back? Which system accepted the next step?

OpenLine receipts are small portable records for those crossings.

The goal is not to centralize every trace.

The goal is to let proof move.

## Build on OpenLine

The primitive is here. The app layer is open.

Useful first surfaces:

### Receipt Viewer

Drop in a receipt JSON and render a clean card:

- claim
- evidence
- action or outcome
- issuer
- timestamp
- parent chain
- verification status

Bonus: parent-chain view, signature check, embeddable card, dark mode.

### GitHub Issue / PR Connector

Turn an issue, pull request, or review into an OpenLine receipt.

Useful outputs:

- export as OpenLine receipt
- attach receipt to issue comment
- capture claim, change, test, reviewer, and outcome
- preserve parent issue or PR link

### Discovery UI

Create an Opportunity Pack and export a receipt.

The form should capture:

- claim
- falsifier
- measurable KPI
- cheapest credible witness
- expected test window
- result or outcome

### Agent Wrapper

Wrap an agent run so a portable receipt is created at the handoff.

Useful outputs:

- receipt for a tool call
- receipt for an agent-to-agent handoff
- receipt for a human-review escalation
- receipt for a verified outcome

Want to build one? Start with the issue: [Build OpenLine Connectors](https://github.com/terryncew/openline-agents/issues/1).

## Example receipt

A minimal handoff receipt lives at:

```text
examples/simple-handoff.receipt.json
```

The basic shape is:

```json
{
  "schema": "openline.receipt.v1",
  "type": "handoff_receipt",
  "id": "olr_demo_001",
  "created_at": "2026-06-25T00:00:00Z",
  "issuer": {
    "type": "agent",
    "name": "research-agent-demo",
    "id": "agent_demo_research"
  },
  "handoff": {
    "from": "research-agent-demo",
    "to": "review-agent-demo",
    "boundary": "agent_to_agent"
  },
  "claim": {
    "text": "The linked source supports the claim that AI agent handoffs need portable verification records.",
    "confidence": 0.78
  },
  "evidence": [
    {
      "type": "url",
      "label": "source_document",
      "value": "https://example.com/source"
    }
  ],
  "action": {
    "type": "handoff",
    "summary": "Research agent passed a claim and supporting source to a review agent."
  },
  "outcome": {
    "status": "pending_review",
    "summary": "Receipt created before review so downstream systems can verify what crossed the boundary."
  },
  "parents": [],
  "verification": {
    "signature": "demo_unsigned",
    "hash": "demo_hash_pending",
    "status": "demo"
  }
}
```

## What the loop does

```text
agent run
  -> signed Canon input
  -> COLE measurement
  -> externally witnessed outcome
  -> shadow controller proposal
  -> caller-approved revision
  -> next signed measurement linked to the prior input
```

The controller proposes `accept`, `retry`, or `human_review`.

Shadow mode never executes a retry without a caller-supplied approval callback. Context revision is also supplied by the caller. The package does not silently rewrite prompts.

## Install

```bash
python -m pip install \
  "git+https://github.com/terryncew/cole-portable-core.git@v0.1.0-draft" \
  "git+https://github.com/terryncew/openline-agents.git"
```

## Attach capture

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from agents import add_trace_processor
from openline_agents import OpenLineTraceProcessor

processor = OpenLineTraceProcessor(Ed25519PrivateKey.generate())
add_trace_processor(processor)
```

Adding the processor preserves the SDK's default OpenAI trace exporter.

Use `set_trace_processors([processor])` only when you intend to replace it.

## Emit explicit coherence input

Use these helpers inside the same Agents SDK trace:

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

Only content hashes enter the portable graph. Raw evidence remains local.

## Orthogonal outcomes

Calibration labels come from a separate witness: tests, a human decision, a schema check, or an observed environment result.

The agent cannot sign its own outcome as an external witness.

Every controller proposal requires an explicit trusted witness public key. A valid outcome signed by any other key is rejected.

```python
from openline_agents import Outcome, issue_outcome_receipt

outcome = Outcome(
    label="pass",
    score_micros=1_000_000,
    label_schema_id="ci.pass-fail.v1",
    evidence_hash=sha256(test_output).hexdigest(),
    witness_id="ci-test-suite",
    observed_at_unix_micros=observed_at,
)

receipt = issue_outcome_receipt(bundle.receipt, outcome, witness_key)
```

## Self-service calibration

`verified_record(...)` accepts only recomputable COLE measurements and outcomes bound to the same signed input.

Training and holdout corpora must be disjoint.

`issue_calibration_profile(...)` fits deterministic per-metric thresholds and reports false-accept and false-retry rates on the held-out records.

A profile remains `shadow_only` until all caller-declared gates pass and the combined corpus contains at least 500 unique labeled runs.

Eligibility still requires an explicit choice to operate the controller in active mode.

## Current boundary

This is a draft surface for signed capture and shadow control.

Current limits:

- workflow improvement, not model-weight training
- COLE and the orthogonal witness remain separate inputs
- a failed outcome and a metric disagreement escalate to human review
- the adapter preserves provisional/self-attested Canon trust labels
- production routing, distributed collection, and hosted calibration are outside this draft

See [`SPEC.md`](./SPEC.md) for signed artifacts and activation rules.

## Verify the release

```bash
python -m unittest discover -s tests -v
python scripts/generate_vectors.py
node verify-node.mjs
```

The fixed vectors cover the signed witness outcome, calibration profile, and controller proposal.

The independent Node verifier accepts all three and rejects a tampered proposal.

## Builder rule

Small receipts. Big accountability.

Build one connector.

Keep it portable.

Leave proof at the handoff.

## License

MIT
