# Held-out diagnostic evaluation — brief for an independent agent

**Purpose.** Test whether OpenFlight's diagnostic behaviour generalises to
cases it has not seen. You design and freeze the cases; the author does not
supply expected answers.

**Revision under test.** The commit SHA supplied with this brief. Verify with
`git rev-parse HEAD`; do not modify the repository.

## What to read

`README.md`, `docs/CONTRACT_ENGINE.md`, the diagnose sections of `docs/`, and
the implementation in `openflight/diagnose.py`, `openflight/contract/`, and
`openflight/cli.py`. Use the documentation only to define documented behaviour
(error codes, exit codes, stage names); do not use it to infer answers for
cases you have already designed.

## Hypotheses

- **H1 Localisation.** For valid-but-faulty deployments, OpenFlight reports
  the first-divergent stage (`preprocessing`, `model`, `end_to_end`) that
  matches ground truth.
- **H2 Robustness.** For invalid or malformed evidence, OpenFlight returns a
  structured rejection rather than a confident diagnosis or a traceback.
- **H3 Controls.** Valid configurations produce no diagnosis.
- **H4 Repeatability.** Repeated diagnoses of the same case are equivalent.
- **H5 Gate.** Semantically invalid but structurally readable contracts are
  blocked with the documented specific code, exit 2, and no deployable
  artifacts.
- **H0 Baseline.** Compare localisation accuracy, false accepts/rejects, and
  time-to-diagnosis against a hand-written baseline that compares stage
  outputs under the same tolerance rule.

## Case design (independently designed, at least 24 cases)

Cover, without copying any prior case list (prior benchmark artifacts are not
in this repository and must not be sought out):

1. Runtime faults at each stage, including at least one **tolerance-edge** case
   where each stage's error is individually within tolerance but the composed
   end-to-end result diverges.
2. Valid controls that must not be flagged.
3. Malformed evidence: non-finite values, shape/dtype mismatches, missing keys,
   and unreadable artifacts.
4. Structurally readable contracts with semantic defects, exercising the
   specific documented codes (`E201`, `E203`, `E205`, and any others the docs
   assign).
5. At least one case where the available evidence **cannot establish a unique
   stage**. Decide the expected behaviour from the documentation before
   running and state it.

Include cases that are unlike the common textbook injections; the point is
unfamiliarity, not volume.

## Freeze protocol

1. Write cases and expected answers in a separate directory or repository.
   Do not read the author's prior benchmark results or expected answers.
2. Hash every case and expectation file (SHA-256) and commit/timestamp them
   **before** running either system. Record the hashes in your report.
3. Do not edit cases or expectations after seeing outputs. If an amendment is
   unavoidable, keep the original, log the change, the reason, and the time.
4. Run both systems from a clean checkout at the frozen revision. Preserve raw
   logs and per-case outputs.

## Scoring (pre-register before running)

Per case: (a) stage or documented exit code, (b) structured rejection code
where the docs define one, (c) no deployable artifacts on rejection, (d)
control cleanliness. Report repeatability over two runs and median
time-to-diagnosis. Report every case; no post-hoc exclusion.

## Deliverable

`HELDOUT_REPORT.md` containing: frozen case hashes, environment, per-case
table, aggregate results, amendments, and limitations. State explicitly that
this is a single-agent, single-session evaluation and **not** human-robot or
human-expert validation.

## Do not

Modify the repository under test, add features, or relax the pre-registered
scoring after seeing results. Do not treat a structured rejection as a failure
when the documentation defines it as the correct outcome for invalid evidence.
