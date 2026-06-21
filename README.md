# openline-agents

Signed OLP capture, outcome-grounded calibration, and shadow control for the
OpenAI Agents SDK.

`openline-agents` attaches through the SDK's native trace processor interface.
Ordinary generations, tool calls, handoffs, and guardrails produce a structural
`trace_receipt`. Explicit `olp.*` custom spans produce a hash-bound
`coherence_input_receipt` and disclosure that COLE Portable Core can measure.

The package never infers claims or evidence from ordinary model text.

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

The controller proposes `accept`, `retry`, or `human_review`. Shadow mode never
executes a retry without a caller-supplied approval callback. Context revision
is also supplied by the caller; the package does not silently rewrite prompts.

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

Adding the processor preserves the SDK's default OpenAI trace exporter. Use
`set_trace_processors([processor])` only when you intend to replace it.

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

Calibration labels come from a separate witness: tests, a human decision, a
schema check, or an observed environment result. The agent cannot sign its own
outcome as an external witness.

Every controller proposal requires an explicit trusted witness public key. A
valid outcome signed by any other key is rejected.

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

`verified_record(...)` accepts only recomputable COLE measurements and outcomes
bound to the same signed input. Training and holdout corpora must be disjoint.
`issue_calibration_profile(...)` fits deterministic per-metric thresholds and
reports false-accept and false-retry rates on the held-out records.

A profile remains `shadow_only` until all caller-declared gates pass and the
combined corpus contains at least 500 unique labeled runs. Eligibility still
requires an explicit choice to operate the controller in active mode.

## Current boundary

- This is workflow improvement, not model-weight training.
- COLE and the orthogonal witness remain separate inputs.
- A failed outcome and a metric disagreement escalate to human review.
- The adapter preserves provisional/self-attested Canon trust labels.
- Production routing, distributed collection, and hosted calibration are
  outside this draft.

See [SPEC.md](SPEC.md) for the signed artifacts and activation rules.

## Verify the release

```bash
python -m unittest discover -s tests -v
python scripts/generate_vectors.py
node verify-node.mjs
```

The fixed vectors cover the signed witness outcome, calibration profile, and
controller proposal. The independent Node verifier accepts all three and
rejects a tampered proposal.
