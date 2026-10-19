# OpenFlight

A fail-closed deployment toolkit that takes PyTorch policies to
microcontrollers, gated by a sensor-contract validation layer. Before a
model is compiled or flashed, OpenFlight checks that every sensor quantity
the model declares (units, frame, ordering, layout) is consistent with the
hardware sensor contract it will run against — and refuses to deploy when it
cannot prove the mapping is safe, rather than guessing.

## What it checks

A model contract declares, per feature, the sensor quantity it reads, its
units, its coordinate frame, quaternion ordering (if any), and its raw-layout
slot. The checker cross-checks this against a sensor contract and fails closed
on: unit/dimension mismatches (E101/E102), normalization errors (E201/E205),
missing units or ordering (E202/E204/E102), input-size mismatches (E203),
off-layout bindings (E402), unknown quantities (E401), and frame
mismatch/undocumented frames (E301/U301). U-codes mean "cannot prove safe",
never "probably fine".

## Install

From a clean checkout of this repo:

```bash
pip install '.[dev]'      # full: torch, numpy, pyyaml, pytest, matplotlib
openflight doctor         # verify the installation
openflight version        # print version
```

The core is dependency-light on purpose — the contract checker, the draft
layer, the gym/ros2 importers, and the evidence graph are torch- and
numpy-free, so `openflight validate`, `import`, and `evidence` run without
pulling PyTorch. PyTorch is only needed to load weights:

```bash
pip install '.[torch]'          # weight loading + compile/benchmark/deploy
pip install '.[torch,yaml]'     # + YAML contract validation
```

Cross-compilers (`arm-none-eabi-g++`, `xtensa-esp32-elf-g++`) and `pyserial`
are optional and only needed for hardware targets.

## Supported environments

- **Linux and macOS** — native, supported.
- **Windows** — supported through **WSL** (i.e. a Linux environment).

Native (non-WSL) Windows is **not** a supported target at this revision. An
independent reviewer's native-Windows run surfaced platform-portability issues:
generated artifacts written with the implicit platform encoding, POSIX-vs-Windows
path normalisation, C++ path escaping in the generated harness, and the benchmark
socket path. The encoding issue is fixed (generated diagnosis artifacts are now
written as explicit UTF-8); the rest are out of scope until native Windows is
prioritised — use WSL in the meantime.

Prerequisites (supported environments): Python 3.10+ (verified 3.12.9) and a
host C++ compiler (`c++`) plus C compiler (`cc`).

## Reproduce every result

```bash
python3 openflight/repro.py     # expect: REPRODUCTION OK, then records evidence
```

This runs the full test suite, regenerates each report under `results/`, and
verifies it against the claimed values. On success it records the evidence
graph to `results/evidence.json`. See `docs/REPRODUCE.md`.

## Layout

- `openflight/` — the package: `contract/` (checker, draft, units),
  `compiler/`, `adapters/`, `importers/`, `benchmark/`, `targets/`,
  `cli.py`, `evidence.py`, `repro.py`.
- `docs/` — claims, evaluation, test plan, conventions, pilot protocol.
- `tests/openflight/` — the test suite.
- `examples/` — quadrotor adapter and MLP-observer contracts + weights.
- `firmware/` — host-sim harness (`generic/`, `host_sim/`) + ESP32 target.
- `results/` — regenerated-by-`repro.py` reports and the evidence graph.
- `pilot/` — the PhD-student pilot cover page and protocol.

## License

MIT — see `LICENSE`.
