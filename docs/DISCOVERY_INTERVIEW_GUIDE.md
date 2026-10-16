# Researcher discovery — interview guide (v1)

Status: **materials only — no recruitment or data collection until the
permissions/consent preconditions in `PILOT_PREREGISTRATION_v0.2.6.md` §4
are confirmed.** If the interviews feed a publishable study, applicable
institutional ethics requirements apply first (same rule as the student
pilot). Prepared 2026-10-15 per `RESEARCH_PLAN.md` §7.

## Purpose

Establish whether the chosen problem — *trust that a deployed network
receives meaningfully equivalent inputs, and reproducible evidence for that
trust* — actually recurs in researchers' work, how they currently handle it,
and where automation might help. This is discovery, not persuasion: we are
gathering evidence that could **narrow or change the research question**
(`RESEARCH_PLAN.md` §3, possibility 3 is an allowed outcome).

## Who to approach

- Target: ~3–5 researchers (PhD students, postdocs, or faculty) who have
  **actually moved a trained model into a robot or embedded controller**.
- Do not start with theorists who have never done an integration.
- Do not approach people likely to praise the idea without prior integration
  experience; their opinions are not the datum.

## Rules of conduct (fixed)

1. Ask about **specific past events**, never about whether OpenFlight
   sounds useful.
2. Never lead toward a expected answer; no mentioning what OpenFlight
   catches before they have described their own failures.
3. Record problems even when tools behaved correctly — an accurate but
   incomprehensible diagnostic is a finding.
4. No recording unless separately authorised; default to written notes.
5. Collect no unnecessary identifying data; store notes per the confirmed
   data-handling rules; delete on the agreed schedule.

## Consent preamble (plain language, read before questions)

> I'm studying how researchers verify sensor-to-model integration when
> deploying learned models to embedded systems. I'd like to ask about your
> most recent such deployment — what was hard, what went wrong, how you
> found out. Your answers will be summarised in research notes; [no
> recording / recording only if separately authorised]. Participation is
> voluntary, you can skip any question or stop at any time, and nothing you
> say will be attributed to you by name without your explicit permission.
> Do you consent to proceed?

## Interview questions

Context first — the most recent deployment only:

1. Think about the last time you moved a trained model into a robot or
   embedded controller. What was the most difficult part?
2. What went wrong during the integration, if anything?
3. How did you discover the problem? (Who or what first noticed?)
4. How much time did it take to diagnose and fix?
5. What tools did you use?
6. Which checks were automated, and which did you perform manually?
7. Have you hit a case where the model ran successfully but produced
   incorrect results because its inputs or preprocessing differed from what
   was expected? *(The core question — get the concrete episode.)*
8. How do you currently establish that the embedded implementation
   corresponds to the model you evaluated?
9. What evidence would you need before trusting an automated tool with this
   workflow?
10. If you could automate one part of the process, which part would you
    choose?

Follow-up probes (only to extract specifics, never to suggest answers):
"Walk me through what you actually did that day." · "What did the failure
look like when you first saw it?" · "What was the fix, and how did you
confirm it was right?" · "Did anything like that happen again later?"

## Capture template (per participant)

| Field | Entry |
|---|---|
| Participant ID (pseudonymous) | |
| Domain (e.g. aerial, manipulation, nav) | |
| Most recent deployment (model → target) | |
| Hardest part (their words) | |
| Concrete failures observed | |
| How detected + time to diagnose | |
| Automated vs manual checks | |
| Input/preprocessing-mismatch episode (y/n + detail) | |
| How they verify embedded == evaluated | |
| Evidence they'd need to trust automation | |
| What they'd automate first | |
| Tooling they currently use | |
| Surprises / answers we didn't anticipate | |

## After the interviews (fixed analysis steps)

1. Categorise problems by frequency and severity in their words.
2. Map each category against what OpenFlight can realistically address.
3. Note any category where a competitor already handles it adequately —
   feed directly into `RESEARCH_PLAN.md` §3 possibility 3.
4. Feed observed friction and fault types into the benchmark case list
   (`BENCHMARK_DRAFT.md` revision window, before independent sign-off).
5. Report raw counts (how many participants reported each category), not
   impressions.
