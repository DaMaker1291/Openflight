# OpenFlight claims, assumptions, and invalidation conditions

Every property OpenFlight claims, what it depends on, how it was checked,
its evidence status, and what would invalidate it. Status vocabulary:
**measured** (host execution produced the number), **simulated**
(QEMU/emulation produced the number — not silicon), **declared only**
(asserted in prose without execution evidence), **static** (analysis of a
built artifact or source text without executing the behavior).

Claims are ordered by dependency: later claims assume earlier ones hold.

---

## C1. Numerical equivalence (generated C++ vs PyTorch)

| Field | Value |
|---|---|
| **Claim** | For the supported model class (feed-forward MLP), generated C++ inference matches the PyTorch reference within a predefined tolerance of 1e-4 on tested inputs. Observed max abs error: 3.576e-07. |
| **Assumptions** | (a) The state-dict loader maps checkpoint tensors to the compiled weights correctly. (b) float32 IEEE-754 semantics hold on the execution target (host and Xtensa: yes; verified by identical results). (c) The test inputs (recorded windows + seeded random normals) exercise representative input space — NOT a proof for all inputs. |
| **Evidence** | `results/esp32/numerical_parity.csv` (200 samples), `results/esp32/qemu_run.log` (boot SELFTEST N=200 + protocol N=50), `results/esp32/numerical_parity.json`, pytest parity tests (host path). |
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
| **Evidence** | `firmware/esp32/qemu_test.py` scenarios A–D; `results/esp32/qemu_run.log`. |
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
| **Evidence** | `results/esp32/stack_highwater.txt`, `results/esp32/qemu_run.log` (`stack:` line). |
| **Status** | simulated (QEMU). Post-protocol-loop watermark NOT yet measured. |
| **Invalidated by** | Protocol-loop stack use exceeding the selftest high-water (measurement gap, not contradiction); a FreeRTOS config change altering task stack size; silicon measurement differing materially. |

## C9. Freeze integrity

| Field | Value |
|---|---|
| **Claim** | The freeze manifest `results/freeze_v0.1.json` (62 source-file SHA-256s, dependency versions, model hashes, git head `d0d070a`) verifies against the tree: 47 files unchanged, 15 diverged (exactly the documented v0.2 changes), 0 missing. **Correction (2026-10-14): the claimed `openflight-v0.1.tar.gz` archive was never created — the previous claim was unverifiable and is replaced by this manifest verification.** From here, git tags are the freeze mechanism. |
| **Assumptions** | (a) Hash function (SHA-256) is collision-resistant. (b) The manifest itself has not been tampered with since the freeze. |
| **Evidence** | `reproduction/freeze_v0.1_manifest_verification.log` (per-file verification run 2026-10-14). |
| **Status** | measured (manifest-level). Archive-level clean-extraction reproduction: **not performed — no archive exists**. |
| **Invalidated by** | Any hash mismatch on the 47 unchanged files; discovery of a later-created archive that disagrees with the manifest. |

## C10. Reproducibility (working tree)

| Field | Value |
|---|---|
| **Claim** | From the v0.2 working tree: `python3 openflight/repro.py` exits 0; 144/144 tests pass; all seven result JSONs regenerate with expected values. |
| **Assumptions** | Same dependency assumptions as C9. The working tree has diverged from the freeze by design (v0.2 branch); repro.py's count fix is a v0.2 change. |
| **Evidence** | `reproduction/workingtree_reproduction.log`. |
| **Status** | measured. |
| **Invalidated by** | Any non-zero exit; count drift without documentation; a check regenerating a different value. |

## C11. Contract importers (draft layer)

| Field | Value |
|---|---|
| **Claim** | `openflight import gym` (obs-space JSON + VecNormalize stats) and `openflight import ros2` (.msg text) generate draft contracts in which every filled field carries provenance (`inferred`/`documented`); `openflight contract confirm` emits a schema-valid clean contract plus a provenance-retaining sidecar; ambiguous names (pos/vel-class) omit fields rather than guess, so the checker stays fail-closed on unresolved drafts. |
| **Assumptions** | (a) The offline artifacts (obs JSON, VecNormalize stats, .msg text) faithfully represent the deployed system — the importer cannot verify this and labels its inputs `documented`/`inferred`, never `measured`. (b) External golden cases (legged_gym obs definition, PX4-FRD vs ROS-FLU frames) are transcriptions of public conventions; they test convention handling, not any specific trained policy. (c) Quaternion ordering is left unconfirmed by import (Eigen/SciPy/MuJoCo disagree) — a confirmed quat feature requires a human-supplied ordering or the schema blocks. |
| **Evidence** | `tests/openflight/test_draft_layer.py`, `tests/openflight/test_importers.py`; external golden cases with source citations in fixture headers. |
| **Status** | measured (host). |
| **Invalidated by** | A field appearing in an emitted contract without a provenance entry; a confirm emitting a schema-invalid contract; the checker accepting an unconfirmed ambiguous draft; a golden case that should block passing or that should pass blocking. |

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
