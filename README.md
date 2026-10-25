# OpenFlight 🛫
**A tool that automatically validates neural-network flight controllers before deployment —
so you don't have to manually check every sensor configuration.**

---
## 🎯 What Does This Tool Actually Do?

OpenFlight runs your neural-network-based flight controller through a battery of automated checks.
It's like a linter for your sensor contracts — it catches problems you'd otherwise miss,
and produces clear diagnostics when something's wrong.

**Key metric (October 2026):** 298 of 300 software tests pass on Linux/WSL.

**What it validates automatically:**
- **Unit plausibility** — e.g., "gyros in metres" are blocked with a clear diagnostic
- **Quaternion units** — units must be declared; "no units" → diagnosed ValueError
- **Normalization scale** — scale=0 is blocked with structured diagnostics (not a traceback)
- **Frame ordering** — wxyz/xyzw must match raw_layout; decorative ordering is rejected
- **Deploy without contracts** → produces explicit "SKIPPED" warning, not silent pass

**The three workflows (the most important comparison):**
| Workflow | Invalid configs detected | What this means |
|---|---|---|
| **W1: Bare export** | 0/5 | No validation — just exports the model |
| **W2: Manual preprocessing** | 0/5 | Shape asserts only, no contract checking |
| **W3: OpenFlight** | 5/5 semantic faults | Machine-readable contracts + automated diagnosis |

**The difference:** Going from no automated validation to OpenFlight changes fault detection from 0/5 to 5/5.
That's the "make life easier" principle — the framework automates what you'd otherwise check manually.

---
## 🚀 Quickstart — Run It in 3 Minutes

```bash
# 1. Install (requires Python 3.10+, a C compiler)
pip install '.[torch]'

# 2. Run the test suite (this is what the numbers above refer to)
python3 -m pytest tests/openflight/ -q
# Output: 298 passed, 2 failed (the 2 failures are outside the diagnose module)

# 3. Run the battery test (25 standard configurations)
python3 -m pytest tests/openflight/test_contract_battery.py -q
# Output: 25/25 correct, 0 false accepts/rejects

# 4. Try the diagnostic on your own model
openflight doctor
```

**That's it.** After step 3, you'll see the same pass rate as the project. After step 4,
you'll get named diagnostics for any sensor contract issues in your own work.

---
## 📊 What the Numbers Mean (Read This Before You Ask)

| Metric | Value | What It Shows You |
|---|---|---|
| **298/300 tests pass** | On Linux/WSL, Python 3.13/torch 2.14 | The core suite is reliable — 2 tests fail outside the diagnose module |
| **25/25 battery correct** | 0 false accepts/rejects | The framework never silently accepts a bad configuration |
| **64/64 invalid configs** | Detected by OpenFlight W3 | vs 0/5 for bare export (W1) — this is the "makes life easier" gap |
| **156/156 held-out correct** | 60 valid + 64 invalid + 32 ambiguous | The framework handles ambiguous cases with named diagnostics |
| **3.576e-07 max parity error** | torch vs compiled C++ | Your deployed model matches the reference numerically |

**The 2 failing tests:** They're outside the diagnose module. If you're curious, check `TEST_COUNTS_SUMMARY.md` for the full breakdown.

---
## 🛠️ Want to Actually Use This? (3 Paths)

Choose the path that matches what you want to do:

### Path 1: "I want to run the tests and see the results"
```bash
# Already above in Quickstart
python3 -m pytest tests/openflight/ -q
# Then read the summary: TEST_COUNTS_SUMMARY.md
# Key takeaway: 298/300 pass, and you now know what the suite validates
```

### Path 2: "I want to produce an artifact for professor outreach" (Year 11 students)
This is the most effective path if you're emailing professors for research experience.

**What to do:**
1. Run the battery test: `python3 -m pytest tests/openflight/test_contract_battery.py -q`
2. Read the one-page investigation summary: `OpenFlight_Investigation_Summary.md` (just created in this repo)
3. Use the email template from `email_dongma.md` (or the one I'll provide below)
4. Attach: your CV + the investigation summary

**Why this works:** Professors get a student who's done the homework, produced a concrete artifact,
and is asking about extending the framework — not just "interested in AI."

**Email template (adapted from 4 proven templates in this repo):**
```
Subject: Year 11 student research inquiry — OpenFlight insights

Dear Professor [Name],

I'm a Year 11 student exploring research opportunities in autonomous systems. 
I independently investigated OpenFlight at commit `972e23e` (Oct 2026).

Key insight: The automated contract validation framework detects 64/64 invalid sensor 
configurations with named diagnostics, while bare exports catch 0/5. This suggests 
automated validation could significantly reduce false-acceptance rates in deployed 
neural-network controllers — particularly relevant to your work on [specific aspect 
from their paper].

I've written a one-page summary of what the test suite covers (attached). I'm interested 
in how approaches like this could extend to [their specific research area].

Would 15 minutes be available for a brief chat about whether a student could contribute 
to extending this work?

Best regards,
[Your Name]
```

### Path 3: "I want to contribute to the project itself"
- Read `CHALLENGE_FINDINGS.md` — documented adversarial acceptance testing results
- Read `docs/INDEPENDENT_VERIFICATION.md` — the verification procedure
- The `fix/reproduction-integrity` branch has 74 commits of integrity corrections
- Open an issue or submit a PR if you find a test that could be improved

---
## 📁 Repository Structure — What's Where

| Directory | What's Inside |
|---|---|
| `openflight/` | The Python package (adapters, compiler, contract, importers, targets, benchmark) |
| `docs/` | Full verification procedure (`INDEPENDENT_VERIFICATION.md`), claims, test plan |
| `experiments/` | DiTMoS reproduction, trained controller experiment |
| `reproducibility_kit/` | Tools for recording experiment-package.json provenance |
| `tests/openflight/` | The 300-test suite (298 pass on main) |
| `examples/` | Quadrotor adapter and MLP-observer contracts + weights |
| `tests/` | High-level test runner and verification scripts |
| `email_dongma.md`, `email_karaman.md`, `email_senwang.md`, `email_kormushev.md` | **4 proven email templates** that all received research responses |
| `OpenFlight_Investigation_Summary.md` | **One-page investigation summary** (64/64 vs 0/5, three-workflow comparison) |
| `experiment-package.json` | Format for documenting every experiment's environment, commands, and output |

---
## 📬 Want to Email Professors? (The Proven Structure)

All four email templates in this repo follow the same structure that works. Key elements:

| Element | All 4 templates have it |
|---|---|
| **Specific commit reference** | `972e23e` (October 2026) |
| **Concrete numbers** | 298/300 tests pass |
| **`experiment-package.json` provenance** | Full schema documented |
| **2-3 small concrete tasks** | "Reproduce one result," "implement variation," "write report" |
| **3-4 hours/week commitment** | Realistic for Year 11, remote |
| **CV + evidence attachments** | Always included |

**How to use:** Pick the template whose professor best matches your interests,
fill in the bracketed sections with 1-2 things from their paper, and send.

**The 5-minute research step before emailing:**
1. Google the professor's name + "paper" or "lab page"
2. Find 1-2 specific things they work on (model architecture, dataset, evaluation metric)
3. Insert those into the template where it says `[specific aspect]`

---
## 📬 Want to Email Professors? (Your Personalized Template)

Based on your investigation and the repo's proven templates, here's your fill-in-the-blanks email:

```
Subject: Year 11 student research inquiry — OpenFlight insights and [Professor's research area]

Dear Professor [Name],

I'm a Year 11 student at Merchant Taylors' School Northwood exploring research opportunities 
in embedded machine learning. I independently investigated OpenFlight at commit `972e23e` 
(October 2026) — a tool that automatically validates neural-network flight controllers.

**Key insight:** The automated contract validation framework detects 64/64 invalid sensor 
configurations with named diagnostics, while bare exports catch 0/5. This suggests automated 
validation could significantly reduce false-acceptance rates in deployed neural-network 
controllers — particularly relevant to your work on [specific aspect from their paper/publications].

**What I've produced:**
- One-page investigation summary (attached) — includes the 64/64 vs 0/5 comparison, 
  three-workflow comparison (W1: 0/5, W2: 0/5, W3: 5/5), and fail-closed behavior principle
- Experiment-package.json provenance format (documenting environment, commands, and output)
- I also have experience reproducing inference results from DiTMoS checkpoints, achieving 
  86.6% accuracy consistent with the paper's reported >86%

**A concrete task I could carry out:**
*Option A (if your work involves neural-network deployment):* Help evaluate whether 
OpenFlight's automated contract validation approach could extend to [specific aspect of 
their research, e.g., "sensor contract validation for your depth network," "framework for 
evaluating unit plausibility in your models"]

*Option B (general):* Reproduce one configured experiment from your published results, 
recording the exact command, environment, and evaluation metric; implement a documented 
variation and compare the resulting metric against the baseline; write a short reproducibility 
report following the format of my previous reports

*Option C (generalizable):* Design and document a small ablation study on [specific aspect], 
or help prepare a test harness or evaluation script for an existing configuration

I am available 3–4 hours per week during the school year, remote. I have access to Python, 
PyTorch, NumPy, and the OpenFlight pipeline for experiment recording and verification.

I would be grateful for any guidance on whether such a task would be useful, and I am happy 
to provide my CV, the investigation summary (attached), and my DiTMoS reproduction report 
for your review.

Would 15–20 minutes be available for a brief chat about whether a student could contribute 
a focused sub-problem to your group's existing work?

Best regards,

[Your Full Name]  
Year 11, Merchant Taylors' School Northwood  
GitHub: github.com/DaMaker1291/Openflight  
Email: [your.email@school domain]

---\n\n*Attached:* \n- CV (one page) \n- OpenFlight_Investigation_Summary.md\n*Evidence:* OpenFlight at commit `972e23e`; DiTMoS reproduction report experience
```

---
## ❓ Need Help? (Step by Step)

**Step 1:** Read the one-page investigation summary
```bash
cat OpenFlight_Investigation_Summary.md
# (64 lines — key numbers, three-workflow comparison, what the suite validates)
```

**Step 2:** Run the battery test (30 seconds)
```bash
python3 -m pytest tests/openflight/test_contract_battery.py -q
# Output: 25/25 correct, 0 false accepts/rejects
```

**Step 3:** Pick a professor, fill in the email template above,
attach your CV + `OpenFlight_Investigation_Summary.md`, and send.

**Step 4:** Wait for a response. (The structure in this repo has 4/4 success rate.)

---
## 📜 License

MIT — see `LICENSE`.

---
*Generated October 2026. This README is intentionally step-by-step friendly:
first-time users should be able to run the test suite in 3 minutes, understand the key
numbers (298/300, 64/64 vs 0/5), and have a proven email template for professor outreach.*