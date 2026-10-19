# Competitor gap analysis (scoped)

**Status:** 2026-10-19, post-freeze research note. Static source inspection, not
an execution comparison. Frozen evaluation revision remains
`6c64b16` (tag `eval-frozen-2026-10-19`).

Inspected revisions (shallow clones):

- PAL Robotics `pal_policy_deployer` — `3198c2d2a1dba19caa27e73fb390ef95a2a08d87` (2026-08-21)
- Eximius Labs `efferent` — `f51e1af953afe1016dae9ceeff2b5328fa51781d` (2026-08-05)

Method: read README, runtime/source, tests and startup checks. Neither
repository was executed; dependency-heavy paths (ROS 2, MuJoCo) were not run.
Treat this as a source-level gap list, not a benchmark result.

## What each tool actually does

| Capability | PAL `pal_policy_deployer` | Efferent | OpenFlight |
|---|---|---|---|
| Deployment structure | ROS 2 preprocessor → inferer → postprocessor | `.app` manifest + robot descriptor → ONNX runtime | PyTorch → generated C++ + firmware |
| Observation ordering | Child class builds order; startup checks sizes only | Name-bound joints; permuted-block detection and audit | Contract layout with offsets; generated adapter |
| Units / frames / scale | None beyond sizes | Deg-vs-rad, world-vs-body, missing/extra scale, sign, one-step lag | Unit conversions, order, sample offsets, affine normalization |
| Reference replay | None | ONNX session vs recorded `obs`/`actions` | PyTorch reference vs deployed C++ |
| Diagnoses compiled artifact | No | No (ONNX Runtime only) | Yes (compiled `predict` compared to PyTorch) |
| Stage-wise first divergence | No | Per-term obs audit + separate doctor checks | `preprocessing → model → end_to_end` |
| Invalid evidence | Throws | Raises on missing log keys; PASS/WARN/FAIL | Structured rejection, no attribution |
| Evidence bundle | None | Printed report / dataclasses | `report.json`, `summary.md`, `reproduce.py`, hashes |
| Tests | None found | Extensive (order, frame, scale, lag, replay, audit, simprobe) | Extensive (suite 300) |

## Evidenced gaps

### G1 — Compiled-artifact parity is not covered

Efferent's "deployment pipeline" is ONNX Runtime, not generated firmware:
`src/efferent/runtime/policy.py:9,19` imports `onnxruntime` and constructs
`ort.InferenceSession`; the doctor uses the same session
(`src/efferent/doctor.py:210-214`). Its replay check compares recorded actions
through that ONNX session (`src/efferent/doctor.py:678-707`). PAL likewise runs
ONNX Runtime (`pal_policy_inferer/src/onnx.cpp:23-24`) and only checks tensor
dimensions.

OpenFlight generates C++ (`openflight/compiler/codegen.py:29-117`) and compares
the compiled `predict` against the PyTorch reference in the `model` stage
(`openflight/diagnose.py:36,117-121`). A codegen, dtype, weight-layout or
integration fault that leaves the ONNX path correct is outside both
competitors' evidence.

**Boundary:** this is demonstrated for host-side generated C++; QEMU/embedded
results remain emulation, not physical hardware.

### G2 — Emulated embedded execution is not addressed

PAL targets ROS 2 nodes; Efferent targets ONNX/MuJoCo/DDS. Neither has a
firmware build or emulated execution path. OpenFlight has one, but QEMU is not
a physical measurement and must be reported as emulated.

### G3 — Cross-stage first divergence is not established

Efferent audits observation terms (`src/efferent/audit.py:1-30`) and probes the
network separately. It does not run the same recorded window through
preprocessing, compiled inference and end-to-end in one pass and report the
earliest divergence. OpenFlight does (`openflight/diagnose.py:117-154,538-570`).

### G4 — No reproducible evidence bundle or validity taxonomy

Efferent reports are dataclasses printed by the CLI
(`src/efferent/doctor.py:37-58`; `src/efferent/cli.py:245-250`); there is no
artifact hash set, replay script or bundle. Missing log keys raise; policy
defects return PASS/WARN/FAIL. OpenFlight writes `failing_inputs.npz`,
`reference_values.npz`, `deployed_values.npz`, `artifact_manifest.json`,
`summary.md`, `reproduce.py` and records bundle SHAs
(`openflight/diagnose.py:749-791`), and returns structured invalid-evidence
rejections. Efferent does contain a partial "not inferable" response
(`src/efferent/doctor.py:358`), so abstention is not binary absent.

### G5 — Fault interaction / tolerance-edge is untested by both

No test in either repository composes individually tolerable errors into an
end-to-end divergence, or studies masking pairs. This is the research gap in
`docs/RESEARCH_POSITIONING.md`, not a product claim.

## Where OpenFlight is not differentiated

Do not claim novelty for checks Efferent already performs and tests:

- joint-order permutations (`tests/test_doctor_zero_config.py`, `tests/test_audit.py`)
- world-vs-body frames and missing/extra scale (`tests/test_audit.py`)
- degrees-vs-radians, sign inversion, one-step lag
  (`tests/test_030_fixes.py:204,215,226`)
- replay of recorded observations/actions through the deployed ONNX path
  (`src/efferent/doctor.py:678`)
- modular preprocessing/inference/postprocessing and observation-order metadata
  (PAL README; `preprocessor_tiago_reaching.cpp:113,150-161`)

These should appear in the new benchmark as **non-differentiating controls**:
if OpenFlight loses on them, that is a real regression, not a trade-off.

## One demonstration that is hard to dismiss

Scenario (to be built, not claimed yet):

1. Train/keep a tiny observer; export the same weights to ONNX for Efferent and
   to OpenFlight's C++ codegen.
2. Run Efferent `doctor --reference` (and, where applicable, PAL startup
   checks): it passes, because the ONNX path and normalization agree.
3. Plant a fault only on the compiled path, e.g. de-normalize twice, transpose
   a weight matrix, or apply the wrong activation in generated C++.
4. Run OpenFlight `diagnose`: it should report `model` (compiled inference) as
   the first divergence, name the failing sample, and emit a bundle whose
   `reproduce.py` replays the result.
5. Correct the codegen; `diagnose` agrees; the bundle for step 4 still replays.

Falsifiers: if Efferent's checks also catch the planted fault (they should not,
since they never execute the C++), the gap is not real; if OpenFlight's `model`
stage does not diverge, the fault is not in compiled inference; if the bundle
does not replay on a second machine, G4 fails.

## Benchmark arms implied by the gaps

- Existing-workflow baseline: Efferent doctor/audit on the ONNX path; PAL
  startup checks where the pipeline is ROS-based.
- End-to-end numerical diff only.
- Contracts-only (OpenFlight deploy gate, no diagnosis).
- Full OpenFlight.
- Forced-choice (no abstention) and always-abstain controls.

Case families: compiled-inference faults (G1/G3), emulated execution (G2,
clearly labelled), artifact/version mismatch, malformed evidence (G4),
interaction/tolerance-edge (G5), plus Efferent-covered semantic faults as
controls.

## Limits

- Source-level only; versions are shallow clones and may move.
- Efferent is ONNX/robot-policy-oriented; OpenFlight is PyTorch/embedded. The
  comparison is about **coverage of the deployment path**, not equivalent
  inputs.
- PAL is a deployment framework, not a diagnostic tool; treating it as a
  baseline means "the checks its users get for free", not a like-for-like
  doctor.
- No conclusion here about researcher demand or time savings.
