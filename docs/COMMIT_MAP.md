# Commit map: original monorepo → split repo

This repo was produced by `git filter-repo` from
`hurricane-station-keeping`, keeping only OpenFlight paths. `filter-repo`
rewrites commit hashes, so SHA-256s recorded in older evidence, reports and
review bundles refer to commits in the **original** repo and will not resolve
here. Use this table to reconcile them.

The filter kept all 29 original commits that touch a retained path; 13 are
OpenFlight commits carried 1:1 (below). The other 16 original commits are
OpenRescue/MARAHS/paper work touching only excluded paths and are correctly
absent here.

One OpenFlight commit — `8d4b20d` "declare matplotlib in dev extra" — is
**not** carried because it only modified `dist-openflight/pyproject.toml`,
which this split replaced with a root `pyproject.toml`. Its intent (matplotlib
in the `dev` extra) is preserved in the new root `pyproject.toml`.

| Old commit (original repo) | New commit (split repo) | Subject |
|---|---|---|
| `144215687384` | `cc15771b85b4` | OpenFlight: add pilot cover page; collect responses privately |
| `1f8d86744ad3` | `e7a52aaf7eee` | OpenFlight: track dist-openflight packaging source so fresh clone installs |
| `bf12a2de4232` | `fdfe884d8706` | OpenFlight: pilot package (protocol, feedback form, MIT license) |
| `e690c2634596` | `f47f2088e096` | OpenFlight: make held-out challenge byte-stable across processes |
| `4bc2a6357eec` | `46c62812ec95` | OpenFlight: Phase 1 evidence graph with invalidation |
| `adb1c21f12a9` | `166d58ec8c73` | OpenFlight: advisor-review strengthening — verified golden cases, retained limitations, honest width accounting |
| `fce517a06862` | `6487dac9fef0` | OpenFlight: commit v0.2 tree — contract engine, importers, draft layer, ESP32 target |
| `8cec00917bbf` | `972e23ee4e60` | Ignore separate render projects landauer_render/ and blender_landauer/ |
| `8dec0532b6cf` | `ff69244d41b5` | Add V3.2 validated propulsion core to OpenRescue, plus V2/V3 lineage and artifacts |
| `108c0c99eb32` | `48a3cad9c5ca` | Track macondo_hover.py: the wind-hold plant module that learned_observer.py imports |
| `42777c0efeaa` | `a77f482bb3e0` | Observer: learned disturbance estimator vs analytic observer (macondo plant) |
| `4ea7e24ad64a` | `21e7db837ab6` | Add 3000-episode PPO training results and publication figures |
| `a41a8cc09812` | `938f7995f74c` | MARAHS: Multi-Agent Reinforcement learning with Adaptive Hierarchical Safety |

## The v0.1 freeze is not a commit

`results/freeze_v0.1.json` records `git_head: d0d070a` with
`git_status_openflight` showing every OpenFlight path as untracked (`??`).
The v0.1 tree was **never committed**: it existed only as working-tree files
when the freeze was taken. The freeze is therefore a **content-addressed
snapshot** of 65 SHA-256 hashes (62 `source_files` + 3 `models`), not a git
commit, and no tag can point at it.

Two tags in the original repo record what actually exists:

- `openflight-v0.1-freeze-tree` → `d0d070a` — the OpenRescue commit the
  freeze was taken *at*, while all OpenFlight paths were untracked.
- `openflight-v0.2-first-tracked` → `fce517a` — the first commit that
  tracks all 65 freeze paths; its tree already reflects v0.2 development.

The review bundle's archive hash `121f421e…` refers to
`openflight-v0.1.tar.gz`, an archive that was never created. That hash is
invalid and the archive does not exist.
