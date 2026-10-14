# OpenFlight pilot — start here

OpenFlight checks that a PyTorch policy's declared sensor contract (units,
frames, layout) is consistent before generating microcontroller code, and
blocks deployment when it can't prove the binding is safe.

## The three commands (from a clean checkout)

1. `pip install './dist-openflight[yaml,dev]'`
2. `openflight doctor`
3. `python3 openflight/repro.py`  — expect: `REPRODUCTION OK`

Then deploy the example; full flags in `openflight/QUICKSTART.md`.

## Time, platform, contact

- **Time:** ~5 min install, ~20 min reproduce; the deploy + review session
  runs 60–90 min total (see `openflight/PILOT_PROTOCOL.md`).
- **Platform:** Linux/macOS, Python 3.10–3.12 tested (3.12 recommended).
  Windows is not supported (the protocol uses bash).
- **If something fails:** copy the exact command and its full output into
  `openflight/PILOT_FEEDBACK.md`, then continue past it.
- **Contact:** open an issue with the command, output, and Python/OS version.
