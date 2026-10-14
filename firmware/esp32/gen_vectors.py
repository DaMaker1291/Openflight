#!/usr/bin/env python3
"""Bake recorded parity vectors into firmware/esp32/main/gen/test_vectors.h.

Reproduces tests/openflight/test_recorded_demo.py::_recorded_windows exactly
(same physics, seed, normalization) and stores the PyTorch reference outputs
alongside. Tolerance is predefined (1e-4, same as the host parity test) and
must not be relaxed after seeing results.
"""
import argparse
import sys

import numpy as np
import torch


def cf(v: float) -> str:
    s = f"{float(v):.9g}"
    if "e" not in s and "E" not in s and "." not in s:
        s += ".0"
    return s + "f"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--tol", type=float, default=1e-4)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    import learned_observer as L
    from macondo_hover import Airframe
    from openflight.cli import _arch_for_example

    rng = np.random.default_rng(7)
    af = Airframe()
    t = np.arange(int(5.0 * L.LOOP_HZ)) / L.LOOP_HZ
    wind = L.wind_array("step", t, 22.3, rng, rise=0.15, t_gust=0.5)
    r = L.rollout(af, 0.025, 0.003, 0.030, wind, "analytic",
                  noise_sigma=0.05, rng=rng, t_end=5.0, collect=True)
    X = r["X"].astype(np.float32)
    assert X.shape[1] == 60, X.shape
    X = X[:a.n]

    ck = torch.load("learned_observer.pt", map_location="cpu",
                    weights_only=True)
    mean = np.asarray(ck["mean"], dtype=np.float32)
    std = np.asarray(ck["std"], dtype=np.float32)
    Xn = ((X - mean) / std).astype(np.float32)
    model = _arch_for_example("mlp:60,128,64,1")
    sd = {k[4:] if k.startswith("mlp.") else k: v
          for k, v in ck["model"].items()}
    model.load_state_dict(sd)
    model.eval()
    with torch.no_grad():
        ref = model(torch.from_numpy(Xn)).numpy().reshape(-1).astype(np.float32)

    lines = ["#pragma once",
             "// Auto-generated recorded parity vectors — do not edit.",
             "// Same windows/normalization as test_recorded_demo.py; torch refs.",
             f"#define SELFTEST_N {len(X)}",
             f"#define SELFTEST_TOL {a.tol:.1e}f",
             "static const float SELFTEST_X[] = {"]
    for row in Xn:
        lines.append("    " + ", ".join(cf(v) for v in row) + ",")
    lines += ["};", "static const float SELFTEST_REF[] = {"]
    for row in ref.reshape(-1, 1):
        lines.append("    " + ", ".join(cf(v) for v in row) + ",")
    lines += ["};", ""]
    with open(a.out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {a.out}: N={len(X)} tol={a.tol:.1e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
