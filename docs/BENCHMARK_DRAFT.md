# Fault benchmark — candidate cases (DRAFT, pre-execution)

Status: **candidate case list, defined before execution, NOT yet
independently reviewed and NOT run.** Expected outcomes below are proposed
from the specification (`docs/CONTRACT_ENGINE.md`, `docs/CLAIMS.md`, the
error-code registry) — never by running OpenFlight on the case. Process
freeze: (1) independent reviewer signs off or amends every expectation,
(2) pilot/interview findings (`DISCOVERY_INTERVIEW_GUIDE.md`) may add cases,
(3) the table is versioned and locked, (4) only then is it executed under
`RESEARCH_PLAN.md` §5–§6 scoring. Any post-execution change to an
expectation voids that case and is logged. Prepared 2026-10-15.

## Outcome classes (from `RESEARCH_PLAN.md` §5)

- **V (valid)** — must be accepted; blocking is a false reject.
- **I (invalid)** — demonstrable incompatibility; must be rejected.
- **A (ambiguous)** — insufficient information; tool must name what is
  missing, never guess.
- **U (unsupported)** — outside current capability; tool must say so,
  never silently approximate.

Codes marked `≈` are secondary predictions; the **class + required behavior
is the binding expectation**. A wrong code with correct class/behavior is a
diagnostic-quality finding, not a missed fault.

## Cases

### Physical units

| ID | Setup | Class | Expected behaviour (proposed) |
|---|---|---|---|
| U-01 | Sensor angular velocity `degrees_per_second`, model `radians_per_second` | I | Block: dimension/units clash, both sides named ≈E101/E102, no artifacts |
| U-02 | Both sides declare the same unregistered token (`units: mystery_unit`) | I | Block despite string equality: registry consulted first ≈U101 (audit P0 regression) |
| U-03 | Sensor feature has no `units` key | I | Block: undocumented units cannot be verified ≈E001/U101 |
| U-04 | Sensor declares gravitational-acceleration units, model declares `m/s^2`, conversion supported | V | Accept; generated adapter applies `×9.80665`; composed parity within tolerance |
| U-05 | Both sides declare the same registered, plausible unit | V | Accept, conversion = identity, parity within tolerance |
| U-06 | Registered unit but implausible for the quantity (length unit on angular channel), both sides matching | I | Block: plausibility check independent of equality ≈E102 |
| U-07 | Sensor unit string is free-form nonsense on one side only | A | Block naming the unverifiable token and which side; must not accept ≈U101 |

### Scale / observed-data boundary

| ID | Setup | Class | Expected behaviour (proposed) |
|---|---|---|---|
| S-01 | Both sides declare `m/s^2` but a supplied reference trace shows values scaled as cm/s^2 | I (physical) | Gate **accepts** declarations (documented boundary); when trace/check path is used, the scale disagreement must be **reported, not silently reconciled**; report must not claim physical verification. Gate-accept here is a recorded limitation, not a pass for the case |
| S-02 | Supported unit conversion exists but adapter output is wrong by 10× (seeded adapter defect) | I | End-to-end/reference comparison must fail the deploy; silent success = case failure |

### Feature ordering

| ID | Setup | Class | Expected behaviour (proposed) |
|---|---|---|---|
| F-01 | Model features reference components in an order not determined by `raw_layout` | I | Block: ordering undetermined ≈E402/E206-class |
| F-02 | Sensor order and model order differ, with an explicit, complete declared mapping | V | Accept; generated adapter reorders; composed parity within tolerance |
| F-03 | Two channels swapped relative to training with no distinguishing declaration | A | Cannot establish mapping; tool must say what evidence is missing, never guess |

### Coordinate frames

| ID | Setup | Class | Expected behaviour (proposed) |
|---|---|---|---|
| FR-01 | Sensor declares `world`, model expects `body`, no declared transform | I | Block: frame mismatch ≈U302 |
| FR-02 | Model declares `frame: independent`, sensor declares `body` | V | Accept (frame-irrelevance rule), parity within tolerance |
| FR-03 | Model omits frame, sensor declares one | I | Block: unverifiable without model frame ≈U302 |
| FR-04 | Frame value `none` or `any` | I | Block structurally; never interpreted as a frame ≈E303 |

### Quaternion representation

| ID | Setup | Class | Expected behaviour (proposed) |
|---|---|---|---|
| Q-01 | Declared ordering `wxyz` vs sensor `xyzw` labels | I | Block; tool refuses to guess which side is right ≈E403 |
| Q-02 | Consistent declared ordering, quaternion features dimensionless | V | Accept; parity within tolerance (W203/W204 as specified) |

### Normalisation

| ID | Setup | Class | Expected behaviour (proposed) |
|---|---|---|---|
| N-01 | Deployment normalisation constants differ from training metadata | I | Must not validate silently: either gate-diagnose or fail the composed numerical check; silent accept = case failure |
| N-02 | Normalisation correctly declared and applied per supported pipeline | V | Accept; intermediate + final comparison within tolerance |

### Missing information

| ID | Setup | Class | Expected behaviour (proposed) |
|---|---|---|---|
| M-01 | Required sensor units absent (see U-03) — cross-listed for category counting | I | Block ≈E001/U101 |
| M-02 | Model contract lacks `raw_layout` component referenced by a feature | I | Block: binding target missing ≈E402 |
| M-03 | Deploy attempted with no contracts supplied | A/I | Block by default ≈E003; `--allow-unvalidated` path is out of scope and must be labelled SKIPPED, never validated |

### Ambiguous bindings

| ID | Setup | Class | Expected behaviour (proposed) |
|---|---|---|---|
| A-01 | Duplicate `(quantity, component)` in `raw_layout` | I | Refuse at schema load and at the checker; no artifacts ≈E002/E206 (audit P1 regression) |
| A-02 | One model feature, two candidate sensor sources, no disambiguating evidence | A | Name the ambiguity and the missing discriminator; never pick arbitrarily |

### Stale evidence

| ID | Setup | Class | Expected behaviour (proposed) |
|---|---|---|---|
| ST-01 | Model weights changed after `evidence record` | I | Dependent checks report `STALE`, `evidence status` exits nonzero |
| ST-02 | `openflight/evidence.py` edited | I | All checks stale (documented over-approximation) |
| ST-03 | Unrelated documentation edited (control case, both-sides) | V | No check goes stale; status stays exit 0 |
| ST-04 | `results/e2e_pipeline.json` edited after record | I | e2e check stales |

### Valid conversions and alternatives (must-accept)

| ID | Setup | Class | Expected behaviour (proposed) |
|---|---|---|---|
| V-01 | Full `g → m/s^2` deploy of the example model, host target | V | Deploy succeeds; `artifact_shas` recorded; composed path parity within pre-registered tolerance |
| V-02 | Non-default but valid configuration (different supported arch with matching contracts) | V | Accept; parity within tolerance |
| V-03 | Supported angular conversion `degrees_per_second → radians_per_second` both directions declared | V | Accept with generated conversion, or reclassify to U **only if** the reviewer rules it unsupported — ruling required pre-lock |

### Unsupported / malformed (must explain, not approximate)

| ID | Setup | Class | Expected behaviour (proposed) |
|---|---|---|---|
| UN-01 | Model architecture outside the supported subset | U | Explicit unsupported refusal; no generated artifacts |
| UN-02 | Feature `width: "three"` (non-integer) | I | Structured width diagnostic, not an exception ≈E207 |
| UN-03 | Non-string `units` on both sides | I | Structured block, not a false PROCEED ≈U101/E002 |
| UN-04 | Contract width 6 vs model input width 60 | I | Block **before** generation; staging discarded; report `result: failed`, `artifact_shas {}` ≈E203 (audit P1 regression) |
| UN-05 | Weight tensor shape mismatch with aligned keys | I | Diagnosed exit 3, no raw traceback, staging discarded ≈E030 (audit regression) |

**Count: 37 cases** — V: 10, I: 22, A: 4 (M-03 counted as A/I at
reviewer's ruling), U: 1 (plus reclassifications pending review). Category
coverage matches `RESEARCH_PLAN.md` §5 and the reviewer's 12-category table.

## Known-limitation cases (scored as specification, not as tool failure)

S-01 (declarations agree, physical scale wrong) is the pre-registered test
of the declaration-vs-observation boundary: the *gate* is expected to
accept; the *case* passes only if the limitation is stated wherever the
result is reported and the supplied trace path reports the disagreement.
It must never be tallied as evidence the checker "catches physical errors."

## Independent review requirement (blocking)

1. Reviewer did **not** implement the checker; reviews blind to any tool
   output on these cases (nothing has been run — keep it that way until
   sign-off).
2. Reviewer may amend any expected class/behaviour and add cases; every
   amendment is logged in the lock table with rationale.
3. Minimum bar: ≥30% of cases independently authored or re-authored by the
   reviewer, and every `I` case's fault documented as realistic in the
   literature or from discovery interviews.

## Scoring (pre-fixed, from `RESEARCH_PLAN.md` §5)

Per workflow (A conventional / B careful-manual / C OpenFlight), report raw
counts and percentages: invalid correctly rejected · invalid accepted (false
accepts, reported immediately) · valid rejected (false rejects) · diagnosis
judged correct and useful · end-to-end numerical agreement on valid cases ·
time to identify and fix · manual interventions. Preserve every raw output,
command, environment, and exit code — including failures; no silent fixes
and reruns. If reviewer sign-off or discovery interviews invalidate a
category, the case is retired with a logged reason, never silently dropped.
