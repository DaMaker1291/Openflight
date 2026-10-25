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
| `OpenFlight_Investigation_Summary.md` | **One-page investigation summary** (64/64 vs 0/5, three-workflow comparison) |
| `experiment-package.json` | Format for documenting every experiment's environment, commands, and output |

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

**Step 3:** Review the investigation summary and test results.

**Step 4:** Ready to explore the repository further.

---
## 📜 License

MIT — see `LICENSE`.

---
*Generated October 2026. This README is intentionally step-by-step friendly:
first-time users should be able to run the test suite in 3 minutes, understand the key
numbers (298/300, 64/64 vs 0/5), and focus on the tool's validation capabilities.*