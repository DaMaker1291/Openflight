# Reproducing OpenFlight v0.1 (independent reproduction guide)

For a reviewer reproducing from a clean checkout. No hardware needed; no
engineering-time claims are tested here.

## Prerequisites

- Python 3.11+ with `torch`, `numpy`, `pytest`, `matplotlib`
  (`pip install torch numpy pytest matplotlib`)
- A host C++ compiler (`c++`) and C compiler (`cc`) for the harness tests
- The model files at the repo root: `learned_observer.pt`, `ppo_best.pt`,
  `examples/mlp_observer/model_weights.pt`
- ~10 minutes on a laptop; no network, no MCU, no cross-toolchain

## Steps

1. `git clone <repo> && cd <repo>` (record the commit hash).
2. (Optional, recommended) Verify the freeze manifest:
   `python3 openflight/freeze.py --out /tmp/freeze_check.json`, then compare
   `source_files` hashes and `models` hashes against
   `results/freeze_v0.1.json`. Any source change shows up as a hash mismatch.
3. Run the full evaluation: `python3 openflight/repro.py`.
   This executes all 95 regression tests plus the held-out challenge, then
   verifies each JSON report in `results/` against the claimed result.
   Expected final line: `REPRODUCTION OK`.

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
