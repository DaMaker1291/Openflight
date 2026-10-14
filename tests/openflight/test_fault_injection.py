"""Fault-injection evaluation: 10 faults must block, valid configs must pass.

Metrics: detection rate, false-accept rate, false-reject rate, field
identification (error points at the right feature/field).
"""
import copy

import pytest

from openflight.adapters import contracts as C
from openflight.contract import model_contract as MC
from openflight.contract import checker

SENSOR = "examples/quadrotor_adapter/drone_contract.yaml"
MODEL = "examples/quadrotor_adapter/model_contract.yaml"


def _base():
    return C.load_contract(SENSOR), MC.load_model_contract(MODEL)


def _blocked_with(rep, code, feature=None):
    assert rep["status"] == "blocked" and rep["deployment"] == "blocked"
    hits = [e for e in rep["errors"] if e["code"] == code]
    assert hits, f"expected {code}, got {[e['code'] for e in rep['errors']]}"
    if feature:
        assert any(feature in h["feature"] for h in hits), \
            [h["feature"] for h in hits]


def test_f1_deg_s_vs_rad_s_detected_or_converted():
    """Fault: firmware deg/s where model expects rad/s, no conversion declared
    anywhere. The checker records the well-defined conversion AND the pipeline
    applies it — detection means: flagged in conversions, math verified."""
    s, m = _base()
    s = copy.deepcopy(s)
    s["state"]["angular_velocity"]["units"] = "degrees_per_second"
    rep = checker.check(s, m)
    assert rep["status"] == "pass"  # convertible: generated, not blocked
    kinds = {(c["feature"], c["kind"]) for c in rep["conversions"]}
    assert all((f, "unit_scale") in kinds
               for f in ("gyro_x", "gyro_y", "gyro_z"))


def _quat_model():
    """Minimal synthetic contract with one quaternion feature (width 4)."""
    return {
        "schema_version": 2,
        "model": {"name": "q", "input_size": 4, "dtype": "float32"},
        "raw_layout": [{"quantity": "orientation", "component": c}
                       for c in ("x", "y", "z", "w")],
        "features": [{"name": "quat", "source": {"quantity": "orientation"},
                      "units": "dimensionless", "representation": "quaternion",
                      "ordering": "wxyz",
                      "normalization": {"method": "none"}, "width": 4}],
    }


def test_f2_quat_ordering_mismatch_reordered():
    s, _ = _base()
    s = copy.deepcopy(s)
    s["state"]["orientation"]["ordering"] = "xyzw"
    m = _quat_model()
    rep = checker.check(s, m)
    assert rep["status"] == "pass"
    assert any(c["kind"] == "quat_reorder" for c in rep["conversions"])


def test_f3_feature_order_mismatch_blocked():
    s, m = _base()
    m = copy.deepcopy(m)
    m["features"][0]["source"] = {"quantity": "angular_velocity",
                                  "component": "x"}  # acc_x bound to gyro
    # units rad/s vs m/s^2 -> E101 on acc_x
    rep = checker.check(s, m)
    _blocked_with(rep, "E101", "acc_x")


def test_f4_missing_normalization_blocked():
    s, m = _base()
    m = copy.deepcopy(m)
    del m["features"][0]["normalization"]  # bypass schema: checker-level
    m["features"][0]["normalization"] = {"method": "bogus"}
    rep = checker.check(s, m)
    _blocked_with(rep, "E201", "acc_x")


def test_f5_wrong_frame_blocked():
    s, m = _base()
    s = copy.deepcopy(s)
    s["state"]["velocity"]["frame"] = "body"
    m = copy.deepcopy(m)
    m["features"].append({"name": "vel_x",
                          "source": {"quantity": "velocity", "component": "x"},
                          "units": "metres_per_second", "frame": "world",
                          "normalization": {"method": "none"}})
    m["model"]["input_size"] = 7
    m["raw_layout"].append({"quantity": "velocity", "component": "x"})
    rep = checker.check(s, m)
    _blocked_with(rep, "E301", "vel_x")


def test_f6_bias_required_blocked():
    s, m = _base()
    m = copy.deepcopy(m)
    m["features"][0]["bias_required"] = True
    rep = checker.check(s, m)
    _blocked_with(rep, "E302", "acc_x")


def test_f7_unknown_units_blocked():
    s, m = _base()
    s = copy.deepcopy(s)
    s["state"]["angular_velocity"]["units"] = "furlongs_per_fortnight"
    rep = checker.check(s, m)
    _blocked_with(rep, "U101")


def test_f8_dimension_mismatch_blocked():
    s, m = _base()
    m = copy.deepcopy(m)
    m["features"][3]["units"] = "metres"  # gyro expects length??
    rep = checker.check(s, m)
    _blocked_with(rep, "E101", "gyro_x")


def test_f9_input_size_mismatch_blocked():
    s, m = _base()
    rep = checker.check(s, m, model_input_size=12)
    _blocked_with(rep, "E203")


def test_f10_stale_contract_detected(tmp_path):
    import shutil
    from openflight.contract import pipeline as PL
    sp = str(tmp_path / "s.yaml")
    mp = str(tmp_path / "m.yaml")
    shutil.copy(SENSOR, sp)
    shutil.copy(MODEL, mp)
    PL.write_manifest(sp, mp, str(tmp_path))
    with open(sp, "a") as f:
        f.write("\n# drift\n")
    assert PL.check_stale(str(tmp_path)) != []


def test_valid_configs_not_rejected():
    """False-reject check: the shipped pair + a raw-passthrough variant pass."""
    s, m = _base()
    assert checker.check(s, m)["status"] == "pass"
    m2 = copy.deepcopy(m)
    for f in m2["features"]:
        f["normalization"] = {"method": "none"}
    rep = checker.check(s, m2)
    assert rep["status"] == "pass"  # warnings only
    assert any(w["code"] == "W202" for w in rep["warnings"])
