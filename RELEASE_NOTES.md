# openline-agents v0.1.0-draft

This first draft connects the OpenAI Agents SDK to portable OpenLine receipts,
COLE Portable Core measurements, externally witnessed outcomes, self-service
calibration, and a shadow-first Terrynce Curve controller.

Controller decisions pin outcomes to an explicitly trusted witness public key;
valid signatures from other keys are rejected.

The controller can propose `accept`, `retry`, or `human_review`. It cannot retry
silently. Active mode requires a signed calibration profile that passes a
disjoint holdout test with at least 500 unique labeled runs, and every retry
still requires caller approval and a caller-supplied revision function.

Verification:

- 18 deterministic Python tests pass locally, with one native-SDK integration
  test reserved for GitHub Actions.
- The real OpenAI Agents SDK integration runs in GitHub Actions.
- An independent Node verifier accepts the Python-signed outcome, calibration,
  and controller vectors.
- Signature tampering, corpus leakage, duplicate-run inflation, unknown fields,
  and uncalibrated active control are rejected.

Trust remains explicitly provisional/self-attested except for separately signed
orthogonal outcomes. This draft improves workflows; it does not train model
weights or infer semantic claims from ordinary model text.
