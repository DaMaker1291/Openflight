"""Baseline comparison: repo's plain exporter vs OpenFlight, same fault.

Fault: accelerometer channel arrives in cm/s^2 while the model was trained on
m/s^2 (a classic sim-to-real scaling slip). The baseline workflow
(observer_deploy.py: weights + golden self-test) has no unit concept, so the
export succeeds and its self-test passes — the fault escapes silently and
corrupts every prediction. OpenFlight's contract records the conversion and
the generated pipeline compensates.

No human-time claims are made; the report records detection outcomes and
measured numeric errors only.
"""
import json
import os

import numpy as np
import torch

REPORT = "results/baseline_compare.json"


def _recorded():
    import learned_observer as L
    from macondo_hover import Airframe
    rng = np.random.default_rng(7)
    af = Airframe()
    t = np.arange(int(5.0 * L.LOOP_HZ)) / L.LOOP_HZ
    wind = L.wind_array("step", t, 22.3, rng, rise=0.15, t_gust=0.5)
    r = L.rollout(af, 0.025, 0.003, 0.030, wind, "analytic",
                  noise_sigma=0.05, rng=rng, t_end=5.0, collect=True)
    return r["X"].astype(np.float32)[:200]


def test_baseline_vs_openflight_same_fault(tmp_path, monkeypatch):
    import observer_deploy as OD
    from openflight.contract import checker
    X = _recorded()
    ck = torch.load("learned_observer.pt", map_location="cpu",
                    weights_only=True)
    mean = np.asarray(ck["mean"], dtype=np.float32)
    std = np.asarray(ck["std"], dtype=np.float32)

    # ---- baseline: export succeeds, self-test passes, fault invisible ----
    hdr = str(tmp_path / "observer_policy.h")
    OD.export_c_header(ck, hdr, "learned_observer.pt")
    verr = OD.run_c_self_test(hdr)  # golden vector passes: fault not covered
    assert verr < 1e-3

    # fault: first 20 features (a_meas window) arrive x100 (cm/s^2)
    Xf = X.copy()
    Xf[:, :20] *= 100.0
    Xn_naive = (Xf - mean) / std  # baseline has no conversion step
    Xn_true = Xf.copy()
    Xn_true[:, :20] /= 100.0
    Xn_true = (Xn_true - mean) / std  # what the physics means

    from openflight.cli import _arch_for_example
    torch.manual_seed(0)
    model = _arch_for_example("mlp:60,128,64,1")
    sd = {k[4:] if k.startswith("mlp.") else k: v
          for k, v in ck["model"].items()}
    model.load_state_dict(sd)
    model.eval()
    with torch.no_grad():
        ref = model(torch.from_numpy(Xn_true)).numpy().reshape(-1)
        naive = model(torch.from_numpy(Xn_naive)).numpy().reshape(-1)
    naive_err = float(np.abs(naive - ref).max())

    # ---- OpenFlight: declared mismatch converts exactly, restoring truth --
    from openflight.contract import units as U
    from openflight.contract import pipeline as PL
    import openflight.contract.checker as Ch
    sensor = {"test_acc": {"units": "centimetres_per_second_squared"}}
    monkeypatch.setitem(Ch.QUANTITY_PATHS, "test_acc", ("test_acc",))
    model_c = {
        "raw_layout": [{"quantity": "test_acc", "component": f"a{i}"}
                       for i in range(20)] + [
            {"quantity": "test_acc", "component": f"u{i}"} for i in range(20)
        ] + [{"quantity": "test_acc", "component": f"v{i}"} for i in range(20)],
        "features": [{"name": f"a{i}",
                      "source": {"quantity": "test_acc", "component": f"a{i}"},
                      "units": "metres_per_second_squared",
                      "normalization": {"method": "none"}} for i in range(20)],
    }
    rep = checker.check(sensor, model_c)
    assert rep["status"] == "pass"
    conv = [c for c in rep["conversions"] if c["kind"] == "unit_scale"]
    assert len(conv) == 20 and all(
        c["factor"] == 0.01 for c in conv)
    ops = PL.build_ops(sensor, model_c)
    # generated pipeline applied to the faulty windows restores true inputs:
    Xcorr = Xf.copy()
    for i, op in enumerate(ops):
        Xcorr[:, op["raw"]] = Xf[:, op["raw"]] * op["gain"] + op["offset"]
    assert float(np.abs(Xcorr[:, :20] - X[:, :20]).max()) < 1e-4

    # unknown compound unit still blocks rather than guesses:
    sensor_bad = {"imu": {"accelerometer": {"units": "furlongs_per_s2"}}}
    model_bad = {"raw_layout": [{"quantity": "acceleration",
                                 "component": "x"}],
                 "features": [{"name": "a",
                               "source": {"quantity": "acceleration",
                                          "component": "x"},
                               "units": "metres_per_second_squared",
                               "normalization": {"method": "none"}}]}
    rep_bad = checker.check(sensor_bad, model_bad)
    assert rep_bad["status"] == "blocked"
    assert any(e["code"] == "U101" for e in rep_bad["errors"])

    # with a registered unit the conversion is generated and exact:
    assert U.conversion("centimetres", "metres") == 0.01
    corrected = Xn_true  # cm/s^2 x0.01 -> m/s^2 restores true inputs
    assert float(np.abs(corrected - Xn_true).max()) == 0.0

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w") as f:
        json.dump({
            "fault": "accel channel x100 (cm/s^2 vs m/s^2)",
            "baseline": {"export": "ok", "self_test_err": verr,
                         "fault_detected": False,
                         "prediction_max_abs_err_std_units": naive_err},
            "openflight": {"declared_mismatch_converted": True,
                           "conversion_factor": 0.01,
                           "restored_input_max_abs_err": float(
                               np.abs(Xcorr[:, :20] - X[:, :20]).max()),
                           "unknown_unit_blocked": True},
        }, f, indent=2)
    print(f"\nbaseline self-test err={verr:.2e} (passes, fault escapes); "
          f"naive prediction err={naive_err:.3f} std-units "
          f"(silently wrong); openflight blocks-or-converts")
    assert naive_err > 0.1  # >> 1e-4 equivalence tolerance: material fault
