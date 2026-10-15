"""Generated contract battery: valid / invalid / ambiguous pairs.

Deterministic combinatorial generation (seeded, fully reproducible) over the
checker's input surface. Writes results/contract_battery_report.json and
asserts aggregate rates: 0 false accepts, 0 false rejects, 100% ambiguous
blocked, 100% correct diagnostics.
"""
import itertools
import json
import os

from openflight.contract import checker

SEED = 20261011
REPORT = "results/contract_battery_report.json"

GYRO_UNITS = ["radians_per_second", "degrees_per_second", "rpm"]
ACCEL_UNITS = ["metres_per_second_squared", "g"]
NORMS = [{"method": "affine", "scale": 0.1, "offset": 0.0},
         {"method": "none"}]


def make_sensor(gyro_units="radians_per_second",
                accel_units="metres_per_second_squared",
                gyro_frame="body", drop=()):
    s = {"state": {"angular_velocity": {"units": gyro_units,
                                        "frame": gyro_frame}},
         "imu": {"accelerometer": {"units": accel_units}}}
    for path in drop:
        node = s
        for k in path[:-1]:
            node = node[k]
        node.pop(path[-1], None)
    return s


def make_model(gyro_units="radians_per_second",
               accel_units="metres_per_second_squared",
               norm=None, gyro_frame="body", order=("gx", "gy", "ax", "ay")):
    norm = norm or {"method": "affine", "scale": 0.1, "offset": 0.0}
    feats, raw = [], []
    for comp in order:
        if comp.startswith("g"):
            qty, mu = "angular_velocity", gyro_units
        else:
            qty, mu = "acceleration", accel_units
        feats.append({"name": comp,
                      "source": {"quantity": qty, "component": comp[1]},
                      "units": mu, "frame": gyro_frame if comp.startswith("g")
                      else None,
                      "normalization": dict(norm)})
        raw.append({"quantity": qty, "component": comp[1]})
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
    return {"category": category, "fault": fault,
            "expected": expect, "got": rep["status"],
            "expected_code": expect_code,
            "codes": [e["code"] for e in rep["errors"]],
            "ok": ok, "diag_ok": diag_ok}


def build_battery():
    cases = []
    # ---- VALID: convertible units x norms x frames-matching ----
    for gu, au, nm in itertools.product(GYRO_UNITS, ACCEL_UNITS, NORMS):
        cases.append(run_case(
            "valid", f"units {gu}/{au} norm={nm['method']}",
            make_sensor(gyro_units="radians_per_second",
                        accel_units="metres_per_second_squared"),
            make_model(gyro_units=gu, accel_units=au, norm=nm), "pass"))
    # valid with different feature counts/orderings
    for order in [("gx", "ax"), ("ax", "ay", "gx", "gy"),
                  ("gy", "gx", "ay", "ax")]:
        cases.append(run_case(
            "valid", f"order={order}",
            make_sensor(), make_model(order=order), "pass"))
    # ---- INVALID ----
    s, m = make_sensor(), make_model()
    m2 = dict(m, features=[dict(f, units="metres") if f["name"] == "gx"
                           else f for f in m["features"]])
    cases.append(run_case("invalid", "dimension clash on gx", s, m2,
                          "blocked", "E101"))
    m2 = dict(m, features=[dict(f, frame="world") if f["name"] == "gx"
                           else f for f in m["features"]])
    cases.append(run_case("invalid", "frame mismatch on gx", s, m2,
                          "blocked", "E301"))
    m2 = dict(m, features=[dict(f, source={"quantity": "angular_velocity",
                                           "component": "z"})
                           if f["name"] == "gx" else f for f in m["features"]])
    cases.append(run_case("invalid", "gx bound off-layout", s, m2,
                          "blocked", "E402"))
    m2 = dict(m, features=[dict(f, source={"quantity": "magnetometer",
                                           "component": "x"})
                           if f["name"] == "gx" else f for f in m["features"]])
    cases.append(run_case("invalid", "unknown quantity", s, m2,
                          "blocked", "E401"))
    m2 = dict(m, features=[dict(f, normalization={"method": "zscore"})
                           if f["name"] == "ax" else f for f in m["features"]])
    cases.append(run_case("invalid", "bad norm method on ax", s, m2,
                          "blocked", "E201"))
    cases.append(run_case("invalid", "width sum != model size", s, m,
                          "blocked", "E203", model_input_size=99))
    # unsupported representation declared on sensor side ordering
    s3 = make_sensor()
    s3["state"]["orientation"] = {"representation": "euler",
                                  "ordering": "xyz"}
    m3 = {"raw_layout": [{"quantity": "orientation", "component": "x"}],
          "features": [{"name": "q", "source": {"quantity": "orientation"},
                        "units": "dimensionless",
                        "representation": "quaternion", "ordering": "wxyz",
                        "normalization": {"method": "none"}, "width": 4}]}
    cases.append(run_case("invalid", "quat entries incomplete", s3, m3,
                          "blocked", "E402"))
    # ---- AMBIGUOUS (must block with U-codes, never guess) ----
    cases.append(run_case(
        "ambiguous", "sensor gyro units missing",
        make_sensor(drop=[("state", "angular_velocity", "units")]),
        make_model(), "blocked", "U101"))
    cases.append(run_case(
        "ambiguous", "sensor frame missing, model requires",
        make_sensor(drop=[("state", "angular_velocity", "frame")]),
        make_model(), "blocked", "U301"))
    s4 = make_sensor()
    s4["state"]["orientation"] = {"representation": "quaternion"}  # no ordering
    m4 = {"raw_layout": [{"quantity": "orientation", "component": c}
                         for c in "wxyz"],
          "features": [{"name": "q", "source": {"quantity": "orientation"},
                        "units": "dimensionless",
                        "representation": "quaternion", "ordering": "wxyz",
                        "normalization": {"method": "none"}, "width": 4}]}
    cases.append(run_case("ambiguous", "sensor quat ordering missing",
                          s4, m4, "blocked", "U102"))
    return cases


def summarize(cases):
    by_cat = {}
    for c in cases:
        by_cat.setdefault(c["category"], []).append(c)
    summary = {}
    for cat, cs in by_cat.items():
        summary[cat] = {"n": len(cs),
                        "correct": sum(1 for c in cs if c["ok"]),
                        "diag_correct": sum(1 for c in cs if c["diag_ok"])}
    return summary


def test_battery_rates():
    cases = build_battery()
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w") as f:
        json.dump({"seed": SEED, "summary": summarize(cases),
                   "cases": cases}, f, indent=2)
    by_cat = {}
    for c in cases:
        by_cat.setdefault(c["category"], []).append(c)
    n_valid = len(by_cat["valid"])
    assert all(c["ok"] for c in by_cat["valid"]), \
        [c for c in by_cat["valid"] if not c["ok"]]
    assert all(c["ok"] for c in by_cat["invalid"]), \
        [c for c in by_cat["invalid"] if not c["ok"]]
    assert all(c["ok"] for c in by_cat["ambiguous"]), \
        [c for c in by_cat["ambiguous"] if not c["ok"]]
    print(f"\nvalid: {n_valid} (0 false rejects) | "
          f"invalid: {len(by_cat['invalid'])} (0 false accepts) | "
          f"ambiguous: {len(by_cat['ambiguous'])} (all blocked, fail-closed)")


def test_check_fail_closed_on_empty_contracts():
    # library misuse: check({}, {}) must block with E002, never pass
    rep = checker.check({}, {})
    assert rep["status"] == "blocked"
    assert rep["errors"] and rep["errors"][0]["code"] == "E002"


def test_check_fail_closed_on_non_list_features():
    rep = checker.check({"features": "x"}, {"features": []})
    assert rep["status"] == "blocked"
    assert rep["errors"][0]["code"] == "E002"
    assert "features" in rep["errors"][0]["reason"]


def test_check_fail_closed_on_non_dict_feature_entries():
    rep = checker.check({"features": [1, 2]}, {"features": [{"name": "a"}]})
    assert rep["status"] == "blocked"
    assert rep["errors"][0]["code"] == "E002"


# ------------------------------------------- audit round 4 (v0.2.5 gate holes)

def test_check_blocks_matching_unknown_units():
    # Two declarations that agree on an unregistered token agree only with
    # themselves, not with the unit system. Registry membership must be
    # checked before equality can count as compatibility (audit P0).
    s = make_sensor(accel_units="mystery_unit", gyro_units="mystery_unit")
    m = make_model(accel_units="mystery_unit", gyro_units="mystery_unit")
    rep = checker.check(s, m)
    assert rep["status"] == "blocked"
    assert rep["errors"], "unknown units must produce diagnostics"
    assert all(e["code"] == "U101" for e in rep["errors"]), rep["errors"]
    assert rep["deployment"] == "blocked"


def test_check_blocks_duplicate_raw_layout():
    # A duplicate (quantity, component) binding is ambiguous: the checker
    # must refuse rather than let a dict silently overwrite the first entry
    # (audit P1).
    s = make_sensor()
    m = make_model(order=("gx", "ax"))
    m["raw_layout"].append(dict(m["raw_layout"][0]))
    rep = checker.check(s, m)
    assert rep["status"] == "blocked"
    assert any(e["code"] == "E206" for e in rep["errors"]), rep["errors"]


def test_check_fail_closed_on_malformed_width():
    # width: "three" must be a structured error, never an uncaught
    # ValueError escaping check() (audit schema-hardening).
    s = make_sensor()
    m = make_model()
    m["features"][0]["width"] = "three"
    rep = checker.check(s, m)  # must not raise
    assert rep["status"] == "blocked"
    assert rep["errors"], "malformed width must be diagnosed"


def test_check_fail_closed_on_nonstring_units():
    # units: 42 on both sides must not slip through the equality path
    # (audit schema-hardening: false PROCEED on malformed input).
    s = make_sensor()
    m = make_model()
    s["state"]["angular_velocity"]["units"] = 42
    s["imu"]["accelerometer"]["units"] = 42
    for f in m["features"]:
        f["units"] = 42
    rep = checker.check(s, m)
    assert rep["status"] == "blocked", "matching malformed units passed"


def test_check_fail_closed_on_nonstring_frame():
    # frame: 42 on both sides is not a frame name and must block (E303),
    # never compare equal and pass.
    s = make_sensor()
    m = make_model()
    s["state"]["angular_velocity"]["frame"] = 42
    for f in m["features"]:
        if f["name"].startswith("g"):
            f["frame"] = 42
    rep = checker.check(s, m)
    assert rep["status"] == "blocked", "non-string frames passed"
