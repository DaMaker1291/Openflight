# Trained-controller fault localisation (SIMULATED)

**SIMULATED (host-side deployment evidence; not physical-robot validation)**

- Model: `learned_observer.pt` (mlp:60,128,64,1), trained by `learned_observer.py`
- Trace: 200 samples, tolerances rtol=atol=0.0001
- Environment: Python 3.12.9

## Per-case result

| case | family | expected | diagnose | baseline | diagnose correct |
| --- | --- | --- | --- | --- | --- |
| clean | control (no fault) | (agree) | agree | (agree) |  |
| acc_units | sensor units | preprocessing | preprocessing | preprocessing | yes |
| gyro_units | sensor units | preprocessing | preprocessing | preprocessing | yes |
| order_swap | feature ordering | preprocessing | preprocessing | preprocessing | yes |
| preproc_gain | preprocessing | preprocessing | preprocessing | preprocessing | yes |
| compiled_infer | compiled inference | model | model | model | yes |

## Metrics

- Faults: 5
- Localisation accuracy — diagnose: **100%**, baseline: 100%
- False diagnoses on the clean control — diagnose: 0, baseline: 0
- Median wall-clock — diagnose: 1.969s, baseline: 0.548s
- Reproducibility (diagnose run twice on `acc_units`): True

## Limitations (stated, not hidden)

- All evidence is **simulated host-side**. No hardware, no physical
  controller, no on-MCU timing.
- Wall-clock is a compute proxy, not a human time-to-resolution study;
  it excludes the engineer time to build the baseline harness.
- The reference is recorded from the clean adapter + the trained model;
  faults are injected into the deployed side (contracts or artifacts).
- One controller, one input distribution, one deployment target (host).
