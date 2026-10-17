"""First-divergence diagnosis: reference pipeline vs deployed implementation.

Answers, for one recorded input trace: where did the deployed behaviour
first diverge from the reference, what evidence identifies the stage, and
can the discrepancy be reproduced from a saved bundle?

Supported path (Amendment 2 scope, deliberately narrow):
    recorded raw inputs -> generated preprocessing adapter
        -> reference inference (PyTorch) vs deployed inference (C++)

The diagnosis establishes numerical agreement/disagreement of the recorded
pipelines on the recorded trace only. It does not establish physical
sensor calibration, simulator fidelity, or any safety property — the
"not established" disclaimer ships in every report.

Exit codes: 0 agree, 2 usage/invalid inputs, 3 harness compilation,
4 discrepancy reproduced.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import numpy as np

from openflight.errors import OpenFlightError

SCHEMA_VERSION = 1
STAGE_ORDER = ("preprocessing", "model", "end_to_end")

PREPROCESS_HARNESS = r"""
#include <cstdio>
#include "contract_adapt.h"
int main(int argc, char** argv) {
    const char* fin = argv[1]; const char* fout = argv[2];
    FILE* f = fopen(fin, "rb");
    if (!f) return 1;
    fseek(f, 0, SEEK_END); long bytes = ftell(f); fseek(f, 0, SEEK_SET);
    if (bytes <= 0 || bytes % (long)(sizeof(float) * CONTRACT_N_IN) != 0) return 2;
    long n = bytes / (long)(sizeof(float) * CONTRACT_N_IN);
    float* in = new float[(size_t)n * CONTRACT_N_IN];
    float* out = new float[(size_t)n * CONTRACT_N_OUT];
    if (fread(in, sizeof(float), (size_t)n * CONTRACT_N_IN, f)
            != (size_t)n * CONTRACT_N_IN) return 1;
    fclose(f);
    for (long k = 0; k < n; k++)
        contract_adapt(in + (size_t)k * CONTRACT_N_IN,
                       out + (size_t)k * CONTRACT_N_OUT);
    FILE* g = fopen(fout, "wb");
    if (!g) return 1;
    fwrite(out, sizeof(float), (size_t)n * CONTRACT_N_OUT, g);
    fclose(g);
    delete[] in; delete[] out;
    return 0;
}
"""

PREDICT_HARNESS = r"""
#include <cstdio>
#include "model.h"
int main(int argc, char** argv) {
    const char* fin = argv[1]; const char* fout = argv[2];
    FILE* f = fopen(fin, "rb");
    if (!f) return 1;
    fseek(f, 0, SEEK_END); long bytes = ftell(f); fseek(f, 0, SEEK_SET);
    if (bytes <= 0 || bytes % (long)(sizeof(float) * {IN}) != 0) return 2;
    long n = bytes / (long)(sizeof(float) * {IN});
    float* in = new float[(size_t)n * {IN}];
    float* out = new float[(size_t)n * {OUT}];
    if (fread(in, sizeof(float), (size_t)n * {IN}, f)
            != (size_t)n * {IN}) return 1;
    fclose(f);
    for (long k = 0; k < n; k++)
        openflight::predict(in + (size_t)k * {IN}, out + (size_t)k * {OUT});
    FILE* g = fopen(fout, "wb");
    if (!g) return 1;
    fwrite(out, sizeof(float), (size_t)n * {OUT}, g);
    fclose(g);
    delete[] in; delete[] out;
    return 0;
}
"""

NOT_ESTABLISHED = (
    "This comparison does not independently verify the physical sensor's "
    "calibration, the simulator's fidelity, or any safety property; it "
    "establishes numerical agreement of the recorded pipelines on the "
    "recorded trace under the stated tolerances only."
)

REPRODUCE_PY = '''#!/usr/bin/env python3
"""Reproduce the recorded OpenFlight diagnosis.

Default: self-check — re-derives the recorded first divergence from the
bundled arrays and verifies bundle integrity.  --full additionally re-runs
the full diagnosis from the original artifacts (requires the openflight
package and the original files, unchanged, to still exist).
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE_ORDER = ("preprocessing", "model", "end_to_end")
STAGE_ARRAYS = {
    "preprocessing": ("model_inputs", "model_inputs"),
    "model": ("model_outputs_pytorch", "model_outputs_on_reference"),
    "end_to_end": ("outputs", "outputs"),
}
REQUIRED_REPORT_KEYS = ("schema_version", "status", "tolerances",
                        "first_divergence", "stages")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _feature_name(rep, stage, col):
    if stage == "preprocessing":
        names = rep.get("feature_names")
        if names and col < len(names):
            return names[col]
        return f"feature[{col}]"
    return f"output[{col}]"


def reconstruct(rep):
    """Independently recompute the first divergence from the saved stage
    arrays, searching stages in order with the recorded tolerances."""
    tol = rep["tolerances"]
    rtol, atol = float(tol["rtol"]), float(tol["atol"])
    refz = np.load(os.path.join(HERE, "reference_values.npz"))
    depz = np.load(os.path.join(HERE, "deployed_values.npz"))
    for stage in STAGE_ORDER:
        refk, depk = STAGE_ARRAYS[stage]
        if refk not in refz.files or depk not in depz.files:
            raise RuntimeError(f"saved evidence missing for stage {stage}")
        a = np.asarray(refz[refk], dtype=np.float64)
        b = np.asarray(depz[depk], dtype=np.float64)
        if a.shape != b.shape:
            raise RuntimeError(
                f"stage {stage}: saved shapes differ {a.shape} vs {b.shape}")
        bound = atol + rtol * np.abs(a)
        bad = ~np.isfinite(a) | ~np.isfinite(b) | (np.abs(a - b) > bound)
        rows, cols = np.nonzero(bad)
        if rows.size:
            r, c = int(rows[0]), int(cols[0])
            return {"stage": stage, "row": r, "col": c,
                    "feature": _feature_name(rep, stage, c),
                    "reference": _num(a[r, c]), "deployed": _num(b[r, c])}
    return None


def _stage_statuses(rep):
    """Independently recompute each stage's agree/diverge status from the
    saved arrays (stage order, recorded tolerances)."""
    tol = rep["tolerances"]
    rtol, atol = float(tol["rtol"]), float(tol["atol"])
    refz = np.load(os.path.join(HERE, "reference_values.npz"))
    depz = np.load(os.path.join(HERE, "deployed_values.npz"))
    out = {}
    for stage in STAGE_ORDER:
        refk, depk = STAGE_ARRAYS[stage]
        if refk not in refz.files or depk not in depz.files:
            raise RuntimeError(f"saved evidence missing for stage {stage}")
        a = np.asarray(refz[refk], dtype=np.float64)
        b = np.asarray(depz[depk], dtype=np.float64)
        if a.shape != b.shape:
            raise RuntimeError(
                f"stage {stage}: saved shapes differ {a.shape} vs {b.shape}")
        bound = atol + rtol * np.abs(a)
        bad = ~np.isfinite(a) | ~np.isfinite(b) | (np.abs(a - b) > bound)
        out[stage] = "diverge" if bool(bad.any()) else "agree"
    return out


DUP_FIELDS = ("schema_version", "created_at", "openflight_version",
              "tolerances", "inputs", "shapes")


def self_check():
    with open(os.path.join(HERE, "report.json")) as f:
        rep = json.load(f)
    man_p = os.path.join(HERE, "artifact_manifest.json")
    if not os.path.exists(man_p):
        print("FAIL: artifact_manifest.json missing")
        return 1
    with open(man_p) as f:
        man = json.load(f)
    for k in REQUIRED_REPORT_KEYS:
        if k not in rep:
            print(f"FAIL: report is missing field '{k}'")
            return 1
    for name, want in (rep.get("bundle_shas") or {}).items():
        p = os.path.join(HERE, name)
        if not os.path.exists(p):
            print(f"FAIL: bundle member missing: {name}")
            return 1
        if sha(p) != want:
            print(f"FAIL: bundle member hash mismatch: {name}")
            return 1
    # the report duplicates several fields from the manifest; the manifest
    # is covered by the recorded hashes, so any disagreement means the
    # report no longer faithfully records the original experiment
    for k in DUP_FIELDS:
        if rep.get(k) != man.get(k):
            print(f"FAIL: report field '{k}' disagrees with the recorded "
                  f"manifest")
            return 1
    try:
        recon = reconstruct(rep)
        statuses = _stage_statuses(rep)
    except Exception as e:
        print(f"FAIL: cannot reconstruct from saved evidence: {e}")
        return 1
    recorded = {s["name"]: s["status"] for s in rep.get("stages", [])}
    for stage in STAGE_ORDER:
        if recorded.get(stage) != statuses[stage]:
            print(f"FAIL: recorded stage status for '{stage}' "
                  f"({recorded.get(stage)!r}) disagrees with the saved "
                  f"evidence ({statuses[stage]!r})")
            return 1
    if rep["status"] not in ("agree", "discrepancy"):
        print(f"FAIL: unsupported report status {rep['status']!r} "
              "(expected 'agree' or 'discrepancy')")
        return 1
    fd = rep.get("first_divergence")
    if rep["status"] == "agree":
        if recon is not None:
            print("FAIL: report claims agreement but saved evidence diverges "
                  f"at {recon['stage']} (sample {recon['row']}, "
                  f"element {recon['col']})")
            return 1
        print("recorded status: agree; saved evidence agrees "
              "(reconstruction found no divergence)")
        return 0
    if fd is None:
        print("FAIL: status is discrepancy but no first_divergence recorded")
        return 1
    if recon is None:
        print("FAIL: report claims a divergence but saved evidence agrees")
        return 1
    for k in ("stage", "row", "col", "feature"):
        if recon[k] != fd.get(k):
            print("FAIL: reconstructed first divergence differs from the "
                  f"recorded report ({k}: reconstructed={recon[k]!r}, "
                  f"recorded={fd.get(k)!r})")
            return 1
    if recon["reference"] != fd.get("reference") or \
            recon["deployed"] != fd.get("deployed"):
        print("FAIL: recorded cell values disagree with saved evidence "
              f"(reconstructed=({recon['reference']}, {recon['deployed']}), "
              f"recorded=({fd.get('reference')}, {fd.get('deployed')}))")
        return 1
    print(f"REPRODUCED: {recon['stage']} divergence at sample {recon['row']} "
          f"element {recon['col']} ({recon['feature']}): "
          f"reference={fd['reference']}, deployed={fd['deployed']}")
    return 0


def _verify_artifacts(inp):
    for key in ("model", "trace", "reference"):
        path = inp[key]["path"]
        if not os.path.exists(path):
            print(f"missing original artifact: {path}")
            return False
        if sha(path) != inp[key]["sha256"]:
            print(f"artifact changed since diagnosis: {path}")
            return False
    build = inp["build"]["path"]
    if not os.path.isdir(build):
        print(f"missing deployment directory: {build}")
        return False
    for rel, want in inp["build"].get("artifacts", {}).items():
        p = os.path.join(build, rel)
        if not os.path.exists(p):
            print(f"deployment artifact missing: {p}")
            return False
        if sha(p) != want:
            print(f"deployment artifact changed since diagnosis: {p}")
            return False
    return True


def _same_diagnosis(rep, rerun):
    if rep["status"] != rerun["status"]:
        return False
    a, b = rep.get("first_divergence"), rerun.get("first_divergence")
    if (a is None) != (b is None):
        return False
    if a is not None:
        for k in ("stage", "row", "col", "feature"):
            if a.get(k) != b.get(k):
                return False
        if a.get("reference") != b.get("reference") or \
                a.get("deployed") != b.get("deployed"):
            return False
    ra = {s["name"]: s["status"] for s in rep["stages"]}
    rb = {s["name"]: s["status"] for s in rerun["stages"]}
    return ra == rb


def full_rerun():
    with open(os.path.join(HERE, "report.json")) as f:
        rep = json.load(f)
    inp = rep["inputs"]
    if not _verify_artifacts(inp):
        return 1
    tol = rep["tolerances"]
    outdir = tempfile.mkdtemp(prefix="of_diagnose_rerun_")
    cmd = [sys.executable, "-m", "openflight.cli", "diagnose",
           "--model", inp["model"]["path"],
           "--trace", inp["trace"]["path"],
           "--reference", inp["reference"]["path"],
           "--build", inp["build"]["path"],
           "--output", outdir,
           "--rtol", repr(tol["rtol"]), "--atol", repr(tol["atol"])]
    rc = subprocess.run(cmd).returncode
    with open(os.path.join(outdir, "report.json")) as f:
        rerun = json.load(f)
    ok = _same_diagnosis(rep, rerun)
    a = rep.get("first_divergence") or {}
    b = rerun.get("first_divergence") or {}
    print(f"full re-run: recorded={rep['status']} rerun={rerun['status']} "
          f"-> {'MATCH' if ok else 'MISMATCH'} (exit {rc})")
    if not ok:
        print("  recorded first divergence: "
              f"{a.get('stage')}/{a.get('feature')} "
              f"(sample {a.get('row')}, element {a.get('col')})")
        print("  rerun    first divergence: "
              f"{b.get('stage')}/{b.get('feature')} "
              f"(sample {b.get('row')}, element {b.get('col')})")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--full", action="store_true",
                    help="also re-run the full diagnosis from original inputs")
    args = ap.parse_args()
    rc = self_check()
    if rc:
        return rc
    if args.full:
        return full_rerun()
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _num(x):
    """JSON-safe float: finite floats pass through, anything else -> None."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _err(code, what, where, why, action, exit_code=2):
    return OpenFlightError("diagnose", code, what, where=where, why=why,
                           action=action, exit_code=exit_code)


# ----------------------------------------------------------------- loaders

def load_trace(path: str) -> dict:
    if not os.path.exists(path):
        raise _err("E051", f"trace file not found: {path}", path,
                   "diagnose replays one recorded input trace.",
                   "Record raw inputs to an .npz with a 'raw' array "
                   "(N samples x n_raw elements) and pass it with --trace.")
    try:
        z = np.load(path)
        if "raw" not in z.files:
            raise ValueError(
                f"missing 'raw' key (found: {', '.join(z.files) or 'none'})")
        raw = np.asarray(z["raw"], dtype=np.float64)
    except OpenFlightError:
        raise
    except Exception as e:
        raise _err("E051", f"trace unreadable: {e}", path,
                   "diagnose needs a valid .npz recording.",
                   "Re-record the trace; expected np.savez with key 'raw'.")
    if raw.ndim == 1:
        raw = raw[None, :]
    if raw.ndim != 2 or raw.shape[0] == 0 or raw.shape[1] == 0:
        raise _err("E051", f"trace 'raw' must be a non-empty 2-D array "
                           f"(got shape {raw.shape})", path,
                   "One row per recorded sample, one column per raw input.",
                   "Re-record with raw.shape == (n_samples, n_raw).")
    if not np.isfinite(raw).all():
        bad = int(np.size(raw) - np.isfinite(raw).sum())
        raise _err("E051", f"trace contains {bad} non-finite value(s)", path,
                   "NaN/inf inputs cannot be replayed meaningfully.",
                   "Clean the recording before running diagnose.")
    return {"raw": raw}


def load_reference(path: str) -> dict:
    if not os.path.exists(path):
        raise _err("E052", f"reference file not found: {path}", path,
                   "diagnose compares against recorded reference values "
                   "from the training/evaluation pipeline.",
                   "Record 'model_inputs' (and optionally 'outputs') from "
                   "the reference pipeline to an .npz; pass via --reference.")
    try:
        z = np.load(path)
        if "model_inputs" not in z.files:
            raise ValueError(
                "missing 'model_inputs' key "
                f"(found: {', '.join(z.files) or 'none'})")
        mi = np.asarray(z["model_inputs"], dtype=np.float64)
        outputs = None
        if "outputs" in z.files:
            outputs = np.asarray(z["outputs"], dtype=np.float64)
    except OpenFlightError:
        raise
    except Exception as e:
        raise _err("E052", f"reference unreadable: {e}", path,
                   "diagnose needs the recorded reference values.",
                   "Re-record with keys 'model_inputs'[, 'outputs'].")
    if mi.ndim == 1:
        mi = mi[None, :]
    if mi.ndim != 2 or mi.shape[0] == 0:
        raise _err("E052",
                   f"'model_inputs' must be a non-empty 2-D array "
                   f"(got shape {mi.shape})", path,
                   "One row per sample, one column per model input.",
                   "Re-record the reference pipeline outputs.")
    if outputs is not None:
        if outputs.ndim == 1:
            outputs = outputs[None, :]
        if outputs.ndim != 2:
            raise _err("E052", f"'outputs' must be 2-D (got {outputs.shape})",
                       path, "One row per sample, one column per output.",
                       "Re-record the reference pipeline outputs.")
        if outputs.shape[0] != mi.shape[0]:
            raise _err("E052",
                       f"'outputs' has {outputs.shape[0]} samples but "
                       f"'model_inputs' has {mi.shape[0]}", path,
                       "Both arrays must describe the same recordings.",
                       "Re-record both arrays from one run.")
    if not np.isfinite(mi).all() or (
            outputs is not None and not np.isfinite(outputs).all()):
        raise _err("E052", "reference contains non-finite values", path,
                   "NaN/inf reference values make the comparison vacuous.",
                   "Re-record clean reference outputs.")
    return {"model_inputs": mi, "outputs": outputs}


def check_shapes(trace: dict, reference: dict) -> None:
    n_t = trace["raw"].shape[0]
    n_r = reference["model_inputs"].shape[0]
    if n_t != n_r:
        raise _err("E052",
                   f"trace has {n_t} samples but reference has {n_r}",
                   "trace/reference",
                   "The comparison pairs sample i of one with sample i of "
                   "the other; mismatched counts would compare unrelated "
                   "data.",
                   "Record trace and reference from the same run.")


# ------------------------------------------------------------ comparison

def first_divergence(stage: str, ref: np.ndarray, dep: np.ndarray,
                     rtol: float, atol: float,
                     features=None, derivations=None) -> dict | None:
    """Earliest (row-major) cell where |ref-dep| > atol + rtol*|ref|,
    or either side is non-finite (non-finite always diverges)."""
    ref = np.atleast_2d(np.asarray(ref, dtype=np.float64))
    dep = np.atleast_2d(np.asarray(dep, dtype=np.float64))
    if ref.shape != dep.shape:
        raise ValueError(f"stage {stage}: shape mismatch {ref.shape} vs "
                         f"{dep.shape}")
    tol = atol + rtol * np.abs(ref)
    bad = ~np.isfinite(ref) | ~np.isfinite(dep) | (np.abs(ref - dep) > tol)
    rows, cols = np.nonzero(bad)
    if rows.size == 0:
        return None
    r, c = int(rows[0]), int(cols[0])
    rv, dv = float(ref[r, c]), float(dep[r, c])
    if features and c < len(features):
        name = features[c]
    else:
        name = f"feature[{c}]"
    derivation = None
    if derivations and c < len(derivations):
        derivation = derivations[c]
    return {"stage": stage, "row": r, "col": c, "feature": name,
            "reference": _num(rv), "deployed": _num(dv),
            "abs_err": _num(abs(dv - rv)),
            "ratio": _num(dv / rv) if (np.isfinite(rv) and rv != 0.0) else None,
            "derivation": derivation}


def compare(stages: list[dict], rtol: float, atol: float) -> dict:
    """Run every stage comparison; first divergence = earliest stage.

    Each stage: {name, ref, dep, features?, derivations?}. Returns
    {"stages": [public stage reports with _failing_rows], ...}.
    """
    reports, first = [], None
    for st in stages:
        ref = np.atleast_2d(np.asarray(st["ref"], dtype=np.float64))
        dep = np.atleast_2d(np.asarray(st["dep"], dtype=np.float64))
        if ref.shape != dep.shape:
            raise ValueError(f"stage {st['name']}: shape mismatch "
                             f"{ref.shape} vs {dep.shape}")
        tol = atol + rtol * np.abs(ref)
        nonfinite = ~np.isfinite(ref) | ~np.isfinite(dep)
        bad = nonfinite | (np.abs(ref - dep) > tol)
        cells = int(bad.sum())
        rows = sorted({int(r) for r in np.nonzero(bad)[0]})
        finite_abs = np.abs(ref - dep)[np.isfinite(ref) & np.isfinite(dep)]
        max_abs = float(finite_abs.max()) if finite_abs.size else 0.0
        fd = first_divergence(st["name"], ref, dep, rtol, atol,
                              st.get("features"), st.get("derivations"))
        if fd is not None and first is None:
            first = fd
        reports.append({"name": st["name"],
                        "status": "diverge" if cells else "agree",
                        "shape": [int(ref.shape[0]), int(ref.shape[1])],
                        "max_abs_err": _num(max_abs),
                        "n_nonfinite": int(nonfinite.sum()),
                        "n_failing_cells": cells,
                        "n_failing_samples": len(rows),
                        "_failing_rows": rows})
    return {"stages": reports, "first_divergence": first}


# ------------------------------------------------- deployment-side runners

def _builddir_requirements(build: str) -> dict:
    if not os.path.isdir(build):
        raise _err("E053", f"deployment directory not found: {build}", build,
                   "diagnose reads a deployed implementation.",
                   "Run `openflight deploy --output <dir>` first and pass "
                   "that directory with --build.")
    meta_p = os.path.join(build, "model_metadata.json")
    for rel, why in (("model.h", "deployed inference header"),
                     ("model.cpp", "deployed inference source"),
                     ("model_metadata.json", "model input/output sizes"),
                     ("contract_adapt.h", "deployed preprocessing adapter")):
        if not os.path.exists(os.path.join(build, rel)):
            raise _err("E053",
                       f"not a validated deployment directory: missing {rel}",
                       os.path.join(build, rel), f"The {why} is required.",
                       "Run `openflight deploy --contract ... "
                       "--model-contract ... --output <dir>` to produce a "
                       "complete deployment, then pass it with --build.")
    try:
        meta = json.load(open(meta_p))
        in_w, out_w = int(meta["input_size"]), int(meta["output_size"])
    except Exception as e:
        raise _err("E053", f"model_metadata.json unreadable: {e}", meta_p,
                   "Sizes come from the deployment record.",
                   "Re-run deploy to regenerate the deployment directory.")
    header = open(os.path.join(build, "contract_adapt.h")).read()
    m_in = re.search(r"#define CONTRACT_N_IN (\d+)", header)
    m_out = re.search(r"#define CONTRACT_N_OUT (\d+)", header)
    if not m_in or not m_out:
        raise _err("E053", "contract_adapt.h lacks CONTRACT_N_IN/OUT defines",
                   os.path.join(build, "contract_adapt.h"),
                   "Generated preprocessing declares its widths.",
                   "Re-run deploy with contracts to regenerate the adapter.")
    c_in, c_out = int(m_in.group(1)), int(m_out.group(1))
    if c_out != in_w:
        raise _err("E053",
                   f"preprocessing outputs {c_out} values but the model "
                   f"expects {in_w}", os.path.join(build, "contract_adapt.h"),
                   "A mismatched adapter/model pairing would invalidate "
                   "every comparison.",
                   "Regenerate adapter and model from one deploy run.")
    return {"meta": meta, "in_w": in_w, "out_w": out_w,
            "c_in": c_in, "c_out": c_out}


def _compile_harness(build: str, source: str, extra_src: list[str],
                     work: str, name: str) -> str:
    hpath = os.path.join(work, f"{name}.cpp")
    with open(hpath, "w") as f:
        f.write(source)
    exe = os.path.join(work, name)
    cc = os.environ.get("CXX", "c++")
    cmd = [cc, "-O2", "-std=c++17", "-I", build, hpath, *extra_src,
           "-o", exe]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise _err("E054", f"diagnosis harness failed to compile: "
                           f"{r.stderr[:1500]}", build,
                   "The harness wraps the deployed implementation.",
                   "Check the deployed artifacts (openflight doctor; "
                   "re-run deploy).", exit_code=3)
    return exe


def _run_harness(exe: str, inputs: np.ndarray, width: int,
                 work: str, name: str) -> np.ndarray:
    fin = os.path.join(work, f"{name}.in.bin")
    fout = os.path.join(work, f"{name}.out.bin")
    inputs.astype(np.float32).tofile(fin)
    r = subprocess.run([exe, fin, fout], capture_output=True, text=True)
    if r.returncode != 0:
        raise _err("E054", f"diagnosis harness failed (exit "
                           f"{r.returncode}): {r.stderr[:800]}", exe,
                   "The deployed implementation must run on the recorded "
                   "inputs.",
                   "Inspect the deployment artifacts; re-run deploy if "
                   "needed.", exit_code=3)
    got = np.fromfile(fout, dtype=np.float32)
    n = inputs.shape[0]
    if got.size != n * width:
        raise _err("E053",
                   f"harness produced {got.size} values, expected "
                   f"{n * width}", exe,
                   "Width mismatch between trace/model and the deployed "
                   "code.",
                   "Regenerate the deployment from matching contracts "
                   "and model.")
    return got.reshape(n, width).astype(np.float64)


def run_preprocess(build: str, raw: np.ndarray, req: dict,
                   work: str) -> np.ndarray:
    if raw.shape[1] != req["c_in"]:
        raise _err("E051",
                   f"trace width {raw.shape[1]} does not match deployment "
                   f"raw width {req['c_in']}", build,
                   "The deployment's preprocessing consumes a fixed raw "
                   "vector layout.",
                   "Record the trace with the deployment's raw_layout "
                   "width, or diagnose the matching deployment.")
    exe = _compile_harness(build, PREPROCESS_HARNESS, [], work,
                           "of_preprocess")
    return _run_harness(exe, raw, req["c_out"], work, "of_preprocess")


def run_predict(build: str, inputs: np.ndarray, req: dict,
                work: str) -> np.ndarray:
    if inputs.shape[1] != req["in_w"]:
        raise _err("E057",
                   f"model-input width {inputs.shape[1]} != model "
                   f"input_size {req['in_w']}", build,
                   "Every inference stage must see the model's input "
                   "width.",
                   "Check that reference and deployment were generated "
                   "from the same model.")
    src = PREDICT_HARNESS.replace("{IN}", str(req["in_w"])).replace(
        "{OUT}", str(req["out_w"]))
    exe = _compile_harness(build, src, [os.path.join(build, "model.cpp")],
                           work, "of_predict")
    return _run_harness(exe, inputs, req["out_w"], work, "of_predict")


def pytorch_reference(weights: str, inputs: np.ndarray) -> np.ndarray:
    import torch
    from openflight.compiler import loader
    try:
        model, _meta = loader.load_model(None, weights)
    except ValueError as e:
        raise _err("E011", f"cannot load reference model: {e}", weights,
                   "diagnose replays the trained reference implementation.",
                   "Pass the trained weights (.pt) used for the "
                   "recording; see inspect for supported formats.")
    model.eval()
    try:
        with torch.no_grad():
            out = model(torch.from_numpy(inputs.astype(np.float32)))
    except RuntimeError as e:
        raise _err("E057",
                   f"reference model rejected the reference inputs: {e}",
                   weights,
                   "The reference weights must consume the recorded "
                   "model_inputs.",
                   "Check that --model and --reference come from the same "
                   "model.")
    out = out.numpy() if hasattr(out, "numpy") else np.asarray(out)
    if out.ndim == 1:
        out = out[:, None]
    return out.astype(np.float64)


# -------------------------------------------------------- names, bundles

def load_feature_names(build: str) -> tuple[list[str] | None,
                                            list[str] | None, str | None]:
    """Feature names + derivations for the preprocessing stage, best-effort."""
    man_p = os.path.join(build, "contract_manifest.json")
    if not os.path.exists(man_p):
        return None, None, "no contract manifest; features reported by index"
    try:
        man = json.load(open(man_p))
        from openflight.adapters import contracts as C
        from openflight.contract import model_contract as MC
        from openflight.contract import pipeline as PL
        sensor = C.load_contract(man["sensor_contract"])
        model = MC.load_model_contract(man["model_contract"])
        ops = PL.build_ops(sensor, model)
        return ([op["feature"] for op in ops],
                [op.get("derivation") for op in ops], None)
    except Exception as e:
        return None, None, f"contracts unavailable ({e}); features by index"


def _bundle_members() -> list[str]:
    return ["failing_inputs.npz", "reference_values.npz",
            "deployed_values.npz", "artifact_manifest.json", "summary.md",
            "reproduce.py"]


def _write_bundle(outdir: str, report: dict, failing_rows: list[int],
                  arrays: dict) -> None:
    idx = np.asarray(failing_rows, dtype=int)
    np.savez(os.path.join(outdir, "failing_inputs.npz"),
             raw=arrays["raw"][idx], sample_index=idx)
    # full stage arrays: the self-check independently reconstructs the first
    # divergence from these in stage order, so they must not be subset
    np.savez(os.path.join(outdir, "reference_values.npz"),
             model_inputs=arrays["ref_model_inputs"],
             outputs=arrays["ref_outputs"],
             model_outputs_pytorch=arrays["pytorch_on_ref"])
    np.savez(os.path.join(outdir, "deployed_values.npz"),
             model_inputs=arrays["dep_model_inputs"],
             outputs=arrays["dep_outputs"],
             model_outputs_on_reference=arrays["cpp_on_ref"])
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": report["created_at"],
        "openflight_version": report["openflight_version"],
        "inputs": report["inputs"],
        "shapes": report["shapes"],
        "tolerances": report["tolerances"],
        "failing_samples": failing_rows,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    with open(os.path.join(outdir, "artifact_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, allow_nan=False)
    with open(os.path.join(outdir, "reproduce.py"), "w") as f:
        f.write(REPRODUCE_PY)
    with open(os.path.join(outdir, "summary.md"), "w") as f:
        f.write(render_summary(report))
    report["bundle_shas"] = {
        name: _sha(os.path.join(outdir, name))
        for name in ("failing_inputs.npz", "reference_values.npz",
                     "deployed_values.npz", "artifact_manifest.json")}


# ------------------------------------------------------------ presentation

def render_summary(report: dict) -> str:
    lines = ["# OPENFLIGHT DIAGNOSIS", ""]
    if report["status"] == "agree":
        lines += [f"Status: AGREES — no divergence beyond "
                  f"rtol={report['tolerances']['rtol']:g} / "
                  f"atol={report['tolerances']['atol']:g} on "
                  f"{report['shapes']['n_samples']} recorded sample(s).", ""]
        lines += ["## Stages compared", ""]
        for s in report["stages"]:
            lines.append(
                f"- **{s['name']}**: agree, max |ref-dep| = "
                f"{s['max_abs_err']:.3e} ({s['shape'][0]}x{s['shape'][1]})")
        lines += ["", "The same recorded inputs are available for "
                      "re-verification (`reproduce.py`).", ""]
    else:
        fd = report["first_divergence"]
        lines += ["Status: DISCREPANCY REPRODUCED", "",
                  "## First divergence", "",
                  f"- Stage: **{fd['stage']}**",
                  f"- Feature: **{fd['feature']}** "
                  f"(sample {fd['row']}, element {fd['col']})",
                  f"- Reference value:  **{fd['reference']}**",
                  f"- Deployed value:   **{fd['deployed']}**"]
        if fd.get("ratio") is not None:
            lines.append(f"- Ratio (deployed/reference): "
                         f"**{fd['ratio']:.6g}**")
        if fd.get("derivation"):
            lines += ["", "## Why this stage", "",
                      f"Reference transformation: `{fd['derivation']}`"]
        lines += ["", "## All stages", ""]
        for s in report["stages"]:
            mark = "OK" if s["status"] == "agree" else "DIVERGED"
            lines.append(f"- {s['name']}: **{mark}** "
                         f"(max |ref-dep| = {s['max_abs_err']:.3e}, "
                         f"{s['n_failing_cells']} failing cell(s) in "
                         f"{s['n_failing_samples']} sample(s))")
        lines += ["", "## Evidence", ""]
        for key in ("model", "trace", "reference"):
            item = report["inputs"][key]
            lines.append(f"- {key}: `{item['path']}` "
                         f"sha256 {item['sha256'][:16]}…")
        for name, sha in sorted(report.get("bundle_shas", {}).items()):
            lines.append(f"- bundle `{name}` sha256 {sha[:16]}…")
        lines += ["", "## Next step",
                  "",
                  "Inspect the reference transformation for the feature "
                  "above, correct it (or the deployed generation), then "
                  "re-run the SAME command: `post_fix_comparison.json` "
                  "records whether the discrepancy resolved.", "",
                  "Another person can verify this finding now: "
                  "`python reproduce.py` (self-check) or "
                  "`python reproduce.py --full` (full re-run).", ""]
    lines += ["## Not established", "", NOT_ESTABLISHED, ""]
    return "\n".join(lines)


# ----------------------------------------------------------- orchestration

def run(a) -> int:
    """Execute one diagnosis. `a` exposes model/trace/reference/build/
    output/rtol/atol. Returns 0 (agree) or 4 (discrepancy)."""
    build = a.build
    outdir = a.output.rstrip("/")
    req = _builddir_requirements(build)
    if not os.path.exists(a.model):
        raise _err("E010", f"model file not found: {a.model}", a.model,
                   "diagnose replays the trained reference implementation.",
                   "Pass the trained weights used for the recording.")
    trace = load_trace(a.trace)
    reference = load_reference(a.reference)
    check_shapes(trace, reference)
    raw = trace["raw"]
    ref_mi = reference["model_inputs"]
    if ref_mi.shape[1] != req["c_out"]:
        raise _err("E052",
                   f"reference model_inputs width {ref_mi.shape[1]} != "
                   f"deployment model-input width {req['c_out']}",
                   a.reference,
                   "The reference recording must describe the model's "
                   "inputs.",
                   "Record model_inputs from the pipeline that feeds "
                   "this model.")
    features, derivations, names_note = load_feature_names(build)

    work = tempfile.mkdtemp(prefix="of_diagnose_")
    dep_mi = run_preprocess(build, raw, req, work)
    pytorch_on_ref = pytorch_reference(a.model, ref_mi)
    ref_outputs = (reference["outputs"] if reference["outputs"] is not None
                   else pytorch_on_ref)
    if ref_outputs.shape[1] != req["out_w"]:
        raise _err("E052",
                   f"reference outputs width {ref_outputs.shape[1]} != "
                   f"model output_size {req['out_w']}", a.reference,
                   "Reference outputs must come from this model.",
                   "Record outputs from the same model, or omit 'outputs' "
                   "to use the in-process reference.")
    cpp_on_ref = run_predict(build, ref_mi, req, work)
    dep_outputs = run_predict(build, dep_mi, req, work)

    out_models = [f"output[{j}]" for j in range(req["out_w"])]
    cmp = compare([
        {"name": "preprocessing", "ref": ref_mi, "dep": dep_mi,
         "features": features, "derivations": derivations},
        {"name": "model", "ref": pytorch_on_ref, "dep": cpp_on_ref,
         "features": out_models},
        {"name": "end_to_end", "ref": ref_outputs, "dep": dep_outputs,
         "features": out_models},
    ], rtol=a.rtol, atol=a.atol)

    # first_divergence() already returns JSON-safe (_num) values
    fd = cmp["first_divergence"]
    status = "discrepancy" if fd else "agree"
    if fd is not None:
        fd = dict(fd)

    prev = None
    prev_p = os.path.join(outdir, "report.json")
    if os.path.exists(prev_p):
        try:
            prev = json.load(open(prev_p))
        except Exception:
            prev = None

    inputs = {
        "model": {"path": os.path.abspath(a.model),
                  "sha256": _sha(a.model)},
        "trace": {"path": os.path.abspath(a.trace),
                  "sha256": _sha(a.trace)},
        "reference": {"path": os.path.abspath(a.reference),
                      "sha256": _sha(a.reference)},
        "build": {"path": os.path.abspath(build),
                  "artifacts": {
                      rel: _sha(os.path.join(build, rel))
                      for rel in sorted(os.listdir(build))
                      if os.path.isfile(os.path.join(build, rel))}},
    }
    try:
        from openflight import __version__ as of_version
    except Exception:
        of_version = "unknown"
    report = {
        "schema_version": SCHEMA_VERSION,
        "command": "openflight diagnose",
        "created_at": _now(),
        "openflight_version": of_version,
        "status": status,
        "tolerances": {"rtol": a.rtol, "atol": a.atol,
                       "rule": "|ref-dep| <= atol + rtol*|ref|; "
                               "non-finite always diverges"},
        "inputs": inputs,
        "shapes": {"n_samples": int(raw.shape[0]),
                   "n_raw": int(raw.shape[1]),
                   "n_preprocessed": int(dep_mi.shape[1]),
                   "n_outputs": int(dep_outputs.shape[1])},
        "feature_names": features,
        "feature_names_note": names_note,
        "stages": [{k: v for k, v in s.items() if not k.startswith("_")}
                   for s in cmp["stages"]],
        "first_divergence": fd,
        "bundle_shas": {},
        "not_established": [NOT_ESTABLISHED],
    }

    os.makedirs(outdir, exist_ok=True)
    if status == "discrepancy":
        failing_rows: list[int] = []
        for s in cmp["stages"]:
            failing_rows.extend(s["_failing_rows"])
        failing_rows = sorted(set(failing_rows))
        _write_bundle(outdir, report, failing_rows, {
            "raw": raw, "ref_model_inputs": ref_mi, "ref_outputs": ref_outputs,
            "pytorch_on_ref": pytorch_on_ref, "dep_model_inputs": dep_mi,
            "dep_outputs": dep_outputs, "cpp_on_ref": cpp_on_ref})
    else:
        # a bundle belongs to the current report; stale members from a
        # previous failing run must not outlive a passing one
        for name in _bundle_members():
            p = os.path.join(outdir, name)
            if os.path.exists(p):
                os.remove(p)
        report["bundle_shas"] = {}

    if prev is not None:
        post = {
            "schema_version": SCHEMA_VERSION,
            "created_at": _now(),
            "previous": {"status": prev.get("status"),
                         "created_at": prev.get("created_at"),
                         "first_divergence": prev.get("first_divergence")},
            "current": {"status": status, "created_at": report["created_at"],
                        "first_divergence": fd},
            "resolved": (prev.get("status") == "discrepancy"
                         and status == "agree"),
            "regression": (prev.get("status") == "agree"
                           and status == "discrepancy"),
        }
        with open(os.path.join(outdir, "post_fix_comparison.json"),
                  "w") as f:
            json.dump(post, f, indent=2, allow_nan=False)

    with open(prev_p, "w") as f:
        json.dump(report, f, indent=2, allow_nan=False)
    summary = render_summary(report)
    with open(os.path.join(outdir, "summary.md"), "w") as f:
        f.write(summary)
    print(summary)
    if status == "discrepancy":
        print(f"Bundle written to {outdir}/ "
              f"(reproduce with: python {outdir}/reproduce.py)")
        return 4
    return 0
