"""Transform pipeline: per-feature op chain compiled to Python + C++.

Scalar element math (unit conversion then affine normalization):
    y = ((x * A) * S) + O = x * (A*S) + O
Quaternion features: 4 raw entries permuted from sensor ordering to model
ordering, then the same element math. Combined constants are emitted with a
derivation comment so the generated code is auditable.
"""
from __future__ import annotations

import json
import math
import os

from openflight.contract import units as U

ORDER_COMPS = {"wxyz": ["w", "x", "y", "z"], "xyzw": ["x", "y", "z", "w"]}


def _offset(binding: dict) -> int:
    """Temporal position of a raw/feature binding (sample_offset_steps).

    Absent means 0 (the current sample). Malformed values were already
    rejected by the schema validator; defaulting here keeps the checker and
    pipeline consistent when called directly.
    """
    o = binding.get("sample_offset_steps", 0)
    return o if isinstance(o, int) and not isinstance(o, bool) else 0


def _sensor_units(sensor: dict, qty: str) -> str | None:
    from openflight.contract.checker import _sensor_field
    node = _sensor_field(sensor, qty)
    return (node or {}).get("units")


def _sensor_ordering(sensor: dict, qty: str) -> str:
    from openflight.contract.checker import _sensor_field
    node = _sensor_field(sensor, qty)
    return (node or {}).get("ordering", "wxyz")


def build_ops(sensor: dict, model: dict) -> list[dict]:
    """One op per model-input element. Requires a passing checker report
    (call check() first); raises a diagnosed ValueError (never a bare
    KeyError) on anything unresolvable."""
    raw_index = {(r["quantity"], r["component"], _offset(r)): i
                 for i, r in enumerate(model.get("raw_layout", []))}
    ops: list[dict] = []
    for f in model["features"]:
        qty = f["source"]["quantity"]
        width = int(f.get("width", 1))
        su = _sensor_units(sensor, qty)
        mu = f.get("units")
        if f.get("representation") == "quaternion":
            a = 1.0  # quaternions carry no physical units (checker skips too)
            # missing units key is defaulted to dimensionless by the checker
            # (W204); the value is unused here either way
        else:
            if mu is None:
                raise ValueError(
                    f"[{f['name']}] feature declares no units; the checker "
                    "should have blocked this (E202)")
            try:
                a = 1.0 if su == mu else U.conversion(su, mu)
            except (KeyError, ValueError) as e:
                raise ValueError(
                    f"[{f['name']}] cannot build unit conversion: {e}") from e
        norm = f.get("normalization") or {}
        if norm.get("method") == "affine":
            s = norm.get("scale")
            o = norm.get("offset")
            ok = (isinstance(s, (int, float)) and not isinstance(s, bool)
                  and isinstance(o, (int, float)) and not isinstance(o, bool)
                  and math.isfinite(s) and math.isfinite(o) and s != 0)
            if not ok:
                raise ValueError(
                    f"[{f['name']}] affine normalization needs numeric "
                    f"finite nonzero scale and offset (got scale={s!r} "
                    f"offset={o!r}); the checker should have blocked this")
            s, o = float(s), float(o)
        else:
            s, o = 1.0, 0.0
        gain, off = a * s, o
        if width == 1:
            key = (qty, f["source"]["component"], _offset(f["source"]))
            if key not in raw_index:
                raise ValueError(f"[{f['name']}] source {key} not in raw_layout")
            ops.append({"feature": f["name"], "raw": raw_index[key],
                        "gain": gain, "offset": off,
                        "derivation": f"({su}->{mu} A={a}) then affine S={s} O={o}"})
        else:
            so, mo = _sensor_ordering(sensor, qty), f["ordering"]
            mcomps = ORDER_COMPS[mo]
            # The checker (E403) has verified that raw_layout's component
            # order for this quantity equals the sensor's declared ordering,
            # so sourcing each model component by name implements the
            # permutation; the raw indices below ARE the reorder.
            idx = []
            for mc in mcomps:
                rk = (qty, mc, _offset(f["source"]))
                if rk not in raw_index:
                    raise ValueError(
                        f"[{f['name']}] quaternion entry {rk} not in raw_layout")
                idx.append(raw_index[rk])
            for k, mc in enumerate(mcomps):
                ops.append({"feature": f"{f['name']}.{mc}", "raw": idx[k],
                            "gain": gain, "offset": off,
                            "derivation": f"quat {so}->{mo}: "
                                          f"out[{k}]({mc}) <- raw[{idx[k]}]; "
                                          f"then affine S={s} O={o}"})
    return ops


def _cf(v: float) -> str:
    s = f"{float(v):.9g}"
    if "e" not in s and "E" not in s and "." not in s:
        s += ".0"
    return s + "f"


def generate(sensor: dict, model: dict, py_out: str, cpp_out: str) -> dict:
    ops = build_ops(sensor, model)
    n_in = len(model["raw_layout"])
    n_out = len(ops)
    py = ['"""Auto-generated feature pipeline. Do not edit."""',
          "import numpy as np",
          f"N_IN = {n_in}", f"N_OUT = {n_out}", "",
          "def adapt(raw):",
          "    raw = np.asarray(raw, dtype=float)",
          "    out = np.empty(N_OUT)",
          ]
    for i, op in enumerate(ops):
        py.append(f"    out[{i}] = raw[{op['raw']}] * {op['gain']!r} + {op['offset']!r}  "
                  f"# {op['feature']}: {op['derivation']}")
    py += ["    return out", ""]
    cpp = ["#pragma once", "// Auto-generated feature pipeline. Do not edit.",
           "// float32: expect ~1e-7 agreement with the float64 Python above.",
           f"#define CONTRACT_N_IN {n_in}", f"#define CONTRACT_N_OUT {n_out}",
           "static inline void contract_adapt(const float* raw, float* out) {"]
    for i, op in enumerate(ops):
        cpp.append(f"    out[{i}] = raw[{op['raw']}] * {_cf(op['gain'])} + "
                   f"{_cf(op['offset'])};  // {op['feature']}")
    cpp += ["}", ""]
    os.makedirs(os.path.dirname(py_out) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(cpp_out) or ".", exist_ok=True)
    with open(py_out, "w") as f:
        f.write("\n".join(py))
    with open(cpp_out, "w") as f:
        f.write("\n".join(cpp) + "\n")
    return {"py": py_out, "cpp": cpp_out, "ops": ops,
            "n_in": n_in, "n_out": n_out}


def write_manifest(sensor_path: str, model_path: str, outdir: str,
                   extra: dict | None = None) -> dict:
    def sha(p: str) -> str:
        import hashlib as H
        h = H.sha256()
        with open(p, "rb") as f:
            h.update(f.read())
        return h.hexdigest()
    man = {"schema_version": 1, "sensor_contract": sensor_path,
           "sensor_sha": sha(sensor_path), "model_contract": model_path,
           "model_sha": sha(model_path), **(extra or {})}
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "contract_manifest.json"), "w") as f:
        json.dump(man, f, indent=2)
    return man


def check_stale(outdir: str) -> list[str]:
    """Detect contract changes after code generation. Returns problems ([]) = fresh."""
    mp = os.path.join(outdir, "contract_manifest.json")
    if not os.path.exists(mp):
        return ["no contract_manifest.json; provenance unknown"]
    man = json.load(open(mp))
    problems = []
    for key, path_key in (("sensor_sha", "sensor_contract"),
                          ("model_sha", "model_contract")):
        p = man.get(path_key)
        if not p or not os.path.exists(p):
            problems.append(f"{path_key} {p!r} missing; cannot verify freshness")
            continue
        import hashlib as H
        h = H.sha256()
        with open(p, "rb") as f:
            h.update(f.read())
        if h.hexdigest() != man.get(key):
            problems.append(
                f"{path_key} changed since code generation "
                f"(recorded {man.get(key, '')[:12]}, now {h.hexdigest()[:12]})")
    return problems
