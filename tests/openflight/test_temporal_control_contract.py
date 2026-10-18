"""Temporal sample offsets and the actuator control quantity.

The trained disturbance observer consumes a window of three signals
(measured acceleration, applied control acceleration, velocity), newest
sample first. To express that in a contract each raw binding needs a
temporal position, and the control signal needs its own quantity rather
than masquerading as an accelerometer reading.
"""
from openflight.adapters import contracts as C
from openflight.contract import model_contract as MC
from openflight.contract import checker, pipeline as PL
from openflight.contract import units as U

SENSOR = "examples/quadrotor_adapter/drone_contract.yaml"


def _sensor_with_actuator():
    s = C.load_contract(SENSOR)
    s["actuator"] = {"applied_control_acceleration": {
        "units": "metres_per_second_squared", "frame": "world"}}
    return s


def _observer_model(width=2):
    raw, feats = [], []

    def block(name, qty, comp, units, frame):
        for i in range(width):
            raw.append({"quantity": qty, "component": comp,
                        "sample_offset_steps": i})
            feats.append({
                "name": f"{name}_t{i}",
                "source": {"quantity": qty, "component": comp,
                           "sample_offset_steps": i},
                "units": units, "frame": frame,
                "normalization": {"method": "affine", "scale": 1.0,
                                  "offset": 0.0}})

    block("a_meas", "acceleration", "x", "metres_per_second_squared", None)
    block("u_act", "applied_control_acceleration", "x",
          "metres_per_second_squared", "world")
    block("v", "velocity", "x", "metres_per_second", "world")
    return {"schema_version": 2,
            "model": {"name": "obs", "input_size": 3 * width,
                      "dtype": "float32"},
            "raw_layout": raw, "features": feats}


def test_actuator_quantity_registered():
    assert U.QUANTITY_DIMENSION["applied_control_acceleration"] == {"acceleration"}
    assert checker.QUANTITY_PATHS["applied_control_acceleration"] == (
        "actuator", "applied_control_acceleration")


def test_offset_makes_same_component_distinct():
    # same (quantity, component) at different temporal positions is not a
    # duplicate: without offsets the checker would (correctly) block it.
    s, m = _sensor_with_actuator(), _observer_model()
    rep = checker.check(s, m)
    assert rep["status"] == "pass", rep["errors"]
    assert rep["deployment"] == "proceed"


def test_same_offset_still_a_duplicate():
    s, m = _sensor_with_actuator(), _observer_model()
    m["raw_layout"].append(dict(m["raw_layout"][0]))  # identical offset too
    rep = checker.check(s, m)
    assert rep["status"] == "blocked"
    assert any(e["code"] == "E206" for e in rep["errors"]), rep["errors"]


def test_schema_validates_offset_type():
    bad = _observer_model()
    bad["raw_layout"][0]["sample_offset_steps"] = -1
    try:
        MC.validate_model_contract(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("negative sample_offset_steps must be rejected")


def test_pipeline_resolves_by_offset(tmp_path):
    s, m = _sensor_with_actuator(), _observer_model()
    py_out = str(tmp_path / "adapt.py")
    h_out = str(tmp_path / "adapt.h")
    info = PL.generate(s, m, py_out, h_out)
    ops = {op["feature"]: op["raw"] for op in info["ops"]}
    # newest-first layout: a_meas t0/t1 occupy raw 0/1, control 2/3, vel 4/5
    assert ops["a_meas_t0"] == 0 and ops["a_meas_t1"] == 1
    assert ops["u_act_t0"] == 2 and ops["v_t1"] == 5
    assert len(set(ops.values())) == len(ops)  # no two features share a slot


def test_control_unit_conversion_dimension():
    assert U.conversion("metres_per_second_squared",
                        "centimetres_per_second_squared") == 100.0
    assert U.plausible_for_quantity(
        "metres_per_second_squared", "applied_control_acceleration") is True
    assert U.plausible_for_quantity(
        "radians_per_second", "applied_control_acceleration") is False


def test_backward_compatible_without_offsets():
    # contracts that never mention offsets behave exactly as before
    s = C.load_contract(SENSOR)
    m = MC.load_model_contract("examples/quadrotor_adapter/model_contract.yaml")
    rep = checker.check(s, m)
    assert rep["status"] == "pass"

    def key(r):
        return (r["quantity"], r["component"], r.get("sample_offset_steps", 0))
    keys = [key(r) for r in m["raw_layout"]]
    assert len(keys) == len(set(keys))
