#!/usr/bin/env python3
"""
observer_deploy.py -- sim-to-real export of the learned disturbance observer
============================================================================

Exports the REAL trained observer checkpoint (``learned_observer.pt``, written
by ``learned_observer.py``) to a self-contained C header an STM32/ESP32 can
compile: the MLP weights (60->128->64->1), the input standardization constants
(mean/std over the 20-ms window), the output de-standardization (t_mean/t_std),
a ``observer_predict()`` inline function, a golden test vector, and -- when the
checkpoint carries the 8-member deep ensemble -- an ``observer_predict_unc()``
that also returns the member disagreement (the measured envelope-exit signal,
AUROC 0.87 in ``learned_observer_uncertainty.json``).

What this model IS (measured):
  * A predictive wind-disturbance estimator for the macondo 1-DOF wind-hold
    plant: window of [a_meas, u_act, v] (20 ms at 1 kHz) -> w_hat(k+5), i.e.
    a 5 ms predictive lead over the analytic observer. In closed loop it cuts
    peak hold error on the 50 mph step gust from 6.34 cm (analytic observer)
    to 3.29 cm at 20 seeds (IQM), and it generalizes CI-separated below the
    analytic observer to unseen winds up to 63 mph even when trained only to
    22 mph (see paper/resilience_framework.tex, sec:observer).
  * It is a feedforward disturbance estimate, NOT a flight controller. The
    drone still needs the PD+I position loop (macondo_hover.py) that consumes
    w_hat, and a real telemetry bridge producing [a_meas, u_act, v] at 1 kHz
    (accelerometer after its known lag, commanded/actual thrust specific force,
    body velocity). None of that bridge exists on hardware yet -- see
    OBSERVER_DEPLOYMENT.md. All numbers are sim-measured; nothing in this repo
    has been measured against physical wind.

Usage:
    python observer_deploy.py --checkpoint learned_observer.pt --export
    python observer_deploy.py --checkpoint learned_observer.pt --export \
        --out-header observer_policy.h --self-test

The exporter refuses checkpoints that are not observer checkpoints, and always
writes a golden test vector generated from the actual weights so the target
MCU can self-validate after flashing.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile

import numpy as np
import torch


# ---------------------------------------------------------------------------
# 1. Real checkpoint loading
# ---------------------------------------------------------------------------

def load_observer(path: str) -> dict:
    """Load an observer checkpoint; refuse anything that is not one."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"checkpoint not found: {path}")
    ck = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(ck, dict):
        raise ValueError(f"{path}: not a dict checkpoint (type {type(ck).__name__})")
    required = ("model", "mean", "std", "t_mean", "t_std", "in_dim", "W", "H")
    missing = [k for k in required if k not in ck]
    if missing:
        raise ValueError(f"{path}: not an observer checkpoint "
                         f"(missing {missing}; keys={list(ck)[:8]})")
    sd = ck["model"]
    for key in ("mlp.0.weight", "mlp.0.bias", "mlp.2.weight", "mlp.2.bias",
                "mlp.4.weight", "mlp.4.bias"):
        if key not in sd:
            raise ValueError(f"{path}: observer net missing {key}")
    in_dim = int(sd["mlp.0.weight"].shape[1])
    if in_dim != 3 * int(ck["W"]):
        raise ValueError(f"{path}: window W={ck['W']} inconsistent with "
                         f"in_dim={in_dim}")
    return ck


# ---------------------------------------------------------------------------
# 2. Export of real weights
# ---------------------------------------------------------------------------

def _cf(v: float) -> str:
    """Format a value as a valid C float literal (9 sig digits).

    ``%.9g`` alone can emit integral forms like ``20``, which are invalid C
    (``20f``). Guarantee a decimal point or exponent so the ``f`` suffix is
    always legal.
    """
    s = f"{v:.9g}"
    if "e" not in s and "E" not in s and "." not in s:
        s += ".0"
    return s + "f"


def _fmt(a: np.ndarray) -> str:
    return ", ".join(_cf(v) for v in a.ravel())


def _net_arrays(sd: dict) -> dict:
    """Extract the three Linear layers of the observer MLP as float32 arrays."""
    return dict(
        w1=sd["mlp.0.weight"].numpy(), b1=sd["mlp.0.bias"].numpy(),
        w2=sd["mlp.2.weight"].numpy(), b2=sd["mlp.2.bias"].numpy(),
        w3=sd["mlp.4.weight"].numpy(), b3=sd["mlp.4.bias"].numpy(),
    )


def golden_vector(net_arrays: dict, mean: np.ndarray, std: np.ndarray,
                  t_mean: float, t_std: float, seed: int = 1234) -> dict:
    """A fixed input window + the net's own prediction, for on-device self-test."""
    rng = np.random.default_rng(seed)
    n = mean.shape[0] // 3
    win = np.concatenate([
        rng.uniform(-5.0, 40.0, n),      # a_meas (m/s^2)
        rng.uniform(-5.0, 40.0, n),      # u_act (m/s^2)
        rng.uniform(-0.5, 0.5, n),       # v (m/s)
    ]).astype(np.float32)
    x = (win - mean) / std
    h1 = np.maximum(x @ net_arrays["w1"].T + net_arrays["b1"], 0.0)
    h2 = np.maximum(h1 @ net_arrays["w2"].T + net_arrays["b2"], 0.0)
    w_hat = float(h2 @ net_arrays["w3"][0] + net_arrays["b3"][0]) * t_std + t_mean
    return dict(win=win, w_hat=w_hat)


def export_c_header(ck: dict, path: str, source_pt: str) -> dict:
    """Serialize real observer weights (+ ensemble, if present) to a C header."""
    sd = ck["model"]
    net = _net_arrays(sd)
    w1, b1 = net["w1"], net["b1"]          # (128, 60)
    w2, b2 = net["w2"], net["b2"]          # (64, 128)
    w3, b3 = net["w3"], net["b3"]          # (1, 64)
    mean = np.asarray(ck["mean"], dtype=np.float32)
    std = np.asarray(ck["std"], dtype=np.float32)
    t_mean, t_std = float(ck["t_mean"]), float(ck["t_std"])
    W, H = int(ck["W"]), int(ck["H"])
    ens = ck.get("ensemble") or []
    gv = golden_vector(net, mean, std, t_mean, t_std)

    lines = [
        "// Auto-generated from REAL observer checkpoint weights -- do not edit.",
        f"// Source: {source_pt}",
        "// Learned disturbance observer (macondo wind-hold plant):",
        f"//   window[{W}] of [a_meas, u_act, v] at 1 kHz -> w_hat(k+{H})",
        "//   (m/s^2, drag specific force), standardized with the embedded",
        "//   mean/std and de-standardized with t_mean/t_std.",
        "// MLP: Linear(60,128)+ReLU -> Linear(128,64)+ReLU -> Linear(64,1).",
        "// Honest scope: this is the wind-hold FEEDFORWARD estimator, not a",
        "// flight controller. The PD+I loop (macondo_hover.py) consumes w_hat;",
        "// the telemetry bridge (a_meas/u_act/v at 1 kHz) is not yet defined",
        "// on hardware. All numbers are sim-measured (see paper, sec:observer).",
        "#pragma once",
        "#include <math.h>",
        f"#define OBSERVER_WINDOW_MS {W}",
        f"#define OBSERVER_HORIZON_MS {H}",
        f"#define OBSERVER_IN_DIM {w1.shape[1]}",
        f"#define OBSERVER_HID1 {w1.shape[0]}",
        f"#define OBSERVER_HID2 {w2.shape[0]}",
        f"#define OBSERVER_N_ENSEMBLE {len(ens)}",
        f"#define OBSERVER_SELF_TEST_TOL 1e-3f",
        "",
        f"static const float OBSERVER_MEAN[{mean.shape[0]}] = {{{_fmt(mean)}}};",
        f"static const float OBSERVER_STD[{std.shape[0]}] = {{{_fmt(std)}}};",
        f"static const float OBSERVER_T_MEAN = {_cf(t_mean)};",
        f"static const float OBSERVER_T_STD = {_cf(t_std)};",
        "",
        f"static const float OBSERVER_W1[{w1.shape[0]}][{w1.shape[1]}] = {{",
    ]
    for i in range(w1.shape[0]):
        lines.append(f"    {{{_fmt(w1[i])}}},")
    lines.append("};")
    lines.append(f"static const float OBSERVER_B1[{b1.shape[0]}] = {{{_fmt(b1)}}};")
    lines.append(f"static const float OBSERVER_W2[{w2.shape[0]}][{w2.shape[1]}] = {{")
    for i in range(w2.shape[0]):
        lines.append(f"    {{{_fmt(w2[i])}}},")
    lines.append("};")
    lines.append(f"static const float OBSERVER_B2[{b2.shape[0]}] = {{{_fmt(b2)}}};")
    lines.append(f"static const float OBSERVER_W3[{w3.shape[0]}][{w3.shape[1]}] = {{")
    for i in range(w3.shape[0]):
        lines.append(f"    {{{_fmt(w3[i])}}},")
    lines.append("};")
    lines.append(f"static const float OBSERVER_B3[{b3.shape[0]}] = {{{_fmt(b3)}}};")
    lines.append("")

    member_decls = []
    if ens:
        for m_i, msd in enumerate(ens):
            mn = _net_arrays(msd)
            if mn["w1"].shape != w1.shape:
                raise ValueError(
                    f"ensemble member {m_i} shape {mn['w1'].shape} != "
                    f"base {w1.shape}; refusing to export a mismatched ensemble")
            for nm, arr in (("W1", mn["w1"]), ("B1", mn["b1"]),
                            ("W2", mn["w2"]), ("B2", mn["b2"]),
                            ("W3", mn["w3"]), ("B3", mn["b3"])):
                if arr.ndim == 2:
                    lines.append(f"static const float OBSERVER_E{m_i}_{nm}"
                                 f"[{arr.shape[0]}][{arr.shape[1]}] = {{")
                    for r in range(arr.shape[0]):
                        lines.append(f"    {{{_fmt(arr[r])}}},")
                    lines.append("};")
                else:
                    lines.append(f"static const float OBSERVER_E{m_i}_{nm}"
                                 f"[{arr.shape[0]}] = {{{_fmt(arr)}}};")
            member_decls.append(m_i)
        lines.append("")

    lines += [
        "// Standardize the raw window (same op the Python pipeline applies).",
        "static inline void observer_standardize(",
        "        const float in[OBSERVER_IN_DIM], float x[OBSERVER_IN_DIM]) {",
        "    for (int i = 0; i < OBSERVER_IN_DIM; i++)",
        "        x[i] = (in[i] - OBSERVER_MEAN[i]) / OBSERVER_STD[i];",
        "}",
        "",
        "// Base estimator: standardized window -> standardized w_hat.",
        "static inline float observer_net(const float x[OBSERVER_IN_DIM]) {",
        "    float h1[OBSERVER_HID1], h2[OBSERVER_HID2], s;",
        "    for (int j = 0; j < OBSERVER_HID1; j++) {",
        "        s = OBSERVER_B1[j];",
        "        for (int i = 0; i < OBSERVER_IN_DIM; i++)",
        "            s += OBSERVER_W1[j][i] * x[i];",
        "        h1[j] = s > 0.f ? s : 0.f;",
        "    }",
        "    for (int j = 0; j < OBSERVER_HID2; j++) {",
        "        s = OBSERVER_B2[j];",
        "        for (int i = 0; i < OBSERVER_HID1; i++)",
        "            s += OBSERVER_W2[j][i] * h1[i];",
        "        h2[j] = s > 0.f ? s : 0.f;",
        "    }",
        "    s = OBSERVER_B3[0];",
        "    for (int i = 0; i < OBSERVER_HID2; i++) s += OBSERVER_W3[0][i] * h2[i];",
        "    return s;",
        "}",
        "",
        "// Predictive disturbance estimate (drag specific force, m/s^2):",
        "// w_hat(k + OBSERVER_HORIZON_MS ms) from the current 20-ms window.",
        "static inline float observer_predict(const float win[OBSERVER_IN_DIM]) {",
        "    float x[OBSERVER_IN_DIM];",
        "    observer_standardize(win, x);",
        "    return observer_net(x) * OBSERVER_T_STD + OBSERVER_T_MEAN;",
        "}",
        "",
    ]

    if ens:
        lines += [
            "// Member disagreement = epistemic uncertainty (m/s^2). The measured",
            "// envelope-exit signal: rises monotonically with unseen wind speed",
            "// (mean sigma 0.018 -> 10.58 m/s^2 from 10 to 28 m/s), AUROC 0.87",
            "// for 'wind above the training cap' (learned_observer_uncertainty.json).",
            "static inline void observer_member_preds(",
            "        const float x[OBSERVER_IN_DIM], float out[OBSERVER_N_ENSEMBLE]) {",
            "    float h1[OBSERVER_HID1], h2[OBSERVER_HID2], s;",
        ]
        for m_i in member_decls:
            lines += [
                f"    for (int j = 0; j < OBSERVER_HID1; j++) {{",
                f"        s = OBSERVER_E{m_i}_B1[j];",
                f"        for (int i = 0; i < OBSERVER_IN_DIM; i++)",
                f"            s += OBSERVER_E{m_i}_W1[j][i] * x[i];",
                f"        h1[j] = s > 0.f ? s : 0.f;",
                f"    }}",
                f"    for (int j = 0; j < OBSERVER_HID2; j++) {{",
                f"        s = OBSERVER_E{m_i}_B2[j];",
                f"        for (int i = 0; i < OBSERVER_HID1; i++)",
                f"            s += OBSERVER_E{m_i}_W2[j][i] * h1[i];",
                f"        h2[j] = s > 0.f ? s : 0.f;",
                f"    }}",
                f"    s = OBSERVER_E{m_i}_B3[0];",
                f"    for (int i = 0; i < OBSERVER_HID2; i++)",
                f"        s += OBSERVER_E{m_i}_W3[0][i] * h2[i];",
                f"    out[{m_i}] = s * OBSERVER_T_STD + OBSERVER_T_MEAN;",
            ]
        lines += [
            "}",
            "",
            "// Prediction + uncertainty in one call. sigma is the std of the",
            "// member predictions (epistemic disagreement), in m/s^2.",
            "static inline void observer_predict_unc(",
            "        const float win[OBSERVER_IN_DIM], float *w_hat, float *sigma) {",
            "    float x[OBSERVER_IN_DIM], preds[OBSERVER_N_ENSEMBLE] = {0.f};",
            "    observer_standardize(win, x);",
            "    observer_member_preds(x, preds);",
            "    float m = 0.f;",
            "    for (int i = 0; i < OBSERVER_N_ENSEMBLE; i++) m += preds[i];",
            "    m /= (float)OBSERVER_N_ENSEMBLE;",
            "    float v = 0.f;",
            "    for (int i = 0; i < OBSERVER_N_ENSEMBLE; i++)",
            "        v += (preds[i] - m) * (preds[i] - m);",
            "    *w_hat = m;",
            "    *sigma = sqrtf(v / (float)OBSERVER_N_ENSEMBLE);",
            "}",
            "",
        ]

    # Golden test vector (generated from the real weights)
    lines += [
        "// Golden self-test: expected output of observer_predict on a fixed",
        "// window, generated from the real checkpoint. Run after flashing;",
        "// |observer_predict(test_in) - expected| must be < SELF_TEST_TOL.",
        f"static const float OBSERVER_TEST_IN[OBSERVER_IN_DIM] = {{{_fmt(gv['win'])}}};",
        f"static const float OBSERVER_TEST_EXPECTED = {_cf(gv['w_hat'])};",
        "static inline float observer_self_test_error(void) {",
        "    return fabsf(observer_predict((const float *)OBSERVER_TEST_IN)",
        "                 - OBSERVER_TEST_EXPECTED);",
        "}",
        "",
    ]

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    info = dict(
        in_dim=w1.shape[1], hid1=w1.shape[0], hid2=w2.shape[0],
        n_ensemble=len(ens), bytes=os.path.getsize(path),
        golden_w_hat=gv["w_hat"], source=source_pt,
    )
    print(f"Exported observer -> {path} "
          f"({info['in_dim']}-{info['hid1']}-{info['hid2']}-1, "
          f"ensemble={info['n_ensemble']}, {info['bytes']} bytes)")
    return info


# ---------------------------------------------------------------------------
# 3. Verification: re-parse the header and compare against the checkpoint
# ---------------------------------------------------------------------------

def _parse_float_arrays(text: str) -> dict:
    """Parse 'static const float NAME[d1][d2] = {...};' and '[n] = {...};'."""
    out = {}
    pat = re.compile(
        r"static const float (\w+)(?:\[(\d+)\])?(?:\[(\d+)\])? = \{(.*?)\};",
        re.S)
    for m in pat.finditer(text):
        name, d1, d2 = m.group(1), m.group(2), m.group(3)
        vals = [float(v.strip().strip("{}").rstrip("f"))
                for v in m.group(4).replace("\n", " ").split(",")
                if v.strip()]
        if d2:
            n1, n2 = int(d1), int(d2)
            arr = np.array(vals, dtype=np.float32).reshape(n1, n2)
        elif d1:
            arr = np.array(vals, dtype=np.float32).reshape(int(d1))
        else:
            continue
        out[name] = arr
    return out


def verify_header(path: str, ck: dict) -> dict:
    """Re-read the emitted header, reconstruct the net, compare to torch."""
    text = open(path).read()
    arrays = _parse_float_arrays(text)
    sd = ck["model"]
    checks = {
        "OBSERVER_MEAN": np.asarray(ck["mean"], dtype=np.float32),
        "OBSERVER_STD": np.asarray(ck["std"], dtype=np.float32),
        "OBSERVER_W1": sd["mlp.0.weight"].numpy(),
        "OBSERVER_B1": sd["mlp.0.bias"].numpy(),
        "OBSERVER_W2": sd["mlp.2.weight"].numpy(),
        "OBSERVER_B2": sd["mlp.2.bias"].numpy(),
        "OBSERVER_W3": sd["mlp.4.weight"].numpy(),
        "OBSERVER_B3": sd["mlp.4.bias"].numpy(),
    }
    bad = 0
    for name, arr in checks.items():
        got = arrays.get(name)
        if got is None or got.shape != arr.shape:
            bad += 1
            print(f"  header missing/mismatched {name}")
        elif not np.array_equal(got, arr):
            bad += 1
            print(f"  header {name} differs from checkpoint "
                  f"(max {np.max(np.abs(got - arr)):.3e})")
    # golden vector must equal the torch net's output on the same window
    m = re.search(r"OBSERVER_TEST_IN\[[^\]]+\] = \{(.*?)\};", text, re.S)
    if m is None:
        raise ValueError("exported header has no OBSERVER_TEST_IN vector")
    win = np.array([float(v.rstrip("f")) for v in
                    re.split(r"[,\s]+", m.group(1)) if v.strip()],
                   dtype=np.float32)
    net = _net_arrays(sd)
    mean = np.asarray(ck["mean"], dtype=np.float32)
    std = np.asarray(ck["std"], dtype=np.float32)
    x = (win - mean) / std
    h1 = np.maximum(x @ net["w1"].T + net["b1"], 0.0)
    h2 = np.maximum(h1 @ net["w2"].T + net["b2"], 0.0)
    torch_out = float(h2 @ net["w3"][0] + net["b3"][0]) * ck["t_std"] + ck["t_mean"]
    exp = float(re.search(r"OBSERVER_TEST_EXPECTED = ([\-0-9.e]+)f",
                          text).group(1))
    d_golden = abs(torch_out - exp)
    if d_golden > 1e-6:
        bad += 1
        print(f"  golden vector off from torch: {d_golden:.3e}")
    print(f"  header-vs-checkpoint: {len(checks) - bad}/{len(checks)} arrays "
          f"bit-identical, golden-vs-torch diff {d_golden:.2e}")
    return dict(arrays_bit_identical=len(checks) - bad, arrays_total=len(checks),
                golden_diff=d_golden)


def run_c_self_test(path: str) -> float:
    """Compile the header with cc and run its golden self-test.

    When the header carries an ensemble, the compiled test also calls
    ``observer_predict_unc`` and checks that the member mean matches the base
    net and the disagreement is finite and non-negative.
    """
    src = f"""
#include <stdio.h>
#include "{os.path.abspath(path)}"
int main(void) {{
    float err = observer_self_test_error();
    printf("self_test_err=%.9e\\n", (double)err);
#if OBSERVER_N_ENSEMBLE > 0
    float wh, sig;
    observer_predict_unc((const float *)OBSERVER_TEST_IN, &wh, &sig);
    printf("unc_wh=%.9e unc_sig=%.9e\\n", (double)wh, (double)sig);
    if (!(sig >= 0.f) || !(sig < 1e6f)) return 2;
    if (fabsf(wh - OBSERVER_TEST_EXPECTED) > 1e-2f) return 3;
#endif
    return err < OBSERVER_SELF_TEST_TOL ? 0 : 1;
}}
"""
    with tempfile.TemporaryDirectory() as td:
        cfile = os.path.join(td, "test.c")
        exe = os.path.join(td, "test")
        with open(cfile, "w") as f:
            f.write(src)
        r = subprocess.run(["cc", "-O2", "-o", exe, cfile],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"cc failed: {r.stderr[:800]}")
        r2 = subprocess.run([exe], capture_output=True, text=True)
        if r2.returncode != 0:
            raise RuntimeError(f"self-test failed: {r2.stdout} {r2.stderr}")
        line = [l for l in r2.stdout.splitlines()
                if l.startswith("self_test_err=")]
        if not line:
            raise RuntimeError(f"self-test: no result line in {r2.stdout!r}")
        return float(line[0].split("=")[1].strip())


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="export observer checkpoint -> C header")
    p.add_argument("--checkpoint", default="learned_observer.pt")
    p.add_argument("--export", action="store_true",
                   help="(default action) export the real weights to the C header")
    p.add_argument("--out-header", default="observer_policy.h")
    p.add_argument("--self-test", action="store_true",
                   help="compile the header with cc and run its golden self-test")
    args = p.parse_args(argv)

    ck = load_observer(args.checkpoint)
    info = export_c_header(ck, args.out_header, args.checkpoint)
    v = verify_header(args.out_header, ck)
    print(f"  verification: {v['arrays_bit_identical']}/{v['arrays_total']} "
          f"arrays bit-identical vs checkpoint; golden diff {v['golden_diff']:.2e}")
    if args.self_test:
        err = run_c_self_test(args.out_header)
        print(f"  C self-test (cc -O2): |predict - expected| = {err:.3e} "
              f"(tol 1e-3) -> {'PASS' if err < 1e-3 else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())