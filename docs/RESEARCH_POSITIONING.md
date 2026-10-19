# Research positioning: from deployment tool to diagnostic hypothesis

**Status:** working memo, 2026-10-19. This is a *hypothesis and experimental
plan*, not a novelty claim. The novelty audit below is preliminary; the
systematic review in §8 must be completed before any claim is made.

**Frozen evaluation revision:** `6c64b16e2ea0fce44553ca20a5cf39f603c87bc3`
(tag `eval-frozen-2026-10-19`). Later documentation commits do not change the
behaviour under test; check out the tag explicitly.

---

## 1. Working claim

> A contract-aware diagnostic method can distinguish **justified fault
> localisation** from **unsupported attribution** in deployed ML inference
> pipelines, particularly when faults interact or the available evidence is
> incomplete.

Scope: inference pipelines with a recorded reference execution, where the
deployed path consists of sensor interpretation, preprocessing, model
inference and a compiled artifact. Evidence is currently host-side and
emulated; it is **not** physical-robot validation.

Non-claims, stated up front:

- Not a deployment-verification method that bounds all deployed behaviour.
  "No Soundness in the Real World" shows why that is much harder than it looks
  [Szász et al., ICML 2025].
- Not a bug-finding method that beats compiler fuzzing at finding unknown
  compiler bugs [NNSmith, ASPLOS 2023; ORTHRUS 2025; OATest 2025].
- Not a claim of better localisation accuracy than a hand-written staged
  comparison on ordinary numerical disagreements. The current evidence shows
  parity there, with the baseline faster.
- Not evidence of human usefulness or physical reliability.

The defensible research question is narrower than "deploy embedded ML
correctly":

> **When does the available evidence justify a unique causal diagnosis of a
> deployment-time semantic mismatch, and when must the system abstain?**

## 2. Problem definition

### 2.1 Inputs

- A sensor contract: quantities, components, units, ordering, sample offsets.
- A model contract: feature layout, units, normalization, model input size.
- A recorded reference execution: raw windows, reference model inputs and
  outputs, and the reference artifact identity.
- A deployed execution: the same trace through the deployed path, plus the
  compiled artifacts and their hashes.
- A tolerance rule: `|a - b| <= atol + rtol * |ref|`.

### 2.2 Three questions, not one

1. **Detection:** is there a genuine discrepancy outside tolerance?
2. **Attribution:** what is the earliest stage at which the evidence
   establishes a contract violation?
3. **Justification:** does the evidence distinguish the proposed cause from
   plausible alternatives?

Most differential-testing tools answer (1). Some answer (2) by locating a
stage. Few answer (3) explicitly.

### 2.3 Response taxonomy

| Outcome | Meaning |
|---|---|
| `PASS` | All stages agree within tolerance and the evidence is valid. |
| `DIAGNOSED(h)` | Exactly one candidate cause `h` is consistent with the evidence; every alternative is refuted by at least one observation. |
| `AMBIGUOUS(H')` | Two or more candidate causes remain consistent; the report names `H'` and the observation(s) that would discriminate them. |
| `INVALID` | A validity predicate fails (non-finite input, shape/dtype mismatch, unreadable artifact). No attribution is made. |
| `INSUFFICIENT` | The evidence needed to decide is missing or unusable; no attribution is made. |

A structured error code is **not** automatically a justified diagnosis. The
code must be tied to the evidence that produced it.

### 2.4 Formal sketch

Let `C` be a finite set of candidate causes generated from the contracts
(unit error, component order, normalization, compiled-inference divergence,
artifact version, and their combinations). Let `E` be the observed stage
comparisons plus validity predicates.

- `h` is **consistent** with `E` if the comparison pattern predicted by `h`
  matches `E` under the tolerance rule.
- Let `Cons(E) = { h in C : h consistent with E }`.
- `DIAGNOSED(h)` iff `Cons(E) = {h}`.
- `AMBIGUOUS` iff `|Cons(E)| > 1`.
- Each diagnosis carries a **discriminating certificate**: for every
  `h' != h`, the minimal observation(s) that refute `h'`.

This is a specialization of consistency-based model-based diagnosis
[Reiter 1987; de Kleer & Williams 1987]. The logic is not new. The candidate
contribution is the *instantiation*: executable deployment contracts,
stage-level counterfactual evidence, validity gating, and a certificate that a
third party can check.

## 3. What the current evidence establishes

Source: the 2026-10-18 single-session, two-agent evaluation of 24
pre-registered cases against revision `c6c3f9f`, plus the author re-runs. The
benchmark artifacts live in the evaluator's environment, not this repository.

### 3.1 Established (within that benchmark)

- 7/7 runtime faults localised to the expected stage.
- 5/5 valid controls accepted with no false diagnosis.
- 4/4 invalid-evidence cases returned structured rejections; the baseline
  invented a stage twice and crashed twice.
- 8/8 invalid configurations blocked; three reported `E002` instead of the
  documented `E201`/`E205`/`E203`.
- Repeated diagnoses were equivalent.
- Tolerance-edge case: per-stage errors within tolerance, end-to-end
  divergence; the stage pattern was identified.
- Baseline: 12/12 localisation at 1.07 s median versus 3.67 s for OpenFlight.

The three pre-fix misses were a **diagnostic-interface inconsistency**, not
three detection failures. They were fixed at `ef43715` (semantic schema
violations now carry their documented codes) and the no-artifact guarantee is
tested at `6c64b16`. The original 21/24 result is preserved as historical
evidence; a 24/24 re-run at the frozen revision is expected but must be
produced by the evaluator, not assumed.

### 3.2 Not established

- Generalisation beyond 24 cases, one model architecture, host-side execution
  and one evaluation session.
- Statistical significance of any difference.
- Novelty relative to the closest work (§4).
- That the invalid-evidence advantage is robust rather than an artefact of the
  baseline implementation.
- That extra diagnostic cost buys a measurable debugging benefit.
- Any physical-robot or cross-platform reliability.
- That a `DIAGNOSED` stage label is causal rather than the location where a
  symptom first becomes visible.

## 4. Related work and gap audit (preliminary)

### 4.1 Comparison

| Work | Goal | Evidence used | What it establishes | What it cannot establish | Relation to OpenFlight |
|---|---|---|---|---|---|
| NNSmith (ASPLOS'23) | Find DL-compiler bugs | Generated valid graphs, differential execution | Discrepancy exists; 72 bugs, 51 fixed | Root cause; semantic deployment contracts; when to abstain | OpenFlight is not a compiler fuzzer |
| ORTHRUS (2025) | Detect optimization bugs and aid localisation | Optimizable vs optimization-resistant twins | Which optimization triggers a divergence | Deployment contract violations; ambiguity semantics | Closest on "root cause", but compiler-internal |
| OATest (2025) | Optimization-aware compiler tests | Pattern-guided graphs, differential testing | More compiler bugs, higher coverage | Semantic deployment attribution | Orthogonal |
| Opera (2024) | Test model-loading stage | Library tests migrated to compilers | Loading-stage bugs | Runtime diagnosis | Orthogonal |
| No Soundness (ICML'25) | Expose verification limits | Deployment-environment-sensitive nets | Theoretical soundness does not imply practical soundness | Any diagnostic method | Motivates deployment-aware evidence; OpenFlight does not solve it |
| RAPT (2026) | Runtime OOD detection + failure diagnosis for humanoids | Proprioceptive trajectories, saliency, LLM | 75% root-cause classification over a failure taxonomy; single platform | Contract-level semantic mismatches; evidence-bounded abstention; uniqueness | Closest robotics diagnosis; different evidence and no abstention guarantee |
| SEI ML mismatch (2021–) | Characterise and prevent ML mismatch | Machine-readable descriptors, stakeholder assumptions | Mismatch taxonomy; design-time descriptors; TEC tool | Runtime attribution; counterfactual evidence; ambiguity | OpenFlight contracts are an instance of this idea, not an invention |
| MLDebugger (2020) | Minimal causes of pipeline failures | Provenance + selected re-runs | Minimal cause set for performance failures | Deployment semantic mismatches; invalid evidence; uniqueness certificates | Closest on causal minimality; different failure model |
| ML observability (2021, vision) | Detection, diagnosis, reaction | Pipeline telemetry | Research agenda | A method | OpenFlight is one instantiation |
| PROXAI (PVLDB 2025) | Provenance-aware debugging | XAI influence + lineage | Preprocessing root causes for model behaviour | Deployment contracts; compiled artifacts; abstention | Close on preprocessing lineage; training-data focus |
| Contract-based conceptual bugs (MODELS 2024) | Prevent ML design bugs | Contracts over partial ML designs | Design-time detection of assumptions like unscaled data | Runtime evidence; ambiguous causes | Very close on contracts; design-time, not diagnosis |
| Preprocessing verification (2025) | Verify declared preprocessing was applied | Black-box behaviour indicators | Binary check and multi-class missing-step diagnosis | Deployment artifacts; evidence validity; uniqueness | Close on preprocessing diagnosis |
| Selective prediction (2010–2019) | Abstain when prediction is uncertain | Confidence/risk-coverage | Controlled risk-coverage trade-offs | Causal attribution; diagnosis | Supplies the abstention vocabulary; not causal |

Foundational: consistency-based diagnosis and candidate discrimination are
well established [Reiter 1987; de Kleer & Williams 1987]. OpenFlight's response
taxonomy is a specialization of that framework, not a new logic.

### 4.2 Ingredients that are explicitly not novel

- Differential testing between a reference and a deployed implementation.
- Machine-readable contracts/descriptors for ML system assumptions.
- Stage-level localization of a divergence.
- Provenance, hashing and reproducible bundles.
- Abstention under uncertainty.
- Consistency-based diagnosis and competing-hypothesis elimination.

### 4.3 Candidate differentiators (to be falsified)

- **D1 — Evidence validity gating.** Invalid evidence produces a structured
  rejection, never a stage attribution. *Falsified if* a baseline or simpler
  validity check matches OpenFlight's unsupported-assertion rate on corrupted
  evidence.
- **D2 — Ambiguity-aware abstention with a certificate.** When two causes are
  observationally indistinguishable, OpenFlight reports both and the
  discriminating observation, rather than choosing one. *Falsified if*
  abstention is indistinguishable from always-abstaining (no coverage
  advantage) or from a confidence threshold on the baseline.
- **D3 — Interaction and identifiability.** OpenFlight detects masking
  (faults that cancel), amplification (tolerance-edge composition) and
  collisions (distinct causes, same evidence), and reports the limits.
  *Falsified if* a staged comparison has the same cause-level accuracy on the
  interaction suite.
- **D4 — Reproducible justification.** The bundle lets an independent party
  replay the evidence and check the certificate, not merely reproduce the same
  answer. *Falsified if* replay success is no better than a logging script, or
  if a reproducible diagnosis is still unsupported.

The unoccupied intersection, if it survives review, is: **evidence-validity-
gated, certificate-backed attribution with explicit ambiguity/abstention for
deployment-time semantic mismatches in ML inference pipelines.** That sentence
is the only candidate novelty claim; it is not yet established.

## 5. Experiment plan

### 5.1 Experiment A — serious benchmark (60–100 cases)

Keep the 24-case benchmark frozen as historical evidence. Build a new,
independently authored benchmark across these dimensions:

| Dimension | Levels |
|---|---|
| Fault family | units, ordering, preprocessing, compiled inference, artifact/version, combinations |
| Interaction | single fault, masking pair, amplifying pair, tolerance-edge |
| Evidence quality | complete, missing, corrupted, non-finite, unreadable |
| Identifiability | unique cause, observationally equivalent pair, underdetermined |
| Numerical regime | ordinary, near-tolerance, boundary-crossing composition |
| Pipeline configuration | at least two architectures, two contracts, host and emulated targets |
| Expected response | diagnosis, structured rejection, justified abstention |

At least half the cases should be contributed by an independent author who
does not see OpenFlight's answers. Freeze cases and expected outcomes (hash
before running). For every case record *why* the expected outcome is
justified; ambiguous cases must have ambiguity as the expectation. Target
60–100 genuinely distinct cases, not 100 mutations of one fault.

### 5.2 Experiment B — baselines and ablations

| Arm | Purpose |
|---|---|
| B1 End-to-end numerical diff | Detection only; no stage attribution |
| B2 Hand-written staged baseline | Current comparison method |
| B3 Contracts-only gate | Isolates contract checks without evidence-aware diagnosis |
| B4 Full OpenFlight | Complete method |
| B5 Full minus abstention (forced choice) | Tests D1/D2: does abstention prevent unsupported assertions? |
| B6 Full minus contracts (evidence only) | Tests the contract contribution |
| B7 Full minus certificate | Tests whether the justification record adds checkable support |
| B8 Always-abstain control | Establishes the coverage floor; prevents rewarding a system that never diagnoses |

B3 and B5 are the key ablations: without them a result cannot be attributed to
the evidence machinery rather than to contracts or to extra caution.

### 5.3 Experiment C — metrics and statistics

Primary outcomes, pre-registered before looking at results:

1. **Unsupported assertion rate** on ambiguous/invalid/underdetermined cases
   (asserted cause not in the ground-truth cause set).
2. **Appropriate abstention rate** on ambiguous/invalid cases.
3. **Exact cause-localisation rate** on identifiable cases.

Secondary: missed faults; false rejections of valid controls; over-abstention
(identifiable case, no diagnosis); reproducibility (two runs, semantic
equality); bundle replay success; diagnostic compute time; overhead relative
to B1/B2.

Report per fault family, evidence quality and identifiability. Do not collapse
into one accuracy number; a system that guesses can look good on easy cases.
Use paired comparisons (same cases for every arm), McNemar for paired binary
outcomes, bootstrap confidence intervals, and pre-registered primary endpoints.
Distinguish **diagnostic computation time** from **time to a correct
conclusion**; only the latter speaks to usefulness.

Failure criteria, stated in advance: if B5 (forced choice) matches full
OpenFlight on unsupported assertions, D1/D2 are not supported. If B2 matches
full OpenFlight on cause-level accuracy in the interaction suite, D3 is not
supported. If B8's coverage-adjusted performance is indistinguishable, the
abstention mechanism adds nothing.

### 5.4 Experiment D — identifiability and interaction

For each pair of causes, construct evidence under each and measure whether the
method separates them. Report a distinguishability matrix: unique, colliding,
or masking. Include controlled interventions where one factor changes and the
rest are held fixed. This is the causal core of the work and the most likely
source of a publishable negative result: some faults are fundamentally
indistinguishable from observable evidence, and the correct behaviour is to
say so.

### 5.5 Experiment E — human usefulness (later)

A small expert study (robotics/ML engineers) measuring time-to-correct-cause
and trust calibration with and without the bundle. Not a substitute for the
benchmark, and not needed to falsify the core claim.

## 6. Method specification to write (implementation-independent)

1. Contract semantics: quantities, components, units, ordering, offsets,
   normalization, artifact identity.
2. Validity predicates over inputs, traces, contracts and artifacts.
3. Candidate-cause generation from contract violations.
4. Evidence model: stage comparisons, tolerance rule, propagation.
5. Decision rule: `PASS` / `DIAGNOSED` / `AMBIGUOUS` / `INVALID` /
   `INSUFFICIENT`, with the certificate definition.
6. What the bundle must contain for third-party replay.
7. Explicit limits: what the method cannot distinguish and why.

If the method cannot be stated without reference to the implementation, it is
not yet a research method.

## 7. Threats to validity

- **Oracle trust:** the reference trace and model are treated as ground truth;
  they have their own bugs. This is the same trusted-computing-base criticism
  levelled at differential testing [ORTHRUS 2025].
- **Case-author bias:** the evaluator may design cases that favour the method;
  hence independent authorship and pre-registration.
- **Artificial faults:** injected faults may not reflect field failures.
- **Tolerance choice:** results can hinge on `atol`/`rtol`; pre-register and
  report sensitivity.
- **Single architecture / host-side evidence:** limits generalisation.
- **Statistical power:** 60–100 cases supports coarse paired comparisons, not
  fine-grained claims; report intervals.
- **Evaluator bias:** single-agent, single-session evaluations are preliminary;
  independent replication is required.
- **Reproducibility ≠ correctness:** a flawlessly reproducible wrong diagnosis
  is still wrong; the certificate is meant to address this, and must itself be
  evaluated.

## 8. Immediate next actions

1. **Systematic novelty review** (before any claim): ACM DL, IEEE Xplore,
   arXiv, PMLR, USENIX; queries around contract-based ML diagnosis,
   consistency-based diagnosis for ML pipelines, evidence-bounded attribution,
   abstention in diagnosis, deployment-semantic mismatch; forward/backward
   snowballing from NNSmith, ORTHRUS, RAPT, SEI mismatch, MLDebugger, PROXAI,
   and the MODELS contract paper. Produce a comparison matrix with explicit
   "cannot establish" columns. Timebox and stop at saturation.
2. **Write the method specification** (§6) independently of the code.
3. **Evaluator re-run** of the frozen 24-case benchmark at
   `6c64b16` (tag `eval-frozen-2026-10-19`); preserve the original 21/24 result.
4. **Independent held-out evaluation** per
   `docs/HELDOUT_EVALUATION_BRIEF.md`.
5. Only then build Experiment A/B/C/D. No new features in the meantime.

## 9. Deliverables mapping

| Advisor deliverable | Artifact |
|---|---|
| Rigorous related-work study | §4 expanded by §8.1 into a full matrix |
| Precise technical method | §6 specification, implementation-independent |
| Independently designed benchmark | Experiment A, frozen and published with reasons |
| Evaluation against baselines | Experiment B/C/D with ablations and intervals |
| Defensible paper | Written only after the above; negative results included |

## References

- Liu et al. *NNSmith: Generating Diverse and Valid Test Cases for Deep
  Learning Compilers.* ASPLOS 2023. https://arxiv.org/abs/2207.13066
- Shen et al. *ORTHRUS: Detecting Deep Learning Compiler Optimization Bugs.*
  2025. https://csslab-ustc.github.io/publications/2025/dl-no-opt.pdf
- Shen et al. *Optimization-Aware Test Generation for Deep Learning
  Compilers.* 2025. https://www.alphaxiv.org/abs/2511.18918
- *A Tale of Two DL Cities: When Library Tests Meet Compiler (Opera).* 2024.
  https://arxiv.org/abs/2407.16626
- Szász, Bánhelyi, Jelasity. *No Soundness in the Real World: On the Challenges
  of the Verification of Deployed Neural Networks.* ICML 2025.
  https://proceedings.mlr.press/v267/szasz25a.html
- Munn et al. *RAPT: Model-Predictive Out-of-Distribution Detection and Failure
  Diagnosis for Sim-to-Real Humanoid Robots.* 2026.
  https://arxiv.org/abs/2602.01515
- Lewis, Bellomo, Özkaya. *Characterizing and Detecting Mismatch in
  Machine-Learning-Enabled Systems.* WAIN@ICSE 2021.
  https://arxiv.org/abs/2103.14101 · TEC tool:
  https://www.sei.cmu.edu/projects/automating-mismatch-detection-in-ml-systems/
- *Debugging Machine Learning Pipelines (MLDebugger).* 2020.
  https://arxiv.org/abs/2002.04640
- Shankar, Parameswaran. *Towards Observability for Production Machine Learning
  Pipelines.* 2021. https://arxiv.org/abs/2108.13557
- Lazzaro et al. *PROXAI: Interactive Provenance-Aware Debugging of Machine
  Learning Pipelines.* PVLDB 19. https://www.vldb.org/pvldb/vol19/p4706-lazzaro.pdf
- *Contract-based Validation of Conceptual Design Bugs for Engineering Complex
  Machine Learning Software.* MODELS 2024.
  https://dl.acm.org/doi/10.1145/3652620.3688201
- Li et al. *Privacy-Preserving Verification of ML Preprocessing via Model
  Behavior Indicators.* IEEE Transactions on Privacy, 2025.
  https://pmc.ncbi.nlm.nih.gov/articles/PMC12807549/
- El-Yaniv, Wiener. *On the Foundations of Noise-free Selective
  Classification.* JMLR 2010. https://www.jmlr.org/papers/v11/el-yaniv10a.html
- Geifman, El-Yaniv. *Selective Classification for Deep Neural Networks.*
  NeurIPS 2017. https://arxiv.org/abs/1705.08500
- Reiter. *A Theory of Diagnosis from First Principles.* Artificial
  Intelligence 32(1):57–95, 1987.
- de Kleer, Williams. *Diagnosing Multiple Faults.* Artificial Intelligence
  32(1):97–130, 1987.
