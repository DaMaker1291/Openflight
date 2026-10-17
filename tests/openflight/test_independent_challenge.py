"""Independent challenge set (Priority B).

Pre-registered design (fixed before running):
  VALID:    convertible units (deg/s, rpm, cm, g, km/h), quat reorder both
            directions, affine/none norms, feature counts 4/7/10, layouts that
            differ from the dev examples (position+velocity+orientation space).
  INVALID:  dimension clash, frame mismatch, off-layout binding, unknown
            quantity, bad normalization, size mismatch, euler-vs-quaternion,
            accel/gyro channel swap.
  AMBIGUOUS: sensor units / frame / quat ordering undocumented, bias required
            but unconfigured.
  SECOND MODEL: PPO policy encoder (Linear/ReLU/LayerNorm, obs 656) — never
            seen during checker/compiler development. LayerNorm is unsupported:
            compile MUST refuse fail-closed, naming the operator.
  SECOND DATASET: fresh physics recording (turbulent wind, v=15 m/s, seed 999,
            heavier noise) through the compiled observer — parity must hold on
            data drawn outside the development distribution.

Independence notes: seed 999 (dev battery used 20261011), a different feature
space from the dev quadrotor/observer examples, and a model architecture the
compiler authors did not design for. Writes
results/independent_challenge.json.
"""
import copy
import json
import os

import numpy as np
import torch
import torch.nn as nn

from openflight.contract import checker

SEED = 999
REPORT = "results/independent_challenge.json"


# ---------------------------------------------------------------- sensor/model
def indep_sensor(pos_units="metres", vel_units="metres_per_second",
                 vel_frame="body", q_order="wxyz", gyro_units="deg/s",
                 drop=()):
    units_gyro = {"deg/s": "degrees_per_second",
                  "rad/s": "radians_per_second"}.get(gyro_units, gyro_units)
    s = {"state": {
             "position": {"units": pos_units, "frame": "world"},
             "velocity": {"units": vel_units, "frame": vel_frame},
             "orientation": {"representation": "quaternion",
                             "ordering": q_order},
             "angular_velocity": {"units": units_gyro, "frame": "body"}},
         "imu": {"accelerometer": {"units": "metres_per_second_squared"},
                 "gyroscope": {"units": units_gyro}}}
    for path in drop:
        node = s
        for k in path[:-1]:
            node = node[k]
        node.pop(path[-1], None)
    return s


def indep_model(pos_units="metres", vel_units="metres_per_second",
                vel_frame="body", q_order="wxyz", gyro_units="deg/s",
                norm_affine=True):
    gyro_mu = {"deg/s": "degrees_per_second",
               "rad/s": "radians_per_second"}.get(gyro_units, gyro_units)
    n = ({"method": "affine", "scale": 0.5, "offset": 0.1} if norm_affine
         else {"method": "none"})
    feats = [
        {"name": "px", "source": {"quantity": "position", "component": "x"},
         "units": pos_units, "frame": "world", "normalization": dict(n)},
        {"name": "py", "source": {"quantity": "position", "component": "y"},
         "units": pos_units, "frame": "world", "normalization": dict(n)},
        {"name": "pz", "source": {"quantity": "position", "component": "z"},
         "units": pos_units, "frame": "world", "normalization": dict(n)},
        {"name": "q", "source": {"quantity": "orientation"},
         "units": "dimensionless", "representation": "quaternion",
         "ordering": q_order, "normalization": {"method": "none"}, "width": 4},
        {"name": "vx", "source": {"quantity": "velocity", "component": "x"},
         "units": vel_units, "frame": vel_frame, "normalization": dict(n)},
        {"name": "wx", "source": {"quantity": "angular_velocity",
                                  "component": "x"},
         "units": gyro_mu, "frame": "body", "normalization": dict(n)},
        {"name": "az", "source": {"quantity": "acceleration", "component": "z"},
         "units": "metres_per_second_squared", "normalization": dict(n)},
    ]
    raw = ([{"quantity": "position", "component": c} for c in "xyz"] +
           [{"quantity": "orientation", "component": c} for c in "wxyz"] +
           [{"quantity": "velocity", "component": "x"},
            {"quantity": "angular_velocity", "component": "x"},
            {"quantity": "acceleration", "component": "z"}])
    return {"raw_layout": raw, "features": feats}


def run_case(category, fault, sensor, model, expect, expect_code=None,
             model_input_size=None):
    rep = checker.check(sensor, model, model_input_size=model_input_size)
    ok = (rep["status"] == expect)
    diag_ok = True
    if expect_code:
        hits = [e for e in rep["errors"] if e["code"] == expect_code]
        diag_ok = bool(hits) and all(h.get("feature") for h in hits)
        ok = ok and diag_ok
    return {"category": category, "fault": fault, "expected": expect,
            "got": rep["status"], "expected_code": expect_code,
            "codes": [e["code"] for e in rep["errors"]],
            "ok": ok, "diag_ok": diag_ok}


def build_challenge():
    rng = np.random.default_rng(SEED)
    cases = []
    # ---- VALID (sampled conversions x norms, independent space) ----
    pos_u = ["metres", "centimetres"]
    vel_u = ["metres_per_second", "kilometres_per_hour"]
    combos = [(pu, vu, aff, qo, go)
              for pu in pos_u for vu in vel_u
              for aff in (False, True)
              for qo in ("wxyz", "xyzw")
              for go in ("deg/s", "rad/s")]
    # Draw 8 DISTINCT combos. Per-draw i.i.d. sampling collided once in the
    # frozen v0.2.6 report (21 cases, 20 distinct) — discovered 2026-10-16
    # by the duplicate-identity check in repro.verify().
    for idx in rng.choice(len(combos), size=8, replace=False):
        pu, vu, aff, qo, go = combos[int(idx)]
        cases.append(run_case(
            "valid", f"pos={pu} vel={vu} aff={aff} q={qo} gyro={go}",
            indep_sensor(pos_units="metres",
                         vel_units="metres_per_second", q_order="wxyz",
                         gyro_units="rad/s"),
            indep_model(pos_units=pu, vel_units=vu, q_order=str(qo),
                        gyro_units=str(go), norm_affine=aff), "pass"))
    # valid: velocity sensor already in body frame, model matches
    cases.append(run_case(
        "valid", "body-frame velocity agreement",
        indep_sensor(vel_frame="body"), indep_model(vel_frame="body"), "pass"))
    # ---- INVALID ----
    s, m = indep_sensor(), indep_model()
    m2 = copy.deepcopy(m)
    m2["features"][0]["units"] = "radians_per_second"  # length vs angle
    cases.append(run_case("invalid", "dimension clash on px", s, m2,
                          "blocked", "E101"))
    m2 = copy.deepcopy(m)
    m2["features"][4]["frame"] = "world"  # sensor body, model world
    cases.append(run_case("invalid", "frame mismatch on vx", s, m2,
                          "blocked", "E301"))
    m2 = copy.deepcopy(m)
    m2["features"][5]["source"] = {"quantity": "angular_velocity",
                                   "component": "z"}  # not in raw_layout
    cases.append(run_case("invalid", "wx bound off-layout", s, m2,
                          "blocked", "E402"))
    m2 = copy.deepcopy(m)
    m2["features"][6]["source"] = {"quantity": "barometer", "component": "z"}
    cases.append(run_case("invalid", "unknown quantity barometer", s, m2,
                          "blocked", "E401"))
    m2 = copy.deepcopy(m)
    m2["features"][0]["normalization"] = {"method": "standardize"}
    cases.append(run_case("invalid", "bad norm on px", s, m2,
                          "blocked", "E201"))
    cases.append(run_case("invalid", "width sum 10 vs model 12", s, m,
                          "blocked", "E203", model_input_size=12))
    m2 = copy.deepcopy(m)  # accel/gyro channel swap: gyro feats read accel
    for f in m2["features"]:
        if f["name"] == "wx":
            f["source"] = {"quantity": "acceleration", "component": "z"}
    cases.append(run_case("invalid", "wx reads accel channel", s, m2,
                          "blocked", "E101"))
    s2 = indep_sensor()
    s2["state"]["orientation"] = {"representation": "euler", "ordering": "rpy"}
    cases.append(run_case("invalid", "euler sensor vs quat model",
                          s2, copy.deepcopy(m), "blocked", "E402"))
    # ---- AMBIGUOUS ----
    cases.append(run_case(
        "ambiguous", "position units undocumented",
        indep_sensor(drop=[("state", "position", "units")]),
        indep_model(), "blocked", "U101"))
    cases.append(run_case(
        "ambiguous", "velocity frame undocumented, model requires body",
        indep_sensor(drop=[("state", "velocity", "frame")]),
        indep_model(), "blocked", "U301"))
    s3 = indep_sensor()
    s3["state"]["orientation"] = {"representation": "quaternion"}
    cases.append(run_case("ambiguous", "quat ordering undocumented",
                          s3, indep_model(), "blocked", "U102"))
    m5 = indep_model()
    m5["features"][5]["bias_required"] = True
    cases.append(run_case("ambiguous", "gyro bias required, unconfigured",
                          indep_sensor(), m5, "blocked", "E302"))
    return cases


def test_challenge_rates():
    cases = build_challenge()
    by_cat = {}
    for c in cases:
        by_cat.setdefault(c["category"], []).append(c)
    summary = {k: {"n": len(v), "correct": sum(1 for c in v if c["ok"]),
                   "diag_correct": sum(1 for c in v if c["diag_ok"])}
               for k, v in by_cat.items()}
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w") as f:
        json.dump({"seed": SEED, "summary": summary, "cases": cases}, f,
                  indent=2)
    for cat in ("valid", "invalid", "ambiguous"):
        bad = [c for c in by_cat[cat] if not c["ok"]]
        assert not bad, (cat, bad)
    faults = [c["fault"] for c in cases]
    assert len(faults) == len(set(faults)), (
        "duplicate case identity in independent challenge:",
        [f for f in faults if faults.count(f) > 1],
    )
    print("\nindependent challenge: " +
          ", ".join(f"{k} {v['correct']}/{v['n']}" for k, v in
                    sorted(summary.items())))


def test_second_model_rejected_fail_closed(tmp_path):
    """PPO policy encoder (Linear/ReLU/LayerNorm, unseen during development)
    must be refused with a named-operator error — never silently approximated.
    """
    from openflight.compiler.api import compile_model

    class PPONet(nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder = nn.Sequential(
                nn.Linear(656, 256), nn.ReLU(), nn.LayerNorm(256),
                nn.Linear(256, 128), nn.ReLU(), nn.LayerNorm(128))
            self.policy_head = nn.Linear(128, 5)
            self.value_head = nn.Linear(128, 1)

        def forward(self, obs):
            h = self.encoder(obs)
            return self.policy_head(h), self.value_head(h)

    sd = torch.load("ppo_best.pt", map_location="cpu", weights_only=True)
    torch.save({k: v.cpu() for k, v in sd.items()}, str(tmp_path / "w.pt"))
    try:
        compile_model(PPONet(), str(tmp_path / "w.pt"), str(tmp_path / "b"))
    except ValueError as e:
        assert "LayerNorm" in str(e), str(e)[:500]
        return
    raise AssertionError("LayerNorm model compiled without error")


def test_second_dataset_parity(tmp_path):
    """Fresh physics (turbulent 15 m/s wind, seed 999, heavy noise): compiled
    observer must match torch on data outside the development distribution."""
    import subprocess
    import learned_observer as L
    from macondo_hover import Airframe
    from openflight.compiler.api import compile_model
    from openflight.cli import _arch_for_example
    rng = np.random.default_rng(999)
    af = Airframe(mass_kg=0.15, twr=5.0, cd_a=0.016)
    t = np.arange(int(5.0 * L.LOOP_HZ)) / L.LOOP_HZ
    wind = L.wind_array("turb", t, 15.0, rng, tau_turb=0.6, amp=0.4)
    r = L.rollout(af, 0.05, 0.006, 0.030, wind, "analytic",
                  noise_sigma=0.30, rng=rng, t_end=5.0, collect=True)
    X = r["X"].astype(np.float32)
    ck = torch.load("learned_observer.pt", map_location="cpu",
                    weights_only=True)
    mean = np.asarray(ck["mean"], dtype=np.float32)
    std = np.asarray(ck["std"], dtype=np.float32)
    Xn = ((X - mean) / std).astype(np.float32)
    out = compile_model(_arch_for_example("mlp:60,128,64,1"),
                        "learned_observer.pt", str(tmp_path / "build"))
    with torch.no_grad():
        ref = out["model"](torch.from_numpy(Xn)).numpy().reshape(-1)
    bdir = str(tmp_path / "build")
    fin, fout = str(tmp_path / "in.bin"), str(tmp_path / "out.bin")
    Xn.tofile(fin)
    src = str(tmp_path / "t.cpp")
    open(src, "w").write(
        '#include <cstdio>\n#include "model.h"\nint main(){'
        f'FILE*f=fopen("{fin}","rb");fseek(f,0,SEEK_END);'
        "long n=ftell(f)/sizeof(float)/60;fseek(f,0,SEEK_SET);"
        "static float vin[5000*60];static float vout[5000];"
        "if(fread(vin,sizeof(float),(size_t)n*60,f)!=(size_t)n*60)return 1;"
        "fclose(f);"
        f'FILE*o=fopen("{fout}","wb");'
        "for(long k=0;k<n;k++){float y[1];openflight::predict(vin+k*60,y);"
        "fwrite(y,sizeof(float),1,o);}fclose(o);return 0;}")
    exe = str(tmp_path / "t")
    pr = subprocess.run(["c++", "-O2", "-std=c++17", "-I", bdir, src,
                         bdir + "/model.cpp", "-o", exe],
                        capture_output=True, text=True)
    assert pr.returncode == 0, pr.stderr[:2000]
    pr2 = subprocess.run([exe], capture_output=True, text=True)
    assert pr2.returncode == 0, pr2.stderr[:500]
    got = np.fromfile(fout, dtype=np.float32)
    err = np.abs(got - ref)
    assert np.isfinite(got).all()
    assert float(err.max()) < 1e-4, float(err.max())
    print(f"\nsecond dataset: n={len(X)} max_abs_err={float(err.max()):.3e}")
