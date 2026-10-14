# OpenFlight pilot feedback

Participant ID (e.g. `P1`, pick your own):
Date:
Commit hash (`git rev-parse HEAD`):
Host OS / Python version:

Answer in plain sentences. "I didn't look it up" is a valid and useful
answer. Quote real error messages verbatim where asked.

## 1. Setup (Phase 0–1)

1. Did `openflight doctor` exit 0 on the first try? (yes / no / describe)
2. Did `python3 openflight/repro.py` end in `REPRODUCTION OK`?
   If no, paste the failing check and its detail line.
3. Did `evidence status` report `all checks fresh`? If no, paste the stale
   checks and reasons.

## 2. Deploy (Phase 2)

4. Following `QUICKSTART.md` only (no source reading), did the deploy
   complete? (yes / no / where did you get stuck?)
5. Roughly how many minutes from `pip install` to a
   `deployment_report.json` on disk? (integer minutes)
6. Did `deployment_report.json` contain a `limitations` or `not-run` entry
   you had to act on? Quote it. Did the tool make that limitation clear
   *without* you opening the JSON by hand? (yes / no)

## 3. Break-it (Phase 3) — the core questions

For EACH of the three injected faults (unit mismatch / off-layout /
undocumented units), answer 7a–7d.

7a. Fault name:
7b. Did OpenFlight **block** the deploy? (blocked / deployed-anyway)
7c. Paste the exact diagnostic message you received.
7d. Given ONLY that message (no source code), could you identify the field
    to change and how? (yes / no / partially — explain)

8. **If any fault deployed anyway**, describe what you would have shipped and
   what it would have cost to catch later. This is the highest-value answer
   in the pilot.

## 4. Comparative judgment (the claim under test)

9. Have you previously taken a PyTorch policy onto an MCU or embedded target
   by hand? (never / once / a few times / regularly)
10. On a 1–7 scale (1 = much worse, 4 = same, 7 = much better), relative to
    your prior manual process (or to "no tool"), how did OpenFlight compare
    on:
    a. Time to first working deploy: 1 2 3 4 5 6 7
    b. Confidence the sensor binding is correct: 1 2 3 4 5 6 7
    c. Quality of diagnostics when you broke it: 1 2 3 4 5 6 7
    d. Would you use it again on your own work: 1 2 3 4 5 6 7
11. One thing you'd delete and one thing you'd add before trusting this on a
    real project.

## 5. Consent

12. Consent: I understand my answers will be recorded, stored privately by
    the researcher, and used only to assess OpenFlight's usability — never
    published with my name or student ID. May we quote them anonymized by my
    participant ID? (yes / no)

## Sending your responses

Responses are collected **privately, outside the repository** — do not commit
them. Email the completed form, plus the CSV row below, to the researcher.

```csv
participant,date,commit,doctor_ok,repro_ok,evidence_fresh,deploy_ok,minutes_to_deploy,blocked_unit,blocked_offlayout,blocked_undoc,any_deployed_anyway,score_time,score_confidence,score_diag,score_reuse,consent
P1,YYYY-MM-DD,<hash>,yes,yes,yes,yes,20,yes,yes,yes,no,5,6,6,5,yes
```
