# Changelog

All notable changes to OpenFlight. Versions follow `0.2.x-pilot`; the tag
named here is the version the supervised pilot runs against.

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
