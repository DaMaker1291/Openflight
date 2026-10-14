"""Task 1 (2026-10-14): three checker refinements, each fail-closed-paired.

a) `frame: independent` sentinel — model-side declaration of frame-irrelevance
   passes; undeclared still blocks U302; reserved ambiguous words (none/any/
   invariant/...) are diagnosed E303, never treated as frame mismatches.
b) QUANTITY_DIMENSION maps quantity -> SET of allowed dimensions; orientation
   admits angle and dimensionless (projected gravity / direction cosines).
   Orientation-in-metres and gyro-in-metres still block E102.
c) Quaternion feature with no units key defaults to dimensionless with W204
   (was: hard E202). Explicit non-dimensionless still warns W203. Non-quat
   missing units still blocks E202.
"""
import copy

from openflight.adapters import contracts as C
from openflight.contract import model_contract as MC
from openflight.contract import checker, pipeline as PL

SENSOR = "examples/quadrotor_adapter/drone_contract.yaml"
MODEL = "examples/quadrotor_adapter/model_contract.yaml"


def _base():
    return (copy.deepcopy(C.load_contract(SENSOR)),
            copy.deepcopy(MC.load_model_contract(MODEL)))


def _with_vel_feature(m, frame_key="_omit"):
    m["features"].append({"name": "vel_x",
                          "source": {"quantity": "velocity", "component": "x"},
                          "units": "metres_per_second",
                          "normalization": {"method": "none"}})
    if frame_key != "_omit":
        m["features"][-1]["frame"] = frame_key
    m["model"]["input_size"] = 7
    m["raw_layout"].append({"quantity": "velocity", "component": "x"})
    return m


def _quat_pair(units_key="dimensionless"):
    s, _ = _base()
    s["state"]["orientation"] = {"representation": "quaternion",
                                 "ordering": "xyzw",
                                 "units": "dimensionless"}
    m = {
        "schema_version": 2,
        "model": {"name": "q", "input_size": 4, "dtype": "float32"},
        "raw_layout": [{"quantity": "orientation", "component": c}
                       for c in "xyzw"],
        "features": [{"name": "quat", "source": {"quantity": "orientation"},
                      "units": units_key, "representation": "quaternion",
                      "ordering": "wxyz",
                      "normalization": {"method": "none"}, "width": 4}],
    }
    return s, m


# ---------------------------------------------------------------- a) frames

def test_frame_independent_sentinel_passes():
    s, m = _base()
    _with_vel_feature(m, frame_key="independent")
    rep = checker.check(s, m)
    assert rep["status"] == "pass", rep["errors"]


def test_frame_undeclared_still_blocks_u302():
    s, m = _base()
    _with_vel_feature(m, frame_key="_omit")
    rep = checker.check(s, m)
    assert rep["status"] == "blocked"
    assert any(e["code"] == "U302" and "vel_x" in e["feature"]
               for e in rep["errors"])


def test_frame_reserved_words_e303_not_e301():
    for bad in ("none", "any", "invariant"):
        s, m = _base()
        _with_vel_feature(m, frame_key=bad)
        rep = checker.check(s, m)
        assert rep["status"] == "blocked", bad
        codes = [e["code"] for e in rep["errors"]]
        assert "E303" in codes, (bad, codes)
        assert "E301" not in codes, (bad, codes)


def test_sensor_side_reserved_frame_e303():
    s, m = _base()
    s["state"]["velocity"]["frame"] = "any"
    _with_vel_feature(m, frame_key="world")
    rep = checker.check(s, m)
    assert rep["status"] == "blocked"
    assert any(e["code"] == "E303" for e in rep["errors"])


def test_sensor_independent_is_e303():
    s, m = _base()
    s["state"]["velocity"]["frame"] = "independent"  # sentinel is model-only
    _with_vel_feature(m, frame_key="world")
    rep = checker.check(s, m)
    assert rep["status"] == "blocked"
    assert any(e["code"] == "E303" for e in rep["errors"])


def test_normal_mismatch_still_e301():
    s, m = _base()
    s["state"]["velocity"]["frame"] = "world"
    _with_vel_feature(m, frame_key="body")
    rep = checker.check(s, m)
    assert any(e["code"] == "E301" for e in rep["errors"])


# ------------------------------------------------- b) dimensionless orientation

def _gravity_feature(m, units):
    m["features"].append({"name": "proj_g_z",
                          "source": {"quantity": "orientation",
                                     "component": "z"},
                          "units": units,
                          "normalization": {"method": "none"}})
    m["model"]["input_size"] = 7
    m["raw_layout"].append({"quantity": "orientation", "component": "z"})
    return m


def test_projected_gravity_dimensionless_passes():
    s, m = _base()
    s["state"]["orientation"]["units"] = "dimensionless"
    _gravity_feature(m, "dimensionless")
    rep = checker.check(s, m)
    assert rep["status"] == "pass", rep["errors"]


def test_orientation_in_metres_blocks_e102():
    s, m = _base()
    s["state"]["orientation"]["units"] = "metres"
    _gravity_feature(m, "metres")  # both sides agree — still implausible
    rep = checker.check(s, m)
    assert rep["status"] == "blocked"
    assert any(e["code"] == "E102" and "proj_g_z" in e["feature"]
               for e in rep["errors"])


def test_gyro_in_metres_still_blocks_e102():
    s, m = _base()
    s["state"]["angular_velocity"]["units"] = "metres"
    s["imu"]["gyroscope"]["units"] = "metres"
    for f in m["features"]:
        if f["name"].startswith("gyro"):
            f["units"] = "metres"
    rep = checker.check(s, m)
    assert rep["status"] == "blocked"
    assert any(e["code"] == "E102" and e["feature"].startswith("gyro")
               for e in rep["errors"])


# ------------------------------------------------- c) quaternion units default

def test_quat_missing_units_defaults_w204():
    s, m = _quat_pair()
    m["features"][0].pop("units")
    rep = checker.check(s, m)
    assert rep["status"] == "pass", rep["errors"]
    assert any(w["code"] == "W204" and "quat" in w["feature"]
               for w in rep["warnings"])
    assert not any(e["code"] == "E202" for e in rep["errors"])
    ops = PL.build_ops(s, m)  # pipeline accepts the defaulted feature
    assert len(ops) == 4


def test_quat_nondimensionless_units_w203():
    s, m = _quat_pair(units_key="metres")
    rep = checker.check(s, m)
    assert rep["status"] == "pass", rep["errors"]
    assert any(w["code"] == "W203" for w in rep["warnings"])


def test_nonquat_missing_units_still_e202():
    s, m = _base()
    m["features"][0].pop("units")  # acc_x, scalar
    rep = checker.check(s, m)
    assert rep["status"] == "blocked"
    assert any(e["code"] == "E202" and "acc_x" in e["feature"]
               for e in rep["errors"])
