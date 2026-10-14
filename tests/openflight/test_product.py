"""Product-quality gates (v0.2): CLI reliability, diagnostics, staging.

These test the tool as a product: bad inputs produce diagnosed failures with
stable exit codes (never tracebacks, never misleading success), reports have
the documented structure, and generation is deterministic.
"""
import json
import os

import pytest

from openflight.cli import main as cli_main
from openflight.errors import OpenFlightError

QUAD = "examples/quadrotor_adapter"
W6 = f"{QUAD}/example_weights.pt"
SENSOR = f"{QUAD}/drone_contract.yaml"
MODEL_C = f"{QUAD}/model_contract.yaml"


def run_cli(*argv):
    """Run the CLI entry, returning rc (OpenFlightErrors are handled)."""
    try:
        rc = cli_main(list(argv))
        return rc if isinstance(rc, int) else 0
    except OpenFlightError as e:
        return e.exit_code


def test_version_and_doctor(capsys):
    assert run_cli("version") == 0
    out = capsys.readouterr().out
    assert out.startswith("openflight 0.2.")
    assert run_cli("doctor") == 0
    out = capsys.readouterr().out
    assert "arm-none-eabi-g++" in out and "NOT performed" in out


def test_missing_files_diagnosed_not_traceback(capsys):
    assert run_cli("inspect", "/nonexistent.pt") == 2
    err = capsys.readouterr().err
    assert "E010" in err and "Traceback" not in err
    assert run_cli("validate", "--contract", "/nope.yaml",
                   "--model-contract", MODEL_C) == 2
    assert run_cli("compile", "/nope.pt") == 2
    assert run_cli("deploy", "--model", "/nope.pt") == 2


def test_deploy_contract_warning_fires_before_torch_gate(capsys, tmp_path):
    """The no-contracts WARNING must fire even without torch: the contract
    gate is torch-free and runs before weight loading (E050)."""
    try:
        import torch  # noqa: F401
        pytest.skip("torch present; E050 path not reachable in this env")
    except ImportError:
        pass
    rc = run_cli("deploy", "--model", W6, "--arch", "mlp:6,16,2",
                 "--output", str(tmp_path))
    captured = capsys.readouterr()
    assert "WARNING: no contracts supplied" in captured.err
    assert rc == 5  # E050: torch missing, diagnosed not traceback


def test_unknown_arch_and_bad_args(capsys):
    assert run_cli("inspect", W6, "--arch", "resnet50") == 2
    assert "E012" in capsys.readouterr().err
    assert run_cli("deploy", "--model", W6, "--arch", "mlp:bogus") == 2
    assert run_cli("benchmark", "--model", W6, "--arch", "mlp:6,16,2",
                   "--target", "commodore64") == 2


def test_contract_failure_actionable_and_gated(tmp_path, capsys):
    # frame mismatch between the shipped pair
    import yaml
    mc = yaml.safe_load(open(MODEL_C).read()) \
        if _has_yaml() else _load_jsonish(MODEL_C)
    mc["features"][3]["frame"] = "world"  # sensor says body
    bad = str(tmp_path / "bad_model.yaml")
    _dump_yaml(bad, mc)
    rc = run_cli("validate", "--contract", SENSOR, "--model-contract", bad)
    assert rc == 2
    out = capsys.readouterr().out
    assert "E301" in out and "gyro_x" in out and "Action:" in out
    # deploy gate blocks before generating inference code
    outdir = str(tmp_path / "dep")
    rc = run_cli("deploy", "--model", W6, "--arch", "mlp:6,16,2",
                 "--contract", SENSOR, "--model-contract", bad,
                 "--target", "host", "--output", outdir)
    assert rc == 2
    assert not os.path.exists(os.path.join(outdir, "model.cpp"))
    rep = json.load(open(os.path.join(outdir, "deployment_report.json")))
    assert rep["stages"]["contract_validation"]["status"] == "fail"
    assert rep["stages"]["inference_codegen"]["status"] == "not-run"


def _has_yaml():
    try:
        __import__("yaml")
        return True
    except ImportError:
        return False


def _load_jsonish(path):
    # minimal YAML-subset reader is tested elsewhere; here yaml is required
    import yaml
    return yaml.safe_load(open(path).read())


def _dump_yaml(path, obj):
    import yaml
    with open(path, "w") as f:
        yaml.safe_dump(obj, f)


def test_deploy_report_structure(tmp_path):
    # a full deploy compiles and runs the model — needs torch
    pytest.importorskip("torch")
    outdir = str(tmp_path / "dep")
    rc = run_cli("deploy", "--model", W6, "--arch", "mlp:6,16,2",
                 "--contract", SENSOR, "--model-contract", MODEL_C,
                 "--target", "host", "--output", outdir)
    assert rc == 0
    rep = json.load(open(os.path.join(outdir, "deployment_report.json")))
    expected = ["contract_validation", "adapter_generation",
                "inference_codegen", "host_compilation", "numerical_parity",
                "cross_compilation", "firmware_simulation", "hardware"]
    assert list(rep["stages"].keys()) == expected
    for s in expected[:5]:
        assert rep["stages"][s]["status"] == "pass", s
    for s in expected[5:]:
        st = rep["stages"][s]
        assert st["status"] in ("not-run", "skipped"), s
        assert st["limitation"], s  # never a bare unexplained state
    meta = rep["meta"]
    for k in ("model_sha", "sensor_contract_sha", "model_contract_sha",
              "openflight_version", "compiler", "artifact_shas", "target"):
        assert k in meta, k
    assert meta["target"] == "host"
    assert meta["openflight_version"].startswith("0.2.")


def test_deterministic_generation(tmp_path):
    # two full deploys compare generated artifacts — needs torch
    pytest.importorskip("torch")
    outs = []
    for i in (1, 2):
        d = str(tmp_path / f"b{i}")
        assert run_cli("deploy", "--model", W6, "--arch", "mlp:6,16,2",
                       "--contract", SENSOR, "--model-contract", MODEL_C,
                       "--target", "host", "--output", d) == 0
        outs.append({f: open(os.path.join(d, f), "rb").read()
                     for f in ("model.h", "model.cpp", "contract_adapt.py",
                               "contract_adapt.h")})
    assert outs[0] == outs[1]


def test_stale_manifest_detected(tmp_path):
    import shutil
    from openflight.contract import pipeline as PL
    sens = str(tmp_path / "s.yaml")
    mod = str(tmp_path / "m.yaml")
    shutil.copy(SENSOR, sens)
    shutil.copy(MODEL_C, mod)
    outdir = str(tmp_path / "dep")
    os.makedirs(outdir)
    PL.write_manifest(sens, mod, outdir)
    assert PL.check_stale(outdir) == []
    with open(mod, "a") as f:
        f.write("\n# drifted\n")
    problems = PL.check_stale(outdir)
    assert problems and "model" in problems[0].lower()


def test_error_render_format():
    e = OpenFlightError("deploy", "E301", "frame mismatch", "gyro_x",
                        "sensor=body model=world", "fix the frames",
                        exit_code=2)
    t = e.render()
    assert all(s in t for s in ("deploy", "E301", "gyro_x", "fix the frames"))
    assert e.exit_code == 2
