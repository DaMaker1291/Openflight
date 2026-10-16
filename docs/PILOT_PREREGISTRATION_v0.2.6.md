# OpenFlight supervised pilot — preregistration for v0.2.6

Status: **DRAFT FOR REVIEW — no participant data may be collected until
(1) institutional/school permissions and consent arrangements are confirmed
and (2) an independent second-machine reproduction of the release below has
been recorded.**

This document is version-specific and lives in the repository only. It is
**not** part of the frozen release archive (it was written after the
`v0.2.6-pilot` tag); the published archive is never edited to update this
protocol. If the protocol must change before data collection, a new dated
version of this file is written and the change is logged in §8 below —
changes after data collection begins are prohibited (§7).

## 1. Frozen artefact under test

| Field | Value |
|---|---|
| Release | `v0.2.6-pilot` |
| Commit (tag `v0.2.6-pilot`) | `5840dfe7ddb055cb962fee32bd82ba8419d27f51` |
| Archive | `openflight-v0.2.6-pilot.tar.gz` |
| SHA-256 (published externally on the release page + `.sha256` asset) | `7b349871ffda4746b4a24297b48e6e29bb622b0f8ce007f1435299803fb5f2fd` |
| Assets | https://github.com/DaMaker1291/openflight/releases/tag/v0.2.6-pilot |
| Known host-only results | 242 passed / 0 skipped; `REPRODUCTION OK` (eight host checks); `evidence status` exit 0 with `build`/`qemu` "never run" |
| Known outstanding | ESP32/QEMU target-side validation; second-machine reproduction; independent reviewer's five-property re-audit of *this* archive (their environment could not retrieve the release as of 2026-10-15 — recorded as unverified, not verified); no physical-silicon data exists anywhere |

Verify with `shasum -a 256 openflight-v0.2.6-pilot.tar.gz` against the full
64-character hash above, obtained from the release page or the `.sha256`
asset — never from a file inside the archive.

## 2. Research objective (fixed)

Determine whether people who did not build OpenFlight can, from the release
archive alone:

1. install it and reproduce the host-side results;
2. use the contract gate to accept a correct sensor/model binding and
   reject incorrect ones;
3. interpret a diagnostic well enough to locate and fix a fault; and
4. read `evidence status` and correctly distinguish fresh, stale, failed and
   never-run checks — i.e. say what the evidence does and does not show.

This is an exploratory usability pilot of the **host-side workflow**. It is
not a test of physical embedded deployment and cannot support statistical
claims (§7).

## 3. Scope decision: host-only (Objective A)

Per the 2026-10-15 review: the first pilot is **host-only**. Participants
are told explicitly that they are testing the host workflow, that ESP32/QEMU
target checks are `never run` in their environment, and that no physical
device is involved. A target-side pilot (Objective B) requires a separate
protocol revision, toolchain availability, and — for any physical-performance
claim — real device measurements, none of which this pilot provides.

## 4. Preconditions (all required before any session)

1. **Independent second-machine reproduction.** A person on a separate
   machine, given only the release archive, external checksum and
   `docs/REPRODUCE.md`, obtains: checksum match, `242 passed`, `REPRODUCTION
   OK`, `openflight version` → `0.2.6`, `evidence status` exit 0 (build/qemu
   never run). OS, Python version, dependency versions, commands, exit codes
   and any workarounds are recorded verbatim; problems are recorded, not
   silently fixed.
2. **Permissions and consent.** Applicable institutional/school permissions,
   research-ethics determination, parental consent / participant assent as
   required, data-collection and retention rules confirmed with responsible
   staff. Sessions are not recorded unless separately authorised; no
   unnecessary identifiable data is collected.
3. **This document reviewed and dated** (§8) with criteria unchanged since
   before the first session.

### Gate status (evidence only; PASS/FAIL/NOT COMPLETED per gate)

| Gate | Status | Evidence |
|---|---|---|
| Independent second-machine reproduction | **NOT COMPLETED** | Awaiting an external verifier's verbatim commands/outputs/exit codes; the brief is issued, no results received |
| Independent reviewer re-audit (five properties on this archive) | **NOT COMPLETED** | Reviewer environment could not retrieve the release (2026-10-15); no probe results exist |
| Permissions and consent | **NOT COMPLETED** | No institutional/school confirmation received |
| Supplemental: author-run verification of the downloaded release bytes | PASS (not independent — does not substitute for any gate above) | `reproduction/release_v0.2.6_author_verification_2026-10-15.log`: checksum match; version/doctor exit 0; 242 passed; 12 review+audit probes; 60 evidence-mutation; 19 battery/engine; CLI repros of the v0.2.5 audit faults on release bytes (mystery-unit → BLOCKED exit 2, U101 naming both tokens; duplicate `raw_layout` → BLOCKED exit 2, E002; baseline → PROCEED exit 0); `REPRODUCTION OK` (eight checks); `evidence status` exit 0 with build/qemu never run |

A successful supplement does not establish audit or reproduction success:
the three gates above stay **NOT COMPLETED** until their own evidence
arrives. Failed attempts, when they arrive, are recorded as-is before any
rerun is considered.

## 5. Tasks (observable, in order)

| # | Task | What is observed |
|---|---|---|
| T1 | Install from the archive and initialise (`doctor`, `version`) | Installation friction, missing instructions, environment problems |
| T2 | Reproduce (`repro.py`, `evidence status`) | Ability to reach `REPRODUCTION OK`; interpretation of the check list |
| T3 | Validate a correct sensor/model contract | Whether the participant understands *why* it is accepted |
| T4 | Diagnose an invalid unit declaration (e.g. mismatched units) | Whether the diagnostic identifies the actual problem in their words |
| T5 | Diagnose an invalid feature binding (off-layout `source`) | Whether they can locate and explain the fault |
| T6 | Test a valid unit conversion | Whether they understand the transformation and its effect |
| T7 | Read `evidence status` (incl. a deliberately staled input) | Whether they distinguish fresh / stale / failed / never-run |

Fault injections for T4–T6 use copies of the example YAML files, applied
with a real editor (see `PILOT_PROTOCOL.md` Phase 3 for the reference
diagnostics and the sed caveat). Participants explain their understanding in
their own words; the observer does not lead.

## 6. Scoring rules (fixed)

Per fault injection, exactly one outcome is recorded:

- **true block** — invalid case blocked, diagnosis correct;
- **miss (false accept)** — invalid case accepted; report immediately, it is
  the single most important finding;
- **false reject** — valid case blocked; logged with participant expectation
  vs checker reason;
- **unusable diagnosis** — correctly blocked but the participant cannot
  understand/locate the fault from the message (a usability defect even
  though the software behaved correctly).

Per participant, additionally recorded: install completion (Y/N + wall-clock
minutes), assistance requests (count + what was asked), T1–T7 completion
(Y/N + wall-clock), evidence-interpretation errors (count + nature), blanket
`--confirm-all` uses, and at least one specific friction item (their words).
Observers note the participant's own explanation before any hint.

## 7. Analysis plan (fixed)

Two to three participants → **exploratory only**. Report per-participant
observations and recurring problems (the friction log is the primary
qualitative deliverable). Do **not** compute or imply detection rates,
time-saving claims, or superiority over competing workflows; the fixed
success-criteria table in `PILOT_PROTOCOL.md` remains the set of numbers to
report, not a bar the pilot must clear. Success criteria and task order are
not changed after results are seen (changes after data collection begins
void the run). Negative findings are reported with equal prominence.

## 8. Amendment log

| Date | Change | Reason | Before/after data collection |
|---|---|---|---|
| 2026-10-15 | Initial version (v0.2.6 identifiers, tasks, scoring, analysis) | Reviewer recommendation: v0.2.5 preregistration outdated after the audit fixes | Before any data |
