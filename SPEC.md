# OpenLine Agents 0.1 Draft

## Purpose

OpenLine Agents connects native OpenAI Agents SDK traces to OLP Wire Canon,
COLE Portable Core, an orthogonal outcome witness, and the Terrynce Curve
controller. Each layer remains separately signed and independently inspectable.

## Capture

`OpenLineTraceProcessor` receives native trace and span lifecycle callbacks.
It commits normalized SDK span exports into an RFC 6962-style Merkle root.
Floating-point telemetry is preserved as exact IEEE-754 hexadecimal tags and
integers outside the JavaScript-safe range are string-tagged before hashing.

Ordinary spans produce only `trace_receipt`. A `coherence_input_receipt`
requires explicit custom spans named `olp.claim`, `olp.evidence`,
`olp.relation`, and optionally `olp.signal`. Invalid typed events produce a
signed structural receipt carrying the validation error.

## Outcome

An `outcome_receipt` references the input `payload_hash` and carries a
pass/fail/review label, optional score, label schema, evidence hash, witness
identifier, observation time, and witness signature. Outcome evidence can stay
local. Its hash travels.

The agent under evaluation is not an orthogonal witness for its own outcome.
The controller requires a pinned `expected_witness_key`; a valid signature from
an unregistered key is rejected.

## Calibration

Calibration consumes records made from a recomputable COLE measurement and a
valid outcome bound to the same input. Training and holdout sets must contain
unique, disjoint input hashes.

The draft fits one threshold each for kappa, epsilon, and delta_hol by minimizing
the caller-weighted count of false accepts and false retries in training. The
controller predicts retry when any threshold is reached. Holdout reporting is
kept separate from fitting.

The signed profile remains `shadow_only` unless:

- the combined corpus meets the caller's minimum and contains at least 500
  unique labeled runs;
- the holdout meets the caller's declared minimum;
- both pass and fail labels exist in holdout;
- false-accept and false-retry rates meet the signed criteria.

No default error budget is invented by this package. The caller signs its
criteria into the profile receipt.

## Controller

The controller compares its calibrated threshold proposal with the orthogonal
outcome. Agreement yields accept or retry. Missing measurements, witness review,
or disagreement yields human review.

Shadow proposals never actuate. Active mode requires a valid profile marked
`eligible_for_activation`, and `VerifiedLoop` still requires caller approval
before a retry. Prompt or context revision is implemented by a caller callback,
not inferred inside the controller.

## Chaining

The second and later COLE measurement receipts reference the preceding Canon
input hash. Controller proposals reference the preceding proposal hash. The
original capture receipts remain immutable.
