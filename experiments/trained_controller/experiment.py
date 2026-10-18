"""Trained-controller deployment-fault localisation experiment.

Deploys a genuinely trained controller (``learned_observer.pt``, an MLP
60->128->64->1 trained by ``learned_observer.py``) through OpenFlight's real
deployment pipeline, then introduces realistic deployment faults and asks two
things of the *same* evidence:

  * does ``openflight diagnose`` localise the fault to the correct stage?
  * how does it compare with a hand-written staged comparison (the baseline a
    researcher would script from the deployed artifacts)?

The 60 inputs are the observer's real features: a 20-sample window, newest
sample first, of measured acceleration ``a_meas``, applied control
acceleration ``u_act`` (actuator state, not the command), and velocity ``v``;
each feature is standardised with the checkpoint's mean/std. The contract
declares the temporal offsets and the actuator quantity, so the deployed
adapter reproduces the training-time input pipeline rather than an invented
one.

Everything here is SIMULATED host-side evidence. It is not physical-robot
validation and says nothing about on-hardware behaviour.

Usage:
    python experiments/trained_controller/experiment.py
    python experiments/trained_controller/experiment.py --n-samples 32
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "examples" / "quadrotor_adapter"
MODEL = "learned_observer.pt"
ARCH = "mlp:60,128,64,1"
# The observer consumes a W-sample window of three signals, newest sample
# first: measured acceleration, applied control acceleration, velocity.
W = 20
SIGNAL_BLOCKS = (
    ("a_meas", "acceleration", "metres_per_second_squared", None),
    ("u_act", "applied_control_acceleration",
     "metres_per_second_squared", "world"),
    ("v", "velocity", "metres_per_second", "world"),
)
N_IN = W * len(SIGNAL_BLOCKS)
N_OUT = 1
RTOL = ATOL = 1e-4
SEED = 7
PY = sys.executable

LABEL = "SIMULATED (host-side deployment evidence; not physical-robot validation)"


# ------------------------------------------------------------- contracts

def checkpoint_meta():
    """The training-time standardisation constants, stored in the checkpoint.

    Single source of truth for what the network expects: each input feature is
    standardised as (x - mean)/std, and the target is stored de-standardised as
    y*t_std + t_mean (``learned_observer.py``).
    """
    import torch
    obj = torch.load(REPO / MODEL, map_location="cpu", weights_only=True)
    return {"mean": np.asarray(obj["mean"], dtype=np.float64),
            "std": np.asarray(obj["std"], dtype=np.float64),
            "t_mean": float(obj["t_mean"]), "t_std": float(obj["t_std"]),
            "W": int(obj["W"]), "H": int(obj["H"])}


def sensor_contract(acc_units="metres_per_second_squared",
                    control_units="metres_per_second_squared",
                    velocity_units="metres_per_second"):
    sensor = yaml.safe_load((EXAMPLES / "drone_contract.yaml").read_text())
    sensor["imu"]["accelerometer"]["units"] = acc_units
    sensor["state"]["velocity"]["units"] = velocity_units
    # the control signal is actuator state, not an accelerometer reading
    sensor["actuator"] = {"applied_control_acceleration": {
        "units": control_units, "frame": "world",
        "provenance": "simulator_state",
        "semantics": "actual actuator contribution to horizontal "
                     "acceleration after lag/saturation (not the command)"}}
    return sensor


def model_contract(meta, swap_offsets=False):
    mean, std = meta["mean"], meta["std"]
    raw = [{"quantity": qty, "component": "x", "sample_offset_steps": i}
           for _name, qty, _units, _frame in SIGNAL_BLOCKS for i in range(W)]
    feats = []
    j = 0
    for name, qty, units, frame in SIGNAL_BLOCKS:
        for i in range(W):
            feats.append({
                "name": f"{name}_t{i}",
                "source": {"quantity": qty, "component": "x",
                           "sample_offset_steps": i},
                "units": units, "frame": frame,
                "normalization": {"method": "affine",
                                  "scale": float(1.0 / std[j]),
                                  "offset": float(-mean[j] / std[j])}})
            j += 1
    if swap_offsets:
        # relabel raw slots t0/t1: each window sample claims the other's slot
        raw[0], raw[1] = raw[1], raw[0]
    return {"schema_version": 2,
            "model": {"name": "observer60", "input_size": N_IN,
                      "dtype": "float32"},
            "raw_layout": raw, "features": feats}


def _write_contracts(d, sensor, model):
    d.mkdir(parents=True, exist_ok=True)
    sp, mp = d / "sensor.yaml", d / "model.yaml"
    sp.write_text(yaml.safe_dump(sensor))
    mp.write_text(yaml.safe_dump(model))
    return sp, mp


# --------------------------------------------------------------- pipeline

def deploy(contract_dir, out):
    """Deploy through the supported CLI (contract gate -> codegen -> parity)."""
    sp, mp = contract_dir / "sensor.yaml", contract_dir / "model.yaml"
    r = subprocess.run(
        [PY, "-m", "openflight.cli", "deploy", "--model", MODEL,
         "--arch", ARCH, "--contract", str(sp), "--model-contract", str(mp),
         "--target", "host", "--output", str(out)],
        capture_output=True, text=True, cwd=str(REPO))
    if r.returncode != 0:
        raise RuntimeError(f"deploy failed for {out}:\n{r.stdout[-1500:]}\n"
                           f"{r.stderr[-1500:]}")
    return out


def torch_reference(model_inputs):
    """The trained network on the contract-standardised inputs.

    ``model_inputs`` are already ``(x - mean)/std`` (the contract applies the
    checkpoint's mean/std), so this is exactly the training-time evaluation.
    The output is the standardised ``w_hat``; de-standardising it
    (``y*t_std + t_mean``) is a caller-side step the codegen leaves open, so
    the diagnosis compares in the model's standardised output space.
    """
    import torch
    from openflight.cli import _arch_for_example
    from openflight.compiler.loader import load_model
    model, _meta = load_model(_arch_for_example(ARCH), MODEL)
    model.eval()
    with torch.no_grad():
        out = model(torch.from_numpy(model_inputs.astype(np.float32)))
    return out.numpy().astype(np.float64)


def record_reference(build, raw):
    """Record model_inputs (clean adapter) and outputs (trained model)."""
    spec = importlib.util.spec_from_file_location(
        "ref_adapter", build / "contract_adapt.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    model_inputs = np.stack([mod.adapt(r) for r in raw]).astype(np.float64)
    return model_inputs, torch_reference(model_inputs)


# ------------------------------------------------------- reference compute

def first_divergence(stage, ref, dep, feature_names=None):
    ref = np.atleast_2d(np.asarray(ref, dtype=np.float64))
    dep = np.atleast_2d(np.asarray(dep, dtype=np.float64))
    bad = (~np.isfinite(ref) | ~np.isfinite(dep) |
           (np.abs(ref - dep) > ATOL + RTOL * np.abs(ref)))
    rows, cols = np.nonzero(bad)
    if rows.size == 0:
        return None
    r, c = int(rows[0]), int(cols[0])
    name = (feature_names[c] if feature_names and c < len(feature_names)
            else f"feature[{c}]")
    return {"stage": stage, "row": r, "col": c, "feature": name,
            "reference": _json_num(ref[r, c]), "deployed": _json_num(dep[r, c]),
            "ratio": _json_num(dep[r, c] / ref[r, c])
            if (np.isfinite(ref[r, c]) and ref[r, c] != 0) else None}


def _json_num(x):
    v = float(x)
    return v if np.isfinite(v) else None


def _compile(build, source, name, work, extra=None):
    src = work / f"{name}.cpp"
    src.write_text(source)
    exe = work / name
    cmd = ["c++", "-O2", "-std=c++17", "-I", str(build), str(src),
           *(extra or []), "-o", str(exe)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"harness compile failed ({name}): {r.stderr[:800]}")
    return exe


ADAPT_DRIVER = """
#include <cstdio>
#include "contract_adapt.h"
int main() {
    float raw[CONTRACT_N_IN];
    while (true) {
        for (int i = 0; i < CONTRACT_N_IN; ++i)
            if (scanf("%f", &raw[i]) != 1) return 0;
        float a[CONTRACT_N_OUT];
        contract_adapt(raw, a);
        for (int i = 0; i < CONTRACT_N_OUT; ++i)
            printf("%.9g\\n", (double)a[i]);
    }
}
"""

PREDICT_DRIVER = """
#include <cstdio>
#include "model.h"
int main() {
    float x[openflight::INPUT_SIZE];
    while (true) {
        for (int i = 0; i < openflight::INPUT_SIZE; ++i)
            if (scanf("%f", &x[i]) != 1) return 0;
        float y[openflight::OUTPUT_SIZE];
        openflight::predict(x, y);
        for (std::size_t i = 0; i < openflight::OUTPUT_SIZE; ++i)
            printf("%.9g\\n", (double)y[i]);
    }
}
"""


def _run_io(exe, arr, width):
    inp = "\n".join(f"{float(v):.9g}" for v in np.asarray(arr).ravel())
    r = subprocess.run([str(exe)], input=inp, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"harness run failed: {r.stderr[:500]}")
    vals = np.array([float(v) for v in r.stdout.split()], dtype=np.float64)
    return vals.reshape(-1, width)


def manual_baseline(build, raw, reference, work):
    """A hand-written staged comparison a researcher would script.

    Same artifacts and same reference evidence as ``diagnose``; no bundle, no
    exit-code contract, no reproducibility guarantee. Returns the earliest
    diverging stage (or None) and the wall-clock seconds to compute it.
    """
    t0 = time.perf_counter()
    work.mkdir(parents=True, exist_ok=True)
    adapt = _compile(build, ADAPT_DRIVER, "b_adapt", work)
    predict = _compile(build, PREDICT_DRIVER, "b_predict", work,
                       extra=[str(build / "model.cpp")])
    ref_mi = reference["model_inputs"]
    ref_out = reference["outputs"]
    dep_mi = _run_io(adapt, raw, N_IN)
    torch_on_ref = torch_reference(ref_mi)
    cpp_on_ref = _run_io(predict, ref_mi, N_OUT)
    dep_out = _run_io(predict, dep_mi, N_OUT)
    stages = (("preprocessing", ref_mi, dep_mi),
              ("model", torch_on_ref, cpp_on_ref),
              ("end_to_end", ref_out, dep_out))
    verdict = None
    for name, ref, dep in stages:
        fd = first_divergence(name, ref, dep)
        if fd is not None:
            verdict = fd
            break
    return verdict, time.perf_counter() - t0


# ------------------------------------------------------------- diagnosis

def diagnose(build, trace, reference, out):
    t0 = time.perf_counter()
    r = subprocess.run(
        [PY, "-m", "openflight.cli", "diagnose", "--model", MODEL,
         "--trace", str(trace), "--reference", str(reference),
         "--build", str(build), "--output", str(out)],
        capture_output=True, text=True, cwd=str(REPO))
    seconds = time.perf_counter() - t0
    rp = out / "report.json"
    report = json.loads(rp.read_text()) if rp.exists() else {}
    return report, r.returncode, seconds


# ------------------------------------------------------------- fault set

def build_clean(work, meta):
    cdir = work / "c_clean"
    sp, mp = _write_contracts(cdir, sensor_contract(), model_contract(meta))
    return deploy(cdir, work / "build_clean")


def _deploy_variant(work, name, meta, sensor_kw=None, model_kw=None):
    cdir = work / f"c_{name}"
    sp, mp = _write_contracts(cdir, sensor_contract(**(sensor_kw or {})),
                              model_contract(meta, **(model_kw or {})))
    return deploy(cdir, work / f"build_{name}")


def build_acc_units(work, clean, meta):
    return _deploy_variant(
        work, "acc_units", meta,
        sensor_kw={"acc_units": "centimetres_per_second_squared"})


def build_control_units(work, clean, meta):
    return _deploy_variant(
        work, "control_units", meta,
        sensor_kw={"control_units": "centimetres_per_second_squared"})


def build_order_swap(work, clean, meta):
    return _deploy_variant(
        work, "order_swap", meta, model_kw={"swap_offsets": True})


def build_preproc_gain(work, clean, meta):
    b = work / "build_preproc_gain"
    shutil.copytree(clean, b)
    h = b / "contract_adapt.h"
    txt = h.read_text()
    m = re.search(r"(out\[0\] = raw\[\d+\] \*) ([0-9.eE+-]+)f", txt)
    new = float(m.group(2)) * 2.0
    h.write_text(re.sub(r"(out\[0\] = raw\[\d+\] \*) ([0-9.eE+-]+)f",
                        lambda mm: f"{mm.group(1)}{new!r}f", txt, count=1))
    return b


def build_compiled_infer(work, clean, meta):
    b = work / "build_compiled_infer"
    shutil.copytree(clean, b)
    src = b / "model.cpp"
    txt = src.read_text()
    old = ("    for (std::size_t i = 0; i < OUTPUT_SIZE; ++i) "
           "output[i] = dst[i];")
    new = ("    for (std::size_t i = 0; i < OUTPUT_SIZE; ++i) "
           "output[i] = dst[i] + (i == 0 ? 0.05f : 0.0f);")
    if txt.count(old) != 1:
        raise RuntimeError("could not locate the deployed output loop")
    src.write_text(txt.replace(old, new, 1))
    return b


# id -> (family, expected stage, builder)
FAULTS = {
    "acc_units": ("sensor units", "preprocessing", build_acc_units),
    "control_units": ("sensor units", "preprocessing", build_control_units),
    "order_swap": ("temporal ordering", "preprocessing", build_order_swap),
    "preproc_gain": ("preprocessing", "preprocessing", build_preproc_gain),
    "compiled_infer": ("compiled inference", "model", build_compiled_infer),
}


def _observer_module():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    import learned_observer as L
    return L


def _trace(work, n_samples, seed):
    """Raw deployment input: real windows from simulated trajectories.

    Each row is a W-sample window of [a_meas, u_act, v], newest sample first,
    exactly as ``learned_observer`` builds training features. Drawn from the
    same domain-randomised plant (mass, drag, actuator/sensor lag, wind)."""
    L = _observer_module()
    td = L.TRAIN_DOMAINS
    rng_master = np.random.default_rng(seed)
    cols, total = [], 0
    while total < n_samples:
        rng = np.random.default_rng(int(rng_master.integers(0, 2 ** 31)))
        mass = rng.uniform(*td["mass_kg"])
        cd_a = rng.uniform(*td["cd_a"])
        tau_rot = rng.uniform(*td["tau_rot_s"])
        tau_sens = rng.uniform(*td["tau_sens_s"])
        noise = rng.uniform(*td["noise_ms2"])
        v_steady = rng.uniform(*td["v_steady_ms"])
        kind = str(rng.choice(["step", "turb"]))
        kw = (dict(rise=float(rng.uniform(*td["gust_rise_s"])),
                   t_gust=float(rng.uniform(0.3, 0.8)))
              if kind == "step"
              else dict(tau_turb=float(rng.uniform(*td["turb_tau_s"])),
                        amp=float(rng.uniform(*td["turb_amp"]))))
        af = L.Airframe(mass_kg=mass, twr=5.0, cd_a=cd_a)
        t = np.arange(int(round(5.0 * L.LOOP_HZ))) / L.LOOP_HZ
        wind = L.wind_array(kind, t, v_steady, rng, **kw)
        r = L.rollout(af, tau_rot, tau_sens, 0.030, wind, "analytic",
                      noise_sigma=noise, rng=rng, collect=True)
        cols.append(r["X"].astype(np.float32))
        total += cols[-1].shape[0]
    raw = np.concatenate(cols, axis=0)[:n_samples]
    trace = work / "trace.npz"
    np.savez(trace, raw=raw)
    return raw, trace


def _equivalent_report(a, b):
    """Two diagnose reports are equivalent if the verdict and every stage
    status match (timestamps and recorded paths/shas naturally differ)."""
    if a.get("status") != b.get("status"):
        return False
    if a.get("first_divergence") != b.get("first_divergence"):
        return False
    sa = {s["name"]: s["status"] for s in a.get("stages", [])}
    sb = {s["name"]: s["status"] for s in b.get("stages", [])}
    return sa == sb


def run(out_dir=None, n_samples=200, case_ids=None, seed=SEED, verbose=True):
    case_ids = list(case_ids) if case_ids else (["clean"] + list(FAULTS))
    meta = checkpoint_meta()
    result = {"schema_version": 1, "label": LABEL, "model": MODEL,
              "arch": ARCH, "seed": seed, "n_samples": n_samples,
              "window": {"length": W, "signals": [b[0] for b in SIGNAL_BLOCKS],
                         "order": "newest-first"},
              "standardisation": {
                  "input": "per-feature (x-mean)/std from the checkpoint",
                  "output": "model output is standardised; the physical "
                            "estimate is y*t_std + t_mean (caller-side)",
                  "t_mean": round(meta["t_mean"], 6),
                  "t_std": round(meta["t_std"], 6)},
              "tolerances": {"rtol": RTOL, "atol": ATOL},
              "environment": {"python": platform.python_version(),
                              "platform": platform.platform()},
              "cases": [], "metrics": {}}

    tmp_ctx = tempfile.TemporaryDirectory(prefix="of_trained_")
    work = Path(tmp_ctx.name)
    try:
        clean = build_clean(work, meta)
        raw, trace = _trace(work, n_samples, seed)
        model_inputs, outputs = record_reference(clean, raw)
        reference_npz = work / "reference.npz"
        np.savez(reference_npz, model_inputs=model_inputs, outputs=outputs)
        reference = {"model_inputs": model_inputs, "outputs": outputs}

        builds = {"clean": clean}
        for cid in case_ids:
            if cid == "clean":
                continue
            builds[cid] = FAULTS[cid][2](work, clean, meta)

        for cid in case_ids:
            case = {"id": cid}
            if cid == "clean":
                case.update(family="control (no fault)", expected_stage=None)
            else:
                family, expected, _ = FAULTS[cid]
                case.update(family=family, expected_stage=expected)
            out = work / f"d_{cid}"
            rep, rc, secs = diagnose(builds[cid], trace, reference_npz, out)
            fd = rep.get("first_divergence") or {}
            case["diagnose"] = {"status": rep.get("status"),
                                "stage": fd.get("stage"),
                                "feature": fd.get("feature"),
                                "ratio": fd.get("ratio"),
                                "exit_code": rc, "seconds": round(secs, 3)}
            base, bsecs = manual_baseline(builds[cid], raw, reference,
                                          work / f"bw_{cid}")
            case["baseline"] = {"stage": (base or {}).get("stage"),
                                "feature": (base or {}).get("feature"),
                                "seconds": round(bsecs, 3)}
            if cid == "clean":
                pass
            else:
                exp = case["expected_stage"]
                case["correct"] = {
                    "diagnose": case["diagnose"]["stage"] == exp,
                    "baseline": case["baseline"]["stage"] == exp,
                }
            result["cases"].append(case)
            if verbose:
                print(f"[{cid}] diagnose={case['diagnose'].get('stage')} "
                      f"baseline={case['baseline'].get('stage')} "
                      f"expected={case.get('expected_stage')}")

        faults = [c for c in result["cases"] if c["id"] != "clean"]
        clean_case = next(c for c in result["cases"] if c["id"] == "clean")
        result["metrics"] = {
            "faults": len(faults),
            "localisation_accuracy": {
                "diagnose": sum(c["correct"]["diagnose"] for c in faults)
                / len(faults),
                "baseline": sum(c["correct"]["baseline"] for c in faults)
                / len(faults),
            },
            "false_diagnoses_on_clean": {
                "diagnose": int(clean_case["diagnose"]["status"]
                                == "discrepancy"),
                "baseline": int(clean_case["baseline"]["stage"] is not None),
            },
            "seconds_median": {
                "diagnose": _median([c["diagnose"]["seconds"] for c in
                                     result["cases"]]),
                "baseline": _median([c["baseline"]["seconds"] for c in
                                     result["cases"]]),
            },
            "time_note": ("wall-clock proxy only; excludes the engineer time "
                          "to write and maintain the baseline harness"),
        }

        first_fault = faults[0]["id"] if faults else None
        if first_fault is not None:
            r1, _, _ = diagnose(builds[first_fault], trace, reference_npz,
                                work / "rep_a")
            r2, _, _ = diagnose(builds[first_fault], trace, reference_npz,
                                work / "rep_b")
            result["metrics"]["reproducibility"] = {
                "case": first_fault,
                "second_run_equivalent": _equivalent_report(r1, r2),
            }
    finally:
        if out_dir is not None:
            _write_outputs(Path(out_dir), result)
        tmp_ctx.cleanup()
    return result


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    mid = n // 2
    return round(xs[mid] if n % 2 else (xs[mid - 1] + xs[mid]) / 2, 3)


def _write_outputs(out_dir, result):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(result, indent=2))
    (out_dir / "REPORT.md").write_text(render_report(result))


def render_report(r):
    m = r["metrics"]
    lines = [
        "# Trained-controller fault localisation (SIMULATED)",
        "",
        f"**{LABEL}**",
        "",
        f"- Model: `{r['model']}` ({r['arch']}), trained by `learned_observer.py`",
        f"- Input: {r['window']['length']}-sample window of "
        f"{', '.join(r['window']['signals'])} ({r['window']['order']}), "
        "standardised with the checkpoint mean/std",
        f"- Trace: {r['n_samples']} samples, tolerances rtol=atol={r['tolerances']['atol']}",
        f"- Environment: Python {r['environment']['python']}",
        "",
        "## Per-case result",
        "",
        "| case | family | expected | diagnose | baseline | diagnose correct |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for c in r["cases"]:
        corr = c.get("correct", {}).get("diagnose")
        corr = "" if corr is None else ("yes" if corr else "no")
        lines.append(
            f"| {c['id']} | {c.get('family','')} | "
            f"{c.get('expected_stage') or '(agree)'} | "
            f"{c['diagnose'].get('stage') or c['diagnose']['status']} | "
            f"{c['baseline'].get('stage') or '(agree)'} | {corr} |")
    lines += [
        "",
        "## Metrics",
        "",
        f"- Faults: {m['faults']}",
        f"- Localisation accuracy — diagnose: "
        f"**{m['localisation_accuracy']['diagnose']:.0%}**, "
        f"baseline: {m['localisation_accuracy']['baseline']:.0%}",
        f"- False diagnoses on the clean control — diagnose: "
        f"{m['false_diagnoses_on_clean']['diagnose']}, "
        f"baseline: {m['false_diagnoses_on_clean']['baseline']}",
        f"- Median wall-clock — diagnose: "
        f"{m['seconds_median']['diagnose']}s, baseline: "
        f"{m['seconds_median']['baseline']}s",
        f"- Reproducibility (diagnose run twice on "
        f"`{m.get('reproducibility', {}).get('case')}`): "
        f"{m.get('reproducibility', {}).get('second_run_equivalent')}",
        "",
        "## Limitations (stated, not hidden)",
        "",
        "- All evidence is **simulated host-side**. No hardware, no physical",
        "  controller, no on-MCU timing.",
        "- Inputs are real windows of `[a_meas, u_act, v]` from simulated",
        "  trajectories, standardised with the **checkpoint's** mean/std — the",
        "  same transform `learned_observer.py` trains with. `u_act` is a",
        "  simulator state; it is shown here because the simulator exposes it,",
        "  which does not establish it is directly measurable on a real drone.",
        "- Model outputs are compared **standardised**; the physical estimate is",
        "  `y*t_std + t_mean`, a caller-side de-normalisation the codegen leaves",
        "  open. A divergence in standardised output implies one in physical.",
        "- Wall-clock is a compute proxy, not a human time-to-resolution study;",
        "  it excludes the engineer time to build the baseline harness.",
        "- The reference is recorded from the clean adapter + the trained model;",
        "  faults are injected into the deployed side (contracts or artifacts).",
        "- One controller, one input distribution, one deployment target (host).",
    ]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n-samples", type=int, default=200)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent))
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    res = run(out_dir=args.out, n_samples=args.n_samples,
              case_ids=args.only, seed=args.seed)
    print(json.dumps(res["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
