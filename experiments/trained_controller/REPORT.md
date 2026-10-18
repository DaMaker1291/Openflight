# Trained-controller fault localisation (SIMULATED)

**SIMULATED (host-side deployment evidence; not physical-robot validation)**

- Model: `learned_observer.pt` (mlp:60,128,64,1), trained by `learned_observer.py`
- Input: 20-sample window of a_meas, u_act, v (newest-first), standardised with the checkpoint mean/std
- Trace: 200 samples, tolerances rtol=atol=0.0001
- Environment: Python 3.12.9

## Per-case result

| case | family | expected | diagnose | baseline | diagnose correct |
| --- | --- | --- | --- | --- | --- |
| clean | control (no fault) | (agree) | agree | (agree) |  |
| acc_units | sensor units | preprocessing | preprocessing | preprocessing | yes |
| control_units | sensor units | preprocessing | preprocessing | preprocessing | yes |
| order_swap | temporal ordering | preprocessing | preprocessing | preprocessing | yes |
| preproc_gain | preprocessing | preprocessing | preprocessing | preprocessing | yes |
| compiled_infer | compiled inference | model | model | model | yes |

## Metrics

- Faults: 5
- Localisation accuracy — diagnose: **100%**, baseline: 100%
- False diagnoses on the clean control — diagnose: 0, baseline: 0
- Median wall-clock — diagnose: 1.966s, baseline: 0.569s
- Reproducibility (diagnose run twice on `acc_units`): True

## Limitations (stated, not hidden)

- All evidence is **simulated host-side**. No hardware, no physical
  controller, no on-MCU timing.
- Inputs are real windows of `[a_meas, u_act, v]` from simulated
  trajectories, standardised with the **checkpoint's** mean/std — the
  same transform `learned_observer.py` trains with. `u_act` is a
  simulator state; it is shown here because the simulator exposes it,
  which does not establish it is directly measurable on a real drone.
- Model outputs are compared **standardised**; the physical estimate is
  `y*t_std + t_mean`, a caller-side de-normalisation the codegen leaves
  open. A divergence in standardised output implies one in physical.
- Wall-clock is a compute proxy, not a human time-to-resolution study;
  it excludes the engineer time to build the baseline harness.
- The reference is recorded from the clean adapter + the trained model;
  faults are injected into the deployed side (contracts or artifacts).
- One controller, one input distribution, one deployment target (host).
