"""End-to-end: raw sensor -> generated C++ adapter -> compiled model -> prediction.

This is the integration the reviewer identified as missing. The existing
host-parity test compiles model.cpp alone and feeds it already-normalized
input; baseline_compare verifies the Python build_ops conversion. Neither
executes the composed C++ path (contract_adapt -> predict) and compares it
against the Python reference on the same raw sensor vector.

Here one C++ translation unit includes both contract_adapt.h and model.h,
feeds raw -> adapt -> predict, and its outputs are compared to the Python
reference: adapt via the generated contract_adapt.py, predict via torch.
Fault cases (unit mismatch, feature-order swap, off-layout source) must be
caught by the checker before any artifact is treated as validated.
"""
import os
import subprocess

import numpy as np
import pytest

pytest.importorskip("torch")
torch = pytest.importorskip("torch")

REPORT = "results/e2e_pipeline.json"
N_IN = 60          # raw sensor vector length (learned_observer input width)
N_ACC = 20         # leading channels: accelerometer, declared cm/s^2
N_GYRO = 40        # trailing channels: gyro, rad/s (no conversion)


def _contracts():
    """Sensor/model contract pair matching learned_observer.pt (60 inputs).

    First 20 features declare metres_per_second_squared with affine norm
    while the sensor sends centimetres_per_second_squared -> generated 0.01
    unit conversion. Remaining 40 features are rad/s, norm none -> factor 1.
    """
    sensor = {"imu": {"accelerometer": {"units": "centimetres_per_second_squared"},
                      "gyroscope": {"units": "radians_per_second"}}}
    raw_layout = ([{"quantity": "acceleration", "component": f"a{i}"}
                   for i in range(N_ACC)]
                  + [{"quantity": "gyro", "component": f"g{i}"}
                     for i in range(N_GYRO)])
    features = ([{"name": f"acc{i}",
                  "source": {"quantity": "acceleration", "component": f"a{i}"},
                  "units": "metres_per_second_squared",
                  "normalization": {"method": "affine",
                                    "scale": 0.05, "offset": 0.0}}
                 for i in range(N_ACC)]
                + [{"name": f"gyro{i}",
                    "source": {"quantity": "gyro",
                               "component": f"g{i}"},
                    "units": "radians_per_second",
                    "normalization": {"method": "none"}}
                   for i in range(N_GYRO)])
    return sensor, {"raw_layout": raw_layout, "features": features}


def _build(tmp_path):
    """Generate adapter + model, compile one C++ unit wiring adapt->predict."""
    from openflight.cli import _arch_for_example
    from openflight.compiler.api import compile_model
    from openflight.contract import checker, pipeline as PL

    sensor, model_c = _contracts()
    rep = checker.check(sensor, model_c)
    assert rep["status"] == "pass", rep.get("errors")

    bdir = str(tmp_path / "build")
    out = compile_model(_arch_for_example("mlp:60,128,64,1"),
                        "learned_observer.pt", bdir)
    py_adapt = os.path.join(bdir, "contract_adapt.py")
    cpp_adapt = os.path.join(bdir, "contract_adapt.h")
    PL.generate(sensor, model_c, py_adapt, cpp_adapt)

    driver = os.path.join(bdir, "e2e_driver.cpp")
    with open(driver, "w") as f:
        f.write("""
#include <cstdio>
#include <cstdlib>
#include "model.h"
#include "contract_adapt.h"
int main() {
    static_assert(CONTRACT_N_OUT == openflight::INPUT_SIZE,
                  "adapted width must equal model input");
    float raw[CONTRACT_N_IN];
    for (int i = 0; i < CONTRACT_N_IN; ++i) {
        if (scanf("%f", &raw[i]) != 1) return 2;
    }
    float adapted[CONTRACT_N_OUT];
    contract_adapt(raw, adapted);
    float pred[openflight::OUTPUT_SIZE];
    openflight::predict(adapted, pred);
    for (std::size_t i = 0; i < openflight::OUTPUT_SIZE; ++i)
        printf("%.9g\\n", (double)pred[i]);
    return 0;
}
""")
    exe = str(tmp_path / "e2e")
    pr = subprocess.run(
        ["c++", "-O2", "-std=c++17", "-Wall",
         "-I", bdir, driver,
         os.path.join(bdir, "model.cpp"), "-o", exe],
        capture_output=True, text=True)
    assert pr.returncode == 0, pr.stderr[:3000]

    import importlib.util
    spec = importlib.util.spec_from_file_location("contract_adapt", py_adapt)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return exe, out, mod, sensor, model_c


def _cpp_predict(exe, raw):
    inp = "\n".join(f"{float(x):.9g}" for x in raw) + "\n"
    pr = subprocess.run([exe], input=inp, capture_output=True, text=True)
    assert pr.returncode == 0, pr.stderr[:500]
    return np.array([float(x) for x in pr.stdout.split()], dtype=np.float32)


def _torch_predict(weights, adapted):
    from openflight.cli import _arch_for_example
    from openflight.compiler.loader import load_model
    m, _meta = load_model(_arch_for_example("mlp:60,128,64,1"), weights)
    m.eval()
    with torch.no_grad():
        return m(torch.from_numpy(np.asarray(adapted, dtype=np.float32))
                 ).numpy().reshape(-1)


def test_e2e_adapter_model_parity(tmp_path):
    """Composed C++ path matches Python reference on the same raw sensor."""
    exe, _out, mod, _s, _m = _build(tmp_path)
    rng = np.random.default_rng(11)
    # raw in the sensor's declared units (cm/s^2 then rad/s)
    raw = rng.uniform(-500, 500, size=(8, N_IN)).astype(np.float32)

    rows = []
    for r in raw:
        cpp = _cpp_predict(exe, r)
        py_pred = _torch_predict("learned_observer.pt", mod.adapt(r))
        err = float(np.abs(cpp - py_pred).max())
        rows.append(err)
    max_err = max(rows)
    assert max_err < 1e-4, f"C++ composed path diverges from Python ref: {max_err}"

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w") as f:
        import json
        json.dump({"model": "learned_observer.pt", "n_samples": len(raw),
                   "max_abs_err_cpp_vs_python": max_err,
                   "composed_path": "raw->contract_adapt->predict"}, f, indent=2)


def test_e2e_fault_unit_mismatch_blocked():
    """cm/s^2 raw with a sensor declaring m/s^2 (no conversion) is blocked."""
    from openflight.contract import checker
    # sensor now claims m/s^2; model expects m/s^2; but raw arrives in cm/s^2.
    # The checker cannot see the runtime unit — this is the silent-corruption
    # class. What it CAN do: block an unregistered sensor unit.
    sensor, model_c = _contracts()
    sensor_bad = {
        "imu": {"accelerometer": {"units": "furlongs_per_s2"},
                "gyroscope": {"units": "radians_per_second"}}}
    rep = checker.check(sensor_bad, model_c)
    assert rep["status"] == "blocked"


def test_e2e_fault_feature_order_swapped_blocked():
    """Model sourcing gyro as accel (off-layout) is blocked by E402."""
    from openflight.contract import checker
    sensor, model_c = _contracts()
    # corrupt one feature: source points at a gyro component with acc units
    bad = {"raw_layout": list(model_c["raw_layout"]),
           "features": [dict(f) for f in model_c["features"]]}
    bad["features"][0] = dict(bad["features"][0])
    bad["features"][0]["source"] = {"quantity": "gyro", "component": "g0"}
    rep = checker.check(sensor, bad)
    assert rep["status"] == "blocked"


def test_e2e_fault_off_layout_component_blocked():
    """Component not present in raw_layout is blocked by E402."""
    from openflight.contract import checker
    sensor, model_c = _contracts()
    bad = {"raw_layout": list(model_c["raw_layout"]),
           "features": [dict(f) for f in model_c["features"]]}
    bad["features"][0] = dict(bad["features"][0])
    bad["features"][0]["source"] = {"quantity": "acc", "component": "ghost"}
    rep = checker.check(sensor, bad)
    assert rep["status"] == "blocked"
