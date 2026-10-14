# OpenFlight pilot protocol (2–3 PhD students)

**Goal.** Establish whether OpenFlight makes it *faster and more reliable* to
take a PyTorch policy onto a microcontroller **without** shipping a wrong
sensor-to-model binding. This is the human-time claim the solo evaluation
explicitly cannot make (see `EVALUATION.md`: "no human study has been run").
You are the study.

**What you are NOT being asked to do.** No hardware, no MCU, no cross-compile.
Everything runs on a laptop in ~10–15 minutes of compute; the human task is
~60–90 minutes.

## Time budget

| Phase | Task | Wall time |
|---|---|---|
| 0 | Install + doctor | ~5 min |
| 1 | Reproduce solo results (`repro.py`) | ~10 min |
| 2 | Deploy the example yourself (`QUICKSTART.md`) | ~10 min |
| 3 | Break it on purpose (three fault injections) | ~20 min |
| 4 | Write the questionnaire (`PILOT_FEEDBACK.md`) | ~20 min |

## Phase 0 — install

```bash
pip install -r requirements-lock.txt  # exact verified set (recommended)
pip install -e . --no-deps            # the package itself
openflight doctor                     # must exit 0, no errors
openflight version                    # expect 0.2.0
```

If `doctor` fails, stop and report — that is a finding, not a setup problem.

## Phase 1 — reproduce

```bash
python3 openflight/repro.py              # expect final line REPRODUCTION OK
python3 -m openflight.cli evidence status  # expect: all checks fresh, exit 0
```

Record the `git rev-parse HEAD` you ran from. `repro.py` is expected to run
the full 162-test suite and regenerate every report in `results/`. Any
`MISMATCH` or `stale` check is a finding.

## Phase 2 — deploy the example

Follow `QUICKSTART.md` verbatim. It deploys `examples/quadrotor_adapter/`
(6→16→2 MLP) to the `host` target and writes
`build/quickstart/deployment_report.json`. Every stage records `status`,
`evidence`, and `limitations`; `not-run` means not verified. Note anything
that forced you to read source rather than docs.

## Phase 3 — break it on purpose

The value proposition is fail-closed validation: a bad binding should be
*blocked with a diagnostic*, not silently deployed. Inject these three faults
into `examples/quadrotor_adapter/` and run the validator after each:

```bash
openflight validate --contract examples/quadrotor_adapter/drone_contract.yaml \
  --model-contract examples/quadrotor_adapter/model_contract.yaml
```

For each, record the exact code you ran, the exact message you got, and
whether you consider that message sufficient to fix the fault yourself.

> Use a copy of the two YAML files, not the originals. Apply the edits with a
> real editor or Python — naive `sed '0,/.../s//.../'` patterns silently match
> the wrong line in these files (they hit `raw_layout` or the wrong feature).
> After each edit, re-open the file and confirm the change landed where you
> intended before you trust the result.

The reference diagnostics (what you *should* see; matching is not required,
but a different result is a finding):

1. **Unit mismatch.** In `model_contract.yaml`, change the `acc_x` feature's
   `units` from `metres_per_second_squared` to `radians_per_second`.
   Expect `exit 2`, `Deployment status: BLOCKED`, and E101/E102 naming
   `acc_x` and the acceleration vs angular-velocity dimension clash.
2. **Off-layout binding.** In `model_contract.yaml`, change the `acc_x`
   feature's `source` to `{quantity: acceleration, component: ghost}`
   (the `raw_layout` has no `ghost` component). Expect `exit 2`, BLOCKED, and
   E402 naming `('acceleration', 'ghost')` as not present in `raw_layout`.
3. **Undocumented units.** In `drone_contract.yaml`, empty the
   `imu.accelerometer` block so it has no `units` field. Expect `exit 2`,
   BLOCKED, and E001: `imu.accelerometer needs units`.

If any of these three **deploys anyway** (exit 0), that is the single most
important finding in the pilot — report it immediately.

## Phase 4 — questionnaire

Fill in `PILOT_FEEDBACK.md`. Be blunt; negative results are the useful ones.
