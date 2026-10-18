#!/usr/bin/env python3
"""Independent verification harness for the `openflight diagnose`
reproduction-integrity corrections.

Corrections under verification (newest first):
  ed03d0e  overall report status must be supported and agree with evidence
  8d40267  report metadata duplicated from the manifest must agree with it
  3b44a2d  full re-run must verify build artifacts and reconstruct from the
           saved arrays rather than trust the recorded summary

The harness is deliberately independent of the author-run pytest checks: it
builds its own bundle with the `openflight diagnose` CLI, then perturbs one
field at a time and observes the behaviour of the generated `reproduce.py`.
It writes nothing into the repository; all work happens in a temporary
directory.

Run it from a clean virtual environment holding the pinned dependencies
(`pip install -r requirements-lock.txt`) and the project importable
(`pip install -e . --no-deps`).

  python reproduction/verify_diagnose_integrity.py

To also demonstrate that the pre-fix candidate ACCEPTED these same
tampering cases (i.e. that the defects were real), check out the frozen
candidate in a separate worktree and point the harness at it:

  git worktree add /tmp/openflight-e8187af e8187af
  python reproduction/verify_diagnose_integrity.py \
      --prefix-root /tmp/openflight-e8187af

Exit code 0 iff every check produced the expected verdict.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCK = REPO / "requirements-lock.txt"
FROZEN_TAG = "v0.2.6-pilot"
FROZEN_TAG_COMMIT = "5840dfe7ddb055cb962fee32bd82ba8419d27f51"
FROZEN_CANDIDATE = "e8187af3dc3a05db581adecccdf6d229ce0638d2"
DEFAULT_EXPECTED_PASSED = 290

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
_results = []


def _record(status, name, detail=""):
    _results.append((status, name, detail))
    line = f"[{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line, flush=True)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ------------------------------------------------------------------ worker


def _corrupt_first_gain(h_path):
    """Multiply out[0]'s gain by 100 in the generated adapter header."""
    import re
    pattern = r"(out\[0\] = raw\[\d+\] \*) ([0-9.eE+-]+)f"
    text = h_path.read_text()
    m = re.search(pattern, text)
    if not m:
        raise RuntimeError("expected a generated out[0] line in contract_adapt.h")
    corrupted = float(m.group(2)) * 100.0
    new_text, n = re.subn(pattern, lambda mm: f"{mm.group(1)}{corrupted!r}f",
                          text, count=1)
    if n != 1 or new_text == text:
        raise RuntimeError("failed to corrupt the adapter gain")
    h_path.write_text(new_text)


def _worker_build(root, base):
    """Build a genuine discrepancy bundle using *root*'s openflight package,
    and print its path. Runs in a subprocess so each root uses its own code."""
    import numpy as np
    import torch

    sys.path.insert(0, str(root))
    from openflight import cli
    from openflight.adapters import contracts as C
    from openflight.compiler import loader
    from openflight.compiler.api import compile_model
    from openflight.contract import checker, model_contract as MC, pipeline as PL

    examples = Path(root) / "examples" / "quadrotor_adapter"
    work = Path(base) / "work"
    work.mkdir(parents=True, exist_ok=True)
    sensor_path = work / "drone_contract.yaml"
    model_path = work / "model_contract.yaml"
    shutil.copy(examples / "drone_contract.yaml", sensor_path)
    shutil.copy(examples / "model_contract.yaml", model_path)

    sensor = C.load_contract(str(sensor_path))
    model = MC.load_model_contract(str(model_path))
    rep = checker.check(sensor, model, model_input_size=6)
    if rep["status"] != "pass":
        raise RuntimeError(f"example contracts did not validate: {rep['errors']}")

    build = work / "deployed"
    build.mkdir()
    PL.generate(sensor, model, str(build / "contract_adapt.py"),
                str(build / "contract_adapt.h"))
    PL.write_manifest(str(sensor_path), str(model_path), str(build))

    torch.manual_seed(3)
    sd = {"0.weight": torch.randn(16, 6) * 0.2, "0.bias": torch.zeros(16),
          "2.weight": torch.randn(3, 16) * 0.2, "2.bias": torch.zeros(3)}
    weights = work / "controller.pt"
    torch.save(sd, weights)
    compile_model(cli._resolve_arch("mlp:6,16,3"), str(weights), str(build))

    spec = importlib.util.spec_from_file_location(
        "contract_adapt_ref", build / "contract_adapt.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rng = np.random.default_rng(7)
    raw = rng.uniform(-2.0, 2.0, size=(8, 6))
    model_inputs = np.stack([mod.adapt(r) for r in raw]).astype(np.float64)
    ref_model, _meta = loader.load_model(None, str(weights))
    ref_model.eval()
    with torch.no_grad():
        outputs = ref_model(torch.from_numpy(
            model_inputs.astype(np.float32))).numpy().astype(np.float64)

    trace = work / "trace.npz"
    reference = work / "reference.npz"
    np.savez(trace, raw=raw)
    np.savez(reference, model_inputs=model_inputs, outputs=outputs)

    _corrupt_first_gain(build / "contract_adapt.h")

    out = Path(base) / "diagnosis"
    rc = cli.main(["diagnose",
                   "--model", str(weights), "--trace", str(trace),
                   "--reference", str(reference), "--build", str(build),
                   "--output", str(out)])
    if rc != 4:
        raise RuntimeError(f"expected a discrepancy bundle (exit 4), got {rc}")
    print(f"BUNDLE={out}")
    return 0


# ----------------------------------------------------------- tamper cases


def _load_report(bundle):
    with open(bundle / "report.json") as f:
        return json.load(f)


def _save_report(bundle, rep):
    with open(bundle / "report.json", "w") as f:
        json.dump(rep, f)


def _mut_status(bundle):
    rep = _load_report(bundle)
    assert rep["status"] == "discrepancy"
    rep["status"] = "tampered"
    _save_report(bundle, rep)


def _mut_tolerances(bundle):
    rep = _load_report(bundle)
    rep["tolerances"]["rtol"] = float(rep["tolerances"]["rtol"]) * 2.0
    _save_report(bundle, rep)


def _mut_stage_status(bundle):
    rep = _load_report(bundle)
    assert rep["stages"][0]["status"] == "diverge"
    rep["stages"][0]["status"] = "agree"
    _save_report(bundle, rep)


def _mut_shapes(bundle):
    rep = _load_report(bundle)
    rep["shapes"]["n_samples"] = rep["shapes"]["n_samples"] + 1
    _save_report(bundle, rep)


def _mut_build_artifact(bundle):
    rep = _load_report(bundle)
    target = Path(rep["inputs"]["build"]["path"]) / "model.cpp"
    original = target.read_bytes()
    target.write_bytes(original + b"\n// verification tamper\n")

    def undo():
        target.write_bytes(original)
    return undo


# id, description, extra reproduce.py argv, mutation, (returns undo|None)
SCENARIOS = [
    ("baseline", "faithful bundle, no tampering", [], lambda b: None),
    ("status", "overall status set to unsupported value", [], _mut_status),
    ("tolerances", "report tolerances altered", [], _mut_tolerances),
    ("stage_status", "one stage status flipped", [], _mut_stage_status),
    ("shapes", "report shapes altered", [], _mut_shapes),
    ("build_artifact", "build artifact changed, checked with --full",
     ["--full"], _mut_build_artifact),
]


def _expected_reject(is_candidate, sid):
    """On the corrected candidate every tamper is rejected and the baseline
    passes; on the frozen pre-fix candidate nothing is rejected."""
    if sid == "baseline":
        return False
    return bool(is_candidate)


def _run_scenarios(label, root, bundle, is_candidate, tmp):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    for sid, desc, argv, mutate in SCENARIOS:
        case = tmp / f"{label}_{sid}"
        shutil.copytree(bundle, case)
        undo = mutate(case)
        try:
            r = subprocess.run(
                [sys.executable, str(case / "reproduce.py")] + argv,
                capture_output=True, text=True, cwd=case, env=env)
        finally:
            if undo:
                undo()
        rejected = r.returncode != 0
        want = _expected_reject(is_candidate, sid)
        ok = rejected == want
        verdict = "rejected" if rejected else "accepted"
        expected = "rejected" if want else "accepted"
        detail = f"{desc}: {verdict} (expected {expected})"
        _record(PASS if ok else FAIL, f"{label}/{sid}", detail)


# ---------------------------------------------------------- repo checks


def _check_provenance():
    if not (REPO / ".git").exists():
        _record(WARN, "provenance", "not a git checkout; git checks skipped")
        return
    def git(*args):
        return subprocess.run(["git", "-C", str(REPO)] + list(args),
                              capture_output=True, text=True)
    head = git("rev-parse", "HEAD").stdout.strip()
    _record(PASS, "git HEAD", head)
    tag = git("rev-parse", f"{FROZEN_TAG}^{{commit}}").stdout.strip()
    _record(PASS if tag == FROZEN_TAG_COMMIT else FAIL,
            f"tag {FROZEN_TAG} unchanged",
            f"{tag} (expected {FROZEN_TAG_COMMIT})")
    for ref in ("e8187af", "openflight-v0.2"):
        r = git("rev-parse", f"{ref}^{{commit}}")
        if r.returncode != 0:
            _record(WARN, f"ref {ref}", "not present locally")
            continue
        got = r.stdout.strip()
        _record(PASS if got == FROZEN_CANDIDATE else WARN, f"ref {ref}",
                f"{got} (frozen candidate is {FROZEN_CANDIDATE})")


def normalize(name):
    """PEP 503 name normalisation: lowercase, runs of -_. -> single -."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def parse_pins(text):
    """Parse 'name==version' lines (pip freeze or the lock file) into a
    {normalised_name: version} mapping; comments and non-pinned lines
    (editable installs, VCS URLs) are ignored."""
    pins = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, _, ver = line.partition("==")
        pins[normalize(name)] = ver.strip()
    return pins


def check_pins(pins, installed):
    """Return a (status, name, detail) record for every pinned package.
    A package that is missing or at a different version is a FAIL."""
    results = []
    for canon in sorted(pins):
        want = pins[canon]
        got = installed.get(canon)
        if got is None:
            results.append((FAIL, f"dependency {canon}",
                            f"not installed (pin {want})"))
        elif got != want:
            results.append((FAIL, f"dependency {canon}",
                            f"{got} != pinned {want} (required pinned set)"))
        else:
            results.append((PASS, f"dependency {canon}", got))
    return results


def verdict(results):
    """Nonzero iff any check failed."""
    return 1 if any(s == FAIL for s, _n, _d in results) else 0


def _check_environment():
    r = subprocess.run([sys.executable, "-m", "pip", "freeze"],
                       capture_output=True, text=True)
    installed = parse_pins(r.stdout)
    pins = parse_pins(LOCK.read_text())
    for status, name, detail in check_pins(pins, installed):
        _record(status, name, detail)


def _check_suite(expected):
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/openflight",
                        "-q"], capture_output=True, text=True, cwd=REPO)
    tail = (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else ""
    import re
    m = re.search(r"(\d+) passed", r.stdout)
    passed = int(m.group(1)) if m else -1
    ok = r.returncode == 0 and passed == expected
    _record(PASS if ok else FAIL, "test suite",
            f"{passed} passed (expected {expected}); {tail}")


def _check_repro():
    r = subprocess.run([sys.executable, "openflight/repro.py"],
                       capture_output=True, text=True, cwd=REPO)
    ok = r.returncode == 0 and "REPRODUCTION OK" in r.stdout
    _record(PASS if ok else FAIL, "repro.py",
            "REPRODUCTION OK" if ok else "did not report REPRODUCTION OK")


def _verify_root(label, root, tmp, is_candidate):
    base = tmp / f"build_{label}"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()),
         "--worker-build", str(base), "--worker-root", str(root)],
        capture_output=True, text=True, cwd=str(tmp), env=env)
    if r.returncode != 0:
        _record(FAIL, f"{label}/build", (r.stdout + r.stderr).strip()[-300:])
        return
    bundle = None
    for line in r.stdout.splitlines():
        if line.startswith("BUNDLE="):
            bundle = Path(line.split("=", 1)[1].strip())
    if not bundle or not bundle.is_dir():
        _record(FAIL, f"{label}/build", "worker produced no bundle")
        return
    _record(PASS, f"{label}/build", f"discrepancy bundle at {bundle}")
    _run_scenarios(label, root, bundle, is_candidate, tmp)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--worker-build", help=argparse.SUPPRESS)
    ap.add_argument("--worker-root", help=argparse.SUPPRESS)
    ap.add_argument("--prefix-root",
                    help="an existing checkout of the pre-fix candidate "
                         "(e.g. a worktree of e8187af) to compare against")
    ap.add_argument("--expect-passed", type=int, default=DEFAULT_EXPECTED_PASSED,
                    help=f"expected number of passing tests (default "
                         f"{DEFAULT_EXPECTED_PASSED})")
    ap.add_argument("--skip-suite", action="store_true")
    args = ap.parse_args()

    if args.worker_build:
        return _worker_build(Path(args.worker_root), args.worker_build)

    print(f"verify_diagnose_integrity: candidate root = {REPO}", flush=True)
    print(f"python {sys.version.split()[0]}", flush=True)
    _check_provenance()
    _check_environment()
    if args.skip_suite:
        _record(WARN, "test suite", "skipped by request")
    else:
        _check_suite(args.expect_passed)
    _check_repro()

    with tempfile.TemporaryDirectory(prefix="of_verify_") as tmpdir:
        tmp = Path(tmpdir)
        _verify_root("candidate", REPO, tmp, is_candidate=True)
        if args.prefix_root:
            _verify_root("prefix", Path(args.prefix_root).resolve(), tmp,
                         is_candidate=False)

    failed = [r for r in _results if r[0] == FAIL]
    warned = [r for r in _results if r[0] == WARN]
    print("\n================ summary ================", flush=True)
    print(f"checks: {len(_results)}  failed: {len(failed)}  warnings: {len(warned)}")
    if failed:
        for status, name, detail in failed:
            print(f"  FAIL {name}: {detail}")
    print("VERDICT:", "FAIL" if failed else "PASSWITHWARNINGS" if warned else "PASS")
    return verdict(_results)


if __name__ == "__main__":
    sys.exit(main())
