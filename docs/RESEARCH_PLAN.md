# OpenFlight research plan (post-v0.2.6)

Status: **planning document — no implementation is authorised under it.**
Written 2026-10-15 on the external reviewer's recommendation, while the
v0.2.6-pilot release stays frozen and the independent second-machine
reproduction, reviewer re-audit, and permissions/consent checks are
outstanding. Prior versions of the protocol and the related-work brief live
in `PILOT_PREREGISTRATION_v0.2.6.md` and `LITERATURE.md`.
**Amended 2026-10-17** on the advisor's strategic recommendation: the
project now carries two candidate problems under adjudication (§1). No new
planning document was created; the amendment is in-place. All gates,
preregistration, and the feature gate are unchanged.

## 1. The problem space (two candidates under adjudication)

### H1 — the validated fallback (current engineering identity)

> The difficulty of establishing that a deployed neural network is
> receiving the sensor data it was actually designed and trained to
> process — and of reproducing the evidence that supports that conclusion.

This combines two documented pain points (robotics reproducibility, and
heterogeneous components disagreeing about what data means) with
**sensor-to-model semantic correctness as the distinctive contribution**.
OpenFlight is not a general robotics testing platform, not a general
reproducibility tool, and not a general ML-mismatch detector.

Vision statement (H1):

> OpenFlight is a research tool for establishing trustworthy, reproducible
> sensor-to-model integration in embedded robotics. It represents model and
> sensor semantics as machine-checkable contracts, generates supported
> transformations, validates the composed inference pipeline, and tracks the
> evidence supporting each deployment claim. Its research objective is to
> determine whether this approach can reduce undetected integration errors
> and verification effort without creating excessive false rejections.

### H2 — the candidate broader problem (advisor recommendation, 2026-10-17)

> Why does a learned robot controller that performs well during training
> and simulation fail, slow down or behave differently when deployed — and
> how can researchers identify the cause without spending enormous amounts
> of time debugging the entire system?

Candidate value proposition (H2):

> OpenFlight helps robotics researchers diagnose why learned controllers
> change behavior when deployed, through reproducible comparisons of the
> model, input pipeline and embedded execution environment.

Central question (H2), measurable and falsifiable:

> Can differential, closed-loop testing isolate deployment-induced
> failures in learned robotic controllers more effectively than existing
> export checks, manual debugging and ordinary inference benchmarks?

The literature establishes the wider challenges (sim-to-real reality gap,
real-time inference, reliable evaluation, reproducible pipelines) — **it
does not yet establish demand for this specific tool.** H2 is a hypothesis
to test against researchers' actual experience, not a decided pivot.

### Adjudication rule (fixed)

H1 and H2 compete on evidence from the discovery interviews (§7). Until
that evidence exists: H1 remains the validated identity of the frozen
v0.2.6 engineering and the pilot; H2 is investigated only through
interviews and literature. If the interviews surface repeated
deployment-failure-diagnosis pain that existing tools do not address, the
plan adopts H2 and the stages in §10 sequence its prototype work. If they
do not, H1 stands or narrows — a finding either way. No implementation of
H2 begins before the Stage 1–2 gates clear.

## 2. Central hypothesis (falsifiable)

> Machine-checkable semantic contracts and generated adapters reduce
> undetected sensor-to-model integration errors compared with conventional
> export and careful manual integration, without causing an unacceptable
> rate of false rejections.

Any outcome is informative: catching more faults, reducing effort, excessive
false rejection, or no benefit over competent manual practice each refines
the research question. Until the benchmark exists this is a *question*, not
a claim; CLAIMS.md already keeps it under "Explicitly NOT claimed."

H2's falsifiable form (candidate, pending §7 evidence):

> On at least one supported learned-controller workflow, an automated
> differential pipeline (reference vs deployed implementation on identical
> inputs, plus controlled closed-loop perturbations) isolates the cause of
> a deployment-behavior change in less researcher effort than export
> checks + manual debugging + ordinary inference benchmarks, and produces
> a reproducible failure case another person can rerun.

Falsifiers include: researchers report the pain rarely; existing tools
already close it; or the prototype fails to isolate causes better than a
competent baseline. Simulation-only evidence can never be presented as a
physical-robot or safety result (§11).

## 3. Differentiation discipline

Do not claim novelty for mismatch detection (SEI/Lewis et al. TEC), embedded
code generation or profiling (Edge Impulse; TFLite/STM32Cube.AI/ONNX), or
reproducibility packaging (IROS 2016 automated-reproduction work and
successors). `LITERATURE.md` holds the verified related-work table and the
narrowest defensible novelty claim (the *combination*, to be tested).

Three possibilities to investigate with evidence, keeping whichever survives:

1. Existing tools validate model execution but establish too little about
   sensor semantics → OpenFlight's check is stronger.
2. Similar problems are detectable but only via manual configuration →
   OpenFlight's contribution is automation/effort/fewer mistakes.
3. Existing tools already cover the important cases → the research
   question changes; that is a finding, not a failure.

Competition discipline (added 2026-10-17, if H2 is investigated): do not
compete on capabilities that established work already owns. Embedded
inference latency/accuracy/energy benchmarking → **MLPerf Tiny** (v1.3,
2025). Scalable real-world policy ranking → **RoboArena** (7 institutions,
600+ episodes). General robot-learning infrastructure and transfer
pipelines → open end-to-end platform work (Berkeley EECS 2026-163). The
candidate opportunity is narrower: *isolating deployment-induced failures
in learned controllers with reproducible evidence* — a gap to test with
interviews, not a demonstrated hole.

Relevant concerns from the literature (for the eventual related-work
section): robotics reproducibility (*Nature Machine Intelligence* 2025,
"Towards reproducible robotics research"; Lynnerup et al., CoRL 2020 —
real-robot RL reproducibility), ROS software engineering gaps (JSS mapping
study, 63 studies), testing/TVV maturity for autonomous systems (TOSEM
systematic review, 195 studies), and structured evaluation practice
(MLPerf Tiny; ACM artifact-review functional/reusable/reproduced
distinctions). For H2's related-work section specifically: sim-to-real
reality-gap review (Annual Review of Control, Robotics, and Autonomous
Systems, 2024), foundation-model real-time challenges (IJRR survey,
2024), and distributed real-world evaluation (RoboArena, PMLR 2025).

## 4. Research contributions (in priority order)

| # | Contribution | Priority | Notes |
|---|---|---|---|
| B | **Independently reviewed fault benchmark** (§5) | Highest next research task | Tests the central hypothesis directly |
| C | **Evidence graph completeness** — do tracked dependencies match what checks actually read, and are the conclusions trustworthy under mutation? | High | Foundation exists (60 mutation tests); needs *independent* evaluation, not more self-tests |
| A | **Formal model of sensor-to-model semantic compatibility** — quantity/units/frame/representation/order/normalisation/transforms; what is decidable from declarations vs executable tests vs external physical evidence | Medium | The declaration-vs-observation boundary must stay explicit (contracts check declarations, never physical reality — CLAIMS C5 boundary b) |
| D | **Reproducible deployment study** on realistic models, with external reproduction | After B | Persuasive only when run by others |

Development priorities held in reserve until the benchmark shows what
matters (reviewer's table): diagnostics quality and composed-pipeline
validation are *high if user evidence supports them*; more architectures,
GUIs, and more targets are *low now*.

## 5. Fault benchmark requirements (design before execution)

Candidate case list and pre-fixed scoring: `BENCHMARK_DRAFT.md` (37 cases,
awaiting independent sign-off before any execution).

- ~30–50 specified cases initially, expanding by identified fault category.
- Categories: physical units, unit scaling, feature ordering, coordinate
  frames, quaternion ordering, normalisation, missing information, ambiguous
  bindings, stale evidence, **and valid configurations that must be accepted**.
- Every case's correct outcome is fixed **before** running the tool, in one
  of four classes:
  - **Valid** — must be accepted;
  - **Invalid** — demonstrable incompatibility, must be rejected;
  - **Ambiguous** — insufficient information; the tool must say what is
    missing rather than guess;
  - **Unsupported** — outside current capability; the tool must say so
    rather than silently approximate.
- A checker that rejects everything must not be able to score well: valid
  cases and false-rejection counts are mandatory.
- Someone who did not implement the checker reviews (or writes) a meaningful
  subset of cases and expected outcomes, blind to what OpenFlight reports.
- Scoring fixed in advance; report **raw counts alongside percentages**:
  invalid correctly rejected; invalid accepted (false accepts — reported
  immediately); valid rejected (false rejects); diagnosis judged correct and
  useful; numerical agreement on valid end-to-end paths; time to identify
  and fix a fault.

## 6. Three-workflow comparison

| Workflow | Description |
|---|---|
| A | Conventional documented export + integration |
| B | Careful manual integration: same requirements/specs, checklist, free inspection |
| C | OpenFlight: contracts, generated adapters, gate, evidence graph |

Baselines are not weakened for the comparison; if manual catches the same
faults, the residual hypotheses are effort, error rate, diagnostic clarity,
and reproducibility — each measured separately. Existing tools (TEC for
mismatch detection, Edge Impulse-class platforms for codegen/profiling) are
added as baselines only where capabilities genuinely overlap, with the
overlap stated. No single ranking of dissimilar tools.

Measures: fault detection, false-rejection rate, diagnostic quality,
task-completion time, manual interventions, end-to-end numerical parity,
resource measurements actually established, and reproducibility of the
reported result.

## 7. Researcher discovery exercise (before building more)

Materials: `DISCOVERY_INTERVIEW_GUIDE.md` (consent preamble, questions,
capture template). Interview ~3–5 researchers who actually deploy learned models into robotic
systems, about their **most recent** deployment (concrete past events, not
reactions to the idea): hardest part; what went wrong; how it was found;
time to diagnose; tools used; automated vs manual checks; any case where the
model ran but produced wrong results because inputs/preprocessing differed;
how they establish embedded-vs-evaluated correspondence; what evidence they
would need to trust an automated tool; what one step they would automate.
Plus the five H2-adjudication probes (added 2026-10-17; fixed wording in the
guide): whether they experienced a controller that worked in simulation or
the original framework but failed after deployment; what caused it; how
long diagnosis took and which experiments isolated it; which tools they used
and what those tools could not establish; whether an automated,
reproducible differential test would have materially changed the
investigation. Then categorise problems and map them against what OpenFlight can realistically
address, feeding the §1 adjudication rule (H1 vs H2) with raw counts. If
the interviews surface that possibility §3.3 holds, narrow the
research question accordingly. Any structured study intended for publication
follows the applicable ethics/consent/data-handling requirements — same rule
as the student pilot.

## 8. Standalone product principle (first ten minutes)

After validation completes, one worked example that demonstrates the core
promise end-to-end: familiar model + honest sensor contract → clean
validation (what was checked / not checked) → deliberate fault blocked with
an actionable diagnostic → valid unit conversion (`g` → `m/s²`, 1.0 g ≈
9.80665) visibly applied by the generated adapter → evidence report naming
model, contracts, adapter, compiled build, checks, limitations. Measure
completion time, interventions, and correct interpretation. Ten minutes is a
design target, not a result.

## 9. Feature gate (standing rule)

No major feature without answers to: which researcher/workflow needs it;
which concrete failure it addresses; what existing capability nearly solves
it; what test shows it works; what measurement shows it is useful; how false
positives/negatives and new failure modes will be caught. Growth is driven
by benchmark and user evidence, not anticipation.

## 10. Sequenced plan with exit criteria

| Stage | Content | Exit condition |
|---|---|---|
| 1. Finish validating v0.2.6 | Second-machine reproduction (verbatim outputs/env/exit codes); reviewer's five-property re-audit once the artefact is retrievable; permissions/consent in parallel; code frozen unless a demonstrated defect forces a separately documented correction | Known which behaviours are independently reproduced vs unverified; any release-blocking defect found and reproduced before changes |
| 2. Host-only pilot (2–3 participants) | Preregistered tasks T1–T7; record false accepts/rejects, diagnosis quality, install friction, interventions | Prioritised, observation-backed list of real usability/correctness problems |
| 3. Discovery + benchmark + adjudication | Researcher interviews (§7, incl. the five H2 probes); 30–50-case benchmark with blind-reviewed expected outcomes; run workflows A/B/C under fixed scoring | Reproducible dataset, raw results, analysis script, account of strengths/weaknesses/unresolved cases; **explicit H1-vs-H2 adjudication decision recorded in this plan** |
| 3b. *Conditional* — H2 deployment-failure prototype | Only if Stage 3 adopts H2. Advisor's order: (1) minimal differential-testing example for ONE supported learned controller (reference vs deployed implementation, identical defined inputs; first meaningful divergence located across input pipeline → preprocessing → network output → timing); (2) simple closed-loop simulator for that example (does the divergence change the simulated trajectory?); (3) controlled deployment perturbations (precision, inference latency, sensor timing/jitter, input noise, dropped observations, resource budget) with measured performance envelope; (4) automatic failure-case preservation (model, inputs, transforms, config, environment, discrepancy — rerunnable by another person); (5) diagnostic value measured against a competent baseline (export checks + manual debugging + ordinary inference benchmarks) | First milestone is not a feature release: one real deployment failure identified, reproduced end-to-end, and diagnosed with evidence the researcher's existing tools did not provide; then a second distinct control task to test generalisation beyond the original example |
| 4. Research package | Problem statement, related work (`LITERATURE.md` expanded to full review), method, design, results, limitations; artefact packaged for external evaluation | Someone outside the project can understand the question, run the evaluation, inspect the evidence, and judge the contribution |

Sequencing note: Stage 3's benchmark design uses Stage 2's observations;
Stage 1's reproduction results gate Stage 2. No coding sprint begins until
Stage 1–2 evidence exists — this includes Stage 3b; H2 prototype work is
equally gated. Stage 3b results are simulation-based and must be labelled
as such; no physical-robot or safety claim without hardware collaboration
(§11). If the pilot or benchmark falsifies the
hypothesis, the research question is refined — features are never added to
conceal a weakness.

## 11. Explicitly out of scope (unchanged)

Safety guarantees, physical-device performance claims (need real silicon
measurements), complete-firmware verification, general robotics testing,
general reproducibility tooling, and any statistical superiority claim from
2–3 participants. These remain in CLAIMS.md's non-claim table until the
corresponding evidence exists.
