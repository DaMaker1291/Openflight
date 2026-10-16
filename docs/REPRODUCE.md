# Reproducing OpenFlight (independent reproduction guide)

For a reviewer reproducing from a verified release archive or a clean
checkout. No hardware needed; no engineering-time claims are tested here.

## Prerequisites

- Python 3.10+ (verified on 3.10.16, 3.11.13, 3.12.9, and 3.13.2 —
  the v0.2.6-pilot clean-room extraction)
- A host C++ compiler (`c++`) and C compiler (`cc`) for the harness tests
- The model files at the source root: `learned_observer.pt`, `ppo_best.pt`,
  `examples/mlp_observer/model_weights.pt`
- ~10 minutes on a laptop; no network after install, no MCU, no
  cross-toolchain

## Installing dependencies

Two options:

1. **Pinned (recommended):** `pip install -r requirements-lock.txt`
   — the exact set verified for this release (torch 2.14.1, numpy 2.5.4,
   matplotlib 3.11.2, pyyaml 6.0.3, pytest 9.1.1 + transitives, captured
   2026-10-14 from a clean 3.12.9 venv).
2. **Ranges:** `pip install '.[dev]'` — uses the bounded ranges in
   `pyproject.toml`, which are narrowed to versions actually tested;
   anything below those lower bounds is untested.

Then install the project itself: `pip install -e . --no-deps`.

## Steps

1. Obtain the source, exactly one of:
   - **Release archive (recommended for verification):** download
     `openflight-vX.Y.Z-pilot.tar.gz` and its `.sha256` asset from the
     official release page, compare `shasum -a 256` against the published
     hash (taken from the release notes/asset, never from inside the
     archive), then extract into an empty directory and work there. There
     is no `.git`; the verified archive checksum is the provenance anchor —
     **do not `git clone` instead**, that tests development HEAD, not the
     frozen release.
   - **Git checkout:** `git clone <repo> && cd <repo>`, then check out the
     release tag (e.g. `git checkout v0.2.6-pilot`) and record the commit
     hash.
2. (Optional, recommended) Verify the freeze manifest:
   `python3 openflight/freeze.py --out /tmp/freeze_check.json`, then compare
   `source_files` hashes and `models` hashes against
   `results/freeze_v0.1.json`. Any source change shows up as a hash mismatch.
3. Run the full evaluation: `python3 openflight/repro.py`.
   This executes the full regression suite (242 passed, 0 skipped as of
   2026-10-15, v0.2.6-pilot; the former E050 skip `test_product.py:54` was
   retired when the contract gate became required-by-default) plus the
   held-out challenge, then verifies each JSON report in `results/`
   against the claimed result. Expected final line: `REPRODUCTION OK`.
   On success it also records the evidence graph to `results/evidence.json`
   with a live result for each of the eight host checks it runs.
4. (Optional) Inspect staleness: `python3 -m openflight.cli evidence status`.
   Expected after step 3: the eight host checks `fresh`, `build` and `qemu`
   `never run` (they need an ESP32 toolchain; the host-only tree cannot
   run them, and `evidence status` names the claims that therefore have
   no live evidence), exit 0. Mutate any input artifact (a weight
   file, a contract, one line of checker code) and re-run — exactly the
   checks that read it report `STALE` and the command exits 1.

## What is verified

1. Numerical parity (compiled observer vs PyTorch, incl. recorded windows and
   the firmware-over-pipes path).
2. Contract challenge results (dev battery, independent set, held-out set).
3. Three-workflow comparison incl. corrupted-input cases.

## What is NOT verified (outstanding, stated in EVALUATION.md)

- On-silicon latency, Flash/SRAM, stack high-water mark, hardware timers.
- Engineering-time savings (no human study).
- External review of the held-out set (seed-published but author-generated).

## Reporting problems

Record: commit hash, `results/freeze_v0.1.json` `dependencies` block, the
full `pytest` output, which `repro.py` check failed, and the diff of the
mismatched JSON report. Open an issue with all five.
