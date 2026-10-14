# OpenFlight v0.1 review snapshot (frozen, do not modify)

> **Correction (2026-10-14): the tarball below was never created.** The
> freeze that actually exists and is verified is the manifest
> `results/freeze_v0.1.json` (62 SHA-256s). Verified against the tree:
> 47 files unchanged, 15 diverged (the documented v0.2 changes), 0
> missing — see `reproduction/freeze_v0.1_manifest_verification.log`.
> The "do not modify this archive" policy is void; from here, git tags
> are the freeze mechanism. The remainder of this file is retained as
> the originally intended snapshot description.

Archive (never created): `openflight-v0.1.tar.gz`
SHA-256 (of a file that does not exist): `121f421e885fd86c67c61022d14b865c8c25e3dc77154e45d048a38aa731c18f`

## Contents (91 entries)

`openflight/` (contract engine, compiler, benchmark, CLI, docs incl.
EVALUATION.md, REPRODUCE.md, freeze.py, repro.py, make_snapshot.sh),
`tests/openflight/` (97 tests), `firmware/` (generic + host_sim),
`examples/` (observer + quadrotor contracts/weights),
`learned_observer.pt`, `ppo_best.pt`, `learned_observer.py`,
`macondo_hover.py`, `observer_deploy.py`, `openrescue/` (import closure),
all seven `results/*.json` reports, `results/freeze_v0.1.json`,
`.github/workflows/openflight.yml`.

## Verification performed

1. All 62 `freeze_v0.1.json` source hashes match archive bytes exactly
   (0 missing, 0 mismatched).
2. Archive extracted to an empty directory and `openflight/repro.py` run
   there: full suite passes and every reported result regenerates —
   `REPRODUCTION OK`. This check caught and fixed one real omission (the
   physics/exporter modules were initially missing from the bundle).

## Policy

v0.1 is preserved. Reviewer-found problems are fixed in a new revision, never
by editing this archive. Fixes reference the archive hash above.

## For the reviewer

Extract anywhere with Python 3.11+, `torch`, `numpy`, `pytest`,
`matplotlib`, and a host C++ compiler; run
`python3 openflight/repro.py`. Then design additional valid/invalid/ambiguous
contract cases WITHOUT consulting `tests/openflight/test_heldout_challenge.py`
scoring internals, and report: false accepts, false rejections, wrong
diagnostics, reproduction failures. Please also read the checker itself
(`openflight/contract/checker.py`, ~200 lines), not just the tests.
Known boundary to probe: declaration-vs-reality (see EVALUATION.md §5.1).
Hardware (latency/RAM/stack on silicon) is out of scope for this bundle.
