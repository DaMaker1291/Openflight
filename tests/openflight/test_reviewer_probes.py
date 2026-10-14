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


def test_probe7_deploy_without_contracts_warns_loudly(tmp_path, capsys):
    """The contract gate is opt-in; deploying without contracts must print
    an explicit WARNING to stderr (and still record 'skipped')."""
    pytest.importorskip("torch")  # full deploy (rc 0) compiles + runs the model
    import json
    import os
    from openflight import cli
    rc = cli.main(["deploy", "--model", "learned_observer.pt",
                   "--arch", "mlp:60,128,64,1",
                   "--output", str(tmp_path)])
    captured = capsys.readouterr()
    assert "WARNING: no contracts supplied" in captured.err
    assert "contract gate SKIPPED" in captured.out
    assert rc == 0
    report = json.load(open(os.path.join(tmp_path, "deployment_report.json")))
    assert report["meta"]["model"] == "learned_observer.pt"
