"""Held-out challenge set (seed 777001) — kept separate from the regression set.

SCORING RULES (defined before evaluation, frozen with this file):
  valid_*      -> expect status "pass"            (false reject if blocked)
  invalid_*    -> expect status "blocked" + expected code naming the feature
                                                 (false accept if pass)
  ambiguous_*  -> expect status "blocked" with U-code (must never guess)
Metrics: false accepts, false rejects, ambiguous-blocked rate, detection rate
by fault category, diagnostic accuracy. Written to
results/heldout_challenge.json with seed + all cases. A subsample of valid
cases also runs full Python-vs-C++ pipeline parity.

The generator randomizes conversion factors, feature positions (shuffled raw
layouts), normalization parameters, and incomplete-metadata patterns — it does
not reuse the dev battery's hand-picked combinations.
"""
import json
import os
import random

import numpy as np

from openflight.contract import checker
from openflight.contract import pipeline as PL
from openflight.contract import units as U

SEED = 777001
REPORT = "results/heldout_challenge.json"

# dimension -> units available (sensor and model sides draw independently)
DIMS = {
    "angle": ["radians", "degrees"],
    "angular_velocity": ["radians_per_second", "degrees_per_second", "rpm"],
    "length": ["metres", "centimetres", "millimetres", "kilometres"],
    "velocity": ["metres_per_second", "kilometres_per_hour",
                 "centimetres_per_second"],
    "acceleration": ["metres_per_second_squared",
                     "centimetres_per_second_squared", "g"],
    "time": ["seconds", "milliseconds", "microseconds"],
}
# quantity -> dimension (subset of checker QUANTITY_PATHS with scalar comps)
QTY_DIM = {
    "position": "length",
    "velocity": "velocity",
    "angular_velocity": "angular_velocity",
    "acceleration": "acceleration",
}
QTY_PATH = {
    "position": ("state", "position"),
    "velocity": ("state", "velocity"),
    "angular_velocity": ("state", "angular_velocity"),
    "acceleration": ("imu", "accelerometer"),
}
FRAMES = ["body", "world", "sensor"]
SCALES = [0.01, 0.1, 0.5, 2.0, 10.0]
OFFSETS = [-1.5, 0.0, 0.25, 3.0]


def _sensor_entry(rng, qty, dim, frame="body"):
    return {"units": rng.choice(DIMS[dim]),
            **({"frame": frame} if qty != "acceleration" else {})}


def build_valid(rng):
    n = rng.randint(2, 6)
    qtys = [rng.choice(sorted(QTY_DIM)) for _ in range(n)]
    sensor = {"state": {}, "imu": {}}
    # sorted(set(...)), never bare set(): set iteration order is
    # hash-randomized per process (PYTHONHASHSEED), which would consume the
    # rng in a different order each run and break report reproducibility.
    for q in sorted(set(qtys)):
        node = sensor
        for k in QTY_PATH[q][:-1]:
            node = node.setdefault(k, {})
        node[QTY_PATH[q][-1]] = _sensor_entry(rng, q, QTY_DIM[q])
    feats, raw = [], []
    for i, q in enumerate(qtys):
        dim = QTY_DIM[q]
        mu = rng.choice(DIMS[dim])
        norm = ({"method": "affine", "scale": rng.choice(SCALES),
                 "offset": rng.choice(OFFSETS)}
                if rng.random() < 0.7 else {"method": "none"})
        comp = f"c{i}"
        f = {"name": f"f{i}", "source": {"quantity": q, "component": comp},
             "units": mu, "normalization": norm}
        if q != "acceleration":
            f["frame"] = sensor_field(sensor, q)["frame"]
        feats.append(f)
        raw.append({"quantity": q, "component": comp})
    rng.shuffle(raw)
    return sensor, {"raw_layout": raw, "features": feats}


def sensor_field(sensor, qty):
    node = sensor
    for k in QTY_PATH[qty]:
        node = node[k]
    return node


def run_case(category, fault, sensor, model, expect, expect_code=None):
    rep = checker.check(sensor, model)
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


def mutate_invalid(rng, sensor, model, kind=None):
    """Return (fault_name, expected_code, mutated_model, mutated_sensor).

    kind=None keeps the old draw-at-random behaviour; build_suite passes a
    deterministic kind from fault_cycle() so the report is reproducible."""
    if kind is None:
        kind = rng.choice(["dim_clash", "frame", "off_layout", "unknown_qty",
                           "bad_norm", "size", "euler", "swap_units"])
    m = json.loads(json.dumps(model))
    s = json.loads(json.dumps(sensor))
    f0 = m["features"][0]
    q0 = f0["source"]["quantity"]
    d0 = QTY_DIM[q0]
    if kind == "dim_clash":
        other = rng.choice([d for d in DIMS if d != d0])
        f0["units"] = rng.choice(DIMS[other])
        return "dimension clash", "E101", m, s
    if kind == "frame":
        if q0 == "acceleration":
            f0["frame"] = "body"  # sensor accel documents no frame
            return "frame required but undocumented", "U301", m, s
        cur = sensor_field(s, q0)["frame"]
        f0["frame"] = rng.choice([f for f in FRAMES if f != cur])
        return "frame mismatch", "E301", m, s
    if kind == "off_layout":
        f0["source"] = {"quantity": q0, "component": "ghost-component"}
        return "off-layout binding", "E402", m, s
    if kind == "unknown_qty":
        f0["source"] = {"quantity": "magnetometer", "component": "x"}
        return "unknown quantity", "E401", m, s
    if kind == "bad_norm":
        f0["normalization"] = {"method": "zscore"}
        return "bad normalization", "E201", m, s
    if kind == "size":
        return "size mismatch", "E203", m, s  # flagged via model_input_size
    if kind == "euler":
        # add quat feature while sensor orientation is euler-ordered
        s.setdefault("state", {})["orientation"] = {
            "representation": "euler", "ordering": "rpy"}
        m["features"].append(
            {"name": "q0", "source": {"quantity": "orientation"},
             "units": "dimensionless", "representation": "quaternion",
             "ordering": "wxyz", "normalization": {"method": "none"},
             "width": 4})
        m["raw_layout"].append({"quantity": "orientation", "component": "x"})
        return "euler vs quaternion", "E402", m, s
    # swap_units: steal another dimension's units for f0
    other = rng.choice([d for d in DIMS if d != d0])
    f0["units"] = rng.choice(DIMS[other])
    return "swapped units", "E101", m, s


def mutate_ambiguous(rng, sensor, model, kind=None):
    if kind is None:
        kind = rng.choice(["drop_units", "drop_frame", "drop_ordering",
                           "unknown_unit", "bias_required"])
    m = json.loads(json.dumps(model))
    s = json.loads(json.dumps(sensor))
    f0 = m["features"][0]
    q0 = f0["source"]["quantity"]
    if kind == "drop_units":
        sensor_field(s, q0).pop("units", None)
        return "sensor units missing", "U101", m, s
    if kind == "drop_frame":
        if q0 == "acceleration":
            f0["frame"] = "body"
            return "frame required but undocumented", "U301", m, s
        sensor_field(s, q0).pop("frame", None)
        f0["frame"] = "body"
        return "sensor frame missing", "U301", m, s
    if kind == "drop_ordering":
        s.setdefault("state", {})["orientation"] = {
            "representation": "quaternion"}  # ordering missing
        m["features"].append(
            {"name": "q0", "source": {"quantity": "orientation"},
             "units": "dimensionless", "representation": "quaternion",
             "ordering": "wxyz", "normalization": {"method": "none"},
             "width": 4})
        for c in "wxyz":
            m["raw_layout"].append({"quantity": "orientation",
                                    "component": c})
        return "quat ordering missing", "U102", m, s
    if kind == "unknown_unit":
        sensor_field(s, q0)["units"] = "furlongs_per_fortnight"
        return "unknown unit string", "U101", m, s
    f0["bias_required"] = True
    return "bias required, unconfigured", "E302", m, s


def fault_cycle(rng, kinds, n):
    """Deterministic stream of n fault kinds, each kind guaranteed coverage.

    Repeated shuffled rounds, not rng.choice, so the held-out report is
    byte-identical across runs (pilot reproducibility) and every fault
    kind appears the same number of times (no sampling lottery)."""
    stream = []
    while len(stream) < n:
        round_ = list(kinds)
        rng.shuffle(round_)
        stream.extend(round_)
    return stream[:n]


INVALID_KINDS = ["dim_clash", "frame", "off_layout", "unknown_qty",
                 "bad_norm", "size", "euler", "swap_units"]
AMBIGUOUS_KINDS = ["drop_units", "drop_frame", "drop_ordering",
                   "unknown_unit", "bias_required"]


def build_suite():
    rng = random.Random(SEED)
    cases = []
    valid_pairs = []
    for i in range(60):
        s, m = build_valid(rng)
        valid_pairs.append((s, m))
        cases.append(run_case("valid", f"combo-{i}", s, m, "pass"))
    invalid_kinds = fault_cycle(rng, INVALID_KINDS, 64)
    for i, kind in enumerate(invalid_kinds):
        s, m = valid_pairs[rng.randrange(len(valid_pairs))]
        fault, code, m2, s2 = mutate_invalid(rng, s, m, kind=kind)
        kw = {"model_input_size": 10 ** 6} if code == "E203" else {}
        rep = checker.check(s2, m2, **kw)
        ok = (rep["status"] == "blocked")
        hits = [e for e in rep["errors"] if e["code"] == code]
        diag_ok = bool(hits) and all(h.get("feature") for h in hits)
        cases.append({"category": "invalid", "fault": f"{fault}-{i}",
                      "expected": "blocked", "got": rep["status"],
                      "expected_code": code,
                      "codes": [e["code"] for e in rep["errors"]],
                      "ok": ok and diag_ok, "diag_ok": diag_ok})
    ambiguous_kinds = fault_cycle(rng, AMBIGUOUS_KINDS, 32)
    for i, kind in enumerate(ambiguous_kinds):
        s, m = valid_pairs[rng.randrange(len(valid_pairs))]
        fault, code, m2, s2 = mutate_ambiguous(rng, s, m, kind=kind)
        cases.append(run_case("ambiguous", f"{fault}-{i}", s2, m2,
                              "blocked", code))
    return cases, valid_pairs


def test_heldout_rates():
    cases, _ = build_suite()
    by_cat = {}
    for c in cases:
        by_cat.setdefault(c["category"], []).append(c)
    summary = {k: {"n": len(v), "correct": sum(1 for c in v if c["ok"]),
                   "diag_correct": sum(1 for c in v if c["diag_ok"]),
                   "false": [c for c in v if not c["ok"]][:5]}
               for k, v in by_cat.items()}
    # JSON-serializable summary (strip case bodies from 'false' lists)
    slim = {k: {"n": v["n"], "correct": v["correct"],
                "diag_correct": v["diag_correct"],
                "failures": [{kk: c[kk] for kk in
                              ("fault", "expected", "got", "expected_code",
                               "codes")} for c in v["false"]]}
            for k, v in summary.items()}
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w") as f:
        json.dump({"seed": SEED, "scoring": "valid->pass; invalid->blocked+"
                   "code; ambiguous->blocked+U-code", "summary": slim,
                   "cases": cases}, f, indent=2)
    for cat in ("valid", "invalid", "ambiguous"):
        bad = [c for c in by_cat[cat] if not c["ok"]]
        assert not bad, (cat, bad[:3])
    print("\nheld-out: " + ", ".join(
        f"{k} {v['correct']}/{v['n']}" for k, v in sorted(slim.items())))


def test_heldout_pipeline_parity(tmp_path):
    """Subsample of held-out valid cases: generated C++ matches Python."""
    import subprocess
    cases, pairs = build_suite()
    valids = [(s, m) for (s, m) in pairs][:5]
    for vi, (s, m) in enumerate(valids):
        rep = checker.check(s, m)
        assert rep["status"] == "pass"
        ops = PL.build_ops(s, m)
        # numeric: each op gain equals conversion*scale by construction
        for op, f in zip(ops, [f for f in m["features"]
                               for _ in range(int(f.get("width", 1)))]):
            su = sensor_field(s, f["source"]["quantity"]).get("units")
            a = 1.0 if su == f["units"] else U.conversion(su, f["units"])
            nm = f["normalization"]
            sc = float(nm["scale"]) if nm["method"] == "affine" else 1.0
            assert op["gain"] == float(a * sc)
        py_out = str(tmp_path / f"a{vi}.py")
        h_out = str(tmp_path / f"a{vi}.h")
        PL.generate(s, m, py_out, h_out)
        n_in = len(m["raw_layout"])
        vrng = np.random.default_rng(SEED + vi)
        X = vrng.uniform(-50, 50, size=(8, n_in))
        ns = {}
        exec(open(py_out).read(), ns)  # noqa: S102 - generated test artifact
        py = np.array([ns["adapt"](v) for v in X])
        rows = []
        for v in X:
            lit = ",".join(
                f"{x:.9g}f" if ("." in f"{x:.9g}" or "e" in f"{x:.9g}".lower())
                else f"{x:.9g}.0f" for x in v)
            rows.append(f"{{float r[{n_in}]={{{lit}}};float o[{len(ops)}];"
                        f"contract_adapt(r,o);"
                        f"printf(\"{' '.join(['%.9g'] * len(ops))}\\n\", " +
                        ",".join(f"o[{i}]" for i in range(len(ops))) + ");}")
        src = (f'#include <stdio.h>\n#include "{h_out}"\nint main(){{\n' +
               "\n".join(rows) + "\nreturn 0;}")
        open(tmp_path / f"t{vi}.c", "w").write(src)
        exe = str(tmp_path / f"t{vi}")
        r = subprocess.run(["cc", "-O2", str(tmp_path / f"t{vi}.c"), "-o",
                            exe, "-lm"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[:2000]
        out = subprocess.run([exe], capture_output=True, text=True)
        assert out.returncode == 0
        got = np.array([[float(v) for v in ln.split()]
                        for ln in out.stdout.strip().splitlines()])
        assert got.shape == py.shape
        assert np.allclose(got, py, atol=2e-6), np.abs(got - py).max()
