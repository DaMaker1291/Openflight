"""Challenge (acceptance) tests for `openflight diagnose` at e8187af.

The implementation under test is FROZEN: openflight/diagnose.py and
openflight/cli.py are exactly as committed in e8187af and are NOT modified
by this file or by this round. This file only ADDS tests.

Each test below corresponds to a row of the diagnostic acceptance matrix.
Any failure is a documented defect of the frozen candidate; it is recorded
here and classified after the round, not fixed in-place.
"""
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import torch

from openflight import cli, diagnose
from openflight.adapters import contracts as C
from openflight.compiler.api import compile_model
from openflight.contract import checker, model_contract as MC
from openflight.contract import pipeline as PL

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "quadrotor_adapter"
RTOL, ATOL = 1e-4, 1e-4


def _stage(name, ref, dep, features=None, derivations=None):
    return {"name": name, "ref": ref, "dep": dep,
            "features": features, "derivations": derivations}


def _import_adapt(path):
    spec = importlib.util.spec_from_file_location("contract_adapt_ref", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_torch(weights):
    from openflight.compiler import loader
    m, _meta = loader.load_model(None, str(weights))
    m.eval()
    return m


def _build_fixture(tmp_path):
    """Validated deployment builddir + recorded trace/reference from the
    shipped quadrotor example contracts and a tiny MLP (same as the
    released feature test)."""
    work = tmp_path / "work"
    work.mkdir()
    sensor_path = work / "drone_contract.yaml"
    model_path = work / "model_contract.yaml"
    shutil.copy(EXAMPLES / "drone_contract.yaml", sensor_path)
    shutil.copy(EXAMPLES / "model_contract.yaml", model_path)

    sensor = C.load_contract(str(sensor_path))
    model = MC.load_model_contract(str(model_path))
    rep = checker.check(sensor, model, model_input_size=6)
    assert rep["status"] == "pass", rep["errors"]

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

    adapt = _import_adapt(build / "contract_adapt.py")
    rng = np.random.default_rng(7)
    raw = rng.uniform(-2.0, 2.0, size=(8, 6))
    model_inputs = np.stack([adapt.adapt(r) for r in raw]).astype(np.float64)
    ref_model = _load_torch(weights)
    with torch.no_grad():
        outputs = ref_model(torch.from_numpy(model_inputs.astype(np.float32))
                            ).numpy().astype(np.float64)

    trace = work / "trace.npz"
    reference = work / "reference.npz"
    np.savez(trace, raw=raw)
    np.savez(reference, model_inputs=model_inputs, outputs=outputs)
    return {"work": work, "weights": weights, "build": build,
            "trace": trace, "reference": reference}


def _diagnose_args(fx, out):
    return ["diagnose",
            "--model", str(fx["weights"]),
            "--trace", str(fx["trace"]),
            "--reference", str(fx["reference"]),
            "--build", str(fx["build"]),
            "--output", str(out)]


def _run(fx, out):
    return cli.main(_diagnose_args(fx, out))


def _corrupt_first_gain(h_path):
    """Multiply out[0]'s gain by 100 (offsets are 0 -> exact x100)."""
    pattern = r"(out\[0\] = raw\[\d+\] \*) ([0-9.eE+-]+)f"
    text = h_path.read_text()
    m = re.search(pattern, text)
    assert m, "expected a generated out[0] line in contract_adapt.h"
    corrupted = float(m.group(2)) * 100.0
    new_text, n = re.subn(
        pattern,
        lambda mm: f"{mm.group(1)}{corrupted!r}f",
        text, count=1)
    assert n == 1 and new_text != text
    h_path.write_text(new_text)


def _corrupt_gain_slightly(h_path):
    """Multiply out[0]'s gain by 1.00001 -> every comparison within tol."""
    pattern = r"(out\[0\] = raw\[\d+\] \*) ([0-9.eE+-]+)f"
    text = h_path.read_text()
    m = re.search(pattern, text)
    assert m
    corrupted = float(m.group(2)) * 1.00001
    new_text, n = re.subn(
        pattern,
        lambda mm: f"{mm.group(1)}{corrupted!r}f",
        text, count=1)
    assert n == 1 and new_text != text
    h_path.write_text(new_text)


def _corrupt_model_output_bias(build):
    """Deployed predict adds 0.05 to output[0] (model stage, not adapter)."""
    hpath = build / "model.cpp"
    text = hpath.read_text()
    old = ("    for (std::size_t i = 0; i < OUTPUT_SIZE; ++i) "
           "output[i] = dst[i];")
    new = ("    for (std::size_t i = 0; i < OUTPUT_SIZE; ++i) "
           "output[i] = dst[i] + (i == 0 ? 0.05f : 0.0f);")
    assert text.count(old) == 1, "expected exactly one output copy loop"
    hpath.write_text(text.replace(old, new, 1))


# ------------------------------------------------------------------ matrix


def test_correct_pipeline_no_false_diagnosis(tmp_path):
    """No fault: agree, exit 0, no bundle, no first divergence."""
    fx = _build_fixture(tmp_path)
    out = tmp_path / "diagnosis"
    rc = _run(fx, out)
    assert rc == 0, f"clean pipeline must agree, got {rc}"
    rep = json.loads((out / "report.json").read_text())
    assert rep["status"] == "agree"
    assert rep["first_divergence"] is None
    assert all(s["status"] == "agree" for s in rep["stages"])
    # summary.md is the human-readable report and is always written; the
    # failure-bundle members must be absent on a passing run.
    assert (out / "summary.md").exists()
    for name in ("failing_inputs.npz", "reference_values.npz",
                 "deployed_values.npz", "artifact_manifest.json",
                 "reproduce.py", "post_fix_comparison.json"):
        assert not (out / name).exists(), f"unexpected bundle member: {name}"


def test_known_preprocessing_fault_localised(tmp_path):
    """x100 gain on the preprocessing adapter: first divergence = the
    preprocessing stage, feature acc_x, ratio ~100, bundle written."""
    fx = _build_fixture(tmp_path)
    out = tmp_path / "diagnosis"
    rc = _run(fx, out)
    assert rc == 0  # condition 1: clean
    _corrupt_first_gain(fx["build"] / "contract_adapt.h")
    rc = _run(fx, out)
    assert rc == 4, f"x100 fault must be reproduced, got {rc}"
    rep = json.loads((out / "report.json").read_text())
    assert rep["status"] == "discrepancy"
    fd = rep["first_divergence"]
    assert fd["stage"] == "preprocessing", fd
    assert fd["feature"] == "acc_x", fd
    assert fd["row"] == 0 and fd["col"] == 0, fd
    assert fd["ratio"] == pytest.approx(100.0, rel=1e-3), fd
    for name in ("failing_inputs.npz", "reference_values.npz",
                 "deployed_values.npz", "artifact_manifest.json",
                 "summary.md", "reproduce.py"):
        assert (out / name).exists(), f"bundle member missing: {name}"


def test_post_preprocessing_discrepancy_model_stage(tmp_path):
    """Deployed predict corrupted (bias on output[0]) while the adapter is
    correct: earliest divergence must be the model stage."""
    fx = _build_fixture(tmp_path)
    out = tmp_path / "diagnosis"
    _corrupt_model_output_bias(fx["build"])
    rc = _run(fx, out)
    assert rc == 4, f"model-stage fault must be reproduced, got {rc}"
    rep = json.loads((out / "report.json").read_text())
    assert rep["status"] == "discrepancy"
    fd = rep["first_divergence"]
    assert fd["stage"] == "model", fd
    stages = {s["name"]: s["status"] for s in rep["stages"]}
    assert stages["preprocessing"] == "agree", stages
    assert stages["model"] == "diverge", stages
    assert stages["end_to_end"] == "diverge", stages  # propagated


def test_simultaneous_faults_earliest_reported_not_unique(tmp_path):
    """Two faults at once (adapter x100 + predict bias): report identifies
    the earliest OBSERVED divergence (preprocessing) and lists every
    diverged stage; it must not claim a unique root cause."""
    fx = _build_fixture(tmp_path)
    out = tmp_path / "diagnosis"
    _corrupt_first_gain(fx["build"] / "contract_adapt.h")
    _corrupt_model_output_bias(fx["build"])
    rc = _run(fx, out)
    assert rc == 4
    rep = json.loads((out / "report.json").read_text())
    fd = rep["first_divergence"]
    assert fd["stage"] == "preprocessing", fd  # earliest observed stage
    diverged = [s["name"] for s in rep["stages"]
                if s["status"] == "diverge"]
    assert len(diverged) >= 2, diverged  # more than one stage affected
    assert "model" in diverged and "end_to_end" in diverged, diverged
    # No field in the report claims a unique root cause; the summary lists
    # each stage independently (OK / DIVERGED).
    assert all(k in rep for k in ("stages", "first_divergence", "status"))


def test_small_in_tolerance_perturbation_no_failure(tmp_path):
    """A 0.001% gain change keeps every cell within atol + rtol*|ref|:
    no inappropriate failure."""
    fx = _build_fixture(tmp_path)
    out = tmp_path / "diagnosis"
    _corrupt_gain_slightly(fx["build"] / "contract_adapt.h")
    rc = _run(fx, out)
    assert rc == 0, f"in-tolerance perturbation must pass, got {rc}"
    rep = json.loads((out / "report.json").read_text())
    assert rep["status"] == "agree"
    assert rep["first_divergence"] is None


def test_tolerance_rule_engine_level():
    """The comparison rule is |ref-dep| <= atol + rtol*|ref|; non-finite
    always diverges (engine, unit level)."""
    ref = np.ones((4, 3)) * 2.0
    # below tolerance: 0.5e-4 < atol(1e-4) + rtol*2 = 1.0002e-4
    dep = ref + 0.5e-4
    out = diagnose.compare([_stage("preprocessing", ref, dep)],
                           rtol=RTOL, atol=ATOL)
    assert out["first_divergence"] is None
    assert out["stages"][0]["status"] == "agree"

    # above tolerance: 0.9 > bound
    dep = ref + 0.9
    out = diagnose.compare([_stage("preprocessing", ref, dep)],
                           rtol=RTOL, atol=ATOL)
    fd = out["first_divergence"]
    assert fd is not None and fd["stage"] == "preprocessing"
    assert out["stages"][0]["status"] == "diverge"


def test_non_finite_comparison_always_diverges():
    """Non-finite compared values diverge per the documented rule."""
    ref = np.ones((2, 3))
    dep_nan = ref.copy()
    dep_nan[0, 1] = float("nan")
    out = diagnose.compare([_stage("preprocessing", ref, dep_nan)],
                           rtol=RTOL, atol=ATOL)
    fd = out["first_divergence"]
    assert fd is not None
    assert (fd["row"], fd["col"]) == (0, 1)
    # the reference side is finite here and is reported numerically; the
    # non-finite deployed side is reported as null (_num(NaN) -> None).
    assert fd["reference"] == 1.0 and fd["deployed"] is None
    assert out["stages"][0]["n_nonfinite"] == 1
    assert out["stages"][0]["status"] == "diverge"

    dep_inf = ref.copy()
    dep_inf[1, 2] = float("inf")
    out = diagnose.compare([_stage("preprocessing", ref, dep_inf)],
                           rtol=RTOL, atol=ATOL)
    assert out["first_divergence"] is not None
    assert out["stages"][0]["n_nonfinite"] == 1


def test_non_finite_inputs_rejected_at_cli(tmp_path):
    """Non-finite trace/reference inputs are rejected before comparison
    (E051/E052 -> exit 2), not diagnosed as a stage divergence."""
    fx = _build_fixture(tmp_path)
    out = tmp_path / "diagnosis"

    bad_trace = tmp_path / "bad_trace.npz"
    raw = np.load(fx["trace"])["raw"]
    raw[0, 0] = float("nan")
    np.savez(bad_trace, raw=raw)
    rc = cli.main(["diagnose", "--model", str(fx["weights"]),
                   "--trace", str(bad_trace), "--reference",
                   str(fx["reference"]), "--build", str(fx["build"]),
                   "--output", str(out / "badtrace")])
    assert rc == 2, f"non-finite trace must be E051 (exit 2), got {rc}"

    bad_ref = tmp_path / "bad_ref.npz"
    refd = np.load(fx["reference"])
    mi = refd["model_inputs"].copy()
    mi[2, 1] = float("inf")
    np.savez(bad_ref, model_inputs=mi, outputs=refd["outputs"])
    rc = cli.main(["diagnose", "--model", str(fx["weights"]),
                   "--trace", str(fx["trace"]), "--reference",
                   str(bad_ref), "--build", str(fx["build"]),
                   "--output", str(out / "badref")])
    assert rc == 2, f"non-finite reference must be E052 (exit 2), got {rc}"


def _copy_bundle(src_outdir: Path, dst: Path):
    """Copy the artifacts a standalone reproduction needs."""
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("report.json", "reference_values.npz",
                 "deployed_values.npz", "failing_inputs.npz",
                 "artifact_manifest.json", "reproduce.py"):
        shutil.copy(src_outdir / name, dst / name)


def test_changed_artifact_not_accepted_as_current(tmp_path):
    """After a disagree diagnosis, altering an original artifact must make
    reproduce.py --full refuse ('artifact changed since diagnosis'), and
    altering a bundle member must fail the self-check (hash/cell mismatch)."""
    fx = _build_fixture(tmp_path)
    out = tmp_path / "diagnosis"
    _corrupt_first_gain(fx["build"] / "contract_adapt.h")
    rc = _run(fx, out)
    assert rc == 4

    # 1) original model altered -> full re-run detects the change
    with open(fx["weights"], "ab") as f:
        f.write(b"\x00")
    r = subprocess.run([sys.executable, str(out / "reproduce.py"), "--full"],
                       capture_output=True, text=True, cwd=out)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "artifact changed since diagnosis" in r.stdout, r.stdout

    # 2) bundle member altered -> self-check fails (old evidence not trusted)
    dep = np.load(out / "deployed_values.npz")
    mi = dep["model_outputs_on_reference"].copy()
    mi[0, 0] += 1.0
    np.savez(out / "deployed_values.npz",
             model_inputs=dep["model_inputs"],
             outputs=dep["outputs"],
             model_outputs_on_reference=mi)
    r = subprocess.run([sys.executable, str(out / "reproduce.py")],
                       capture_output=True, text=True, cwd=out)
    assert r.returncode == 1, r.stdout + r.stderr
    assert ("cell mismatch" in r.stdout
            or "bundle member hash mismatch" in r.stdout), r.stdout


def test_fresh_workspace_self_check_reproduces(tmp_path):
    """Copying only the bundle artifacts to a clean workspace must reproduce
    the same diagnosis via reproduce.py (self-check), without local paths,
    caches or generated files beyond the bundle itself."""
    fx = _build_fixture(tmp_path)
    out = tmp_path / "diagnosis"
    _corrupt_first_gain(fx["build"] / "contract_adapt.h")
    rc = _run(fx, out)
    assert rc == 4

    clean = tmp_path / "clean_workspace"
    _copy_bundle(out, clean)
    assert not (clean / "contract_adapt.h").exists()
    assert not (clean / "controller.pt").exists()

    r = subprocess.run([sys.executable, str(clean / "reproduce.py")],
                       capture_output=True, text=True, cwd=clean)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "REPRODUCED:" in r.stdout, r.stdout
    assert "preprocessing divergence at sample 0 element 0" in r.stdout

    # --full re-runs the diagnosis and is documented to require the original
    # artifacts. With the originals still present it reproduces.
    r = subprocess.run([sys.executable, str(clean / "reproduce.py"), "--full"],
                       capture_output=True, text=True, cwd=clean)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "MATCH" in r.stdout, r.stdout

    # With the originals gone (a true third-party workspace) --full refuses
    # honestly instead of pretending.
    shutil.rmtree(fx["work"])
    r = subprocess.run([sys.executable, str(clean / "reproduce.py"), "--full"],
                       capture_output=True, text=True, cwd=clean)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "missing original artifact" in r.stdout, r.stdout

    # Tampering the copied bundle breaks reproduction.
    dep = np.load(clean / "deployed_values.npz")
    ref = dep["model_outputs_on_reference"].copy()
    ref[0, 0] += 1.0
    np.savez(clean / "deployed_values.npz",
             model_inputs=dep["model_inputs"],
             outputs=dep["outputs"],
             model_outputs_on_reference=ref)
    r = subprocess.run([sys.executable, str(clean / "reproduce.py")],
                       capture_output=True, text=True, cwd=clean)
    assert r.returncode == 1, r.stdout + r.stderr
    assert ("cell mismatch" in r.stdout
            or "bundle member hash mismatch" in r.stdout), r.stdout


# ------------------------------------------------- additional review finding

def test_reproduction_integrity_changed_build_not_reported_as_match(tmp_path):
    """Finding (reviewer, 2026-10-17): reproduce.py --full verifies the
    model/trace/reference hashes but NOT the deployment build artifacts that
    the report records, and it compares only the overall status. A build
    change that keeps status='discrepancy' but moves the first divergence is
    therefore reported as a faithful MATCH.

    Desired property (not yet implemented): a full rerun must either reject
    a changed deployment artifact or surface a changed first divergence.

    Against the frozen implementation this test FAILS (it observes MATCH),
    recording the gap. It is a verification finding, not a feature request.
    """
    fx = _build_fixture(tmp_path)
    out = tmp_path / "diagnosis"
    h_path = fx["build"] / "contract_adapt.h"
    original_adapter = h_path.read_text()

    # original diagnosis: the preprocessing stage diverges (x100 gain)
    _corrupt_first_gain(h_path)
    rc = _run(fx, out)
    assert rc == 4
    rep = json.loads((out / "report.json").read_text())
    assert rep["first_divergence"]["stage"] == "preprocessing"
    # the report DOES record build-artifact hashes (used only for the record)
    assert rep["inputs"]["build"]["artifacts"], "build hashes must be recorded"

    # Change the build so the rerun is STILL a discrepancy, but at a
    # different stage: repair the adapter and corrupt the model instead.
    h_path.write_text(original_adapter)
    _corrupt_model_output_bias(fx["build"])

    r = subprocess.run([sys.executable, str(out / "reproduce.py"), "--full"],
                       capture_output=True, text=True, cwd=out)
    # desired: reject the changed build / detect the changed diagnosis
    assert r.returncode == 1, (
        "a changed build (same status, different first divergence) must not "
        "be reported as a faithful reproduction:\n" + r.stdout)
    assert "MATCH" not in r.stdout, r.stdout


def _bundle_out(tmp_path, fx):
    out = tmp_path / "diagnosis"
    _corrupt_first_gain(fx["build"] / "contract_adapt.h")
    assert _run(fx, out) == 4
    return out


def test_self_check_rejects_report_pointing_to_later_cell(tmp_path):
    """The self-check must recompute the FIRST divergence from the saved
    arrays, not merely trust the recorded cell. A tampered report that points
    to a later (still divergent) cell must be rejected."""
    fx = _build_fixture(tmp_path)
    out = _bundle_out(tmp_path, fx)
    rep_path = out / "report.json"
    rep = json.loads(rep_path.read_text())
    assert rep["first_divergence"]["row"] == 0
    ref = np.load(out / "reference_values.npz")["model_inputs"]
    dep = np.load(out / "deployed_values.npz")["model_inputs"]
    rep["first_divergence"]["row"] = 1  # a later, also-divergent row
    rep["first_divergence"]["reference"] = float(ref[1, 0])
    rep["first_divergence"]["deployed"] = float(dep[1, 0])
    rep_path.write_text(json.dumps(rep))

    r = subprocess.run([sys.executable, str(out / "reproduce.py")],
                       capture_output=True, text=True, cwd=out)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "reconstructed first divergence differs" in r.stdout, r.stdout


def test_self_check_rejects_report_contradicting_evidence(tmp_path):
    """A report claiming agreement while the saved evidence diverges must
    be rejected."""
    fx = _build_fixture(tmp_path)
    out = _bundle_out(tmp_path, fx)
    rep_path = out / "report.json"
    rep = json.loads(rep_path.read_text())
    rep["status"] = "agree"
    rep["first_divergence"] = None
    rep_path.write_text(json.dumps(rep))

    r = subprocess.run([sys.executable, str(out / "reproduce.py")],
                       capture_output=True, text=True, cwd=out)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "claims agreement but saved evidence diverges" in r.stdout, r.stdout


def test_full_rerun_uses_recorded_tolerances(tmp_path):
    """--full must reuse the tolerances recorded at diagnosis time. A clean
    pipeline diagnosed at atol=rtol=1e-9 diverges; a rerun at the default
    1e-4 tolerances would agree, so a faithful rerun (same tolerances) is
    distinguishable."""
    fx = _build_fixture(tmp_path)
    out = tmp_path / "diagnosis"
    rc = cli.main(_diagnose_args(fx, out) + ["--rtol", "1e-9", "--atol", "1e-9"])
    assert rc == 4, f"tight tolerance on a clean pipeline must diverge, got {rc}"
    rep = json.loads((out / "report.json").read_text())
    assert rep["tolerances"]["rtol"] == pytest.approx(1e-9)
    assert rep["tolerances"]["atol"] == pytest.approx(1e-9)

    r = subprocess.run([sys.executable, str(out / "reproduce.py"), "--full"],
                       capture_output=True, text=True, cwd=out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "MATCH" in r.stdout, r.stdout


# ------------------------------------------ bundle metadata consistency

def test_self_check_rejects_altered_report_tolerances(tmp_path):
    """Altering only report.json's tolerances (evidence and manifest
    untouched) must be rejected: the report duplicates the manifest's
    tolerances and must still agree with the hash-protected manifest."""
    fx = _build_fixture(tmp_path)
    out = _bundle_out(tmp_path, fx)
    rep_path = out / "report.json"
    man_path = out / "artifact_manifest.json"
    rep = json.loads(rep_path.read_text())
    man = json.loads(man_path.read_text())
    assert rep["tolerances"] == man["tolerances"]
    # a small change that keeps the same first divergence
    rep["tolerances"]["atol"] = rep["tolerances"]["atol"] * 1.5
    assert rep["tolerances"] != man["tolerances"]
    rep_path.write_text(json.dumps(rep))

    r = subprocess.run([sys.executable, str(out / "reproduce.py")],
                       capture_output=True, text=True, cwd=out)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "tolerances" in r.stdout and "manifest" in r.stdout, r.stdout


def test_self_check_rejects_altered_stage_status(tmp_path):
    """Flipping a recorded stage status while the evidence is unchanged must
    be rejected: per-stage statuses are re-derived from the saved arrays."""
    fx = _build_fixture(tmp_path)
    out = _bundle_out(tmp_path, fx)
    rep_path = out / "report.json"
    rep = json.loads(rep_path.read_text())
    first_stage = rep["first_divergence"]["stage"]
    flipped = None
    for s in rep["stages"]:
        if s["status"] == "diverge" and s["name"] != first_stage:
            s["status"] = "agree"
            flipped = s["name"]
            break
    assert flipped is not None, "expected a non-first diverged stage"
    rep_path.write_text(json.dumps(rep))

    r = subprocess.run([sys.executable, str(out / "reproduce.py")],
                       capture_output=True, text=True, cwd=out)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "stage status" in r.stdout and flipped in r.stdout, r.stdout


def test_self_check_rejects_altered_report_shapes(tmp_path):
    """Other duplicated metadata (e.g. shapes) must also agree with the
    manifest."""
    fx = _build_fixture(tmp_path)
    out = _bundle_out(tmp_path, fx)
    rep_path = out / "report.json"
    rep = json.loads(rep_path.read_text())
    rep["shapes"]["n_samples"] = rep["shapes"]["n_samples"] + 1
    rep_path.write_text(json.dumps(rep))

    r = subprocess.run([sys.executable, str(out / "reproduce.py")],
                       capture_output=True, text=True, cwd=out)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "shapes" in r.stdout and "manifest" in r.stdout, r.stdout


def test_self_check_rejects_unsupported_status(tmp_path):
    """The overall status must be a supported value and agree with the saved
    evidence. Setting it to an unsupported value while leaving all evidence
    unchanged must be rejected."""
    fx = _build_fixture(tmp_path)
    out = _bundle_out(tmp_path, fx)
    p = out / "report.json"
    rep = json.loads(p.read_text())
    assert rep["status"] == "discrepancy"
    rep["status"] = "tampered"  # unsupported; evidence and manifest unchanged
    p.write_text(json.dumps(rep))

    r = subprocess.run([sys.executable, str(out / "reproduce.py")],
                       capture_output=True, text=True, cwd=out)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "unsupported report status" in r.stdout, r.stdout


def test_valid_discrepancy_bundle_still_passes(tmp_path):
    """A faithful discrepancy bundle must still self-check successfully."""
    fx = _build_fixture(tmp_path)
    out = _bundle_out(tmp_path, fx)
    r = subprocess.run([sys.executable, str(out / "reproduce.py")],
                       capture_output=True, text=True, cwd=out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "REPRODUCED:" in r.stdout, r.stdout


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _rewrite_as_coherent_agree(out):
    """Turn a discrepancy bundle into a coherent agree bundle: make the
    deployed arrays equal the reference arrays, flip statuses, and recompute
    the recorded hashes so the bundle is internally consistent."""
    ref = np.load(out / "reference_values.npz")
    np.savez(out / "deployed_values.npz",
             model_inputs=ref["model_inputs"],
             outputs=ref["outputs"],
             model_outputs_on_reference=ref["model_outputs_pytorch"])
    rep = json.loads((out / "report.json").read_text())
    rep["status"] = "agree"
    rep["first_divergence"] = None
    for s in rep["stages"]:
        s["status"] = "agree"
        s["n_failing_cells"] = 0
        s["n_failing_samples"] = 0
    members = ("failing_inputs.npz", "reference_values.npz",
               "deployed_values.npz", "artifact_manifest.json")
    rep["bundle_shas"] = {m: _sha(out / m) for m in members}
    (out / "report.json").write_text(json.dumps(rep))


def test_valid_agree_bundle_still_passes(tmp_path):
    """A coherent agree report (evidence agrees, statuses agree) must still
    self-check successfully."""
    fx = _build_fixture(tmp_path)
    out = _bundle_out(tmp_path, fx)
    _rewrite_as_coherent_agree(out)
    r = subprocess.run([sys.executable, str(out / "reproduce.py")],
                       capture_output=True, text=True, cwd=out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "agree" in r.stdout, r.stdout

