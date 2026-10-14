"""Model-contract schema (the 5 layers, operational).

A model contract binds each model input feature to a sensor source and states
exactly what the network expects: units, frame, representation, normalization.
Every field the checker needs is required — ambiguity blocks deployment.
"""
from __future__ import annotations

import json
import math


def _parse(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        try:
            import yaml  # type: ignore
            return yaml.safe_load(text)
        except Exception:
            from openflight.adapters.contracts import _parse_simple_yaml
            return _parse_simple_yaml(text)


def load_model_contract(path: str) -> dict:
    with open(path) as f:
        c = _parse(f.read())
    return validate_model_contract(c)


NORM_METHODS = ("affine", "none")


def validate_model_contract(c: dict) -> dict:
    if not isinstance(c, dict) or c.get("schema_version") != 2:
        raise ValueError("model contract needs schema_version: 2")
    m = c.get("model", {})
    if "input_size" not in m:
        raise ValueError("model contract needs model.input_size")
    raw = c.get("raw_layout")
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            "model contract needs raw_layout: the flat raw sensor vector as "
            "a list of {quantity, component} entries")
    for i, r in enumerate(raw):
        if not isinstance(r, dict) or "quantity" not in r or "component" not in r:
            raise ValueError(f"raw_layout[{i}] needs quantity + component")
    feats = c.get("features")
    if not isinstance(feats, list) or not feats:
        raise ValueError("model contract needs a non-empty features list")
    if sum(int(f.get("width", 1)) for f in feats if isinstance(f, dict)) != int(
            m["input_size"]):
        raise ValueError(
            "sum of feature widths must equal model.input_size")
    seen = set()
    for i, f in enumerate(feats):
        where = f"features[{i}]"
        for k in ("name", "source", "units", "normalization"):
            if k not in f:
                raise ValueError(f"{where} missing {k!r}")
        if f["name"] in seen:
            raise ValueError(f"duplicate feature name {f['name']!r}")
        seen.add(f["name"])
        src = f["source"]
        if not isinstance(src, dict) or "quantity" not in src:
            raise ValueError(f"{where}.source needs 'quantity'")
        width = int(f.get("width", 1))
        if width not in (1, 4):
            raise ValueError(f"{where}: width must be 1 or 4")
        if width == 1 and "component" not in src:
            raise ValueError(f"{where}.source needs 'component' for width 1")
        if width == 4 and f.get("representation") != "quaternion":
            raise ValueError(f"{where}: width 4 requires representation: "
                             "quaternion")
        # every feature element must resolve into raw_layout (checked fully
        # by the checker; here only the total width must fit input_size)
        norm = f["normalization"]
        if not isinstance(norm, dict) or norm.get("method") not in NORM_METHODS:
            raise ValueError(
                f"{where}.normalization needs method in {NORM_METHODS}")
        if norm["method"] == "affine":
            for k in ("scale", "offset"):
                if (k not in norm or not isinstance(norm[k], (int, float))
                        or isinstance(norm[k], bool)):
                    raise ValueError(
                        f"{where}.normalization affine needs numeric {k!r}")
                if not math.isfinite(norm[k]):
                    raise ValueError(
                        f"{where}.normalization affine {k} must be finite")
            if norm["scale"] == 0:
                raise ValueError(f"{where}.normalization scale must be nonzero")
        # quaternion features must declare ordering (Layer 1)
        if f.get("representation") == "quaternion" and "ordering" not in f:
            raise ValueError(
                f"{where}: quaternion feature must declare ordering")
        if "ordering" in f and f["ordering"] not in ("wxyz", "xyzw"):
            raise ValueError(f"{where}: bad ordering {f['ordering']!r}")
    return c
