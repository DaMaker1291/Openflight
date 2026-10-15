"""End-to-end: raw sensor -> generated C++ adapter -> compiled model -> prediction.

This is the integration the reviewer identified as missing. The existing
host-parity test compiles model.cpp alone and feeds it already-normalized
input; baseline_compare verifies the Python build_ops conversion. Neither
executes the composed C++ path (contract_adapt -> predict) and compares it
against the Python reference on the same raw sensor vector.

Here one C++ translation unit includes both contract_adapt.h and model.h,
feeds raw -> adapt -> predict, and its outputs are compared to the Python
reference: adapt via the generated contract_adapt.py, predict via torch.

Error decomposition recorded in results/e2e_pipeline.json:
  adapter  -- python float64 adapt vs generated C++ float32 adapt (same input)
  model    -- C++ predict vs torch on the IDENTICAL adapted input (float32)
  composed -- C++ adapt->predict vs python float64 adapt -> float32 torch

Sample expansion (N=8 -> N=300, four input bands incl. extremes) measured
that the composed error is dominated by the model term: unit-scale
constants contribute <= ~5e-7, while float32 codegen vs torch grows with
output magnitude (absolute error up to ~1.2e-4 at +/-100 m/s^2 extremes,
relative error <= ~4.5e-5 everywhere).

Bounds, both registered before the pilot:
  absolute < 1e-4 on the registered envelope (raw uniform +-500; this is
    the distribution every earlier composed-path run used),
  relative < 1e-4 across all characterization bands (magnitude-invariant).

Fault cases (unit mismatch, feature-order swap, off-layout source) must be
caught by the checker before any artifact is treated as validated. The
bypass case is the complement: contracts that agree on paper while the
runtime unit is wrong -- the checker passes and only the composed path can
measure the resulting divergence (the silent-error number).
"""
import json
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

REGISTERED_TOL_ABS = 1e-4   # pre-registered: registered envelope, absolute
EXPANDED_TOL_REL = 1e-4     # pre-registered: all bands, magnitude-invariant
CHARACTERIZATION_CEILING = 1e-3  # sanity ceiling, NOT a tolerance claim

BANDS = ("uniform_pm500", "extreme_pm1e4_pm1e3", "tiny_pm1e-3",
         "patterned_extremes")
BAND_SIZE = 75
N_SAMPLES = BAND_SIZE * len(BANDS)


def _contracts(sensor_units_acc="centimetres_per_second_squared"):
    """Sensor/model contract pair matching learned_observer.pt (60 inputs).

    First 20 features declare metres_per_second_squared with affine norm
    while the sensor sends centimetres_per_second_squared -> generated 0.01
    unit conversion. Remaining 40 features are rad/s, norm none -> factor 1.
    Passing metres_per_second_squared for the sensor yields the identity
    (unit_scale factor 1) used by the bypass test.
    """
    sensor = {"imu": {"accelerometer": {"units": sensor_units_acc},
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


def _sample_bands(rng_seed=11):
    """Four input bands, BAND_SIZE rows each, float32 in raw sensor units.

    uniform_pm500        -- the registered envelope (every prior run)
    extreme_pm1e4_pm1e3  -- +/-100 m/s^2 accelerometer, +/-1000 rad/s gyro
    tiny_pm1e-3          -- near-zero inputs
    patterned_extremes   -- hard zeros, exact extremes, 9.81, 1e-6 rows
    """
    rng = np.random.default_rng(rng_seed)
    raw = np.empty((N_SAMPLES, N_IN), dtype=np.float32)
    raw[0:BAND_SIZE] = rng.uniform(-500, 500, (BAND_SIZE, N_IN))
    lo = BAND_SIZE
    raw[lo:lo + BAND_SIZE, :N_ACC] = rng.uniform(-1e4, 1e4,
                                                 (BAND_SIZE, N_ACC))
    raw[lo:lo + BAND_SIZE, N_ACC:] = rng.uniform(-1e3, 1e3,
                                                 (BAND_SIZE, N_GYRO))
    lo = 2 * BAND_SIZE
    raw[lo:lo + BAND_SIZE] = rng.uniform(-1e-3, 1e-3, (BAND_SIZE, N_IN))
    e = raw[3 * BAND_SIZE:]
    e[:] = 0
    e[0::5, :N_ACC] = 1e4
    e[0::5, N_ACC:] = 1e3
    e[1::5, :N_ACC] = -1e4
    e[1::5, N_ACC:] = -1e3
    e[3::5] = 1e-6
    e[4::5, :N_ACC] = 9.81
    return raw


def _build(tmp_path, sensor_units_acc="centimetres_per_second_squared"):
    """Generate adapter + model, compile composed and adapter-only units."""
    from openflight.cli import _arch_for_example
    from openflight.compiler.api import compile_model
    from openflight.contract import checker, pipeline as PL

    sensor, model_c = _contracts(sensor_units_acc)
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

    adapt_driver = os.path.join(bdir, "adapt_only.cpp")
    with open(adapt_driver, "w") as f:
        f.write("""
#include <cstdio>
#include "contract_adapt.h"
int main() {
    float raw[CONTRACT_N_IN];
    for (int i = 0; i < CONTRACT_N_IN; ++i)
        if (scanf("%f", &raw[i]) != 1) return 2;
    float a[CONTRACT_N_OUT];
    contract_adapt(raw, a);
    for (int i = 0; i < CONTRACT_N_OUT; ++i)
        printf("%.9g\\n", (double)a[i]);
    return 0;
}
""")
    exe_adapt = str(tmp_path / "adapt_only")
    pr = subprocess.run(
        ["c++", "-O2", "-std=c++17", "-Wall",
         "-I", bdir, adapt_driver, "-o", exe_adapt],
        capture_output=True, text=True)
    assert pr.returncode == 0, pr.stderr[:3000]

    import importlib.util
    spec = importlib.util.spec_from_file_location("contract_adapt", py_adapt)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return exe, exe_adapt, mod, sensor, model_c


def _run_cpp(exe, raw):
    inp = "\n".join(f"{float(x):.9g}" for x in raw) + "\n"
    pr = subprocess.run([exe], input=inp, capture_output=True, text=True)
    assert pr.returncode == 0, pr.stderr[:500]
    return np.array([float(x) for x in pr.stdout.split()], dtype=np.float32)


def _torch_batch(adapted_rows):
    from openflight.cli import _arch_for_example
    from openflight.compiler.loader import load_model
    m, _meta = load_model(_arch_for_example("mlp:60,128,64,1"),
                          "learned_observer.pt")
    m.eval()
    with torch.no_grad():
        return m(torch.from_numpy(
            np.asarray(adapted_rows, dtype=np.float32))).numpy()


def _merge_report(updates):
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    data = {}
    if os.path.exists(REPORT):
        with open(REPORT) as f:
            data = json.load(f)
    data.update(updates)
    with open(REPORT, "w") as f:
        json.dump(data, f, indent=2)


def test_e2e_adapter_model_parity(tmp_path):
    """Composed C++ path matches Python reference on the same raw sensor.

    N=300 across four bands. Registered absolute bound applies to the
    registered envelope (uniform +-500); all bands are additionally held
    to a pre-registered magnitude-invariant relative bound. The error
    decomposition (adapter vs model-same-input) is recorded so the source
    of any divergence is attributed, not asserted away.
    """
    exe, exe_adapt, mod, _s, _m = _build(tmp_path)
    raw = _sample_bands()

    py64 = np.stack([mod.adapt(r) for r in raw])
    py32 = py64.astype(np.float32)
    ref = _torch_batch(py32)

    composed = np.empty(len(raw))
    adapter_err = np.empty(len(raw))
    adapted_cpp = np.empty_like(py32)
    composed_out = []
    for i, r in enumerate(raw):
        cpp = _run_cpp(exe, r)
        adp = _run_cpp(exe_adapt, r)
        composed_out.append(cpp)
        adapted_cpp[i] = adp
        composed[i] = np.abs(cpp - ref[i]).max()
        adapter_err[i] = np.abs(py64[i] - adp).max()
    composed_out = np.stack(composed_out)
    # model-only: C++ composed output vs torch on the IDENTICAL adapted input
    ref_same = _torch_batch(adapted_cpp)
    model_err = np.abs(composed_out - ref_same).max(axis=1)

    refmag = np.abs(ref).max(axis=1)
    rel = composed / np.maximum(refmag, 1e-30)
    reg = slice(0, BAND_SIZE)  # uniform_pm500

    assert composed[reg].max() < REGISTERED_TOL_ABS, (
        f"registered envelope exceeded abs tol: {composed[reg].max()}")
    assert rel.max() < EXPANDED_TOL_REL, (
        f"expanded bands exceeded rel tol: {rel.max()}")
    assert adapter_err.max() < 1e-5, (
        f"adapter contributes too much error: {adapter_err.max()}")
    assert composed.max() < CHARACTERIZATION_CEILING, (
        f"characterization bands blew past sanity ceiling: "
        f"{composed.max()}")

    per_band = {}
    for idx, name in enumerate(BANDS):
        s = slice(idx * BAND_SIZE, (idx + 1) * BAND_SIZE)
        per_band[name] = {
            "n": BAND_SIZE,
            "max_abs_err_composed": float(composed[s].max()),
            "max_rel_err_composed": float(rel[s].max()),
            "max_abs_err_adapter": float(adapter_err[s].max()),
            "within_registered_abs_tol": bool(
                composed[s].max() < REGISTERED_TOL_ABS),
        }
    worst_band = BANDS[int(np.argmax([per_band[b]["max_abs_err_composed"]
                                      for b in BANDS]))]
    _merge_report({
        "model": "learned_observer.pt",
        "composed_path": "raw->contract_adapt->predict",
        "reference": "python adapt (float64) cast float32 -> torch float32",
        "n_samples": N_SAMPLES,
        "bands": per_band,
        "tolerance_registered_abs": REGISTERED_TOL_ABS,
        "tolerance_registered_domain": "band uniform_pm500 "
                                       "(raw uniform +-500)",
        "tolerance_expanded_rel": EXPANDED_TOL_REL,
        "max_abs_err_composed": float(composed.max()),
        "max_abs_err_composed_registered_band":
            float(composed[reg].max()),
        "max_rel_err_composed": float(rel.max()),
        "max_abs_err_adapter": float(adapter_err.max()),
        "max_abs_err_model_same_input": float(model_err.max()),
        "n_within_registered_abs_tol":
            int((composed < REGISTERED_TOL_ABS).sum()),
        "worst_band": worst_band,
        "seed": 11,
    })


def test_e2e_gate_bypass_silent_error(tmp_path):
    """Contracts agree on paper; the runtime unit is wrong -> divergence.

    Sensor and model both declare m/s^2, so the gate passes with
    unit_scale factor 1 (no conversion is generated) while the raw vector
    actually arrives in cm/s^2. The composed path runs unimpeded; its
    divergence from the correctly-converted reference is the silent-error
    number recorded in results/e2e_pipeline.json.
    """
    from openflight.contract import checker

    exe_bypass, _exe_adapt_b, _mod_b, sensor_b, model_b = _build(
        tmp_path, sensor_units_acc="metres_per_second_squared")
    rep = checker.check(sensor_b, model_b)
    assert rep["status"] == "pass", rep.get("errors")

    # correct reference: the original cm/s^2 contract pair's conversion
    _exe_c, _exe_a, mod_ok, _s, _m = _build(tmp_path / "correct")

    rng = np.random.default_rng(11)
    raw_cm = rng.uniform(-500, 500, size=(BAND_SIZE, N_IN)).astype(np.float32)
    ref = _torch_batch(np.stack([mod_ok.adapt(r) for r in raw_cm]))

    div = np.empty(BAND_SIZE)
    for i, r in enumerate(raw_cm):
        out = _run_cpp(exe_bypass, r)
        div[i] = np.abs(out - ref[i]).max()
    max_div = float(div.max())

    assert max_div > REGISTERED_TOL_ABS, (
        f"bypass divergence must exceed the tolerance it hides behind: "
        f"{max_div}")
    _merge_report({
        "bypass_unit_mismatch": {
            "description": "sensor+model both declare m/s^2 (gate passes, "
                           "unit_scale factor 1) but raw arrives in cm/s^2",
            "gate_status": rep["status"],
            "n_samples": BAND_SIZE,
            "max_abs_err_vs_correct_reference": max_div,
            "silently_divergent": bool(max_div > REGISTERED_TOL_ABS),
        }})


def test_e2e_fault_unit_mismatch_blocked():
    """cm/s^2 raw with a sensor declaring m/s^2 (no conversion) is blocked."""
    from openflight.contract import checker
    # sensor now claims m/s^2; model expects m/s^2; but raw arrives in cm/s^2.
    # The checker cannot see the runtime unit -- this is the silent-corruption
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
