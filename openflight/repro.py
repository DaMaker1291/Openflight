"""Independent reproduction entry point for OpenFlight (current version).

Runs the full host-side evaluation from a clean checkout and checks each
reported result. No hardware required. Fails loudly on any deviation.

Usage: python3 openflight/repro.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPENFLIGHT_TESTS = "tests/openflight"

# result -> (report file, check description)
CHECKS = {
    "parity": ("results/firmware_harness.json",
               "firmware-path max_abs_err < 1e-4"),
    "battery": ("results/contract_battery_report.json",
                "25/25 correct, 0 false accepts/rejects"),
    "independent": ("results/independent_challenge.json",
                    "21/21 correct"),
    "heldout": ("results/heldout_challenge.json",
                "156/156 correct, 0 false accepts/rejects"),
    "workflows": ("results/three_workflows.json",
                  "5/5 semantic faults escape W1/W2, stopped by W3"),
    "baseline": ("results/baseline_compare.json",
                 "fault escapes baseline, blocked-or-converted by OpenFlight"),
    "importers": ("results/importers_report.json",
                  "6/6 importer/draft provenance pipeline cases"),
    "e2e": ("results/e2e_pipeline.json",
            "300-sample 4-band: registered abs 1e-4, expanded rel 1e-4"),
}

# Complete expected case inventories for the benchmark reports (fixed
# before execution; a truncated or regenerated-short report must fail
# reproduction rather than verify against its own self-consistent counts).
EXPECTED_REPORTS = {
    "battery": {"total": 25,
                "categories": {"valid": 15, "invalid": 7, "ambiguous": 3},
                "seed": 20261011, "category_key": "category",
                "identity_key": "fault"},
    "independent": {"total": 21,
                    "categories": {"valid": 9, "invalid": 8, "ambiguous": 4},
                    "seed": 999, "category_key": "category",
                    "identity_key": "fault"},
    "heldout": {"total": 156,
                "categories": {"valid": 60, "invalid": 64, "ambiguous": 32},
                "seed": 777001, "category_key": "category",
                "identity_key": "fault"},
    "importers": {"total": 6, "categories": {"importers": 6},
                  "schema_version": 1, "category_key": None,
                  "identity_key": "name"},
}


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          timeout=kw.get("timeout", 900))


def main():
    failures = []
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from openflight import __version__
        version = __version__
    except Exception:
        version = "unknown"
    print(f"== OpenFlight {version} independent reproduction ==")
    print(f"root: {ROOT}")
    r = run([sys.executable, "-m", "pytest", OPENFLIGHT_TESTS, "-q"])
    # Find the summary line ("N passed in Xs" / "N failed"); the naive
    # "last 2 lines" approach captured pytest's warnings footer instead.
    lines = [ln for ln in (r.stdout + r.stderr).strip().splitlines()
             if "passed" in ln or "failed" in ln or "error" in ln.lower()]
    print("pytest:", lines[-1] if lines else "(no summary line captured)")
    suite_ok = r.returncode == 0
    if not suite_ok:
        failures.append(f"pytest suite failed (rc={r.returncode})")
    check_ok = {}
    for name, (rel, desc) in CHECKS.items():
        p = ROOT / rel
        if not p.exists():
            failures.append(f"{name}: missing {rel}")
            check_ok[name] = False
            continue
        try:
            rep = json.loads(p.read_text())
        except Exception as e:
            failures.append(f"{name}: unparsable {rel}: {e}")
            check_ok[name] = False
            continue
        ok, detail = verify(name, rep)
        check_ok[name] = ok
        print(f"{name}: {'OK' if ok else 'MISMATCH'} ({desc}) {detail}")
        if not ok:
            failures.append(f"{name}: {detail}")
    fr = ROOT / "results" / "freeze_v0.1.json"
    if fr.exists():
        print("freeze manifest: present")
    else:
        failures.append("freeze manifest missing (run openflight/freeze.py)")
    print()
    # outcomes: a check is "ok" only if this attempt actually reproduced it
    # (suite ran clean AND the report verified) — a failed attempt must
    # never leave the previous success presented as the current state.
    outcomes = {name: ("ok" if suite_ok and check_ok.get(name) else "fail")
                for name in CHECKS}
    if failures:
        print("REPRODUCTION FAILED:")
        for f in failures:
            print(f"  - {f}")
        _record(outcomes)
        print("evidence graph: recorded this attempt "
              "(failed checks marked fail in results/evidence.json)")
        return 1
    print("REPRODUCTION OK: all reported results regenerated and verified.")
    _record(outcomes)
    print("evidence graph: recorded results/evidence.json")
    return 0


def _record(outcomes, root=None):
    """Write this reproduction attempt to the evidence graph.

    `outcomes` maps check name -> "ok"|"fail". Records exceptions are
    printed, never raised: evidence must neither mask a successful repro
    nor crash an already-failing one.
    """
    root = ROOT if root is None else root
    try:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from openflight import evidence as EV
        EV.record(root=str(root),
                  results={name: {"result": r} for name, r in outcomes.items()})
    except Exception as e:
        print(f"evidence graph: record failed ({e})")


def _verify_case_report(rep, exp):
    """Verify a benchmark report against its pre-fixed case inventory.

    Fails on: wrong seed/schema, missing or unparsable case list, case
    count != expected total, duplicate/missing case identities, categories
    outside the benchmark, per-category counts differing from the manifest,
    or a summary that disagrees with the case list (including any case not
    scoring correct).
    """
    if not isinstance(rep, dict):
        return False, "report is not an object"
    if "seed" in exp and rep.get("seed") != exp["seed"]:
        return False, f"seed={rep.get('seed')!r}, expected {exp['seed']}"
    if "schema_version" in exp and \
            rep.get("schema_version") != exp["schema_version"]:
        return False, (f"schema_version={rep.get('schema_version')!r}, "
                       f"expected {exp['schema_version']}")
    cases = rep.get("cases")
    if not isinstance(cases, list):
        return False, "missing case list"
    if len(cases) != exp["total"]:
        return False, f"cases={len(cases)}, expected {exp['total']}"
    catkey, idkey = exp["category_key"], exp["identity_key"]
    only_cat = next(iter(exp["categories"])) if catkey is None else None
    seen = set()
    counts = {k: 0 for k in exp["categories"]}
    correct = {k: 0 for k in exp["categories"]}
    diag = {k: 0 for k in exp["categories"]}
    for i, case in enumerate(cases):
        if not isinstance(case, dict):
            return False, f"case #{i} is not an object"
        ident = case.get(idkey)
        if not ident:
            return False, f"case #{i} missing {idkey}"
        if ident in seen:
            return False, f"duplicate case identity: {ident!r}"
        seen.add(ident)
        cat = only_cat if catkey is None else case.get(catkey)
        if cat not in exp["categories"]:
            return False, f"case {ident!r}: unexpected category {cat!r}"
        counts[cat] += 1
        if case.get("ok") is True:
            correct[cat] += 1
        if case.get("diag_ok") is True:
            diag[cat] += 1
    if counts != exp["categories"]:
        return False, f"category counts {counts}, expected {exp['categories']}"
    summary = rep.get("summary")
    if not isinstance(summary, dict):
        return False, "missing summary"
    n = c_ok = 0
    for cat, exp_n in exp["categories"].items():
        entry = summary.get(cat)
        if not isinstance(entry, dict):
            return False, f"summary missing {cat!r}"
        if entry.get("n") != exp_n:
            return False, (f"summary[{cat}].n={entry.get('n')}, "
                           f"expected {exp_n}")
        if entry.get("correct") != correct[cat]:
            return False, (f"summary[{cat}].correct={entry.get('correct')} "
                           f"but cases show {correct[cat]}/{exp_n}")
        if "diag_correct" in entry and entry["diag_correct"] != diag[cat]:
            return False, (f"summary[{cat}].diag_correct="
                           f"{entry['diag_correct']} but cases show "
                           f"{diag[cat]}/{exp_n}")
        n += entry["n"]
        c_ok += entry["correct"]
    if c_ok != n:
        return False, f"{c_ok}/{n} not all correct"
    return True, f"{c_ok}/{n}"


def verify(name, rep):
    if name == "parity":
        e = rep["latency_observed_us"]["max_abs_err"]
        return e < 1e-4, f"max_abs_err={e:.3e}"
    if name in EXPECTED_REPORTS:
        return _verify_case_report(rep, EXPECTED_REPORTS[name])
    if name == "workflows":
        cells = rep["cells"]
        sem = [k for k in cells if not k.startswith("control")]
        w3 = all(cells[k]["W3_openflight"]["detected"] for k in sem)
        w1 = all(not cells[k]["W1_bare"]["detected"] for k in sem)
        return w3 and w1, f"{len(sem)} fault classes"
    if name == "baseline":
        b, o = rep["baseline"], rep["openflight"]
        ok = (not b["fault_detected"]) and (
            o.get("unknown_unit_blocked") or
            o.get("declared_mismatch_converted"))
        return ok, "fault escapes baseline"
    if name == "e2e":
        reg = rep["bands"]["uniform_pm500"]
        ok = (rep["n_samples"] == 300
              and rep["max_rel_err_composed"] < rep["tolerance_expanded_rel"]
              and reg["max_abs_err_composed"] < rep["tolerance_registered_abs"]
              and rep["n_within_registered_abs_tol"] == reg["n"]
              and isinstance(rep.get("n_within_abs_tol_all"), int)
              and rep["bypass_unit_mismatch"]["silently_divergent"] is True)
        bypass = rep["bypass_unit_mismatch"][
            "max_abs_err_vs_correct_reference"]
        return ok, (f"registered={reg['max_abs_err_composed']:.3e}, "
                    f"rel={rep['max_rel_err_composed']:.3e}, "
                    f"bypass={bypass:.3f}")
    return False, "unknown check"


if __name__ == "__main__":
    raise SystemExit(main())
