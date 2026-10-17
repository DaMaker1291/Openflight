# OpenFlight Technical Report: fail-closed contract validation for embedded neural inference

Status: host-validated prototype, frozen as **v0.1** (`results/freeze_v0.1.json`:
65 hashes = 62 `source_files` + 3 `models`, dependency versions, git head).
**97/97 tests pass** in the frozen snapshot suite (**266 passed, 0 skipped**
in the current v0.2.7.dev0 working tree: 97 frozen + product-quality, external-review
probe, Task-1 refinement, draft-layer, importer, advisor-review strengthening,
evidence-graph, v0.2.5-audit regression, end-to-end composed-path,
v0.2.6 reproducibility-correction, and first-divergence-diagnosis tests
added since the freeze).
The former single skip (`test_product.py:54`, an E050 path) was retired when
the contract gate became required-by-default; with torch installed nothing
is skipped.
No on-silicon measurements exist anywhere in this report.
*(Correction 2026-10-14: no frozen v0.1 archive was ever created; the
freeze that actually exists and is verified is the manifest
`results/freeze_v0.1.json` — 65 SHA-256 hashes, not 62. Re-verified against
the original repo tree on 2026-10-15: 48 files unchanged (45 source files +
3 models), 17 diverged as documented
(`reproduction/freeze_v0.1_manifest_verification.log` is the stricter
2026-10-14 source-file-subset run: 47/62 unchanged, 15 diverged — the 2
file delta is `docs/REPRODUCE.md` and `test_heldout_challenge.py`, which
diverged after that log ran). Git tags are the
freeze mechanism going forward.)*

## 1. Research question and hypothesis

> To what extent can automated sensor-contract validation detect semantic
> input incompatibilities in neural-network robotics deployments, compared
> with bare export and manually configured deployment workflows?

Hypothesis: a workflow that validates machine-readable sensor contracts will
detect or block a greater proportion of declared semantic input
incompatibilities than workflows that verify model computation without
equivalent automated contract checks, while preserving numerical equivalence
for valid configurations. Independent variables: workflow, fault category.
Outcomes: detection, false acceptance/rejection, diagnostic correctness,
numerical deviation. No human-time claims: no human study has been run.

## 2. Method

- Models: disturbance-observer MLP (12→64→64→3), trained gust observer
  (`learned_observer.pt`, 60→128→64→1), PPO policy encoder (656→256→128,
  LayerNorm — must-reject case).
- Inputs: uniform sweeps, saturation sweeps, RECORDED physics rollouts
  (dev: step gust 22.3 m/s seed 7; second: turbulent 15 m/s seed 999, heavy
  noise, different airframe).
- Faults: predefined categories; seeded battery (20261011); independent
  challenge (seed 999, different feature space); held-out challenge
  (seed 777001, ~150 generated variations, predefined scoring); 10
  hand-written regression faults.
- Baselines on identical faults: (W1) bare export + golden self-test,
  (W2) careful manual preprocessing + shape assert (steelmanned: matches the
  reference to 0.0 when configured correctly — the comparison measures
  *detection*, not arithmetic), (W3) OpenFlight gate + generated pipeline.
- Firmware: `firmware/generic/benchmark_main.cpp` behind `hal.h`, executed
  unmodified against `firmware/host_sim/` over the real binary protocol.

## 3. Results

Parity (torch vs compiled C++): 7.45e-08 uniform; 1.79e-07 observer uniform;
4.77e-07 over 300 recorded dev windows; second dataset <1e-4;
firmware-over-pipes 3.58e-07 over 200 recorded windows.

Contract validation: dev battery 25/25; independent challenge 21/21;
**held-out 156/156** (valid 60/60, invalid 64/64 with named diagnostics,
ambiguous 32/32 fail-closed); PPO/LayerNorm refused naming the operator;
34 bidirectional unit tests (both directions, roundtrips).

Three-workflow matrix (`results/three_workflows.json`): on 5 semantic fault
classes W1 detects 0/5 and W2 detects 0/5, while W3 converts-or-blocks 5/5
(×0.01 generated op, U101, E402, E201, E301). Control (corrupt checkpoint):
all three refuse — the comparison is not rigged.

Firmware harness (`results/firmware_harness.json`): HELLO/CONFIGURE gating,
RUN_TEST-before-CONFIGURE, size mismatch, CRC corruption, unknown type all
answered with ERROR, link alive; dead link exits nonzero without hanging;
predict-only latencies observed p50=6µs p95=7µs max=26µs (host-sim ONLY —
not MCU evidence, not WCET bounds). Cross-compile: CI configured
(`.github/workflows/openflight.yml`); local toolchain absent so
`firmware/check_cross.sh` reports SKIP; sources compile warning-free under
`-Wall -Wextra -fno-exceptions -fno-rtti` with the host compiler.

## 4. Failed cases and bugs found (preserved, not hidden)

- Firmware/host header mismatch (8 vs 10 bytes, `<BBHIH` u32 length): the
  live harness caught it on first contact. Fixed; covered thereafter.
- Accel ÷9.8 lie: only 0.0035 std-units of corruption on this model —
  assumed-material, empirically negligible. The ×100 variant (0.595) carries
  the blind-spot demonstration instead.
- PPO rejection test first failed on checkpoint key names before reaching the
  LayerNorm path; the arch now mirrors the real module names so the refusal
  exercised is the genuine one.
- Held-out `cc` vs `<cstdio>` portability slip in a test driver (macOS):
  switched to `<stdio.h>`; firmware itself is unaffected.

## 5. Limitations (what OpenFlight cannot do)

1. **Declaration vs reality.** The checker compares declarations with
   declarations. A consistently-lying sensor contract passes validation and
   corrupts outputs (pinned by `test_declaration_reality_gap_documented`).
   Layers: contract compatibility (built) / compiled behavior on verified
   inputs (built) / physical-interface truth (REQUIRES external calibration).
2. **No silicon.** No MCU, no cross-toolchain in this environment. Host-sim
   executes the exact firmware logic but proves nothing about DWT/ccount
   timers, linker maps, or stack high-water marks.
3. **Held-out authorship.** Seeds are published and scoring was predefined,
   but the generator is author-written; true external review is outstanding.
4. **Deferred scope.** Frame-transform synthesis, GRU/LSTM, new targets, and
   time-saving claims stay deferred until 1–2 are measured.
5. **Test-space limits.** 97 passing tests measure consistency with the suite,
   not real-world reliability.

## 6. Reproducing (for the independent reviewer)

Prerequisites: Python 3.11+, `torch`/`numpy`/`pytest`, host `c++`/`cc`,
the three model files; no network/MCU/toolchain. Steps:
`git clone`, optionally verify `openflight/freeze.py` hashes against
`results/freeze_v0.1.json`, then `python3 openflight/repro.py` — expected
final line `REPRODUCTION OK` (verified this environment).
Full instructions + failure-reporting checklist: `docs/REPRODUCE.md`.
Hardware run when available: `docs/HARDWARE_PLAN.md`.
