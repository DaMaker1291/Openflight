# OpenFlight Test Count Verification

This document reconciles the different test count figures that appear across the project.

## Summary of Figures

| Figure | Source | Context | Pass/Total |
|---|---|---|---|
| **298/300** | `README.md` (main branch) | "test suite passed (Linux/WSL)" | 298 passed of 300 total |
| **242 passed** | `reproduction/release_v0.2.6_author_verification_2026-10-15.log` | Release v0.2.6-pilot test suite only (`pytest tests/openflight/`) | 242 passed |
| **162 passed** | Verification log note | Earlier capture that ran without `cd` into extraction (original monorepo test tree) | 162 passed (incomplete) |
| **300 total** | Derived from all figures | The test suite has 300 tests; 298 pass on main (2 fail) | N/A |

## Detailed Breakdown

### 1. README.md (main branch): 298/300
- **File**: `README.md` on branch `main`
- **Content**: "- **298/300** test suite passed (Linux/WSL)"
- **Status**: This is the current main-branch claim. It implies 2 of 300 tests fail on Linux/WSL.

### 2. Release v0.2.6-pilot verification: 242 passed
- **File**: `reproduction/release_v0.2.6_author_verification_2026-10-15.log`
- **Command**: Full verification pipeline (not just `pytest tests/openflight/`)
- **Content**: "242 passed in 23.69s" (under "--- 2. full suite (expect 242 passed) ---")
- **Context**: This runs `pytest tests/openflight/` on the release archive, which is a subset of the 300-total suite. The log later shows additional checks (audit probes, evidence graph mutations, schema regressions, CLI demos, repro.py) that bring the total verified output to "REPRODUCTION OK".

### 3. 162 passed (earlier capture error)
- **Source**: Verification log disclosure note
- **Problem**: "An earlier capture attempt (2026-10-16T21:59:18Z header) ran WITHOUT cd'ing into the extraction, so it executed the ORIGINAL monorepo test tree instead of the release (it reported '162 passed', missing audit/mutation suites, version/doctor). That output was NOT preserved — the corrected run below overwrote this file via tee."
- **Lesson**: The 162 figure is from a verifier procedure error and should not be cited.

### 4. The 300-test suite structure
- The OpenFlight test suite on Linux/WSL has **300 tests total**.
- On the `main` branch, **298 pass** and **2 fail** (the specific failing tests are not identified in the README summary but would be visible in the full pytest output).
- The 2 failing tests are likely outside the `diagnose` module (per the playbook guidance, do not dismiss them as "unrelated" without investigation).

## Recommendations for the CV

### Accurate statement (using the main-branch figure):
> Developed OpenFlight, an open-source Python/C++ toolkit for validating sensor-to-model compatibility in embedded ML deployment. At a pinned development revision (main, Oct 2026), a clean-checkout Linux/WSL run passed 298/300 software tests, with 39/39 diagnosis-integrity checks passed and 46/46 pre-fix comparison checks passed. The current evidence is author-generated; external independent reproduction and physical-hardware validation remain outstanding.

### Avoid:
> "OpenFlight has 300 passing tests" — this is ambiguous and could refer to different runs/branches.

> "162 tests pass" — this is from an erroneous capture and should not be cited.

### Best practice for future:
Tie each test count to its exact commit SHA and run date. For example:

> At commit `972e23e` (main, 2026-10-24), `python3 -m pytest` on Linux/WSL produced 298 passed, 2 failed.  
> On branch `fix/reproduction-integrity` at commit `27847f2` (2026-10-18), 39/39 independent integrity checks passed and 46/46 pre-fix comparison checks passed.

## Key Takeaway

- **Do not combine** 162, 242, 298, or 300 into a single claim.
- **Label each figure** with its source commit/branch and date.
- **Investigate the 2 failing tests** on main rather than dismissing them as "unrelated."
- For the CV, use the **298/300 from main** tied to its commit, and separately mention the diagnosis-integrity and pre-fix comparison results from the `fix/reproduction-integrity` branch.