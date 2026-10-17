# Challenge-round findings — `openflight diagnose` @ `e8187af`

Scope: adversarial acceptance testing of the frozen diagnosis candidate
`e8187af` (branch `challenge/diagnose-acceptance`, test-only commits).
`openflight/diagnose.py` and `openflight/cli.py` are unchanged throughout.

## Result

- Acceptance matrix: **10 / 10 checks pass** (no false diagnosis;
  preprocessing localisation; model-stage earliest divergence; simultaneous
  faults report the earliest observed divergence without a uniqueness claim;
  in-tolerance noise passes; tolerance rule and non-finite handling at the
  engine and CLI levels; stale/altered-evidence detection; fresh-workspace
  reproduction via `reproduce.py`).
- Three earlier failures were **test-expectation discrepancies**, now
  corrected (summary.md is always written; a finite reference side is
  reported numerically; `--full` needs the original files and reproduces
  when they are present). None were implementation defects.
- One **implementation review finding** is confirmed (below).

## Confirmed finding — `reproduce.py --full` does not verify all artifacts or the actual diagnosis

`full_rerun()` in the generated `reproduce.py`:

1. verifies the recorded hashes of the original `model`, `trace` and
   `reference` files, but **not** the deployment build artifacts, even though
   `report["inputs"]["build"]["artifacts"]` records their hashes; and
2. considers a rerun a match when **only the overall status** agrees — not
   the first-divergence stage, feature, location or values.

Consequently a change to the deployment build that leaves the status at
`discrepancy` but moves the fault is reported as a faithful `MATCH`.

Demonstration (`test_reproduction_integrity_changed_build_not_reported_as_match`):

| | Recorded diagnosis | After the build changed |
|---|---|---|
| Stage | preprocessing | model |
| Feature | acc_x | output[0] |
| Status | discrepancy | discrepancy |

`--full` verdict in both cases: `MATCH (exit 4)`, returncode 0 — the changed
diagnosis is **not** surfaced.

The self-check (`python reproduce.py`) still reproduces the *original*
bundle correctly; the gap is specific to `--full`'s acceptance check.

This is a **verification-integrity defect**, not a feature gap, and it does
not invalidate the passing acceptance checks.

## Desired property for a future (authorised) correction

A full rerun should:

- verify that all recorded source and deployment artifacts are unchanged
  before re-executing (including the build directory);
- use the original tolerances;
- reproduce the same first-divergence stage and location, not merely the
  same overall status; and
- surface any material disagreement between the original and rerun reports
  explicitly.

No fix is applied in this round. The implementation stays frozen at
`e8187af` pending reviewer examination of the implementation, the challenge
suite and this finding together.

## Correction (2026-10-17, branch `fix/reproduction-integrity`)

The reviewer authorised the fix ("Fix the reproduction-integrity defect.
Nothing else comes first."). A separate corrective commit addresses it
without touching `e8187af` or the release artifacts:

- `--full` now verifies **all** recorded source and deployment artifacts
  (including the build directory the report already hashes) before rerunning;
- it re-runs with the **recorded tolerances** and compares the **full
  diagnosis** (status, first-divergence stage/feature/sample/element/values,
  and every stage status), not just the overall status;
- the self-check now **independently reconstructs** the first divergence from
  the saved stage arrays in stage order (the bundle stores the full arrays
  now, plus the manifest in its recorded hashes), rather than trusting the
  recorded cell;
- adversarial regression tests cover a moved-divergence build, a report
  pointing to a later cell, a report contradicting the evidence, a changed
  build under `--full`, changed tolerances, and modified bundle members. The
  original failing regression test is retained and now passes.

Status: **addressed on `fix/reproduction-integrity`; pending independent
verification before it replaces `e8187af` as the candidate.**

## Follow-up finding and correction (2026-10-17)

Reviewer source review of the correction found a residual metadata gap:
`self_check()` read its tolerances from `report.json` and never compared them
with the separately recorded, hash-protected `artifact_manifest.json`.
Changing only the report's tolerances — even by an amount small enough to
keep the same first divergence — was therefore accepted, and a tampered
per-stage status was not checked at all.

Corrected in the same branch: the self-check now requires every duplicated
metadata field (`schema_version`, `created_at`, `openflight_version`,
`tolerances`, `inputs`, `shapes`) to match the manifest, and independently
re-derives each stage's agree/diverge status from the saved arrays. Three
fail-first tests cover altered tolerances, an altered stage status and
altered shapes; all were red before the fix and green after. Suite
**280 → 283 passed**; ruff scoped baseline 38; `repro.py` →
`REPRODUCTION OK`.

Residual limitation (documented, not fixed): offline bundles cannot
cryptographically anchor `report.json` itself; a coherent re-forge of the
report *and* manifest together remains theoretically possible. The checks
above protect against single-file tampering and against any report that no
longer matches the recorded evidence.


