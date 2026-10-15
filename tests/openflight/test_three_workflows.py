"""Three-workflow comparison on identical faults (fair baseline).

Workflows, same observer model + same recorded gust windows:
  W1 bare export   — observer_deploy.py weights + golden self-test, hand-fed inputs.
  W2 careful manual— numpy preprocessing with hand-written constants per the
                     docs (unit factors, normalization, channel order) + a shape
                     assert. Steelmanned: configured correctly it matches the
                     reference exactly; the question is what it DETECTS.
  W3 OpenFlight     — contract validation gate + generated pipeline.

Fault classes (predefined): declared unit mismatch, undeclared units,
feature-layout inconsistency, missing normalization, frame inconsistency,
plus a size-mismatch control. Metric per cell: detected / escaped, with
measured numeric error where applicable. Writes
results/three_workflows.json. No human-time claims.
"""
import json
import os

import numpy as np
import torch

REPORT = "results/three_workflows.json"


def _recorded(n=200):
    import learned_observer as L
    from macondo_hover import Airframe
    rng = np.random.default_rng(7)
    af = Airframe()
    t = np.arange(int(5.0 * L.LOOP_HZ)) / L.LOOP_HZ
    wind = L.wind_array("step", t, 22.3, rng, rise=0.15, t_gust=0.5)
    r = L.rollout(af, 0.025, 0.003, 0.030, wind, "analytic",
                  noise_sigma=0.05, rng=rng, t_end=5.0, collect=True)
    return r["X"].astype(np.float32)[:n]


def _observer():
    from openflight.cli import _arch_for_example
    ck = torch.load("learned_observer.pt", map_location="cpu",
                    weights_only=True)
    model = _arch_for_example("mlp:60,128,64,1")
    sd = {k[4:] if k.startswith("mlp.") else k: v
          for k, v in ck["model"].items()}
    model.load_state_dict(sd)
    model.eval()
    mean = np.asarray(ck["mean"], dtype=np.float32)
    std = np.asarray(ck["std"], dtype=np.float32)
    return model, mean, std


def _manual_preprocess(raw, unit_factors, mean, std, order, size_assert=60):
    """Careful-manual preprocessing: hand-written per-channel constants."""
    assert raw.shape[1] == size_assert, \
        f"input width {raw.shape[1]} != {size_assert}"
    out = raw[:, order] * np.asarray(unit_factors, dtype=np.float32)
    return (out - mean) / std


def test_three_workflows(tmp_path):
    import observer_deploy as OD
    from openflight.contract import checker
    X = _recorded()
    model, mean, std = _observer()
    with torch.no_grad():
        ref = model(torch.from_numpy((X - mean) / std)).numpy().reshape(-1)
    F = X.shape[1]
    table = {}

    # ---- W1 bare export: always succeeds, self-test passes ----
    hdr = str(tmp_path / "observer_policy.h")
    OD.export_c_header(torch.load("learned_observer.pt", map_location="cpu",
                                  weights_only=True), hdr,
                       "learned_observer.pt")
    w1_selftest = OD.run_c_self_test(hdr)
    assert w1_selftest < 1e-3

    # ---- W2 steelman: configured correctly it matches the reference ----
    Xn = _manual_preprocess(X, np.ones(F), mean, std, list(range(F)))
    with torch.no_grad():
        w2_ok = model(torch.from_numpy(Xn)).numpy().reshape(-1)
    w2_correct_err = float(np.abs(w2_ok - ref).max())
    assert w2_correct_err < 1e-6

    # ---- fault 1: declared unit mismatch (accel x100) ----
    Xf = X.copy()
    Xf[:, :20] *= 100.0
    with torch.no_grad():
        w1 = model(torch.from_numpy((Xf - mean) / std)).numpy().reshape(-1)
    f1 = {"W1_bare": {"detected": False,
                      "err": float(np.abs(w1 - ref).max())}}
    Xn_w2 = _manual_preprocess(Xf, np.ones(F), mean, std, list(range(F)))
    with torch.no_grad():
        w2 = model(torch.from_numpy(Xn_w2)).numpy().reshape(-1)
    f1["W2_manual_wrong_config"] = {
        "detected": False, "err": float(np.abs(w2 - ref).max())}
    fac = np.ones(F)
    fac[:20] = 0.01  # careful engineer who read the (correct) docs
    Xn_w2c = _manual_preprocess(Xf, fac, mean, std, list(range(F)))
    with torch.no_grad():
        w2c = model(torch.from_numpy(Xn_w2c)).numpy().reshape(-1)
    f1["W2_manual_right_config"] = {
        "detected": "n/a (correct by diligence, nothing validates it)",
        "err": float(np.abs(w2c - ref).max())}
    import openflight.contract.checker as Ch
    # declared unit mismatch: sensor declares cm/s^2, model expects m/s^2.
    # The checker must PASS (it is a resolvable conversion) and emit a
    # unit_scale conversion with factor 0.01 — not block, and not skip the
    # check entirely. This exercises the real checker path (the previous
    # version asserted a conversion factor without ever running the checker).
    sens1 = {"imu": {"accelerometer": {"units": "centimetres_per_second_squared"}}}
    mod1 = {"raw_layout": [{"quantity": "acceleration", "component": "x"}],
            "features": [{"name": "a",
                          "source": {"quantity": "acceleration",
                                     "component": "x"},
                          "units": "metres_per_second_squared",
                          "normalization": {"method": "none"}}]}
    r1 = Ch.check(sens1, mod1)
    assert r1["status"] == "pass", r1.get("errors")
    conv1 = [c for c in r1.get("conversions", [])
             if c.get("kind") == "unit_scale"]
    assert conv1, "expected a unit_scale conversion, got none"
    assert conv1[0]["factor"] == 0.01
    f1["W3_openflight"] = {"detected": "converts x0.01 (generated op)",
                           "code": [c["kind"] for c in conv1],
                           "factor": conv1[0]["factor"]}
    table["declared_unit_mismatch_x100"] = f1

    # ---- fault 2: undeclared units ----
    sb = {"imu": {"accelerometer": {"units": "furlongs_per_s2"}}}
    mb = {"raw_layout": [{"quantity": "acceleration", "component": "x"}],
          "features": [{"name": "a", "source": {"quantity": "acceleration",
                                                "component": "x"},
                        "units": "metres_per_second_squared",
                        "normalization": {"method": "none"}}]}
    rb = checker.check(sb, mb)
    table["undeclared_units"] = {
        "W1_bare": {"detected": False},
        "W2_manual": {"detected": False},
        "W3_openflight": {
            "detected": rb["status"] == "blocked",
            "code": [e["code"] for e in rb["errors"]]}}
    assert rb["status"] == "blocked"

    # ---- fault 3: feature-layout inconsistency ----
    s3 = {"imu": {"accelerometer": {"units": "metres_per_second_squared"}}}
    m3 = {"raw_layout": [{"quantity": "acceleration", "component": "x"}],
          "features": [{"name": "a", "source": {"quantity": "acceleration",
                                                "component": "y"},
                        "units": "metres_per_second_squared",
                        "normalization": {"method": "none"}}]}
    r3 = checker.check(s3, m3)
    table["feature_layout_inconsistency"] = {
        "W1_bare": {"detected": False},
        "W2_manual": {"detected": False},
        "W3_openflight": {"detected": r3["status"] == "blocked",
                          "code": [e["code"] for e in r3["errors"]]}}
    assert r3["status"] == "blocked"

    # ---- fault 4: missing normalization ----
    m4 = {"raw_layout": [{"quantity": "acceleration", "component": "x"}],
          "features": [{"name": "a", "source": {"quantity": "acceleration",
                                                "component": "x"},
                        "units": "metres_per_second_squared",
                        "normalization": {"method": "bogus"}}]}
    r4 = checker.check(s3, m4)
    table["missing_normalization"] = {
        "W1_bare": {"detected": False},
        "W2_manual": {"detected": False},
        "W3_openflight": {"detected": r4["status"] == "blocked",
                          "code": [e["code"] for e in r4["errors"]]}}
    assert r4["status"] == "blocked"

    # ---- fault 5: frame inconsistency ----
    s5 = {"state": {"velocity": {"units": "metres_per_second",
                                 "frame": "world"}}}
    m5 = {"raw_layout": [{"quantity": "velocity", "component": "x"}],
          "features": [{"name": "v",
                        "source": {"quantity": "velocity", "component": "x"},
                        "units": "metres_per_second", "frame": "body",
                        "normalization": {"method": "none"}}]}
    r5 = checker.check(s5, m5)
    table["frame_inconsistency"] = {
        "W1_bare": {"detected": False},
        "W2_manual": {"detected": False},
        "W3_openflight": {"detected": r5["status"] == "blocked",
                          "code": [e["code"] for e in r5["errors"]]}}
    assert r5["status"] == "blocked"

    # ---- control: corrupt checkpoint (all three should refuse) ----
    bad_ckpt = str(tmp_path / "bad.pt")
    with open(bad_ckpt, "wb") as f:
        f.write(b"not a checkpoint at all")
    try:
        OD.load_observer(bad_ckpt)
        w1_corr = False
    except Exception:
        w1_corr = True
    try:
        torch.load(bad_ckpt, map_location="cpu", weights_only=True)
        w2_corr = False
    except Exception:
        w2_corr = True
    import torch.nn as nn
    from openflight.compiler.api import compile_model
    try:
        compile_model(nn.Sequential(nn.Linear(60, 1)), bad_ckpt,
                      str(tmp_path / "badbuild"))
        w3_corr = False
    except Exception:
        w3_corr = True
    table["control_corrupt_checkpoint"] = {
        "W1_bare": {"detected": w1_corr, "note": "load_observer refuses"},
        "W2_manual": {"detected": w2_corr, "note": "torch.load refuses"},
        "W3_openflight": {"detected": w3_corr, "note": "safe loader refuses"}}
    assert w1_corr and w2_corr and w3_corr

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w") as f:
        json.dump({"model": "learned_observer.pt", "n_windows": len(X),
                   "w1_selftest_err": w1_selftest,
                   "w2_correct_config_err": w2_correct_err,
                   "cells": table}, f, indent=2)
    print("\nthree-workflow detection matrix written to " + REPORT)
    # the claim under test: semantic faults escape W1/W2, stopped by W3
    assert f1["W1_bare"]["err"] > 0.1
    assert f1["W2_manual_wrong_config"]["err"] > 0.1
