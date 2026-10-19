"""Fail-first tests for `openflight diagnose` (RESEARCH_PLAN Amendment 2).

The feature: automatic first-divergence diagnosis between a reference
pipeline (recorded training-side values + PyTorch) and a deployed
implementation (generated preprocessing adapter + generated C++) over one
recorded input trace, with a reproducible failure bundle.

Unit tests target the comparison engine; the integration test runs the
three conditions required by the advisor's demonstration on 2026-10-17:
(1) clean pipelines agree, (2) a deliberately corrupted preprocessing
transformation is localized as the first divergence, (3) the correction
is verified by re-running the same recorded test.
"""
import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from openflight import cli, diagnose
from openflight.errors import OpenFlightError

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "quadrotor_adapter"
RTOL, ATOL = 1e-4, 1e-4


# ---------------------------------------------------------------- engine

def _stage(name, ref, dep, features=None, derivations=None):
    return {"name": name, "ref": ref, "dep": dep,
            "features": features, "derivations": derivations}


def test_compare_localizes_first_divergence():
    ref = np.tile(np.arange(1, 7, dtype=float) * 0.5, (5, 1))
    dep = ref.copy()
    dep[3, 2] *= 100.0
    out = diagnose.compare([_stage("preprocessing", ref, dep,
                                   features=[f"f{i}" for i in range(6)])],
                           rtol=RTOL, atol=ATOL)
    fd = out["first_divergence"]
    assert fd is not None, "divergence must be localized"
    assert (fd["row"], fd["col"]) == (3, 2)
    assert fd["stage"] == "preprocessing"
    assert fd["feature"] == "f2"
    assert fd["ratio"] == pytest.approx(100.0)
    assert fd["reference"] == ref[3, 2] and fd["deployed"] == dep[3, 2]
    assert out["stages"][0]["status"] == "diverge"


def test_compare_agrees_within_tolerance():
    ref = np.ones((4, 6)) * 2.0
    dep = ref + 0.5e-4  # below atol=1e-4 + rtol*|ref|
    out = diagnose.compare([_stage("preprocessing", ref, dep)],
                           rtol=RTOL, atol=ATOL)
    assert out["first_divergence"] is None
    assert out["stages"][0]["status"] == "agree"
    assert out["stages"][0]["n_failing_cells"] == 0


def test_compare_reports_earliest_stage():
    ref_p = np.ones((3, 4))
    dep_p = ref_p * 50.0
    ref_m = np.ones((3, 2))
    dep_m = ref_m * 7.0
    out = diagnose.compare(
        [_stage("preprocessing", ref_p, dep_p),
         _stage("model", ref_m, dep_m)], rtol=RTOL, atol=ATOL)
    assert out["first_divergence"]["stage"] == "preprocessing"
    assert out["stages"][1]["status"] == "diverge"  # both reported


def test_compare_model_only_divergence():
    ref = np.ones((3, 4))
    out = diagnose.compare(
        [_stage("preprocessing", ref, ref.copy()),
         _stage("model", np.ones((3, 2)), np.ones((3, 2)) * 3.0)],
        rtol=RTOL, atol=ATOL)
    fd = out["first_divergence"]
    assert fd is not None and fd["stage"] == "model"


def test_nonfinite_value_always_diverges():
    ref = np.ones((2, 3))
    dep = ref.copy()
    dep[1, 1] = np.nan
    out = diagnose.compare([_stage("preprocessing", ref, dep)],
                           rtol=RTOL, atol=ATOL)
    fd = out["first_divergence"]
    assert fd is not None and (fd["row"], fd["col"]) == (1, 1)


def test_feature_names_fall_back_to_indices():
    ref = np.zeros((2, 3))
    dep = ref.copy()
    dep[0, 2] = 9.0
    out = diagnose.compare([_stage("preprocessing", ref, dep, features=None)],
                           rtol=RTOL, atol=ATOL)
    assert out["first_divergence"]["feature"] == "feature[2]"


# ----------------------------------------------------------- config errors

def test_load_trace_requires_raw_key(tmp_path):
    p = tmp_path / "trace.npz"
    np.savez(p, inputs=np.zeros((2, 6)))
    with pytest.raises(OpenFlightError) as ei:
        diagnose.load_trace(str(p))
    assert ei.value.code == "E051"


def test_load_reference_requires_model_inputs(tmp_path):
    p = tmp_path / "ref.npz"
    np.savez(p, outputs=np.zeros((2, 3)))
    with pytest.raises(OpenFlightError) as ei:
        diagnose.load_reference(str(p))
    assert ei.value.code == "E052"


def test_sample_count_mismatch_diagnosed(tmp_path):
    t = tmp_path / "trace.npz"
    r = tmp_path / "ref.npz"
    np.savez(t, raw=np.zeros((3, 6)))
    np.savez(r, model_inputs=np.zeros((5, 6)))
    with pytest.raises(OpenFlightError) as ei:
        diagnose.check_shapes(diagnose.load_trace(str(t)),
                              diagnose.load_reference(str(r)))
    assert ei.value.code in ("E051", "E052")


# --------------------------------------------------- integration fixture

def _import_adapt(path):
    spec = importlib.util.spec_from_file_location("contract_adapt_ref", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_fixture(tmp_path):
    """Assemble a validated deployment builddir + recorded trace/reference
    from the shipped quadrotor example contracts and a tiny MLP."""
    import torch

    from openflight.adapters import contracts as C
    from openflight.compiler.api import compile_model
    from openflight.contract import checker, model_contract as MC
    from openflight.contract import pipeline as PL

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
    # generated adapt() transforms one sample at a time
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


def _load_torch(weights):
    from openflight.compiler import loader
    m, _meta = loader.load_model(None, str(weights))
    m.eval()
    return m


def _diagnose_args(fx, out):
    return ["diagnose",
            "--model", str(fx["weights"]),
            "--trace", str(fx["trace"]),
            "--reference", str(fx["reference"]),
            "--build", str(fx["build"]),
            "--output", str(out)]


def _corrupt_first_gain(h_path: Path):
    """Multiply out[0]'s gain by 100 (offsets are 0 -> exact x100)."""
    pattern = r"(out\[0\] = raw\[\d+\] \*) ([0-9.eE+-]+)f"
    text = h_path.read_text()
    m = re.search(pattern, text)
    assert m, "expected a generated out[0] line in contract_adapt.h"
    corrupted = float(m.group(2)) * 100.0
    new_text, n = re.subn(
        pattern,
        lambda mm: f"{mm.group(1)}{corrupted!r}f",  # always a C++ float
        text, count=1)
    assert n == 1 and new_text != text
    h_path.write_text(new_text)


def test_diagnose_three_conditions(tmp_path):
    fx = _build_fixture(tmp_path)
    out = tmp_path / "diagnosis"

    # -- condition 1: correct pipelines -> agree, no bundle, no post-fix
    rc = cli.main(_diagnose_args(fx, out))
    assert rc == 0, "clean pipelines must agree"
    rep = json.loads((out / "report.json").read_text())
    assert rep["status"] == "agree" and rep["first_divergence"] is None
    assert not (out / "failing_inputs.npz").exists()
    assert not (out / "post_fix_comparison.json").exists()
    assert (out / "summary.md").exists()

    # -- condition 2: deliberately wrong deployed preprocessing
    h_path = fx["build"] / "contract_adapt.h"
    original = h_path.read_text()
    _corrupt_first_gain(h_path)
    rc = cli.main(_diagnose_args(fx, out))
    assert rc == 4, "a x100 preprocessing fault must be reproduced"
    rep = json.loads((out / "report.json").read_text())
    assert rep["status"] == "discrepancy"
    fd = rep["first_divergence"]
    assert fd["stage"] == "preprocessing"
    assert fd["feature"] == "acc_x", fd
    assert fd["row"] == 0 and fd["col"] == 0
    assert fd["ratio"] == pytest.approx(100.0, rel=1e-3)
    for name in ("failing_inputs.npz", "reference_values.npz",
                 "deployed_values.npz", "artifact_manifest.json",
                 "summary.md", "reproduce.py"):
        assert (out / name).exists(), f"bundle member missing: {name}"

    # another person can rerun the recorded self-check
    r = subprocess.run([sys.executable, str(out / "reproduce.py")],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"reproduce.py failed:\n{r.stdout}\n{r.stderr}"

    # -- condition 3: correction applied -> same test rerun agrees
    h_path.write_text(original)
    rc = cli.main(_diagnose_args(fx, out))
    assert rc == 0, "corrected pipeline must agree"
    rep = json.loads((out / "report.json").read_text())
    assert rep["status"] == "agree"
    post = json.loads((out / "post_fix_comparison.json").read_text())
    assert post["resolved"] is True
    assert post["previous"]["status"] == "discrepancy"


def test_valid_configuration_produces_no_diagnostic(tmp_path):
    """False-diagnosis guard: a correct run never invents a divergence."""
    fx = _build_fixture(tmp_path)
    out = tmp_path / "diagnosis_clean"
    rc = cli.main(_diagnose_args(fx, out))
    assert rc == 0
    rep = json.loads((out / "report.json").read_text())
    assert rep["first_divergence"] is None
    stages = {s["name"]: s for s in rep["stages"]}
    assert all(s["status"] == "agree" for s in rep["stages"])
    # preprocessing agreement is tight (float32 vs float64, ~1e-7)
    assert stages["preprocessing"]["max_abs_err"] < 1e-5


def test_generated_artifacts_are_utf8_under_legacy_default_encoding(tmp_path):
    """Regression (F1, found on native Windows): the generated bundle must be
    written as UTF-8 regardless of the host's default text encoding. Windows'
    cp1252 default wrote the em dash in ``reproduce.py`` as a non-UTF-8 byte,
    so the generated script failed to parse. Force an ASCII file default (a
    stricter superset of the Windows case) and assert the *artifact* is valid
    UTF-8, parses, and runs — testing the generated file, not the template.
    """
    fx = _build_fixture(tmp_path)
    out = tmp_path / "diagnosis"
    _corrupt_first_gain(fx["build"] / "contract_adapt.h")
    env = {**os.environ, "LC_ALL": "C", "LANG": "C",
           "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0",
           # isolate the *file* default: keep stdio UTF-8 so the run reaches
           # the bundle writer rather than failing on a stdout print first
           "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run(
        [sys.executable, "-m", "openflight.cli", *_diagnose_args(fx, out)],
        capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert r.returncode == 4, (
        f"diagnose must reproduce the fault under {env}:\n"
        f"{r.stdout}\n{r.stderr}")
    text = (out / "reproduce.py").read_bytes().decode("utf-8")
    ast.parse(text)               # SyntaxError if the bytes are not UTF-8 source
    assert "\u2014" in text       # the em dash survived intact
    summary = (out / "summary.md").read_bytes().decode("utf-8")
    assert "DISCREPANCY REPRODUCED" in summary
    r2 = subprocess.run([sys.executable, str(out / "reproduce.py")],
                        capture_output=True, text=True, timeout=300)
    assert r2.returncode == 0, (
        f"generated reproduce.py failed:\n{r2.stdout}\n{r2.stderr}")
