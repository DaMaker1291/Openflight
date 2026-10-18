# Independent verification — `openflight diagnose` reproduction integrity

This guide is for a reviewer verifying, **independently of the author**, the
reproduction-integrity corrections to `openflight diagnose`. It specifies a
clean pinned environment, the exact commands, and the expected observations.

The author has run the full procedure below (25 checks across the candidate
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
  experiment (see "After verification").

## Prerequisites

- Python 3.10+ (author-verified on 3.12.9).
- A host C++ compiler (`c++`) and C compiler (`cc`).
- The exact pinned dependency set: `requirements-lock.txt` (torch 2.14.1,
  numpy 2.5.4, matplotlib 3.11.2, PyYAML 6.0.3, pytest 9.1.1 + transitives).
  A missing dependency, or one whose version differs from the pin, **fails**
  the run — a passing exit code means the pinned set was actually used.
- The revision to check out: branch `fix/reproduction-integrity` at its tip
  (`af48dae`). This contains **both** the diagnosis implementation under test
  (last mechanism commit `ed03d0e`) and the verification materials
  (`reproduction/verify_diagnose_integrity.py` and this guide).
  `ed03d0e` alone predates the harness and cannot run the procedure.

## Procedure

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

Expected final lines (candidate only — **18 checks**):

```
checks: 18  failed: 0  warnings: 0
VERDICT: PASS
```

The pre-fix comparison in step 3 adds seven checks, for a combined total of
25.

This runs, in order: provenance checks (tag `v0.2.6-pilot` and ref `e8187af`
unchanged), a pinned-dependency check (a missing **or** mismatched dependency
fails the run), the full test suite (expects **286 passed**; override with
`--expect-passed N` if you are verifying a different commit),
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
The combined run ends with **25 checks** and the same `warnings: 0` /
`VERDICT: PASS` line as step 2. This is the key independent evidence that the
corrections fix real defects rather than adding decorative checks.

### 4. Optional manual cross-checks

```bash
python -m pytest tests/openflight -q     # 286 passed
python openflight/repro.py               # REPRODUCTION OK
```

## Reporting a discrepancy

If any scenario behaves differently from the table, record: the commit under
test, your `pip freeze` output, the full harness output, the exact scenario
id, and the `reproduce.py` stdout/stderr for that case, and open an issue.

## After verification

Only once the above passes should the next gate be attempted: running
OpenFlight on a genuinely **trained** controller and fault corpus, and
comparing it against a researcher's existing manual/differential workflow.
That experiment — not the count of detected tampering cases — is what
establishes research value.
