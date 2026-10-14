# OpenFlight v0.1 — Literature and Novelty Assessment (research brief, not a claim)

Scope: PhD-level research requires an original contribution to knowledge.
This brief locates OpenFlight against verified prior work, states the
narrowest defensible novelty claim, and lists what would invalidate it.
It is a starting brief for a full systematic review, not the review itself.
No v0.1 source files were modified to write it.

## Verified related work (sources checked October 2026)

| Work | What it does | What it does not do (gap relevant to OpenFlight) |
|---|---|---|
| Lewis, Bellomo & Ozkaya 2021, "Characterizing and Detecting Mismatch in ML-Enabled Systems" (WAIN@ICSE; arXiv:2103.14101) + SEI TEC mismatch-detection tool | Interview/survey taxonomy of ML mismatches across data-science/SE/ops roles; machine-readable JSON-Schema descriptors; design-time stakeholder alignment analysis | No fail-closed deployment gate; no generated cross-language sensor adapters; not scoped to embedded robotics sensor semantics (units/frames/orderings) |
| Warden et al. 2022, "Machine Learning Sensors" (arXiv:2206.03266) + Stewart et al. 2023 ML-sensor datasheet framework | Sensor-2.0 paradigm: self-contained ML sensors with datasheets documenting hardware, model, dataset, and end-to-end performance for transparency/auditability | Documentation paradigm, not automated checking: nothing verifies a declaration against a model's expectations, blocks deployment, or generates adapter code |
| MLGuard (arXiv:2309.01379, 2023): contracts + generated wrappers | Design-by-contract for ML with pre/post conditions; generates runtime wrappers that detect *probabilistic* violations (drift, miscalibration) via validation models | Targets runtime probabilistic violations via learned validators, not static semantic compatibility (units/frames) with exact generated conversions; no embedded deployment gate |
| Edge Impulse (DSP blocks, normalization option, BYOM, deployment metadata) | Bundles tested DSP + normalization config into the deployable impulse; estimates latency/RAM/flash; publishes deployment metadata | Correctness of the preprocessing/training match rests on developer diligence (docs example: config "should match the params used to preprocess before training"). No automated check that deployed preprocessing matches the training contract; no fail-closed semantic gate |
| TFLite / EON, STM32Cube.AI, ONNX Runtime | Model conversion, optimization, on-device runtimes, profiling | Numerical/operator compatibility, not semantic input compatibility |

## Narrowest defensible novelty claim (to be tested, not asserted)

The combination, for resource-constrained robotics deployment, of:
1. machine-readable physical/representational input semantics (units, frames,
   orderings, normalization) on BOTH the sensor and model sides;
2. a fail-closed compatibility gate that refuses deployment on incompatibility
   or unverifiability (including the ambiguous/unknown cases, U-codes);
3. exact generated Python+C++ adapters for the declared transformations;
4. a pre-registered empirical evaluation (detection / false-accept /
   false-reject / diagnostic accuracy vs. bare-export and careful-manual
   baselines on identical faults).

Each element exists elsewhere in some form; the claim is about the
combination applied to this problem, plus the measured detection gap
(5/5 semantic fault classes escape both baselines in our experiments).
Whether that combination is sufficiently original is for the literature
review + independent scrutiny to decide — not for this brief to declare.

## What would invalidate or shrink the claim

- A prior system that already gates embedded deployment on machine-checked
  sensor semantics AND generates the adapters (strongest invalidator).
- Evidence that the 5/5-vs-0/5 gap is an artifact of weak baselines (e.g., a
  careful-manual workflow with its own validation step catching them — which
  would mean the contribution is "automation of diligence" rather than
  "detection others miss"; still useful, but a smaller claim).
- Independent cases showing high false-accept rates outside our distributions.
- The declaration-vs-reality boundary (EVALUATION.md §5.1) already bounds the
  claim: consistently-lying declarations pass. Any novelty statement must
  carry this boundary.

## Reviewer brief (what independent review should do)

1. Reproduce: `openflight/repro.py` from the v0.1 archive
   (`openflight/SNAPSHOT_v0.1.md`).
2. Adversarial cases: new valid/invalid/ambiguous contracts WITHOUT reading
   `test_heldout_challenge.py` internals; report false accepts/rejects, wrong
   diagnostics. Probe especially: same-dimension unit swaps that SHOULD pass,
   near-miss frames, and consistently-false declarations.
3. Literature check: confirm or refute the table above; name any system that
   already does 1–4 combined. A single concrete counterexample outweighs
   pages of test counts.
4. Do not test: on-silicon behavior (out of scope for this bundle),
   engineering time (unmeasured by design).

## Status of the three advances

1. Original contribution: BRIEFED here, NOT established — needs the systematic
   review + reviewer verdict.
2. Generality: initial evidence (21-case independent set, 156-case held-out,
   second model/dataset) but author-generated; external cases outstanding.
3. Practical significance: host-sim only; silicon + human study outstanding
   by design. Nothing in this file changes that.
