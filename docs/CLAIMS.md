# OpenFlight claims, assumptions, and invalidation conditions

Every property OpenFlight claims, what it depends on, how it was checked,
its evidence status, and what would invalidate it. Status vocabulary:
**measured** (host execution produced the number), **simulated**
(QEMU/emulation produced the number — not silicon), **declared only**
(asserted in prose without execution evidence), **static** (analysis of a
built artifact or source text without executing the behavior).

Claims are ordered by dependency: later claims assume earlier ones hold.

**Reproducibility disclosure.** `openflight/repro.py` re-runs the host-side
suite, contract battery, and challenge suites and verifies the tracked JSON
reports, but it does **not** rebuild the ESP-IDF firmware or re-run the
QEMU experiment. The QEMU-derived claims (C1, C2, C4, C8) rest on
tracked artifacts — `results/esp32/numerical_parity.json`
(`qemu_max_abs_err = 3.576e-07`, `qemu_parity_observed = true`),
`results/esp32/numerical_parity.csv`, `results/esp32/stack_highwater.txt`,
`results/esp32/openflight_bench.map`, `results/esp32/idf_size.txt` — and on
the reproducible scenario driver `firmware/esp32/qemu_test.py`. The raw
serial capture `qemu_run.log` was gitignored (`.gitignore` `*.log`) and is
not in the release archive; re-running `qemu_test.py` regenerates it. These
claims are classified as existing reported (simulated) evidence that has
**not** been independently reproduced from this release, pending an
ESP-IDF/QEMU-capable second machine.

---

## C1. Numerical equivalence (generated C++ vs PyTorch)

| Field | Value |
|---|---|
| **Claim** | For the supported model class (feed-forward MLP), generated C++ inference matches the PyTorch reference within a predefined tolerance of 1e-4 on tested inputs. Observed max abs error: 3.576e-07. |
| **Assumptions** | (a) The state-dict loader maps checkpoint tensors to the compiled weights correctly. (b) float32 IEEE-754 semantics hold on the execution target (host and Xtensa: yes; verified by identical results). (c) The test inputs (recorded windows + seeded random normals) exercise representative input space — NOT a proof for all inputs. |
| **Evidence** | `results/esp32/numerical_parity.csv` (200 samples), `results/esp32/numerical_parity.json` (`qemu_max_abs_err = 3.576e-07`, `qemu_parity_observed = true`; boot SELFTEST N=200 + protocol N=50), pytest parity tests (host path), `tests/openflight/test_e2e_pipeline.py` (composed C++ adapter→model vs Python reference, max abs err 3.05e-5). Raw `qemu_run.log` regenerable via `firmware/esp32/qemu_test.py` (not shipped — see reproducibility disclosure). |
| **Status** | simulated (QEMU) + measured (host); tolerance predefined, never relaxed post-hoc. |
| **Invalidated by** | Any tested input exceeding 1e-4 abs error; a weight-mapping bug found in the loader; a compiler flag change (e.g. -ffast-math) altering results; a new model class added without re-establishing parity. |

## C2. Compiler target compatibility (ESP32)

| Field | Value |
|---|---|
| **Claim** | Generated model + adapter sources compile inside an ESP-IDF v5.3.2 application with xtensa-esp-elf-gcc 13.2.0 and link into a bootable image. |
| **Assumptions** | (a) ESP-IDF v5.3.2 and the pinned toolchain are available. (b) The generated code uses only C++ features the target toolchain supports (no exceptions/RTTI — enforced by build flags). |
| **Evidence** | Successful `idf.py build`; `results/esp32/openflight_bench.map`; `results/esp32/idf_size.txt`; `openflight_bench.bin` boots in QEMU. |
| **Status** | measured (build + boot). |
| **Invalidated by** | Toolchain upgrade breaking compilation; ESP-IDF API change; generated-code change that fails the build. |

## C3. Model weight storage footprint

| Field | Value |
|---|---|
| **Claim** | The observer's weights occupy 64,516 bytes in flash, matching the compiler's predicted weight storage exactly. |
| **Assumptions** | (a) Linker map sections attributed to model.cpp are entirely weights (one 4-byte output bias is folded into the literal pool — verified via objdump/nm). (b) No duplicate weight copies exist elsewhere in the image. |
| **Evidence** | `results/esp32/openflight_bench.map` (five named .rodata sections + literal pool); symbol-by-symbol reconciliation in `ESP32_SIM_EVALUATION.md`. |
| **Status** | static (build artifact analysis). |
| **Invalidated by** | Compiler/linker emitting weight copies; model change altering parameter count; alignment padding growth. |

## C4. Protocol correctness (host↔firmware)

| Field | Value |
|---|---|
| **Claim** | The binary protocol (HELLO/CONFIGURE/RUN_TEST/RESULT/ERROR) behaves correctly under valid, corrupted-CRC, unknown-type, premature-CONFIGURE, wrong-size, and truncated-frame conditions. |
| **Assumptions** | (a) QEMU UART faithfully delivers byte streams (framing is verified end-to-end, so gross UART loss would have failed scenarios). (b) The host-side decoder matches the firmware encoder by construction (shared Python source). |
| **Evidence** | `firmware/esp32/qemu_test.py` scenarios A–D (tracked, reproducible driver); run log regenerable via that script (raw `qemu_run.log` not shipped — see reproducibility disclosure). |
| **Status** | simulated (QEMU). |
| **Invalidated by** | Any scenario failing; a framing change without both-side update; silent misbehavior under a new fault type (e.g. mid-frame length corruption — currently: exact-frame receiver, resync requires link reset, documented). |

## C5. Deployment gating (fail-closed on contract mismatch)

| Field | Value |
|---|---|
| **Claim** | Incompatible or invalid sensor/model contract pairs are blocked with specific error codes; inference is never generated or run from a failed contract check. |
| **Assumptions** | (a) The contract checker's logic correctly implements its declared semantics. (b) Contracts are complete enough that a *physically wrong but internally consistent* contract is out of scope — the checker validates declarations against declarations, NOT against physical reality (documented boundary, EVALUATION.md §5.1). (c) **The gate is opt-in**: `openflight deploy` without `--contract`/`--model-contract` records `contract_validation: skipped`, prints a stderr WARNING, and proceeds — this claim applies ONLY when contracts are supplied. (d) Quaternion ordering declarations are now load-bearing (raw_layout order is checked against the declared ordering, E403), but a consistently-wrong labeling remains inside boundary (b). (e) **Task-1 refinements (2026-10-14)**: the model may declare `frame: independent` to assert frame-irrelevance (undeclared frames still block U302; reserved words none/any/invariant are diagnosed E303, never compared as frames); `orientation` admits dimensionless units (projected gravity / direction cosines — E102 still blocks e.g. orientation-in-metres and gyro-in-metres); a quaternion feature with no units key defaults to dimensionless with warning W204 (explicit non-dimensionless units still warn W203; non-quat missing units still blocks E202). Each relaxation is paired with a still-blocked companion test. |
| **Evidence** | `results/contract_battery_report.json` (25/25), `results/heldout_challenge.json` (156/156, 0 false accepts/rejects), `results/independent_challenge.json` (21/21); pytest suite; `tests/openflight/test_reviewer_probes.py` (7 external-review fault classes, all blocked/passed as specified). |
| **Status** | measured (host). Held-out cases were self-generated — NOT independent validation. An external review (2026-10-13) found 7 engine failures (quaternion ordering decorative, model-frame fail-open, no quantity plausibility, normalization crashes, checker/pipeline units disagreement, E201 overload, silent gate skip); all 7 are fixed with regression probes, and the review itself demonstrates why self-generated cases are not independent evidence. |
| **Invalidated by** | Any false accept (invalid contract passing) or false reject (valid contract blocked) found in battery or external review; a bypass path around the gate; checker logic bug found by inspection; deploy without contracts being mistaken for a validated deployment (mitigated by the stderr WARNING and SKIPPED status). |

## C6. Fault-class detection (three-workflow comparison)

| Field | Value |
|---|---|
| **Claim** | Across five predefined semantic fault classes (unit mismatch ×100, undeclared units, feature-layout inconsistency, missing normalization, frame inconsistency): bare export (W1) detects 0/5; steelmanned manual workflow (W2) detects 0/5 but matches reference when correctly configured (err 0.0); OpenFlight (W3) converts or blocks 5/5. Same ×100 unit fault: baseline passes its own self-test with 0.595 std-units silent error; OpenFlight converts ×0.01 or blocks U101. |
| **Assumptions** | (a) The five fault classes and their scoring were predefined before the run (they were — categories fixed in test code, seeds fixed). (b) W2 steelman is genuine (configured correctly it matches reference to 0.0 — demonstrated). |
| **Evidence** | `results/three_workflows.json`, `results/baseline_compare.json`; reproduction log (`workflows: OK 5/5`). |
| **Status** | measured (host). Cases self-generated — external confirmation pending (Phase 2 plan: pre-registered taxonomy, blind generation). |
| **Invalidated by** | A sixth fault class found in practice that W3 misses while claiming coverage; W2 outperforming the stated steelman; scoring-rule drift. |

## C7. Zero-heap generated inference path

| Field | Value |
|---|---|
| **Claim** | The generated `predict()` path contains no heap allocation (no malloc/free/new/delete); activation buffers are stack-resident per the memory plan. |
| **Assumptions** | (a) Source-text scan covers the full generated inference call graph. (b) This claim is scoped to the GENERATED code only — the complete firmware (ESP-IDF, UART driver, FreeRTOS) is NOT claimed heap-free. |
| **Evidence** | Allocation scan in build output ("allocation scan of generated predict path: CLEAN"); generated `model.cpp` source. |
| **Status** | static (source scan) + simulated (runs without heap faults in QEMU). |
| **Invalidated by** | Any heap call appearing in generated code; a codegen change introducing allocation; compiler-internal allocation (not observable in source scan — noted as residual risk). |

## C8. Stack high-water (post-workload, emulated)

| Field | Value |
|---|---|
| **Claim** | Minimum free stack of the main task is 6152 bytes after the 200-window selftest workload, before the protocol loop, in the QEMU-emulated ESP32 build. |
| **Assumptions** | (a) `uxTaskGetStackHighWaterMark(NULL)` returns bytes on this target (verified from ESP-IDF v5.3 source: `portSTACK_TYPE = uint8_t` on Xtensa). (b) QEMU's FreeRTOS scheduling matches silicon closely enough for a functional watermark — NOT a silicon number. |
| **Evidence** | `results/esp32/stack_highwater.txt` (`STACK_HIGHWATER_BYTES=6152`); raw QEMU run log regenerable via `firmware/esp32/qemu_test.py` (`stack:` line; not shipped — see reproducibility disclosure). |
| **Status** | simulated (QEMU). Post-protocol-loop watermark NOT yet measured. |
| **Invalidated by** | Protocol-loop stack use exceeding the selftest high-water (measurement gap, not contradiction); a FreeRTOS config change altering task stack size; silicon measurement differing materially. |

## C9. Freeze integrity

| Field | Value |
|---|---|
| **Claim** | The freeze manifest `results/freeze_v0.1.json` holds 65 SHA-256 hashes (62 `source_files` + 3 `models`) and git head `d0d070a`. Re-verified against the tree on 2026-10-15: 48 files match (45 `source_files` + 3 models), 17 diverge (all documented v0.2 changes), 0 missing. The archived log `reproduction/freeze_v0.1_manifest_verification.log` (run 2026-10-14) reports the source-file subset alone: 62 total, 47 match, 15 changed — a stricter same-day run taken before `docs/REPRODUCE.md` and `tests/openflight/test_heldout_challenge.py` diverged; both runs agree 0 missing. **Correction (2026-10-14): the claimed `openflight-v0.1.tar.gz` archive was never created — the previous claim was unverifiable and is replaced by this manifest verification.** From here, git tags are the freeze mechanism. |
| **Assumptions** | (a) Hash function (SHA-256) is collision-resistant. (b) The manifest itself has not been tampered with since the freeze. |
| **Evidence** | `reproduction/freeze_v0.1_manifest_verification.log` (per-file verification run 2026-10-14, source-file subset) + re-verification of all 65 hashes on 2026-10-15. |
| **Status** | measured (manifest-level). Archive-level clean-extraction reproduction: **not performed — no archive exists**. |
| **Invalidated by** | Any hash mismatch on the 48 currently-matching files; discovery of a later-created archive that disagrees with the manifest. |

## C10. Reproducibility (working tree)

| Field | Value |
|---|---|
| **Claim** | From the v0.2 working tree: `python3 openflight/repro.py` exits 0; **211 passed, 0 skipped** (as of 2026-10-15, v0.2.4-pilot; the former single skip `test_product.py:54` — an E050 torch-missing path — was retired when the contract gate became required-by-default and the no-contracts deploy path stopped reaching the torch gate); all **six** host-check result JSONs regenerate with expected values (parity, battery, independent, heldout, workflows, baseline); the run records `results/evidence.json` with a live result for each of the six host checks it actually runs, plus the interpreter/library/platform environment. **Partial dependency coverage (2026-10-15, probe round 2):** the ESP32 `build` and `qemu` checks cannot run in a host-only tree, so they are recorded as **never run** — never "fresh" — and the claims they back (C1's QEMU half, C2, C3, C4, C7, C8) plus C10's firmware scope are reported by `evidence status` under "claims without live evidence" until a real ESP32 build/qemu run is recorded. A recorded `fail` result is reported **failed** (not fresh) with its claims at risk; parity/build/qemu go **stale** when the python/torch/numpy/platform environment changes, even with no tracked-file change. |
| **Assumptions** | Same dependency assumptions as C9. The working tree has diverged from the freeze by design (v0.2 branch); repro.py's count fix is a v0.2 change. |
| **Evidence** | `results/evidence.json` (live result for each of the six host checks repro.py actually runs, plus environment); `evidence status` reports the ESP32 `build`/`qemu` checks as never-run (they are absent from the record because a host-only tree cannot run them — never "fresh"), which is the honest record, not a defect. The `repro.py` exit code (0) and the suite count above are the reproduction result; the raw log is regenerable by re-running `repro.py` (not shipped). |
| **Status** | measured. |
| **Invalidated by** | Any non-zero exit; count drift without documentation; a check regenerating a different value. |

## C11. Contract importers (draft layer)

| Field | Value |
|---|---|
| **Claim** | `openflight import gym` (obs-space JSON + VecNormalize stats) and `openflight import ros2` (.msg text) generate draft contracts in which every filled field carries provenance (`inferred`/`documented`); `openflight contract confirm` emits a schema-valid clean contract plus a provenance-retaining sidecar; ambiguous names (pos/vel-class) omit fields rather than guess, so the checker stays fail-closed on unresolved drafts. **Strengthened 2026-10-14 (advisor review):** the gym importer cannot emit frame values at all (no laundering of FRD/FLU); W301 clip and the VecNormalize distribution caveat are retained as sidecar `limitations`, not just printed; `confirmed_blanket` fields appear in the sidecar under `not_individually_verified`; the legged_gym golden case is a verbatim transcription of master@8fa29ac (commit hash + file/line in the fixture header), and the PX4 FRD-vs-FLU claim is verified against the live PX4 ROS 2 guide. |
| **Assumptions** | (a) The offline artifacts (obs JSON, VecNormalize stats, .msg text) faithfully represent the deployed system — the importer cannot verify this and labels its inputs `documented`/`inferred`, never `measured`. (b) External golden cases test convention handling, not any specific trained policy. (c) Quaternion ordering is left unconfirmed by import (Eigen/SciPy/MuJoCo disagree) — a confirmed quat feature requires a human-supplied ordering or the schema blocks. (d) A wrongly-confirmed frame (both sides blanket-confirmed under the same name while the true stacks differ) makes the checker pass on declarations alone — the sidecar retains the origin doubt; this is inside the C5(b) declared-vs-physical boundary and is not claimed to be detected. |
| **Evidence** | `tests/openflight/test_draft_layer.py`, `tests/openflight/test_importers.py`; external golden cases with source citations in fixture headers. |
| **Status** | measured (host). |
| **Invalidated by** | A field appearing in an emitted contract without a provenance entry; a confirm emitting a schema-invalid contract; the checker accepting an unconfirmed ambiguous draft; a golden case that should block passing or that should pass blocking; **a provenance sidecar changing after the evidence record without C11 appearing under claims-at-risk** (evidence graph tracks `*.provenance.json` as a claim-level input since v0.2.3-pilot). |

## C12. Evidence graph (staleness detection)

| Field | Value |
|---|---|
| **Claim** | `openflight evidence record` hashes the artifact groups each check reads into `results/evidence.json` (schema v3, including the python/torch/numpy/platform environment); `openflight evidence status` re-hashes and reports exactly the checks whose inputs changed, plus the CLAIMS.md claim ids that depend on them. Globs are expanded against the `--root` argument, never the cwd, so a foreign or partial root fails loudly (`EvidenceGraphError`) instead of silently reporting "all fresh". Mutating one input (weights, a contract unit, one line of checker.py, a challenge test file, generated C++, the firmware binary) stales exactly the checks that read it — verified per-artifact by mutation tests. A check whose recorded result is `fail` reports **failed** (never fresh) with its claims at risk; parity/build/qemu report **stale** when the environment changes. Provenance sidecars (`*.provenance.json`, written by `contract confirm`) are hashed as a **claim-level** input: changing a confirmation or switching a field to blanket confirmation puts C11 under claims-at-risk and makes `evidence status` exit nonzero — without staling any technical check, because no check reads a sidecar. Provenance sidecars and blanket confirmations also appear in status output under unresolved limitations. |
| **Assumptions** | (a) The declared check→artifact dependency map (`openflight/evidence.py`) matches what the checks actually read; a check reading an undeclared artifact is invisible to staleness. (b) Hashes are SHA-256. (c) `repro.py` records evidence only after a fully successful run. |
| **Evidence** | `tests/openflight/test_evidence.py` (7 status/record tests); `tests/openflight/test_evidence_mutation.py` (45 mutation/env/failed-check/provenance/closure-derivation tests); `results/evidence.json` (recorded by each successful repro). |
| **Status** | measured (host). |
| **Invalidated by** | A mutation leaving a dependent check reported fresh; a stale check whose claims are missing from claims_at_risk; the dependency map diverging from what the tests actually read. |

---

## Explicitly NOT claimed (out of scope until evidence exists)

| Non-claim | Would require |
|---|---|
| Physical-device latency, WCET, or stack numbers | Silicon measurements with documented timer/clock configuration |
| Complete-firmware heap-freedom | Link-time and runtime heap tracing of the whole image |
| Zero OOM risk during flight | Full RAM budget accounting + silicon stack high-water under worst-case load |
| Simulation-to-physical sensor correspondence | `verify-observed` runs on public datasets (EuRoC, TUM VI) + user logs (Phase 3) |
| Detection of physically-wrong-but-internally-consistent contracts | Observed-semantics checks (value-range vs declared bounds) — Phase 3 |
| Research novelty vs prior work | Systematic literature comparison — Phase 5 |
| Held-out challenge independence | Externally written cases (Phase 2: pre-registered taxonomy, blind generation) |
| Human-study time savings | Participant study with confidence intervals — Phase 5 |

## Invalidation protocol

1. Any new evidence that contradicts a claim above updates this file in the
   same change: status degrades (measured → declared only) or the claim is
   withdrawn.
2. The claims in this file are the canonical list; prose in other documents
   that exceeds this file is non-normative and should be corrected toward it.
3. Phase 1 (evidence graph) mechanizes this: each claim's evidence nodes are
   hash-pinned; when an input hash changes, dependent claims are marked stale
   until re-verified.

---
Created 2026-10-13, OpenFlight v0.2 working tree. Supersedes ad-hoc claim
statements in prose documents where they differ.
