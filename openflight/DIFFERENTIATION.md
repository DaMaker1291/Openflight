# OpenFlight Differentiation — where the gap vs existing tools actually is

Scope note: assessed from the tools' public documentation and the current
repo state; no new benchmarking of third-party tools was run in this audit.
"Existing" claims below are to be verified hands-on before any publication.

## Overlap (OpenFlight does not currently differentiate here)

| Capability | Existing coverage | OpenFlight status |
|---|---|---|
| MLP→C++ export (Linear/ReLU/…) | TFLM, STM32Cube.AI, ONNX Runtime, hand-rolled exporters (e.g. this repo's `observer_deploy.py`) | Parity at best; smaller op set |
| Host numerical check | Standard practice (any exporter + pytest) | Parity |
| Latency/memory numbers | Cube.AI profiler, TFLM benchmarks, Edge Impulse | Behind: host-only, one board family stub |

Conclusion: competing as "a better exporter" is a losing strategy.

## Candidate gaps (ranked)

### 1. Cross-language sensor-contract validation (B) — RECOMMENDED BET

**Remaining problem.** Exporters verify the *network*; nobody verifies the
*plumbing*: sim outputs xyzw quats while firmware assumes wxyz; velocity in
world frame feeds a model trained on body frame; accelerometer sign convention
flips; feature order/normalization drifts between `train.py` and firmware.
These failures compile, run, and produce plausible-but-wrong control.

**OpenFlight's head start.** Contract schema + validator (`adapters/contracts.py`),
shared Py/C++ generator, deterministic-vector parity harness pattern
(`test_py_vs_c_parity`: 50 vectors, atol 2e-6), mismatch detector
(`check_compat`).

**What is missing to make it real.**
- Generate **unit conversions** from the contract (today: declared, ignored).
- Wire `check_compat` into `deploy` so mismatches fail the pipeline, with the
  sim-side and model-side conventions printed side by side.
- Extend the parity chain to feature ordering + normalization
  (sim state → sensor model → features → network, both languages).
- Negative tests: each mismatch class must be *caught* (test writes wrong-order
  contract, asserts deploy stops with the right message).

**Evaluation.** Fault-injection study: N convention faults × detection rate +
time-to-diagnosis vs manual debugging. This is the study that could justify
adoption and a paper claim.

### 2. Deployment failure diagnosis (A) — second, builds on B

**Remaining problem.** "Output differs from reference" wastes days; the cause
(normalization, ordering, stale weights, quantization) is found by hand.

**Proposal (evidence-only).** Diagnose *only* what tests support: range check
each feature against training stats → "feature 4 out of range" style reports;
never guess. Each diagnostic rule ships with a fault-injection test proving
precision/recall on that fault class.

**Evaluation.** Time-to-diagnosis on injected faults, OpenFlight vs baseline.

### 3. Reproducible hardware benchmarking (C) — table stakes, not the lead

Manifests + raw CSV + timer/method labels are good practice (already shipped).
Valuable combined with B (a repro bundle that includes the contract + vectors),
weak alone — several vendors already do per-board profiling better.

## Ranked next steps (no GRU/LSTM until #1–#3 are done)

1. **Real-MCU validation** of the current slice (HARDWARE_PLAN.md) — without it,
   everything above is host-side claims.
2. **Contract gap closure**: unit conversion + `check_compat` in `deploy` +
   mismatch fault-injection tests (the B vertical slice).
3. **Evidence-only diagnostics** for the fault classes B already detects (A).
4. **Time-saving study** (3 tasks × 3 workflows, hands-on time + correctness +
   diagnosis time) — only after 1–2, else there is nothing real to measure.
5. Operator expansion (GRU/LSTM/Conv1D) — *only* when user demand from 1–4
   requires it.
