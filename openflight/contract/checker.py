"""Compatibility checker: sensor contract vs model contract.

Never silently repairs. Convertible units and quaternion reorderings are
recorded as *generated* operations (well-defined math); everything ambiguous
blocks deployment with a field-identifying error code.
"""
from __future__ import annotations

import math

from openflight.contract import units as U

# quantity -> path inside the sensor contract
QUANTITY_PATHS = {
    "position": ("state", "position"),
    "velocity": ("state", "velocity"),
    "orientation": ("state", "orientation"),
    "angular_velocity": ("state", "angular_velocity"),
    "acceleration": ("imu", "accelerometer"),
    "accelerometer": ("imu", "accelerometer"),
    "gyro": ("imu", "gyroscope"),
    "gyroscope": ("imu", "gyroscope"),
    # actuator state: the control actually applied, after actuator lag and
    # saturation (a command, u_cmd, is a different signal)
    "applied_control_acceleration": ("actuator", "applied_control_acceleration"),
}


def _sensor_field(sensor: dict, quantity: str) -> dict | None:
    path = QUANTITY_PATHS.get(quantity)
    if path is None:
        return None
    node = sensor
    for k in path:
        if not isinstance(node, dict) or k not in node:
            return None
        node = node[k]
    return node if isinstance(node, dict) else None


def check(sensor: dict, model: dict,
          model_input_size: int | None = None) -> dict:
    # fail closed on library misuse: an empty or malformed contract pair
    # must block with E002, never pass vacuously (the CLI validator
    # rejects these before calling; direct importers must be safe too)
    malformed = []
    for label, c in (("sensor", sensor), ("model", model)):
        if not isinstance(c, dict):
            malformed.append(f"{label} contract is not a mapping")
            continue
        feats = c.get("features")
        if label == "model":
            # the model contract must declare a non-empty feature list
            if not isinstance(feats, list) or not feats:
                malformed.append("model contract features must be a "
                                 "non-empty list")
            elif not all(isinstance(f, dict) for f in feats):
                malformed.append("model contract features must be mappings")
        elif feats is not None and (
                not isinstance(feats, list)
                or not all(isinstance(f, dict) for f in feats)):
            # sensor contracts normally have no features key; if present
            # it must still be well-formed
            malformed.append("sensor contract features must be a list of "
                             "mappings")
    if malformed:
        from openflight.errors import CODE_ACTIONS
        return {
            "status": "blocked",
            "checks": {"representation": "FAIL", "units": "FAIL",
                       "frames": "FAIL", "features": "FAIL",
                       "normalization": "FAIL"},
            "errors": [{"code": "E002", "feature": "<contract>",
                        "reason": "; ".join(malformed),
                        "action": CODE_ACTIONS.get(
                            "E002",
                            "Provide two well-formed contracts with a "
                            "non-empty features list.")}],
            "warnings": [], "conversions": [],
        }

    errors: list[dict] = []
    warnings: list[dict] = []
    conversions: list[dict] = []
    checks = {"representation": "PASS", "units": "PASS", "frames": "PASS",
              "features": "PASS", "normalization": "PASS"}

    def fail(section: str, code: str, feature: str, reason: str,
             source=None, target=None):
        from openflight.errors import CODE_ACTIONS
        checks[section] = "FAIL"
        e = {"code": code, "feature": feature, "reason": reason,
             "action": CODE_ACTIONS.get(code, "See openflight diagnostics "
                                        "documentation.")}
        if source is not None:
            e["source"] = source
        if target is not None:
            e["target"] = target
        errors.append(e)

    feats = model.get("features", [])

    def _width_of(f):
        w = f.get("width", 1)
        if isinstance(w, bool) or not isinstance(w, int) or w < 1:
            return None
        return w

    malformed_width = [(f.get("name", "?"), f.get("width", 1))
                       for f in feats if isinstance(f, dict)
                       and _width_of(f) is None]
    if malformed_width:
        n0, v0 = malformed_width[0]
        fail("features", "E207",
             ", ".join(str(n) for n, _ in malformed_width),
             f"feature width must be a positive integer; {n0!r} declares "
             f"{v0!r} and the contract cannot be checked",
             source=v0, target=None)
    width_sum = sum(w for f in feats if isinstance(f, dict)
                    for w in [_width_of(f)] if w is not None)
    if (not malformed_width and model_input_size is not None
            and width_sum != model_input_size):
        fail("features", "E203", "<model>",
             f"contract feature widths sum to {width_sum} but compiled model "
             f"takes {model_input_size} inputs",
             source=width_sum, target=model_input_size)
    # duplicate (quantity, component, sample_offset_steps) bindings are
    # ambiguous: fail closed instead of letting dict indexing silently drop
    # the first entry. The temporal offset is part of the identity — the same
    # signal at two points in a window is two distinct raw inputs.
    def _off(d):
        o = d.get("sample_offset_steps", 0)
        return o if isinstance(o, int) and not isinstance(o, bool) else 0

    raw_keys = [(r.get("quantity"), r.get("component"), _off(r))
                for r in model.get("raw_layout", []) if isinstance(r, dict)]
    seen_keys, dup_keys = set(), []
    for k in raw_keys:
        if k in seen_keys and k not in dup_keys:
            dup_keys.append(k)
        seen_keys.add(k)
    if dup_keys:
        fail("features", "E206", "<model>",
             "duplicate raw_layout binding(s): "
             + ", ".join(f"{q!r}/{c!r}@{o}" for q, c, o in dup_keys)
             + "; each (quantity, component, sample_offset_steps) triple may "
             "appear at most once, or feature ordering is ambiguous",
             source=dup_keys[0], target=None)
    raw_index = {k: i for i, k in enumerate(raw_keys)}

    for f in feats:
        name = f.get("name", "?")
        qty = (f.get("source") or {}).get("quantity")
        sens = _sensor_field(sensor, qty) if qty else None
        if sens is None:
            fail("features", "E401", name,
                 f"source quantity {qty!r} not described by the sensor "
                 f"contract; refusing to guess the mapping",
                 source=qty, target=None)
            continue
        # --- raw vector binding (feature ordering) ---
        width = _width_of(f)
        if width is None:
            continue  # malformed width already recorded as E207
        if width == 1:
            src = f.get("source") or {}
            key = (qty, src.get("component"), _off(src))
            if key not in raw_index:
                fail("features", "E402", name,
                     f"source {key} not present in raw_layout; feature order "
                     f"cannot be established", source=key, target=None)
                continue
        else:
            sorder_declared = sens.get("ordering")
            sorder = sorder_declared or "wxyz"
            comps = list(sorder) if sorder in ("wxyz", "xyzw") else None
            if comps is None or any((qty, k, 0) not in raw_index for k in comps):
                fail("features", "E402", name,
                     f"quaternion source entries for {qty!r} not fully "
                     f"present in raw_layout", source=qty, target=None)
                continue
            # sensor ordering is load-bearing: the order of this quantity's
            # components in raw_layout must equal the declared ordering.
            # A contradiction means the labels and the declaration cannot
            # both be right — generated math would be unverifiable (E403).
            # Undocumented sensor ordering is handled later as U102.
            if sorder_declared is not None:
                seq = [r.get("component")
                       for r in model.get("raw_layout", [])
                       if isinstance(r, dict) and r.get("quantity") == qty]
                if seq != comps:
                    fail("representation", "E403", name,
                         f"raw_layout lists {qty!r} components in order "
                         f"{seq} but the sensor contract declares ordering "
                         f"{sorder_declared!r}; the quaternion labels cannot "
                         "both be right",
                         source=seq, target=sorder_declared)
                    continue
        # --- units (Layer 2; quaternions carry no physical units) ---
        su, mu = sens.get("units"), f.get("units")
        is_quat = f.get("representation") == "quaternion"
        if is_quat:
            if mu is None:
                # quaternion magnitude is dimensionless by definition;
                # default loudly (W204) rather than block on a missing key
                mu = "dimensionless"
                warnings.append({"code": "W204", "feature": name,
                                 "reason": "quaternion feature declares no "
                                           "units; defaulting to "
                                           "dimensionless"})
            elif mu != "dimensionless":
                warnings.append({"code": "W203", "feature": name,
                                 "reason": f"quaternion feature units {mu!r} "
                                           "should be 'dimensionless'; "
                                           "quaternions carry no physical "
                                           "units"})
        elif mu is None:
            # every non-quat feature needs a units key — the pipeline reads it
            fail("units", "E202", name,
                 "model feature declares no units", source=su, target=mu)
        elif su is None:
            fail("units", "U101", name,
                 "sensor side declares no units for this quantity; "
                 "cannot verify compatibility", source=su, target=mu)
        elif U.dimension(su) is None or U.dimension(mu) is None:
            # a unit string unknown to the registry is not a unit: two
            # sides matching on the same unknown token agree only with
            # themselves, so equality must not count as compatibility
            # (registry membership gates BEFORE the equality shortcut)
            token = su if U.dimension(su) is None else mu
            side = "sensor" if U.dimension(su) is None else "model"
            fail("units", "U101", name,
                 f"{side} units {token!r} are not a registered unit string; "
                 "equality between unknown tokens does not establish "
                 "compatibility",
                 source=su, target=mu)
        elif su == mu:
            pass
        else:
            try:
                a = U.conversion(su, mu)
                conversions.append({"feature": name, "kind": "unit_scale",
                                    "source_units": su, "target_units": mu,
                                    "factor": a})
            except KeyError as e:
                fail("units", "U101", name,
                     f"unknown unit ({e}); cannot verify compatibility",
                     source=su, target=mu)
            except ValueError:
                fail("units", "E101", name,
                     "source and target units have incompatible dimensions "
                     "and no conversion is declared",
                     source=su, target=mu)
        # --- unit plausibility vs quantity (both sides can be wrong together)
        if not is_quat:
            for side, u in (("sensor", su), ("model", mu)):
                if u is not None and U.plausible_for_quantity(u, qty) is False:
                    allowed = sorted(U.QUANTITY_DIMENSION.get(qty, set()))
                    fail("units", "E102", name,
                         f"{side} units {u!r} have dimension "
                         f"{U.dimension(u)!r}, implausible for quantity "
                         f"{qty!r} (allowed dimensions: {allowed})",
                         source=su, target=mu)
                    break
        # --- representation / ordering (Layer 1) ---
        if f.get("representation") == "quaternion":
            so, mo = sens.get("ordering"), f.get("ordering")
            if mo is None:
                fail("representation", "E204", name,
                     "quaternion feature must declare ordering", source=so,
                     target=mo)
            elif so is None:
                fail("representation", "U102", name,
                     "sensor quaternion ordering undocumented; cannot verify",
                     source=so, target=mo)
            elif so != mo:
                conversions.append({"feature": name, "kind": "quat_reorder",
                                    "source_ordering": so,
                                    "target_ordering": mo})
        # --- frames (Layer 3) ---
        # Reserved ambiguous words are never valid frame names: they exist in
        # the wild as sloppy declarations of "don't know" and must be
        # diagnosed as such (E303), not compared as if they were frames.
        _AMBIGUOUS_FRAMES = {"none", "any", "invariant", "unknown", "null",
                             "n/a", ""}
        sf, mf = sens.get("frame"), f.get("frame")
        sf_bad = (sf is not None and
                  (not isinstance(sf, str) or
                   str(sf).lower() in _AMBIGUOUS_FRAMES or
                   sf == "independent"))  # sentinel is model-side only
        mf_bad = (mf is not None and
                  (not isinstance(mf, str) or
                   str(mf).lower() in _AMBIGUOUS_FRAMES))
        if sf_bad or mf_bad:
            side = "sensor" if sf_bad else "model"
            val = sf if sf_bad else mf
            fail("frames", "E303", name,
                 f"{side} frame value {val!r} is not a frame name; use a "
                 "concrete frame (body/world/...), 'independent' on the "
                 "model side for frame-irrelevance, or omit the field to "
                 "block as unverifiable",
                 source=sf, target=mf)
        elif mf == "independent":
            # explicit model-side declaration of frame-irrelevance; the
            # only value that skips frame verification by design
            pass
        elif mf is not None and sf is None:
            fail("frames", "U301", name,
                 "model requires frame "
                 f"{mf!r} but the sensor contract documents no frame; "
                 "cannot verify", source=sf, target=mf)
        elif mf is not None and sf is not None and sf != mf:
            fail("frames", "E301", name,
                 f"frame mismatch ({sf!r} vs {mf!r}) with no valid "
                 "transformation declared; refusing to guess the rotation",
                 source=sf, target=mf)
        elif mf is None and sf is not None:
            # a model that declares no frame cannot be verified against a
            # sensor that documents one — unverifiable, never a silent pass
            fail("frames", "U302", name,
                 f"sensor documents frame {sf!r} for {qty!r} but the model "
                 "feature declares no frame; cannot verify compatibility",
                 source=sf, target=mf)
        # --- normalization (Layer 5) ---
        norm = f.get("normalization") or {}

        def _finite_number(v) -> bool:
            return (isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v))

        if norm.get("method") == "affine":
            s_val, o_val = norm.get("scale"), norm.get("offset")
            if not _finite_number(s_val) or not _finite_number(o_val):
                fail("normalization", "E201", name,
                     "affine normalization needs numeric finite 'scale' and "
                     "'offset'",
                     source=norm.get("scale"), target=norm.get("offset"))
            elif s_val == 0:
                fail("normalization", "E205", name,
                     "affine normalization scale is zero; the transform is "
                     "not invertible and would collapse the feature",
                     source=s_val, target=o_val)
            else:
                conversions.append({"feature": name, "kind": "normalize_affine",
                                    "scale": s_val, "offset": o_val})
        elif norm.get("method") == "none":
            warnings.append({"code": "W202", "feature": name,
                             "reason": "raw passthrough: model consumes "
                                       "un-normalized values; confirm the "
                                       "training pipeline did the same"})
        else:
            fail("normalization", "E201", name,
                 "normalization not fully specified (need method affine|none "
                 "with numeric scale/offset for affine)")
        # --- bias ---
        if f.get("bias_required") and "bias" not in sens:
            fail("normalization", "E302", name,
                 "model requires calibrated bias but the sensor contract "
                 "provides no bias configuration")
        elif "bias" not in sens:
            warnings.append({"code": "W201", "feature": name,
                             "reason": "sensor bias not modeled for this "
                                       "quantity; estimates assume zero bias"})

    blocked = any(v == "FAIL" for v in checks.values())
    return {"schema_version": 1, "status": "blocked" if blocked else "pass",
            "checks": checks, "errors": errors, "warnings": warnings,
            "conversions": conversions,
            "deployment": "blocked" if blocked else "proceed"}


def render_text(report: dict) -> str:
    lines = ["", "OPENFLIGHT CONTRACT VALIDATION", ""]
    checks = report.get("checks", {})
    for k in ("representation", "units", "frames", "features",
              "normalization"):
        lines.append(f"{k.capitalize() + ' checks:':<24}{checks.get(k, 'N/A')}")
    if report.get("warnings"):
        lines += ["", "Warnings:"]
        for w in report["warnings"]:
            lines.append(f"{w['code']}: [{w['feature']}] {w['reason']}")
    if report.get("errors"):
        lines += ["", "Errors:"]
        for e in report["errors"]:
            lines.append(f"{e['code']}: [{e['feature']}] {e['reason']}")
            if "source" in e or "target" in e:
                lines.append(f"      Source: {e.get('source')}")
                lines.append(f"      Target: {e.get('target')}")
            if e.get("action"):
                lines.append(f"      Action: {e['action']}")
    if report.get("conversions"):
        if report.get("deployment") == "proceed":
            lines += ["",
                      "Generated conversions (verified by differential test):"]
        else:
            # A blocked deployment generated nothing; presenting these as
            # verified would misstate which transformations are approved.
            lines += ["",
                      "Planned conversions (NOT applied - deployment "
                      "blocked):"]
        for c in report["conversions"]:
            lines.append(f"  [{c['feature']}] {c['kind']}: " +
                         ", ".join(f"{k}={v}" for k, v in c.items()
                                   if k not in ("feature", "kind")))
    lines += ["", f"Deployment status: {report.get('deployment', 'blocked').upper()}", ""]
    return "\n".join(lines)
