# Contract Engine (2026-10-11) — validation before generation

## Workflow

```
Simulator ---> raw sensor vector (raw_layout)
                     |
Model contract ------+---> checker (units/frames/order/norm) --BLOCKED--> stop, exit 2
                     |
                   PROCEED
                     |
              pipeline codegen (contract_adapt.py/.h, Py+C++)
                     |
              inference codegen (model.h/.cpp)
                     |
              differential tests + manifest (contract_manifest.json)
```

## Commands

```bash
python -m openflight.cli validate --contract sensor.yaml \
    --model-contract model.yaml [--format text|json]
python -m openflight.cli deploy --model w.pt --arch mlp:6,16,2 \
    --contract sensor.yaml --model-contract model.yaml --output build/
```

`deploy` without `--model-contract` behaves as before (no contract gate) but
prints a stderr **WARNING** and records `contract_validation: skipped` — the
gate is opt-in, and a skipped gate is never reported as a pass. With
contracts, any failure stops deployment **before** code generation.

## Semantics (the honest rules)

- Convertible units (same dimension) → conversion **generated** (`unit_scale`,
  y=ax), recorded in the report, proven by the Py/C++ parity test. Not "detected
  as an error": the math is unambiguous, so generating is correct.
- Incompatible dimensions → **E101 BLOCKED**. Unknown unit strings → **U101
  BLOCKED** (never guessed). A registered unit that is implausible for the
  declared quantity (e.g. `metres` on a gyro, even when both sides agree) →
  **E102 BLOCKED** — both declarations can be wrong together.
- Frame required but undocumented → **U301 BLOCKED** ("cannot verify", not
  "compatible"). Frame mismatch → **E301 BLOCKED** (no rotation is invented).
  Model declares no frame while the sensor documents one → **U302 BLOCKED**
  (unverifiable is never compatible). A model feature may instead declare
  `frame: independent` to assert frame-irrelevance explicitly — the only
  value that skips frame verification. Reserved ambiguous words
  (none/any/invariant/unknown/null/n/a) on either side → **E303 BLOCKED**
  (diagnosed as not-a-frame, never compared as a mismatch); `independent`
  on the sensor side is likewise E303 (sentinel is model-only).
- Unit plausibility: quantities map to a SET of allowed dimensions;
  `orientation` admits `angle` and `dimensionless` (projected gravity /
  direction cosines). Orientation-in-metres, gyro-in-metres etc. → **E102
  BLOCKED** even when both sides agree.
- Quaternion features must declare ordering (schema rejects otherwise, E204);
  sensor/model ordering mismatch → **generated reorder** (positions permuted,
  verified: `w<-3,x<-0,y<-1,z<-2` for xyzw→wxyz). The sensor's declared
  ordering is load-bearing: it is checked against raw_layout's component
  order for that quantity; a contradiction → **E403 BLOCKED** (the labels
  and the declaration cannot both be right). A quaternion feature with no
  units key defaults to dimensionless with warning **W204** (magnitude is
  dimensionless by definition); explicit non-dimensionless units warn
  **W203**. Non-quaternion features must declare units (**E202** if missing).
- Normalization affine with numeric, finite, nonzero scale/offset →
  **generated** (`normalize_affine`); `none` → W202 warning; malformed
  (missing/non-numeric/non-finite) → **E201 BLOCKED** (never a traceback);
  zero scale → **E205 BLOCKED** (non-invertible).
- Feature widths must sum to the compiled model's input dim → **E203 BLOCKED**
  (checked against the real compiled model in `deploy`, not just the contract).
- Bias required but unconfigured → **E302 BLOCKED**; otherwise W201 warning.
- Contract edits after generation → `check_stale` flags them (last fault row).

## Fault-injection results (executed, `test_fault_injection.py`)

10/10 faults blocked or converted-and-verified; valid configs pass
(false-reject test included). Per-fault codes: F1 conversion recorded, F2
reorder recorded, F3 E101, F4 E201, F5 E301, F6 E302, F7 U101, F8 E101,
F9 E203, F10 stale-manifest hit.

## External-review probes (executed, `test_reviewer_probes.py`, 2026-10-13)

Seven fault classes an external reviewer reproduced against the pre-review
engine, now permanent regressions: P1 sensor-ordering decorative → E403 +
permutation verified in generated ops; P2 model-frame fail-open → U302;
P3 units implausible for quantity → E102; P4 malformed normalization
crash → E201/E205 block; P5 checker/pipeline quat-units disagreement →
E202 + diagnosed build_ops error; P6 E201 overload → E201/E202 split;
P7 silent gate skip → stderr WARNING + SKIPPED (not PASS). Registered in
TEST_PLAN.md; deliberately separate from the frozen held-out suite.

## Known limits

- No unit conversion for nonlinear scales (temperature-style offsets
  unsupported by design — registry is multiplicative only).
- Frame *transforms* are validated/rejected, not generated (rotation synthesis
  from arbitrary frame conventions remains future work).
- Bias is flagged, not modeled. Timestamps/normalization statistics
  provenance are not yet in the schema.
