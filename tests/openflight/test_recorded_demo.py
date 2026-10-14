"""Recorded-sensor robotics demo: real trained observer + physics rollouts.

Uses the repo's real 1-DOF gust physics (macondo/learned_observer) to record
sensor windows, then checks the openflight-compiled C++ against the PyTorch
reference on THOSE windows (not uniform noise). Also shows the gate passing
a consistent pair and blocking a frame-mismatched pair for the same signals.
"""
import numpy as np
import torch

from openflight.contract import checker


def _recorded_windows(n_windows=300):
    import learned_observer as L
    from macondo_hover import Airframe
    rng = np.random.default_rng(7)
    af = Airframe()
    t = np.arange(int(5.0 * L.LOOP_HZ)) / L.LOOP_HZ
    wind = L.wind_array("step", t, 22.3, rng, rise=0.15, t_gust=0.5)
    r = L.rollout(af, 0.025, 0.003, 0.030, wind, "analytic",
                  noise_sigma=0.05, rng=rng, t_end=5.0, collect=True)
    X = r["X"].astype(np.float32)
    assert X.shape[1] == 60, X.shape
    return X[:n_windows]


def test_recorded_equivalence(tmp_path):
    """Compiled C++ vs torch on recorded gust windows (real observer weights)."""
    import subprocess
    from openflight.compiler.api import compile_model
    from openflight.cli import _arch_for_example
    X = _recorded_windows()
    ck = torch.load("learned_observer.pt", map_location="cpu",
                    weights_only=True)
    mean = np.asarray(ck["mean"], dtype=np.float32)
    std = np.asarray(ck["std"], dtype=np.float32)
    Xn = ((X - mean) / std).astype(np.float32)
    out = compile_model(_arch_for_example("mlp:60,128,64,1"),
                        "learned_observer.pt", str(tmp_path / "build"))
    model = out["model"]
    with torch.no_grad():
        ref = model(torch.from_numpy(Xn)).numpy()
        ref = np.atleast_2d(ref.reshape(-1, 1))
    fin, fout = str(tmp_path / "in.bin"), str(tmp_path / "out.bin")
    Xn.tofile(fin)
    main = ("#include <cstdio>\n#include \"model.h\"\nint main(){"
            "FILE*f=fopen(\"" + fin + "\",\"rb\");"
            "fseek(f,0,SEEK_END);long n=ftell(f)/sizeof(float)/60;fseek(f,0,SEEK_SET);"
            "static float vin[300*60];static float vout[300];"
            "if(fread(vin,sizeof(float),(size_t)n*60,f)!=(size_t)n*60)return 1;fclose(f);"
            "FILE*o=fopen(\"" + fout + "\",\"wb\");"
            "for(long k=0;k<n;k++){float y[1];"
            "openflight::predict(vin+k*60,y);fwrite(y,sizeof(float),1,o);}"
            "fclose(o);return 0;}")
    src = str(tmp_path / "rec.cpp")
    open(src, "w").write(main)
    exe = str(tmp_path / "rec")
    bdir = str(tmp_path / "build")
    r = subprocess.run(["c++", "-O2", "-std=c++17", "-I", bdir, src,
                        bdir + "/model.cpp", "-o", exe],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[:2000]
    r2 = subprocess.run([exe], capture_output=True, text=True)
    assert r2.returncode == 0, r2.stderr[:500]
    got = np.fromfile(fout, dtype=np.float32).reshape(-1, 1)
    err = np.abs(got - ref)
    # recorded gust windows span hover->saturation: assert distribution-aware
    assert np.isfinite(got).all()
    assert float(err.max()) < 1e-4, float(err.max())
    print(f"\nrecorded windows: n={len(X)} max_abs_err={float(err.max()):.3e} "
          f"mean={float(err.mean()):.3e} ref_std={float(ref.std()):.3f}")


def test_gate_on_recording_contracts():
    """Same signals: consistent pair proceeds, frame lie is blocked."""
    sensor = {"state": {"velocity": {"units": "metres_per_second",
                                     "frame": "world"}},
              "imu": {"accelerometer": {"units": "metres_per_second_squared"}}}
    model = {"raw_layout": [{"quantity": "velocity", "component": "x"},
                            {"quantity": "acceleration", "component": "z"}],
             "features": [
                 {"name": "vx",
                  "source": {"quantity": "velocity", "component": "x"},
                  "units": "metres_per_second", "frame": "world",
                  "normalization": {"method": "affine", "scale": 1.0,
                                    "offset": 0.0}},
                 {"name": "az",
                  "source": {"quantity": "acceleration", "component": "z"},
                  "units": "metres_per_second_squared",
                  "normalization": {"method": "affine", "scale": 0.05,
                                    "offset": 0.0}}]}
    assert checker.check(sensor, model)["status"] == "pass"
    bad = dict(model, features=[dict(model["features"][0], frame="body")] +
               model["features"][1:])
    rep = checker.check(sensor, bad)
    assert rep["status"] == "blocked"
    assert any(e["code"] == "E301" and e["feature"] == "vx"
               for e in rep["errors"])


def test_declaration_reality_gap_documented():
    """Known blind spot (§3): the checker validates declarations against
    declarations. A sensor that LIES in its contract (declares m/s^2 while
    physically emitting g) passes validation with consistent paperwork, and
    the numerics go wrong. This test pins that boundary: detection here
    requires external calibration, not more contract logic."""
    import learned_observer as L
    from macondo_hover import Airframe
    rng = np.random.default_rng(7)
    af = Airframe()
    t = np.arange(int(5.0 * L.LOOP_HZ)) / L.LOOP_HZ
    wind = L.wind_array("step", t, 22.3, rng, rise=0.15, t_gust=0.5)
    r = L.rollout(af, 0.025, 0.003, 0.030, wind, "analytic",
                  noise_sigma=0.05, rng=rng, t_end=5.0, collect=True)
    X = r["X"].astype(np.float32)[:100]
    ck = torch.load("learned_observer.pt", map_location="cpu",
                    weights_only=True)
    mean = np.asarray(ck["mean"], dtype=np.float32)
    std = np.asarray(ck["std"], dtype=np.float32)
    from openflight.cli import _arch_for_example
    model = _arch_for_example("mlp:60,128,64,1")
    sd = {k[4:] if k.startswith("mlp.") else k: v
          for k, v in ck["model"].items()}
    model.load_state_dict(sd)
    model.eval()
    # lying sensor: accel physically x100 (cm/s^2), contract still says m/s^2
    Xlie = X.copy()
    Xlie[:, :20] *= 100.0
    sensor = {"imu": {"accelerometer":
                      {"units": "metres_per_second_squared"}}}  # the lie
    model_c = {
        "raw_layout": [{"quantity": "acceleration", "component": f"a{i}"}
                       for i in range(20)],
        "features": [{"name": f"a{i}",
                      "source": {"quantity": "acceleration",
                                 "component": f"a{i}"},
                      "units": "metres_per_second_squared",
                      "normalization": {"method": "none"}} for i in range(20)],
    }
    rep = checker.check(sensor, model_c)
    assert rep["status"] == "pass", \
        "checker cannot see through a false declaration (expected)"
    with torch.no_grad():
        ref = model(torch.from_numpy((X - mean) / std)).numpy().reshape(-1)
        wrong = model(torch.from_numpy(
            (Xlie - mean) / std)).numpy().reshape(-1)
    assert float(np.abs(wrong - ref).max()) > 0.1, \
        "lying declaration must corrupt outputs materially"
