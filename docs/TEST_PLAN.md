# OpenFlight Test Plan — what is covered, how, and what is missing

Executed 2026-10-11 on host (Apple clang 15, CPython 3.13, torch 2.8):
**33 passed** (`tests/openflight/`) — historical snapshot; the table below
predates several later additions.

Updated 2026-10-13 after external review: **113 passed**; updated 2026-10-14
after Task-1 checker refinements: **125 passed**; after Task-2 draft layer:
**133 passed**; after Task-3 importers: **144 passed**; after the 2026-10-14
advisor-review strengthening round (verbatim legged_gym golden case at
48-dim with honest width accounting, W301/L301 limitations retained in
the sidecar, not_individually_verified listing, gym-importer
frame-laundering impossibility, wrongly-confirmed-frame doubt retention,
ROS xyzw ordering fed through E403/schema): **150 passed**; after the
Phase-1 evidence graph + the 2026-10-15 dependency-true revision
(`test_evidence.py`: schema-v2 record/status with fresh/stale/never-run;
`test_evidence_mutation.py`: per-input mutation staleness table,
import-closure derivation guard, fail-closed checker misuse tests;
torch-present deploy test importorskip-guarded so a torch-free tree
still runs green): **162 passed, 1 skipped**
(`tests/openflight/`, CPython 3.12, torch 2.14). New since the snapshot:
`test_contract_engine.py`, `test_contract_battery.py`, `test_fault_injection.py`,
`test_heldout_challenge.py`, `test_independent_challenge.py`,
`test_three_workflows.py`, `test_baseline_compare.py`, `test_recorded_demo.py`,
`test_product.py`, `test_units_bidirectional.py`, `test_firmware_harness.py`,
the post-review probe suite (`test_reviewer_probes.py`), and the Task-1
refinement suite (`test_frame_independence.py`: `frame: independent`
sentinel, E303 reserved-word diagnosis, dimensionless orientation features,
W204 quaternion units default — each relaxation paired with a still-blocked
companion test), the draft layer (`test_draft_layer.py`: provenance
map with inferred/documented/confirmed/confirmed_blanket statuses,
`confirm` per-field and `--confirm-all` with retained sidecar, omit-on-
ambiguity for pos/vel-class names), and the importers
(`test_importers.py`: gym obs-space + VecNormalize affine mapping with
W301 clip warnings, ROS 2 .msg parsing with REP-103/105 provenance,
CLI wiring with diagnosed malformed input, plus external golden cases —
the legged_gym obs definition transcribed from the public repo must
pass the checker; PX4-FRD vs ROS-FLU frames must block).

Updated 2026-10-15 after the independent v0.2.5-tag audit (three gate
defects reproduced fail-first against the frozen code, schema type
hardening, staged deploys, and the evidence-graph repair round wiring the
e2e check as the eighth host check): **242 passed, 0 skipped**
(`tests/openflight/`, CPython 3.12, torch 2.14).

Updated 2026-10-16 (reproducibility-correction round, fail-first against
the v0.2.6 tree per the RESEARCH_PLAN Stage-1 demonstrated-defect clause):
report-integrity verification in `repro.py` (pre-fixed case inventories,
duplicate identities, seed/schema agreement, summary-vs-cases agreement,
failed-run evidence recording), blocked-render conversion honesty, and
independent-challenge sampling without replacement: **255 passed, 0
skipped** (`tests/openflight/`, CPython 3.12, torch 2.14). The frozen
v0.2.6-pilot archive itself still reports 242; the +13 are new tests, not
edits to the frozen suite. Registered below as R1–R4.

## Coverage map

| Area | Test file | Tests | What they execute |
|---|---|---|---|
| Graph/codegen basics | `test_toolkit.py` | 1 | op order, param count, weight bytes, plan>0, comment-stripped heap grep |
| Unsupported refusal | `test_toolkit.py`, `test_compiler_audit.py` | 6 | Conv1d, BatchNorm1d, GELU, bias-free Linear, functional `F.relu` |
| Per-op + saturation differential | `test_compiler_audit.py` | 2 | linear-only chain (U(-1,1)); relu+tanh+sigmoid chain on U(-100,100) incl. `expf` extremes, assert finite + err<1e-5 |
| Shape validation | `test_compiler_audit.py` | 3 | batch≠1, consecutive dim mismatch, empty graph |
| Memory plan fidelity | `test_compiler_audit.py` | 1 | plan peak 512 B, == sum of buffers, emitted `buf_<id>[N]` sizes match, no dead scratch, header constants match |
| Output aliasing | `test_compiler_audit.py` | 1 | compiled C++ `predict(io,io)` == `predict(io,ref)` |
| Reproducibility | `test_compiler_audit.py` | 1 | compile twice → byte-identical h/cpp/json + manifest SHAs |
| Heap symbols (object) | `test_compiler_audit.py` | 1 | `nm -u model.o`: no malloc/free/calloc/realloc/operator new/delete |
| Runner edge | `test_compiler_audit.py` | 1 | `runs=1` works |
| Adapter math | `test_adapters_audit.py` | 5 | xyzw/wxyz consistency (100), roundtrip (100), orthonormality+det (400), gravity sign (+9.81 on z), 90°-about-z vector |
| Adapter errors | `test_adapters_audit.py` | 1 | zero quat + bad ordering raise |
| Py-vs-C parity | `test_adapters_audit.py` | 1 | 50 deterministic vectors, accel+gyro, atol 2e-6 |
| Contracts | `test_adapters_audit.py` | 2 | bad ordering / missing state / missing units rejected; `check_compat` flags ordering/frame/units mismatches, passes on match |
| Protocol | `test_protocol_audit.py` | 2 | truncation, bad version/CRC, oversize cap, empty payload, stream deframing + leftover, seq gap/replay |
| Statistics/reports | `test_protocol_audit.py` | 2 | known median/min/max/miss-rate; all 7 report files created |

## External-review fault taxonomy (registered 2026-10-13)

An external reviewer probed the engine directly and reproduced 7 failures the
self-generated held-out suite (seed 777001, 156 cases) did not cover. Each is
now a permanent regression in `test_reviewer_probes.py` — kept SEPARATE from
the frozen held-out suite so its 156/156 remains comparable and these entries
are honest post-review additions, not post-hoc suite edits. This is the
independence gap CLAIMS.md C5/C6 documents: self-generated cases are not
independent evidence.

| ID | Fault class | Pre-fix behavior | Post-fix behavior | Code |
|---|---|---|---|---|
| P1 | Sensor quaternion ordering decorative (not checked against raw_layout) | wxyz/xyzw declarations produced identical ops; mislabeled raw passed | raw_layout order must equal declared ordering; permutation auditable in ops | E403 |
| P2 | Model frame missing while sensor documents one | silent pass (fail-open) | blocked as unverifiable | U302 |
| P3 | Unit implausible for quantity (gyro in metres, both sides agreeing) | pass (only cross-comparison done) | blocked per-side | E102 |
| P4 | Malformed normalization (affine w/o scale; scale 0) | KeyError traceback; zero scale accepted | blocked with diagnostics | E201 / E205 |
| P5 | Quaternion feature with no units | checker passed, build_ops KeyError | blocked; diagnosed ValueError | E202 |
| P6 | E201 used for two different faults | one code, one action text | E201 normalization-only, E202 units | E201 / E202 |
| P7 | Deploy without contracts | honest "skipped" record, no console signal | + stderr WARNING, "SKIPPED" not "PASS" in summary | — |

### v0.2.5-tag audit faults (registered 2026-10-15)

An independent advisor audited the frozen v0.2.5-pilot tag and proved three
defects; each was first reproduced as a failing test against the v0.2.5 code,
then fixed. A fourth (traceback) was discovered while probing the third.
Permanent regressions: `test_reviewer_probes.py` (5 audit probes),
`test_contract_battery.py` (checker-misuse rows), `test_contract_engine.py`
(schema rows).

| ID | Fault class | Pre-fix behavior | Post-fix behavior | Code |
|---|---|---|---|---|
| A1 | Sensor and model both declaring an unregistered unit string | gate PASS / PROCEED (units equality checked before any registry lookup; plausibility returns None for unknown tokens) | blocked before equality can count as compatibility; membership gates first | U101 |
| A2 | Duplicate (quantity, component) raw_layout binding | accepted; dict indexing silently dropped the first entry | refused at schema load (CLI E002, no artifacts) and by the checker directly | E002 / E206 |
| A3 | Contract width vs model width (6 features, 60-wide model) | compiled first, blocked last — adapters, manifests and reports already published | caught at the gate before generation; every deployable staged and published only on success, so any non-zero exit leaves exactly the failed report (`result: failed`) | E203 |
| A4 | Weight/arch shape mismatch (keys align, dims do not) | raw torch RuntimeError traceback escaped the CLI | diagnosed E030 exit 3, staging discarded, report `result: failed` | E030 |
| A5 | Malformed schema types (width "three"; units/frame non-string on both sides) | uncaught ValueError from `check()`, or false PROCEED on equal malformed values | structured diagnostics; width → E207, units → U101, frame → E303 | E207 / U101 / E303 |

### Reproducibility-correction defects (registered 2026-10-16)

An independent advisor reviewed the v0.2.6 release verification and proved
three defects in the verification tooling itself (the v0.2.6 results were
correct — these are integrity gaps that could mask a FUTURE regression).
Each was first reproduced as a failing test against the v0.2.6 code, then
fixed. R4 was discovered by the new R1 check against the real report.
Permanent regressions: `test_repro_verifier.py` (11 tests),
`test_contract_battery.py` (2 render tests), `test_independent_challenge.py`
(uniqueness guard inside `test_challenge_rates`).

| ID | Fault class | Pre-fix behavior | Post-fix behavior | Code |
|---|---|---|---|---|
| R1 | Truncated/internally consistent benchmark report (e.g. 1-of-1) | accepted: verify() compared only `summary.n == summary.correct > 0` | rejected against pre-fixed inventories (25/21/156/6), unique case identities, exact seed/schema, and summary-vs-cases/diag agreement | `repro.py` `EXPECTED_REPORTS` |
| R2 | Blocked validation rendering planned conversions | printed "Generated conversions (verified by differential test)" regardless of deployment status | proceed → same header; blocked → "Planned conversions (NOT applied - deployment blocked)" | `checker.py` `render_text` |
| R3 | Failed reproduction run | recorded nothing, leaving the previous success displayed as the current evidence state | records this attempt: each check `ok` only if it reproduced, else `fail` (claims at risk) | `repro.py` `_record` |
| R4 | Independent challenge valid-case sampling (discovered by R1's duplicate check) | 8 i.i.d. draws from 32 combos collided: the v0.2.6 report held 21 cases but only 20 distinct (benign — both copies passed, 21/21 unchanged) | sampled without replacement; generation-side uniqueness guard; frozen archive left untouched and this is disclosed in CHANGELOG | `test_independent_challenge.py` `build_challenge` |

## Deliberately not covered (need hardware or are future work)

1. Target-side timing, linker-map Flash/SRAM, stack high-water mark, on-target
   allocation instrumentation — blocked on hardware (HARDWARE_PLAN.md).
2. Serial transport + device disconnect/incomplete-run handling — no `pyserial`,
   no board; protocol stream helpers are tested, the transport is not built.
3. Unit conversion (contract declares units; nothing converts) — untested because
   unimplemented; this is candidate differentiator B.
4. `deploy --flash` path — prints opt-in notice only; untested by design.
5. Manifest coverage of metadata/contract/vectors (hashes model.h/cpp only).
6. Timer resolution/accuracy characterization beyond labeling the method.
