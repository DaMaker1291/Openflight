"""External-review probes (2026-10-13): fault classes the self-generated
held-out suite did NOT cover, each now a permanent regression test.

Provenance: an external reviewer ran the contract engine directly (bypassing
the schema validator, as a caller might) and reproduced seven failures. These
are registered in TEST_PLAN.md as new taxonomy entries — deliberately kept
separate from the frozen held-out suite (seed 777001) so the original 156
cases stay comparable and the new classes are honest post-review additions,
not post-hoc suite edits.
"""
import copy
import os

import pytest

from openflight.adapters import contracts as C
from openflight.contract import model_contract as MC
from openflight.contract import checker, pipeline as PL

SENSOR = "examples/quadrotor_adapter/drone_contract.yaml"
MODEL = "examples/quadrotor_adapter/model_contract.yaml"


def _quat_pair(sensor_order="xyzw", raw_order="xyzw", model_order="wxyz"):
    """Sensor + synthetic 4-wide quaternion model contract."""
    s = copy.deepcopy(C.load_contract(SENSOR))
    s["state"]["orientation"] = {"representation": "quaternion",
                                 "ordering": sensor_order}
    m = {
        "schema_version": 2,
        "model": {"name": "q", "input_size": 4, "dtype": "float32"},
        "raw_layout": [{"quantity": "orientation", "component": c}
                       for c in raw_order],
        "features": [{"name": "quat", "source": {"quantity": "orientation"},
                      "units": "dimensionless",
                      "representation": "quaternion",
                      "ordering": model_order,
                      "normalization": {"method": "none"}, "width": 4}],
    }
    return s, m


def test_probe1_sensor_ordering_is_load_bearing():
    """wxyz-vs-xyzw must change the generated math; a raw_layout that
    contradicts the sensor's declared ordering must block (E403)."""
    # consistent: sensor xyzw, raw labelled xyzw, model wants wxyz -> permute
    s, m = _quat_pair("xyzw", "xyzw", "wxyz")
    rep = checker.check(s, m)
    assert rep["status"] == "pass"
    assert any(c["kind"] == "quat_reorder" for c in rep["conversions"])
    ops = PL.build_ops(s, m)
    # out.w <- raw[3], out.x <- raw[0], out.y <- raw[1], out.z <- raw[2]
    assert [o["raw"] for o in ops] == [3, 0, 1, 2]
    # same ordering on both sides -> identity permutation
    s2, m2 = _quat_pair("xyzw", "xyzw", "xyzw")
    ops2 = PL.build_ops(s2, m2)
    assert [o["raw"] for o in ops2] == [0, 1, 2, 3]
    # contradiction: sensor declares xyzw but raw_layout is w-ordered
    s3, m3 = _quat_pair("xyzw", "wxyz", "wxyz")
    rep3 = checker.check(s3, m3)
    assert rep3["status"] == "blocked"
    assert any(e["code"] == "E403" for e in rep3["errors"])


def test_probe2_model_frame_missing_fails_closed():
    """Model declares no frame while the sensor documents one: unverifiable,
    must block (U302) — never a silent pass."""
    s = copy.deepcopy(C.load_contract(SENSOR))
    m = copy.deepcopy(MC.load_model_contract(MODEL))
    m["features"].append({"name": "vel_x",
                          "source": {"quantity": "velocity", "component": "x"},
                          "units": "metres_per_second",
                          "normalization": {"method": "none"}})
    m["model"]["input_size"] = 7
    m["raw_layout"].append({"quantity": "velocity", "component": "x"})
    rep = checker.check(s, m)
    assert rep["status"] == "blocked"
    assert any(e["code"] == "U302" and "vel_x" in e["feature"]
               for e in rep["errors"])


def test_probe3_units_plausible_for_quantity():
    """A gyro declared in metres on BOTH sides must not pass just because
    the two declarations agree — both can be wrong together (E102)."""
    s = copy.deepcopy(C.load_contract(SENSOR))
    m = copy.deepcopy(MC.load_model_contract(MODEL))
    s["state"]["angular_velocity"]["units"] = "metres"
    s["imu"]["gyroscope"]["units"] = "metres"
    for f in m["features"]:
        if f["name"].startswith("gyro"):
            f["units"] = "metres"
    rep = checker.check(s, m)
    assert rep["status"] == "blocked"
    assert any(e["code"] == "E102" and e["feature"].startswith("gyro")
               for e in rep["errors"])


def test_probe4_malformed_normalization_blocks_not_crashes():
    """affine without scale -> E201 block (not KeyError traceback);
    scale 0 -> E205 block; non-finite scale -> block."""
    s = C.load_contract(SENSOR)
    m = MC.load_model_contract(MODEL)
    m["features"][0]["normalization"] = {"method": "affine"}  # no scale
    rep = checker.check(s, m)
    assert rep["status"] == "blocked"
    assert any(e["code"] == "E201" for e in rep["errors"])
    m["features"][0]["normalization"] = {"method": "affine",
                                         "scale": 0, "offset": 1.0}
    rep = checker.check(s, m)
    assert rep["status"] == "blocked"
    assert any(e["code"] == "E205" for e in rep["errors"])
    m["features"][0]["normalization"] = {"method": "affine",
                                         "scale": float("nan"),
                                         "offset": 1.0}
    rep = checker.check(s, m)
    assert rep["status"] == "blocked"
    # build_ops must refuse too, with a diagnosed error not a KeyError
    with pytest.raises(ValueError, match="normalization"):
        PL.build_ops(s, m)


def test_probe5_checker_and_pipeline_agree_on_quat_units():
    """A quaternion feature with no units: since Task 1c the checker defaults
    to dimensionless with W204 (quaternion magnitude is dimensionless by
    definition) and build_ops accepts it; an explicit non-dimensionless
    value still warns W203. Non-quat missing units remains a hard E202
    (covered in test_frame_independence.test_nonquat_missing_units_still_e202
    and test_probe6)."""
    s, m = _quat_pair()
    m["features"][0].pop("units")  # bypass schema: direct checker call
    rep = checker.check(s, m)
    assert rep["status"] == "pass", rep["errors"]
    assert any(w["code"] == "W204" for w in rep["warnings"])
    ops = PL.build_ops(s, m)
    assert len(ops) == 4


def test_probe6_units_and_norm_have_distinct_codes():
    """E201 is normalization-only; missing model units is E202; the two
    codes carry distinct action guidance."""
    from openflight.errors import CODE_ACTIONS
    s = C.load_contract(SENSOR)
    m = MC.load_model_contract(MODEL)
    m2 = copy.deepcopy(m)
    m2["features"][0].pop("units")
    rep = checker.check(s, m2)
    assert any(e["code"] == "E202" for e in rep["errors"])
    assert not any(e["code"] == "E201" for e in rep["errors"])
    m3 = copy.deepcopy(m)
    m3["features"][0]["normalization"] = {"method": "bogus"}
    rep3 = checker.check(s, m3)
    assert any(e["code"] == "E201" for e in rep3["errors"])
    assert not any(e["code"] == "E202" for e in rep3["errors"])
    assert CODE_ACTIONS["E201"] != CODE_ACTIONS["E202"]


def test_probe7_deploy_without_contracts_is_blocked(tmp_path, capsys):
    """Contracts are required by default (v0.2.4): deploying without them
    stops with a diagnosed error. --allow-unvalidated is the explicit opt-out
    that records a 'skipped' limitation."""
    pytest.importorskip("torch")  # full deploy (rc 0) compiles + runs the model
    import json
    import os
    from openflight import cli
    # default: blocked
    rc = cli.main(["deploy", "--model", "learned_observer.pt",
                   "--arch", "mlp:60,128,64,1",
                   "--output", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "E003" in captured.err
    assert "--allow-unvalidated" in captured.err
    # explicit opt-out: proceeds, records skipped limitation
    rc = cli.main(["deploy", "--model", "learned_observer.pt",
                   "--arch", "mlp:60,128,64,1",
                   "--allow-unvalidated",
                   "--output", str(tmp_path)])
    captured = capsys.readouterr()
    assert "contract gate SKIPPED (--allow-unvalidated)" in captured.out
    assert rc == 0
    report = json.load(open(os.path.join(tmp_path, "deployment_report.json")))
    assert report["meta"]["model"] == "learned_observer.pt"
    assert report["stages"]["contract_validation"]["status"] == "skipped"


# ------------------------------- v0.2.5 independent audit (round 4, 2026-10-15)
# Three defects the reviewer proved against the frozen v0.2.5-pilot tag:
# P0 an unregistered unit string accepted when both sides match; P1 duplicate
# raw_layout bindings silently collapsed; P1 failed deploys leaving artifacts.

MODEL_W = "examples/quadrotor_adapter/example_weights.pt"


def _rc(*argv):
    """cli.main rc, mapping raised OpenFlightErrors to their exit code.

    Deliberately does NOT catch unexpected exception types: a traceback or
    FileNotFoundError escaping the CLI is the bug under test."""
    from openflight import cli
    from openflight.errors import OpenFlightError
    try:
        rc = cli.main(list(argv))
        return rc if isinstance(rc, int) else 0
    except OpenFlightError as e:
        return e.exit_code


def _replace_units(node, repl="mystery_unit"):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "units" and isinstance(v, str):
                node[k] = repl
            else:
                _replace_units(v, repl)
    elif isinstance(node, list):
        for v in node:
            _replace_units(v, repl)


def test_audit_v025_unknown_equal_units_blocked(tmp_path, capsys):
    """P0: sensor and model both declaring an unregistered unit string used
    to PASS the gate (units compare equal before any registry lookup).
    Registry membership must gate first: BLOCKED, U101, rc 2, and deploy
    must refuse with no deployable artifacts."""
    import yaml
    s = yaml.safe_load(open(SENSOR).read())
    m = yaml.safe_load(open(MODEL).read())
    _replace_units(s)
    _replace_units(m)
    sp, mp = str(tmp_path / "sensor.yaml"), str(tmp_path / "model.yaml")
    yaml.safe_dump(s, open(sp, "w"))
    yaml.safe_dump(m, open(mp, "w"))
    rc = _rc("validate", "--contract", sp, "--model-contract", mp)
    out = capsys.readouterr().out
    assert rc == 2, "validate accepted matching unknown units"
    assert "U101" in out, out
    assert "mystery_unit" in out, out
    assert "Deployment status: BLOCKED" in out, out
    outdir = str(tmp_path / "dep")
    rc = _rc("deploy", "--model", MODEL_W, "--arch", "mlp:6,16,2",
             "--contract", sp, "--model-contract", mp,
             "--target", "host", "--output", outdir)
    assert rc == 2, "deploy accepted matching unknown units"
    names = set(os.listdir(outdir)) if os.path.isdir(outdir) else set()
    assert not any(n.startswith("contract_adapt") for n in names), names
    assert "model.cpp" not in names and "model.h" not in names, names
    assert "contract_manifest.json" not in names, names


def test_audit_v025_duplicate_raw_layout_refused(tmp_path, capsys):
    """P1: a duplicated (quantity, component) binding used to be accepted,
    with dict indexing silently dropping the first entry. Must refuse with
    a diagnosed error and deploy must generate nothing."""
    import yaml
    m = yaml.safe_load(open(MODEL).read())
    m["raw_layout"].append(dict(m["raw_layout"][0]))
    mp = str(tmp_path / "model_dup.yaml")
    yaml.safe_dump(m, open(mp, "w"))
    rc = _rc("validate", "--contract", SENSOR, "--model-contract", mp)
    out = capsys.readouterr().out
    assert rc == 2, "validate accepted a duplicate raw_layout binding"
    assert "E002" in out and "duplicate" in out, out
    outdir = str(tmp_path / "dep")
    rc = _rc("deploy", "--model", MODEL_W, "--arch", "mlp:6,16,2",
             "--contract", SENSOR, "--model-contract", mp,
             "--target", "host", "--output", outdir)
    assert rc == 2, "deploy accepted a duplicate raw_layout binding"
    names = set(os.listdir(outdir)) if os.path.isdir(outdir) else set()
    assert not any(n.startswith("contract_adapt") for n in names), names
    assert "model.cpp" not in names and "model.h" not in names, names


def test_audit_v025_width_mismatch_no_artifacts(tmp_path, capsys):
    """P1: a contract describing six inputs against a 60-wide model used to
    compile first and block last, publishing adapters and reports before the
    width check (the reviewer's exact repro: 6-feature contract, 60-wide
    observer). The mismatch must be caught at the gate, before any artifact
    exists, and the report must say 'failed'."""
    import json
    pytest.importorskip("torch")  # pre-fix this scenario compiles first
    outdir = str(tmp_path / "dep")
    rc = _rc("deploy", "--model", "learned_observer.pt",
             "--arch", "mlp:60,128,64,1",
             "--contract", SENSOR, "--model-contract", MODEL,
             "--target", "host", "--output", outdir)
    assert rc == 2, "width mismatch was not caught at the contract gate"
    names = set(os.listdir(outdir)) if os.path.isdir(outdir) else set()
    assert not any(n.startswith("contract_adapt") for n in names), names
    assert "model.cpp" not in names and "model.h" not in names, names
    assert "contract_manifest.json" not in names, names
    rep = json.load(open(os.path.join(outdir, "deployment_report.json")))
    assert rep["result"] == "failed", rep.get("result")
    assert rep["stages"]["contract_validation"]["status"] == "fail"


def test_audit_v025_late_failure_no_artifacts(tmp_path, capsys):
    """P1: a compile failure after generation (weights do not match the
    arch, E030) used to leave contract_adapt.py/.h and manifests in the
    output. Any non-zero deploy exit must leave only the failed report."""
    import json
    pytest.importorskip("torch")  # the compile failure needs torch
    outdir = str(tmp_path / "dep")
    rc = _rc("deploy", "--model", "learned_observer.pt",
             "--arch", "mlp:6,16,2",   # declared width matches the contract
             "--contract", SENSOR, "--model-contract", MODEL,
             "--target", "host", "--output", outdir)
    assert rc == 3, "expected the E030 weight/arch mismatch"
    names = set(os.listdir(outdir)) if os.path.isdir(outdir) else set()
    assert not any(n.startswith("contract_adapt") for n in names), names
    assert "model.cpp" not in names and "model.h" not in names, names
    assert "contract_manifest.json" not in names, names
    assert names == {"deployment_report.json"}, names
    rep = json.load(open(os.path.join(outdir, "deployment_report.json")))
    assert rep["result"] == "failed", rep.get("result")
    assert rep["stages"]["inference_codegen"]["status"] == "fail"


def test_audit_v025_shape_mismatch_diagnosed_not_traceback(tmp_path, capsys):
    """Discovered while probing P1: a weight/shape mismatch (as opposed to
    a key mismatch) raised a raw torch RuntimeError that escaped the CLI —
    a traceback, contradicting the product rule that deploy always answers
    with a diagnosed error. Must be an E030 exit with a failed report and
    no artifacts (staging discarded)."""
    pytest.importorskip("torch")
    outdir = str(tmp_path / "dep")
    rc = _rc("deploy", "--model", MODEL_W, "--arch", "mlp:60,16,1",
             "--allow-unvalidated",
             "--target", "host", "--output", outdir)
    captured = capsys.readouterr()
    assert rc == 3, f"expected E030 exit 3, got rc={rc}"
    assert "E030" in captured.err, captured.err
    assert "Traceback" not in captured.out + captured.err
    names = set(os.listdir(outdir)) if os.path.isdir(outdir) else set()
    assert names == {"deployment_report.json"}, names
    import json
    rep = json.load(open(os.path.join(outdir, "deployment_report.json")))
    assert rep["result"] == "failed", rep.get("result")
    assert rep["stages"]["inference_codegen"]["status"] == "fail"
