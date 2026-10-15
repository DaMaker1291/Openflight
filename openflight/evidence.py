"""Evidence graph: hash the artifacts each check reads; detect staleness.

Checks (battery, held-out, independent, workflows, baseline, parity, e2e,
importers, build, qemu) declare which artifact groups they read. `record`
hashes those artifacts into results/evidence.json; `status` re-hashes and
reports each check as fresh / stale / failed / never run, plus the
CLAIMS.md claim ids that depend on stale, failed, or never-run checks.

Truth rules (2026-10-15, independent probes + import tracing):
- Dependencies are derived from what the producing test module actually
  reads (imports + file loads), not from what seems related.
  tests/openflight/test_evidence_mutation.py re-derives the import
  closure and fails if a check's declared inputs drift from its reads.
  Whole-directory globs (openflight/contract/, openflight/adapters/,
  openflight/compiler/) are deliberate over-approximations: they also
  cover files no check imports (e.g. contract/draft.py), so an edit to
  any module in those directories policy-warrants re-running the checks.
- Globs are expanded against the `root` argument at record/status time,
  never against the current working directory. A non-optional glob group
  that expands to zero files under `root` raises EvidenceGraphError —
  an empty or foreign root fails loudly, it never reports "all fresh".
- `record` writes a check entry ONLY when that check actually ran, with
  its result. A check with no entry — or with required inputs absent at
  record time — reports "never run", never "fresh".
- "fresh" means: ran, result ok, inputs unchanged, environment unchanged.
  A recorded result of "fail" with unchanged inputs reports "failed"
  and puts its claims at risk.
- The environment (python/torch/numpy/platform versions) is recorded and
  compared: parity, build and qemu are environment-dependent and go
  stale when it changes, even if no tracked file changed.
- Over-approximations kept on purpose (commented): the shipped contract
  YAMLs are declared for the challenge checks even though the challenge
  cases are embedded in the tests; editing the shipped pair policy-
  warrants re-running the challenges; the graph module itself
  (evidence_source) is an input to every check, so editing how staleness
  is computed invalidates every recorded verdict; generated C++ is a
  declared build input, so editing a stale build output warrants a
  rebuild.

Design: docs/superpowers (Phase 1 evidence graph, advisor prompt
2026-10-14; dependency-true revision 2026-10-15; root-resolution +
failed-state + environment revision 2026-10-15, probe round 2). No new
dependencies.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import platform
import time

ROOT_FIXTURES = [
    "learned_observer.py",
    "macondo_hover.py",
    "observer_deploy.py",
]

GLOB_CHARS = "*?["


class EvidenceGraphError(RuntimeError):
    """The root does not contain the tracked tree (empty glob group)."""


# artifact group -> patterns (glob or repo-relative static path).
# Missing static files hash as None; glob patterns are expanded against
# the record/status `root` (never the cwd), and a non-optional group
# whose globs expand to nothing under that root raises.
ARTIFACT_GROUPS: dict[str, list[str]] = {
    # QUICKSTART demo model; read by NO repro check (kept for completeness,
    # wired to no check — all six checks load learned_observer.pt)
    "example_weights": [
        "examples/quadrotor_adapter/example_weights.pt",
    ],
    # the model the parity/workflows/baseline/independent checks load
    "observer_weights": [
        "learned_observer.pt",
    ],
    "ppo_weights": [
        "ppo_best.pt",
    ],
    "model_contract": [
        "examples/quadrotor_adapter/model_contract.yaml",
    ],
    "sensor_contract": [
        "examples/quadrotor_adapter/drone_contract.yaml",
    ],
    # checker + everything it imports at module level (errors) and the
    # contract adapters the contract modules import; the whole directory
    # (incl. draft.py) is a deliberate over-approximation
    "checker_source": ["openflight/contract/*.py",
                       "openflight/errors.py"],
    "adapters_source": ["openflight/adapters/*.py"],
    "compiler_source": ["openflight/compiler/*.py",
                        "openflight/compiler/operators/*.py"],
    "cli_source": [
        "openflight/cli.py",
    ],
    "benchmark_source": ["openflight/benchmark/*.py"],
    "observer_fixtures": list(ROOT_FIXTURES),
    # the host-sim firmware the parity harness compiles and runs
    "firmware_host_source": ["firmware/generic/*",
                             "firmware/host_sim/*"],
    # the ESP32 target the build/qemu checks concern
    "firmware_esp32_source": ["firmware/esp32/main/*",
                              "firmware/esp32/sdkconfig.defaults",
                              "firmware/esp32/CMakeLists.txt",
                              "firmware/esp32/build.sh",
                              "firmware/esp32/qemu_test.py",
                              "firmware/esp32/gen_vectors.py",
                              "firmware/esp32/sim_test.py"],
    # each check's own implementation is an input to that check
    "battery_test": ["tests/openflight/test_contract_battery.py"],
    "heldout_test": ["tests/openflight/test_heldout_challenge.py"],
    "independent_test": ["tests/openflight/test_independent_challenge.py"],
    "workflows_test": ["tests/openflight/test_three_workflows.py"],
    "baseline_test": ["tests/openflight/test_baseline_compare.py"],
    "parity_test": ["tests/openflight/test_firmware_harness.py"],
    # importers / draft layer (C11): the importer sources themselves, the
    # conventions document they cite (REP-103 units, xyzw ordering), the
    # test modules that evidence the layer, and the package root that
    # `from openflight import ...` pulls in
    "importer_source": ["openflight/importers/*.py"],
    "importers_test": ["tests/openflight/test_importers.py",
                       "tests/openflight/test_draft_layer.py"],
    "conventions_doc": ["docs/CONVENTIONS.md"],
    "package_root": [
        "openflight/__init__.py",
    ],
    # optional nodes: absent in a fresh tree (regenerated by compile/build)
    "generated_cxx": [
        "build/model_adapters.cpp",
    ],
    "firmware_binary": [
        "firmware/esp32/build/openflight_bench.bin",
    ],
    # provenance sidecars written by `contract confirm` next to their
    # contracts; optional (absent until someone confirms), but once
    # recorded their content is a claim-level input: C11 cannot look
    # fully supported while the confirmation record drifts
    "provenance_sidecars": ["**/*.provenance.json"],
    # the graph module itself: editing how staleness is computed must
    # invalidate every recorded freshness verdict (deliberate
    # over-approximation — one edit stales all checks, documented here)
    "evidence_source": ["openflight/evidence.py"],
    # e2e pipeline (C1 host half): the producing test, the merged report
    # it reads back before rewriting, and the model it runs
    "e2e_test": ["tests/openflight/test_e2e_pipeline.py"],
    "e2e_report": ["results/e2e_pipeline.json"],
    # qemu runtime images: flash/efuse produced by build.sh, read by
    # qemu_test.py as MTD/efuse drives; absent until a real build
    "qemu_runtime": ["firmware/esp32/build/flash_image.bin",
                     "firmware/esp32/build/qemu_efuse.bin"],
}

# groups whose absence does not mean a check failed to run
OPTIONAL_GROUPS = {"generated_cxx", "firmware_binary", "provenance_sidecars",
                   "qemu_runtime"}

# claims whose support depends on provenance sidecars (claim-level
# inputs: no technical check reads a sidecar, so no check goes stale —
# only these claims lose their "fully supported" status)
PROVENANCE_CLAIMS = ("C11",)

# check -> artifact groups it reads (derived from the producing test
# module's imports and file loads; see module docstring)
CHECK_DEPS = {
    "battery": ("checker_source", "adapters_source", "battery_test",
                "model_contract", "sensor_contract"),
    "heldout": ("checker_source", "adapters_source", "heldout_test",
                "model_contract", "sensor_contract"),
    "independent": ("checker_source", "adapters_source", "independent_test",
                    "model_contract", "sensor_contract", "observer_weights",
                    "ppo_weights", "observer_fixtures", "compiler_source",
                    "cli_source"),
    "workflows": ("checker_source", "adapters_source", "workflows_test",
                  "model_contract", "sensor_contract", "cli_source",
                  "compiler_source", "observer_weights", "observer_fixtures"),
    "baseline": ("checker_source", "adapters_source", "baseline_test",
                 "model_contract", "sensor_contract", "cli_source",
                 "observer_weights", "observer_fixtures"),
    "parity": ("parity_test", "observer_weights", "observer_fixtures",
               "compiler_source", "cli_source", "benchmark_source",
               "firmware_host_source"),
    # draft layer + importers: their sources and tests, the conventions
    # doc they cite, and the modules the producing tests import (checker,
    # adapters, cli)
    "importers": ("importer_source", "importers_test", "conventions_doc",
                  "package_root", "checker_source", "adapters_source",
                  "cli_source"),
    # e2e pipeline (C1 host half): the producing test reads the model
    # weights, generates adapters, and merges its own report back; its
    # import closure is cli + compiler + checker/units/errors (guards
    # test_graph_declares_every_imported_input)
    "e2e": ("e2e_test", "e2e_report", "observer_weights", "cli_source",
            "compiler_source", "checker_source"),
    # build.sh compiles learned_observer.pt through the CLI, imports the
    # repo-root fixtures on host-python steps, and consumes the generated
    # C++ (generated_cxx: over-approximation — editing a stale build
    # output policy-warrants a rebuild)
    "build": ("firmware_esp32_source", "compiler_source", "cli_source",
              "package_root", "observer_weights", "observer_fixtures",
              "generated_cxx"),
    # qemu_test.py imports learned_observer/macondo_hover, the CLI arch
    # factory and the benchmark protocol, loads the weights, and boots
    # the generated flash/efuse images
    "qemu": ("firmware_esp32_source", "observer_weights", "observer_fixtures",
             "cli_source", "benchmark_source", "qemu_runtime"),
}

# every check reads the graph module itself: a change to how staleness is
# computed must invalidate every recorded freshness verdict (documented
# deliberate over-approximation — one edit stales all checks)
CHECK_DEPS = {name: deps + ("evidence_source",)
              for name, deps in CHECK_DEPS.items()}

# checks whose numerical/compile behaviour depends on the interpreter
# and library versions, not just on tracked files (e2e compares C++
# against torch numerically under registered tolerances)
ENVIRONMENT_DEPENDENT = ("parity", "build", "qemu", "e2e")

# check -> CLAIMS.md claim ids it supports (C10 depends on everything).
# C1 is split by evidence: the host half is backed by parity, the QEMU
# half by qemu — so C1 appears under claims_unverified on a host-only
# tree until a qemu run is recorded.
CLAIM_DEPS = {
    "battery": ("C5",),
    "heldout": ("C5",),
    "independent": ("C5",),
    "workflows": ("C6",),
    "baseline": ("C6",),
    "parity": ("C1",),
    "e2e": ("C1",),  # C1's host half: registered/expanded tolerances + bypass
    "importers": ("C11",),
    "build": ("C2", "C3"),
    "qemu": ("C1", "C2", "C4", "C7", "C8"),
}


def _sha256(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _expand_group(root: str, patterns: list[str],
                  group: str) -> list[str]:
    """Repo-relative paths for one group, expanded against `root`."""
    out: list[str] = []
    for pat in patterns:
        if any(c in pat for c in GLOB_CHARS):
            full = os.path.join(root, pat)
            matches = sorted(
                os.path.relpath(p, root).replace(os.sep, "/")
                for p in glob.glob(full, recursive=True)
                if os.path.isfile(p) and "/.git/" not in
                (os.path.relpath(p, root).replace(os.sep, "/") + "/"))
            if not matches and group not in OPTIONAL_GROUPS:
                raise EvidenceGraphError(
                    f"artifact group '{group}' expanded to no files "
                    f"under root {root!r} (pattern {pat!r}); the root "
                    f"does not contain the tracked tree")
            out.extend(matches)
        else:
            out.append(pat)
    return out


def expand_groups(root: str = ".") -> dict[str, list[str]]:
    """Expand every artifact group's patterns against `root`.

    Raises EvidenceGraphError if a non-optional glob group is empty
    under `root` (wrong cwd, foreign or partial checkout).
    """
    return {g: _expand_group(root, pats, g)
            for g, pats in ARTIFACT_GROUPS.items()}


def _env_snapshot() -> dict:
    """Interpreter/library/platform versions that affect numerical checks."""
    snap = {
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    for mod in ("torch", "numpy"):
        try:
            snap[mod] = getattr(__import__(mod), "__version__", "unknown")
        except ImportError:
            snap[mod] = None
    return snap


def _hash_groups(root: str) -> dict:
    out = {}
    for group, rels in expand_groups(root).items():
        out[group] = {rel: _sha256(os.path.join(root, rel)) for rel in rels}
    return out


def record(root: str = ".", out_path: str | None = None,
           results: dict | None = None) -> dict:
    """Hash artifacts; write check entries only for checks that ran.

    `results` maps check name -> {"result": "ok"|"fail"}. Without it no
    check is claimed to have run (standalone CLI record), and status
    reports every check as "never run". Raises EvidenceGraphError if the
    root does not contain the tracked tree.
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    checks = {}
    for name, res in (results or {}).items():
        if name not in CHECK_DEPS:
            continue
        checks[name] = {"reads": list(CHECK_DEPS[name]),
                        "result": res.get("result"),
                        "ran_at": now}
    doc = {
        "schema_version": 3,
        "recorded_at": now,
        "environment": _env_snapshot(),
        "artifacts": _hash_groups(root),
        "checks": checks,
    }
    out = out_path or os.path.join(root, "results", "evidence.json")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as f:
        json.dump(doc, f, indent=2)
    return doc


def _sidecar_limitations(root: str) -> list[dict]:
    found = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if "/.git" in dirpath or "__pycache__" in dirpath:
            continue
        for fn in filenames:
            if not fn.endswith(".provenance.json"):
                continue
            p = os.path.join(dirpath, fn)
            try:
                with open(p) as f:
                    side = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            entry = {"sidecar": os.path.relpath(p, root),
                     "confirm_mode": side.get("confirm_mode"),
                     "not_individually_verified":
                         side.get("not_individually_verified", []),
                     "limitations": side.get("limitations", [])}
            if entry["not_individually_verified"] or entry["limitations"]:
                found.append(entry)
    return found


def _group_diff(recorded: dict, current: dict) -> list[str]:
    reasons = []
    for rel in sorted(set(recorded) | set(current)):
        r, c = recorded.get(rel), current.get(rel)
        if r and c is None:
            reasons.append(f"{rel} missing (was hashed at record)")
        elif r and c and r != c:
            reasons.append(f"{rel} changed")
        elif not r and c:
            reasons.append(f"{rel} appeared since record")
    return reasons


def status(root: str = ".", evidence_path: str | None = None) -> dict:
    path = evidence_path or os.path.join(root, "results", "evidence.json")
    checks: dict[str, dict] = {}
    stale: list[str] = []
    failed: list[str] = []
    never_run: list[str] = []
    empty = {"stale_checks": [], "failed_checks": [], "never_run_checks": [],
             "claims_at_risk": [], "claims_unverified": [],
             "checks": {}, "unresolved_limitations": [],
             "stale_provenance": []}
    try:
        with open(path) as f:
            rec = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return dict(empty, error=f"no usable evidence record at {path}: {e}")

    try:
        current = _hash_groups(root)
    except EvidenceGraphError as e:
        return dict(empty, error=str(e))

    # provenance sidecars are claim-level inputs (not check inputs):
    # drift puts PROVENANCE_CLAIMS at risk without staling any check
    prov_reasons = _group_diff(
        rec.get("artifacts", {}).get("provenance_sidecars", {}),
        current.get("provenance_sidecars", {}))

    cur_env = _env_snapshot()
    rec_env = rec.get("environment")
    env_reasons: list[str] = []
    if rec_env is None:
        env_reasons = ["environment not recorded at record time"]
    else:
        for key in sorted(set(rec_env) | set(cur_env)):
            if rec_env.get(key) != cur_env.get(key):
                env_reasons.append(
                    f"environment changed: {key} "
                    f"{rec_env.get(key)} -> {cur_env.get(key)}")

    for check, deps in CHECK_DEPS.items():
        entry = rec.get("checks", {}).get(check)
        rec_arts = rec.get("artifacts", {})
        if entry is None:
            checks[check] = {"status": "never run",
                             "reasons": ["not recorded as run "
                                         "(repro.py records ran checks)"]}
            never_run.append(check)
            continue
        required_absent = []
        for group in deps:
            if group in OPTIONAL_GROUPS:
                continue
            for rel, h in rec_arts.get(group, {}).items():
                if h is None:
                    required_absent.append(rel)
        if required_absent:
            checks[check] = {
                "status": "never run",
                "reasons": [f"required input absent at record: {rel}"
                            for rel in sorted(required_absent)]}
            never_run.append(check)
            continue
        reasons: list[str] = []
        for group in deps:
            reasons.extend(_group_diff(rec_arts.get(group, {}),
                                       current.get(group, {})))
        if check in ENVIRONMENT_DEPENDENT:
            reasons.extend(env_reasons)
        result = entry.get("result")
        if reasons:
            state = "stale"
        elif result == "fail":
            state = "failed"
        else:
            state = "fresh"
        checks[check] = {"status": state, "reasons": reasons,
                         "result": result}
        if state == "stale":
            stale.append(check)
        elif state == "failed":
            failed.append(check)

    claims: set[str] = set()
    for check in stale + failed:
        claims.update(CLAIM_DEPS.get(check, ()))
    if stale or failed:
        claims.add("C10")  # reproducibility depends on every check
    if prov_reasons:
        claims.update(PROVENANCE_CLAIMS)  # confirmation record drifted

    # claims whose supporting checks never ran have no live evidence
    unverified: set[str] = set()
    for claim in {c for deps in CLAIM_DEPS.values() for c in deps}:
        supporting = [k for k, deps in CLAIM_DEPS.items() if claim in deps]
        if any(k in never_run for k in supporting):
            unverified.add(claim)
    if never_run:
        unverified.add("C10")

    return {
        "recorded_at": rec.get("recorded_at"),
        "checks": checks,
        "stale_checks": sorted(stale),
        "failed_checks": sorted(failed),
        "never_run_checks": sorted(never_run),
        "claims_at_risk": sorted(claims),
        "claims_unverified": sorted(unverified),
        "stale_provenance": prov_reasons,
        "unresolved_limitations": _sidecar_limitations(root),
    }
