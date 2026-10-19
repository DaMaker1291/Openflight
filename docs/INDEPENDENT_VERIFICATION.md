# Independent verification — `openflight diagnose` reproduction integrity

This guide is for a reviewer verifying, **independently of the author**, the
reproduction-integrity corrections to `openflight diagnose` and the
trained-controller experiment. It specifies a clean pinned environment, the
exact commands, and the expected observations.

The author has run the full procedure below (46 checks across the candidate
and pre-fix stages, 0 failed). Logs are gitignored (`*.log` is not tracked),
so that run is a local artifact you will not find in a clone. In any case it
is **not** independent verification; reproduce the run in your own
environment and treat only your own result as evidence.

## What is being verified

Three corrections, all on branch `fix/reproduction-integrity`, newest first:

| commit | correction |
| --- | --- |
| `ed03d0e` | the overall report `status` must be a supported value and agree with the reconstructed evidence |
| `8d40267` | report fields duplicated from the hash-protected manifest (`schema_version`, `created_at`, `openflight_version`, `tolerances`, `inputs`, `shapes`) must agree with it |
| `3b44a2d` | `reproduce.py --full` must verify build artifacts and reconstruct the diagnosis from the saved arrays, not trust the recorded summary |

And one invariant that must hold throughout: the frozen candidate `e8187af`
(remote branch `openflight-v0.2`) and the release tag `v0.2.6-pilot`
(`5840dfe7ddb055cb962fee32bd82ba8419d27f51`) are unchanged.

## Honest scope

- The harness is **author-written**. Independence means *you* run it in *your*
  environment and read `reproduction/verify_diagnose_integrity.py` rather than
  trusting it or the author's log.
- It tests the trust guarantees that were claimed and nothing more. An offline
  report cannot be cryptographically anchored: a coherent re-forge of both
  `report.json` and `artifact_manifest.json` together remains theoretically
  possible. These checks make tampering *detectable and testable*, not
  *impossible*.
- A PASS says nothing about OpenFlight's research value. That is a separate
  experiment (see "Verifying the experiment").

## Prerequisites

- Python 3.10+ (author-verified on 3.12.9).
- A host C++ compiler (`c++`) and C compiler (`cc`).
- The exact pinned dependency set: `requirements-lock.txt` (torch 2.14.1,
  numpy 2.5.4, matplotlib 3.11.2, PyYAML 6.0.3, pytest 9.1.1 + transitives).
  A missing dependency, or one whose version differs from the pin, **fails**
  the run — a passing exit code means the pinned set was actually used.
- The revision to check out: branch `fix/reproduction-integrity`. Record its
  exact head before running (step 0 below). The revision must contain **both**
  the diagnosis implementation under test (last mechanism commit `ed03d0e`)
  and the verification materials (`reproduction/verify_diagnose_integrity.py`,
  introduced in `1bdc8cf`, plus this guide). `ed03d0e` alone predates the
  harness and cannot run the procedure. The branch head moves with each
  handoff commit, so this guide intentionally does not pin a tip SHA.

## Procedure

### 0. Pin the revision

```bash
git rev-parse HEAD                     # record this full SHA with your results
git merge-base --is-ancestor ed03d0e HEAD && echo "contains diagnosis under test"
test -f reproduction/verify_diagnose_integrity.py && echo "contains verification harness"
```

### 1. Clean environment

```bash
python3 -m venv /tmp/of-verify
source /tmp/of-verify/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-lock.txt      # pinned set
pip install -e . --no-deps                # the candidate itself
```

### 2. Verify the corrections on the candidate

```bash
python reproduction/verify_diagnose_integrity.py
```

Expected final lines (candidate only — **39 checks**):

```
checks: 39  failed: 0  warnings: 0
VERDICT: PASS
```

The pre-fix comparison in step 3 adds seven checks, for a combined total of
46.

This runs, in order: provenance checks (tag `v0.2.6-pilot` and ref `e8187af`
unchanged), a pinned-dependency check over **every** package and version in
`requirements-lock.txt` (a missing **or** mismatched dependency fails the
run; names are normalised), the full test suite (expects **299 passed**;
override with `--expect-passed N` if you are verifying a different commit),
`openflight/repro.py` (`REPRODUCTION OK`), and, finally, builds a genuine
discrepancy bundle with the CLI and applies six scenarios:

| scenario | mutation | expected on candidate |
| --- | --- | --- |
| baseline | none | accepted (exit 0) |
| status | `status` → `"tampered"` | rejected (exit ≠ 0) |
| tolerances | report `rtol` doubled | rejected |
| stage_status | one stage status flipped | rejected |
| shapes | report `n_samples` changed | rejected |
| build_artifact | comment appended to `model.cpp`, run with `--full` | rejected |

### 3. Confirm the defects were real (pre-fix comparison)

Check out the frozen pre-fix candidate in a separate worktree and point the
harness at it:

```bash
git worktree add --detach /tmp/openflight-e8187af e8187af
python reproduction/verify_diagnose_integrity.py --prefix-root /tmp/openflight-e8187af
git worktree remove /tmp/openflight-e8187af --force
```

Expected: every `prefix/*` scenario is **accepted** (the pre-fix code does not
detect the tampering) while every `candidate/*` scenario is still **rejected**.
The combined run ends with **46 checks** and the same `warnings: 0` /
`VERDICT: PASS` line as step 2. This is the key independent evidence that the
corrections fix real defects rather than adding decorative checks.

### 4. Optional manual cross-checks

```bash
python -m pytest tests/openflight -q     # 299 passed
python openflight/repro.py               # REPRODUCTION OK
```

## Reporting a discrepancy

If any scenario behaves differently from the table, record: the commit under
test, your `pip freeze` output, the full harness output, the exact scenario
id, and the `reproduce.py` stdout/stderr for that case, and open an issue.

## Verifying the experiment

The branch also carries the first research experiment: a genuinely trained
controller deployed through the real pipeline with five injected faults plus a
clean control. The deployed contract reproduces the observer's **real** input
pipeline — a 20-sample window (newest-first) of `[a_meas, u_act, v]`,
standardised with the checkpoint's mean/std — with the temporal offsets
(`sample_offset_steps`) and the actuator quantity
(`applied_control_acceleration`) declared explicitly.

```bash
python experiments/trained_controller/experiment.py --n-samples 200 \
    --out experiments/trained_controller
```

Expected: each case prints `diagnose=<stage>` equal to its `expected=<stage>`
(the clean control prints `diagnose=None`), and the metrics JSON shows
`localisation_accuracy.diagnose == 1.0`,
`false_diagnoses_on_clean.diagnose == 0`, and
`reproducibility.second_run_equivalent == true`. **Wall-clock seconds will
differ per machine — do not compare them**; compare only the verdicts.
`tests/openflight/test_trained_controller_experiment.py` re-checks this at a
small sample count as part of the suite.

This experiment is **SIMULATED** host-side. Verifying it means confirming that
the pipeline localises the injected faults on *your* machine. It does **not**
establish that OpenFlight beats any baseline: the recorded finding is that a
scripted staged baseline matches it on accuracy and is faster on raw compute,
so the claimed value is the self-contained bundle and reproducibility — accept
or reject that claim on the evidence, not on the demo.

## Independent verification result — 2026-10-18

Recorded here from the independent verifier's report. The verifier ran the
pinned procedure on commit
`eff1bbf5bb215e02182ddadd8e887dbd91d98e47` in a **fresh Linux/WSL
environment** (not the author's). The raw logs are held by the verifier; the
table below is the reported outcome, not an author run.

**Verdict: `PASS WITH FINDINGS`.**

| Verification | Result |
| --- | --- |
| Independent integrity checks | 39/39 passed |
| Pre-fix comparison | 46/46 checks passed |
| Test suite (Linux/WSL) | 298 passed |
| Overall reproduction | `REPRODUCTION OK` |
| Injected faults correctly localised | 5/5 |
| False diagnoses on clean control | 0 |
| Repeated diagnosis equivalent | yes |
| Independent check of all 60 normalisation transforms | passed |
| Native Windows execution | failed — portability findings (F1 fixed; F2–F4 out of scope) |
| ESP32/QEMU reproduction | not performed by that verifier |

This is a pass **in the documented environment only**. It is not a
cross-platform pass, not physical-drone validation, and not evidence that
OpenFlight outperforms existing tools. F1–F4 are described under "Supported
environments" in `README.md`; only the UTF-8 defect (F1) is a confirmed code
defect and it is fixed at the revision that follows `eff1bbf`.

### Post-fix re-run (author, 2026-10-18)

After the F1 fix, the affected checks were re-run in the documented environment
(macOS, pinned set) on commit
`0b8c60debf7beb33db177a8bbe2bf6e69166680b`:

- `python -m pytest tests/openflight -q` → **299 passed**
- `python openflight/repro.py` → **`REPRODUCTION OK`** (eight host checks)
- `python experiments/trained_controller/experiment.py --n-samples 200`
  → 5/5 localised, 0 false diagnoses on the clean control, reproducible

This is an author re-run of the checks affected by the fix, **not** a second
independent verification; the independent `PASS WITH FINDINGS` above stands for
`eff1bbf`.

## Handoff record

The author fills the first block and hands over the exact SHA; the verifier
fills the second in a clean environment. (The 2026-10-18 result for `eff1bbf`
is recorded in the section above.)

```
revision:        <git rev-parse HEAD>
branch:          fix/reproduction-integrity
author result:   candidate 39 / combined 46 checks, 0 failed, VERDICT PASS;
                 suite 299 passed; experiment 5/5 localised, 0 false
verifier:        <name, date, machine>
verifier env:    <paste `pip freeze`>
verifier result: <harness tail + experiment metrics + PASS/FAIL>
discrepancies:   <none, or issue link>
```

Independence means the verifier block is filled by someone other than the
author, in a clean environment. An author run does not satisfy this gate.

## After verification

An independent `PASS WITH FINDINGS` is now recorded (2026-10-18, `eff1bbf`).
The next milestone is **not** another feature or another immediate repeat of the
same verification; it is a credible evaluation of *diagnostic usefulness*: a
blinded benchmark where a reviewer contributes fault cases without seeing
OpenFlight's answers, comparing OpenFlight against the hand-written baseline on
correct localisation, false rejections of valid cases, and time-to-diagnosis.
That is what distinguishes "detects its author's injected faults" from "helps
someone diagnose unfamiliar faults". The preregistered pilot (three prereg
gates not yet complete — see PILOT_PREREGISTRATION) and external researchers
come after that, subject to the repository's approval/permission requirements.
