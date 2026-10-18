# Changelog

All notable changes to OpenFlight. Versions follow `0.2.x-pilot`; the tag
named here is the version the supervised pilot runs against.

## Unreleased (0.2.7.dev0) — reproducibility corrections (2026-10-16)

NOT a pilot release (prereg gates not yet complete — see
PILOT_PREREGISTRATION). Corrections proved by an independent advisor's
review of the v0.2.6 release verification: the v0.2.6 *results* were
correct, but the verification tooling had integrity gaps that could mask a
future regression. Each defect was first reproduced as a test failing
against the v0.2.6 code, then fixed (TEST_PLAN R1–R4). The frozen
v0.2.6 tag/archive stay untouched.

- **R1 (high) — repro.py accepted truncated reports.** `verify()` compared
  only self-reported `summary.n == summary.correct > 0`; a synthetic 1-of-1
  battery report verified OK. Now checked against pre-fixed case
  inventories (battery 25, independent 21, heldout 156, importers 6), unique
  case identities, exact seed/schema_version, and summary-vs-cases
  (n/correct/diag) agreement. `test_repro_verifier.py` (11 tests).
- **R2 (medium) — blocked validation presented conversions as approved.**
  `render_text` printed "Generated conversions (verified by differential
  test)" even when deployment was BLOCKED. Blocked reports now show
  "Planned conversions (NOT applied - deployment blocked)". 2 render tests.
- **R3 — a failed reproduction left prior evidence standing.** Failed runs
  recorded nothing, so the previous successful record remained displayed as
  current. `repro.py` now records this attempt: each check `ok` only if it
  reproduced this run, otherwise `fail` (claims at risk).
- **Lockfile comment** corrected from "v0.2.5-pilot / 221 passed" to its
  actual verification history (v0.2.6-pilot, 242 passed; re-verified on
  Python 3.13.2 from release bytes).
- **R4 (discovered by R1) — the v0.2.6 independent-challenge report held
  21 cases but only 20 distinct.** The valid section drew 8 i.i.d. samples
  from a 32-combo space and one collided (the two copies were identical and
  both passed — every score and total unchanged, benign, but a real
  integrity defect). Sampling is now without replacement with a
  generation-side uniqueness guard. **The frozen v0.2.6 archive retains the
  duplicate — disclosed here rather than silently re-cut.**
- Suite: **242 → 255 passed, 0 skipped** (13 new tests; existing tests
  gained assertions only). Version 0.2.6 → **0.2.7.dev0** (dev marker; no
  0.2.7 release until the prereg gates and pilot complete).

**New (2026-10-17) — `openflight diagnose`, the first feature under
Amendment 2** (narrow authorisation: one feature, fail-first, recorded
single-controller path; RESEARCH_PLAN Stage-1 row). Locates the *first*
point where a deployed pipeline diverges from its recorded reference by
comparing three stages in order — `preprocessing` (generated
`contract_adapt` C++ vs recorded `model_inputs`), `model` (compiled C++
`predict` vs PyTorch on the same inputs), `end_to_end` (composed C++ path
vs recorded outputs) — over a recorded raw trace.

- **CLI** `openflight diagnose --model --trace --reference --build
  --output [--rtol --atol]` (defaults 1e-4/1e-4, matching deploy/benchmark
  parity). Exit codes: **0** agree, **2** usage/invalid input, **3**
  harness compile failure (E054), **4** discrepancy reproduced. Errors
  E051 (trace), E052 (reference), E053 (build), E054 (harness), E057
  (width); non-finite values always diverge.
- **Failure bundle** on divergence: `failing_inputs.npz`,
  `reference_values.npz`, `deployed_values.npz`, `artifact_manifest.json`,
  `report.json` (with bundle SHAs + absolute input paths), `summary.md`
  (with the "not established — numerical agreement only" disclaimer), and
  `reproduce.py` (default self-check re-deriving the recorded first
  divergence; `--full` re-runs the diagnosis from original artifacts).
  A rerun over an existing report writes `post_fix_comparison.json`
  (`resolved`/`regression`); a passing run removes stale bundle members.
- **Fail-first**: the new tests were run against the tree before the
  module existed (ImportError — red for the right reason), then the
  corruption test locally a ×100 gain fault in the generated adapter and
  the engine had to return exit 4 with
  stage `preprocessing` / feature `acc_x` / row 0 / col 0 / ratio 100.
- Suite: **255 → 266 passed** (11 new tests, including a three-condition
  demonstration: agree → corrupted disagrees+bundle+`reproduce.py` →
  corrected agrees with `resolved: true`). ruff scoped baseline unchanged
  at 38. No planner/policy, sensor-contract, metric, or evaluation code
  changed; v0.2.6 stays frozen.

**Correction (2026-10-17) — `reproduce.py` integrity and faithful
reproduction** (branch `fix/reproduction-integrity`, base `e8187af`; found
by the reviewer's source review of the challenge round, not a new feature).
The generated `reproduce.py` verified only the model/trace/reference hashes
and compared only the overall status, so a changed deployment build that
kept `status=discrepancy` but moved the first divergence (e.g.
`preprocessing`→`model`) was reported as a faithful `MATCH`. A tampered
report (a later divergent cell, or a status contradicting the saved
evidence) was also accepted. Fixed to establish four properties:

- **Full artifact integrity** — before a `--full` rerun, verify every
  recorded source *and deployment* artifact (the build directory hashes the
  report already recorded) are unchanged; a changed build is refused
  (`deployment artifact changed since diagnosis`).
- **Faithful reproduction** — re-run with the *recorded* tolerances and
  compare the full diagnosis (status, first-divergence stage/feature/sample/
  element/values, and every stage status), not merely the overall status.
- **Independent reconstruction** — the self-check recomputes the first
  divergence from the saved stage arrays in stage order using the recorded
  tolerances (the bundle now stores the full stage arrays, not a failing
  subset, plus the manifest in its hashes), rather than trusting the
  recorded cell.
- **Adversarial regression tests** (`test_diagnose_challenge.py`) prove the
  corrected mechanism rejects a moved-divergence build, a report pointing to
  a later cell, a report contradicting the saved evidence, a changed build
  under `--full`, changed tolerances (reruns reuse the recorded ones), and
  modified bundle members. The original failing regression test is kept.

Suite: **266 → 280 passed** on this branch (14 challenge tests; the
released `test_diagnose.py` unchanged and still green). ruff scoped baseline
38. `e8187af` remains frozen; v0.2.6 and its archive untouched. Pending
independent verification before this becomes the new candidate.

**Follow-up correction (2026-10-17) — bundle metadata consistency**
(reviewer source review). `self_check()` took its tolerances from
`report.json` and never checked them against the separately recorded,
hash-protected `artifact_manifest.json`; changing only the report's
tolerances (or other duplicated metadata) was accepted as long as the same
first divergence reconstructed. Fixed: the self-check now (a) requires every
field the report duplicates from the manifest — `schema_version`,
`created_at`, `openflight_version`, `tolerances`, `inputs`, `shapes` — to
match the manifest, and (b) re-derives each stage's agree/diverge status
from the saved arrays so a tampered per-stage status is rejected. Three new
fail-first tests (`test_self_check_rejects_altered_report_tolerances`,
`..._altered_stage_status`, `..._altered_report_shapes`) were red before the
fix and green after. Suite **280 → 283 passed**; ruff scoped baseline 38;
`repro.py` → `REPRODUCTION OK`. `e8187af` frozen; no other behaviour changed.

**Follow-up correction (2026-10-17) — overall status validation**
(reviewer source review). `self_check()` special-cased `status == "agree"`
and let every other value fall through the discrepancy path, so an
unsupported status (e.g. `"tampered"`) was accepted when the evidence
genuinely diverged. The self-check now rejects any status outside
`{"agree", "discrepancy"}` and requires the overall status to agree with the
reconstructed evidence. Fail-first test
`test_self_check_rejects_unsupported_status` was red before, green after;
two further tests confirm a valid discrepancy bundle and a coherent agree
bundle still pass. Suite **283 → 286 passed**; ruff scoped baseline 38;
`repro.py` → `REPRODUCTION OK`. This is the last planned change to the
diagnosis mechanism absent a new concrete defect found by independent
verification.

### Trained-controller fault-localisation experiment (2026-10-18)

First experiment milestone (replacing further verification work): a genuinely
trained controller (`learned_observer.pt`, MLP 60→128→64→1, trained by
`learned_observer.py`) is deployed through the real `openflight deploy`
pipeline, and five realistic deployment faults plus a clean control are
injected — accelerometer unit mismatch, gyroscope unit mismatch, feature-order
swap, preprocessing gain error, compiled-inference bias.
`experiments/trained_controller/experiment.py` records a reference from the
clean adapter + trained model, runs `openflight diagnose` and a hand-written
staged comparison (the baseline a researcher would script), and writes
`results.json` + `REPORT.md`. Result (SIMULATED, host-side): both localise
5/5 faults to the correct stage, 0 false diagnoses on the control, diagnosis
reproducible; the scripted baseline is faster on raw compute (≈0.5s vs ≈2.0s
median), so the advantage is engineering (bundle, exit-code contract,
reproducibility), not accuracy — stated rather than hidden.
`tests/openflight/test_trained_controller_experiment.py` (2 tests). Suite
**286 → 290 passed**; ruff scoped baseline 38. No physical-robot validation.
## v0.2.6-pilot (2026-10-15) — candidate after the independent v0.2.5 audit

Fixes defects an independent advisor proved by black-box testing the frozen
v0.2.5-pilot archive. v0.2.5 stays untouched (tag → `7c34899`, SHA-256
`e3829303…b20f`); every fix below was reproduced as a test failing against
v0.2.5 code first, then made to pass.

- **P0 — unknown units passed the semantic gate.** The checker compared the
  sensor's and model's unit strings *before* consulting the registry, so
  both sides declaring `units: mystery_unit` matched, `validate` exited 0
  and a full deploy succeeded (parity is numerical, not physical). Registry
  membership now gates first (`checker.py`: `U.dimension(su)`/`U.dimension(mu)`
  None → **U101** with both tokens in the reason). Regression:
  `test_contract_battery.py::test_check_blocks_matching_unknown_units` +
  probe `test_audit_v025_unknown_equal_units_blocked`.
- **P1 — duplicate `raw_layout` bindings were accepted.** A duplicated
  `(quantity, component)` pair silently overwrote the earlier position in
  the checker's dict (arbitrary choice on an ambiguous mapping). Now
  refused twice: schema load raises (`model_contract.py` → CLI **E002**,
  no artifacts) and the checker reports **E206** when handed the dict
  directly. Tests: battery + engine-schema dup rows, probe
  `test_audit_v025_duplicate_raw_layout_refused`.
- **P1 — failed deploys left generated artifacts behind.** The 6-vs-60
  width mismatch was detected only *after* adapter/manifest generation;
  the advisor observed generated C++ and manifests surviving an exit-2
  block. `cmd_deploy` was restructured: all preconditions (model exists,
  arch check, torch, contract load/schema/gate incl. an **early width
  check** `checker.check(sensor, model, model_input_size=…)`) run before
  anything is generated; everything else runs in an `<output>.staging`
  directory published (shas recorded) only after parity passes. Any
  non-zero exit leaves exactly `deployment_report.json`, now carrying
  `"result": "failed"` (`stages.py::to_dict`), `artifact_shas: {}` on
  discards, and a limitation note. Probes:
  `test_audit_v025_width_mismatch_no_artifacts`,
  `test_audit_v025_late_failure_no_artifacts`.
- **P1 — shape mismatch escaped as a raw traceback.** Torch's
  `RuntimeError` (keys align, dims don't) bypassed the CLI's
  `OpenFlightError`-only handler. Caught in `cmd_deploy` → **E030** exit 3,
  staging discarded. Probe `test_audit_v025_shape_mismatch_diagnosed_not_traceback`.
- **Schema hardening (malformed types → structured errors, never
  exceptions or false PROCEED)**: non-string feature `width` → new
  **E207** (guards both width-sum and per-feature parse; suppresses the
  misleading E203); non-string `units` on either side → U101;
  non-string/non-null `frame` → **E303**. 10 fail-first schema/misuse
  battery+engine tests.
- **Evidence graph repairs** (all with both-side mutation tests — stale set
  AND every unrelated check fresh): new **e2e** check wired to its test
  source, `results/e2e_pipeline.json`, the weights, and the
  cli/compiler/checker sources, backed by **C1**; new `evidence_source`
  group on *every* check (editing `openflight/evidence.py` itself stales
  everything — documented over-approximation); `build` now reads
  `learned_observer.pt`, `learned_observer.py`, the CLI, package root and
  generated C++; `qemu` now reads fixtures, the CLI, the benchmark
  protocol and the flash/efuse images (`qemu_runtime`, optional);
  environment (python/torch/numpy/platform) staleness extended to e2e
  (`ENVIRONMENT_DEPENDENT`). 60 mutation tests.
- **Report/repro correctness**: `n_within_registered_abs_tol` now counts
  only the registered band (was mixing all bands, against its name); new
  `n_within_abs_tol_all` (284/300) and an `environment` block in
  `results/e2e_pipeline.json`; `repro.py` gained the e2e entry + verify
  branch (previously the report was cited but never checked) and its
  banner now reads the live `__version__` instead of "v0.1".
- **Host checks: eight** (parity, battery, independent, heldout,
  workflows, baseline, importers, e2e). Suite: **242 passed, 0 skipped**;
  `REPRODUCTION OK` with all eight checks; `evidence status` exit 0
  (build/qemu honestly "never run").
- Docs (CLAIMS C1/C5/C10/C12, TEST_PLAN, PILOT_PROTOCOL, REPRODUCE,
  EVALUATION) updated to 242/0, eight checks and the v0.2.6-pilot
  designation.

## v0.2.5-pilot (2026-10-15) — final pilot tag (code freeze)

**This is the frozen pilot release. No code changes land during the pilot
sessions.** Defects found by participants are recorded and fixed after the
pilot, never in the artefact the participants are using.

- **End-to-end composed-path test expanded 8 → 300 samples** across four
  input bands (registered envelope ±500, extremes ±100 m/s² and
  ±1000 rad/s, near-zero, patterned extremes), with an error decomposition
  recorded in `results/e2e_pipeline.json`:
  - unit-scale constants (e.g. 0.01 in float32) contribute **≤ 4.65e-07** —
    they are not the source of the composed error;
  - the composed error is dominated by float32 codegen vs PyTorch
    (model-same-input 1.22e-04 worst case);
  - pre-registered bounds, both fixed before the pilot: absolute 1e-4 on
    the ±500 envelope (observed 4.58e-05, N=75) and relative 1e-4 across
    all characterization bands (observed 4.44e-05, N=300). The extreme
    bands reached **1.22e-04 absolute** (284/300 samples within 1e-4
    absolute); that exceedance is recorded in CLAIMS.md, not absorbed —
    the tolerance was not relaxed post-hoc.
- **Gate-bypass silent-error test**: sensor and model both declare m/s²
  (gate passes, unit_scale factor 1) while the raw vector actually arrives
  in cm/s². The composed C++ path runs unimpeded and diverges **11.59
  (abs)** from the correctly-converted reference — 1.16e5× the 1e-4
  tolerance. Recorded as `bypass_unit_mismatch` in
  `results/e2e_pipeline.json` and cited in CLAIMS C5 (the checker
  validates declarations against declarations, never physical reality).
- **E002 split**: "no contracts supplied" on `deploy` now reports
  **E003** with its own `CODE_ACTIONS` entry; E002 keeps malformed
  model-contract diagnostics.
- **Evidence graph: `importers` check (Issue 5)**. The importer sources,
  `docs/CONVENTIONS.md`, `test_importers.py`, `test_draft_layer.py` and
  the package root are now declared artifact groups with their own check,
  mapped to claim C11. Editing any of them stales the check; without the
  check running, C11 reports unverified. Provenance-sidecar drift still
  risks C11 at claim level. One mutation test per group; the import-closure
  guard was strengthened to resolve `from pkg import submodule` imports
  and package `__init__` files. Host checks: **seven** (parity, battery,
  independent, heldout, workflows, baseline, importers).
- **Test-count claims unified**: docs disagreed (CLAIMS 211, EVALUATION /
  REPRODUCE / lockfile 205 with 1 skip). All now state **221 passed,
  0 skipped** (dated changelog lines in TEST_PLAN.md are historical and
  intentionally unchanged).
- `repro.py` verifies and records the new `importers` check
  (`results/importers_report.json`, 6/6 cases).

## v0.2.4-pilot (2026-10-15)

- **Contracts required by default (fail-closed gate)**: `openflight deploy`
  without `--contract`/`--model-contract` is blocked with a diagnosed
  error instead of silently skipping validation. The explicit
  `--allow-unvalidated` flag is the only bypass and records a SKIPPED
  limitation with a stderr WARNING. The E050 torch-gate skip
  (`test_product.py:54`) was retired — the suite reports 0 skips with
  torch installed.
- First end-to-end composed test (raw → `contract_adapt` → `predict` vs
  the Python reference, then N=8) plus three fault cases that must be
  blocked by the checker before any artifact is treated as validated.
- Workflow-3 fault case now runs the real `checker.check()` and asserts
  the generated `unit_scale` factor (0.01), not a mock.
- **QEMU evidence reclassified, plainly**: the raw serial capture
  `qemu_run.log` was gitignored (`.gitignore` contains `*.log`) and was
  **never shipped in any release archive**. An earlier report claiming
  "19 files verified" against it is **unsupported and withdrawn**. The
  QEMU-derived claims (C1, C2, C4, C7, C8) rest only on tracked artifacts
  (`results/esp32/numerical_parity.json`, `.csv`, stack/bench/idf-size
  files) and the regenerable driver `firmware/esp32/qemu_test.py`; they
  remain classified as existing reported (simulated) evidence pending an
  independent ESP-IDF/QEMU machine. Same for `reproduction/*.log` —
  gitignored, not shipped.
- CLAIMS C10: phantom `workingtree_reproduction.log` removed; counts
  corrected.
- Checksum policy adopted: a release archive's SHA-256 is published
  **outside** the archive (release notes + separate `.sha256` asset),
  never embedded in a file it contains.

## v0.2.3-pilot (2026-10-15)

- Provenance sidecars (`*.provenance.json`) wired into the evidence graph
  as a claim-level input of C11: confirmation drift marks the claim at
  risk without staling technical checks that do not read sidecars.
- Independent-verification instructions and the artifact-verification
  table added to the pilot protocol; checksums published externally.

## v0.2.0–v0.2.2-pilot (2026-10-13 → 2026-10-14)

- Contract engine (schema, checker, adapter/pipeline generation),
  importers (gym/ROS 2 drafts with provenance), firmware paths
  (host-sim + ESP32/QEMU harness), evidence graph (record/status with
  fresh/stale/failed/never-run), held-out/independent challenges,
  three-workflow comparison, baseline comparison, `repro.py`.
- Seven external-review engine failures fixed with regression probes
  (quaternion ordering, model-frame fail-open, quantity plausibility,
  normalization crashes, checker/pipeline units disagreement, E201
  overload, silent gate skip).
