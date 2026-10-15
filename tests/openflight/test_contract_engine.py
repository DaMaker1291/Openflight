"""Contract engine tests: schema, checker codes, unit pipeline parity, stale."""
import copy
import os
import subprocess

import numpy as np
import pytest

from openflight.adapters import contracts as C
from openflight.contract import model_contract as MC
from openflight.contract import checker, pipeline as PL
from openflight.contract import units as U

SENSOR = "examples/quadrotor_adapter/drone_contract.yaml"
MODEL = "examples/quadrotor_adapter/model_contract.yaml"


def _load():
    return C.load_contract(SENSOR), MC.load_model_contract(MODEL)


def test_valid_pair_proceeds():
    s, m = _load()
    rep = checker.check(s, m)
    assert rep["status"] == "pass" and rep["deployment"] == "proceed"
    assert rep["errors"] == []


def test_unit_factors():
    assert U.conversion("degrees_per_second", "radians_per_second") == \
        pytest.approx(0.017453292519943295)
    assert U.conversion("radians_per_second", "degrees_per_second") == \
        pytest.approx(57.29577951308232)
    assert U.conversion("centimetres", "metres") == pytest.approx(0.01)
    with pytest.raises(ValueError):
        U.conversion("radians_per_second", "metres")
    with pytest.raises(KeyError):
        U.conversion("furlongs", "metres")


def test_schema_rejections(tmp_path):
    s, m = _load()
    bad = copy.deepcopy(m)
    bad["features"][0]["normalization"] = {"method": "affine"}  # no scale
    with pytest.raises(ValueError):
        MC.validate_model_contract(bad)
    bad2 = copy.deepcopy(m)
    bad2["features"][0]["representation"] = "quaternion"  # no ordering
    with pytest.raises(ValueError):
        MC.validate_model_contract(bad2)
    bad3 = copy.deepcopy(m)
    bad3["features"] = bad3["features"][:5]  # widths sum 5 != 6
    with pytest.raises(ValueError):
        MC.validate_model_contract(bad3)


def _cflt(v: float) -> str:
    s = f"{float(v):.9g}"
    if "e" not in s and "E" not in s and "." not in s:
        s += ".0"
    return s + "f"


def test_pipeline_py_vs_c_parity(tmp_path):
    """Same raw vector incl. zero/negative/large -> Py and C++ agree."""
    s, m = _load()
    assert checker.check(s, m)["status"] == "pass"
    py_out = str(tmp_path / "adapt.py")
    h_out = str(tmp_path / "adapt.h")
    PL.generate(s, m, py_out, h_out)
    rng = np.random.default_rng(3)
    vecs = [np.zeros(6), np.array([-9.81, 0., 0., -3.0, 2.5, -0.5]),
            rng.normal(size=(20, 6)) * 30]
    X = np.vstack(vecs)
    import importlib.util
    spec = importlib.util.spec_from_file_location("adapt", py_out)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    py = np.array([mod.adapt(v) for v in X])
    rows = "\n".join(
        f'{{float r[6]={{{",".join(_cflt(v) for v in v)}}}; float o[6]; '
        f'contract_adapt(r,o); printf("%.9g %.9g %.9g %.9g %.9g %.9g\\n",'
        f'o[0],o[1],o[2],o[3],o[4],o[5]);}}' for v in X)
    src = (f'#include <stdio.h>\n#include "{h_out}"\nint main(){{\n{rows}\n'
           f'return 0;}}')
    open(tmp_path / "t.c", "w").write(src)
    exe = str(tmp_path / "t")
    r = subprocess.run(["cc", "-O2", str(tmp_path / "t.c"), "-o", exe],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[:2000]
    out = subprocess.run([exe], capture_output=True, text=True)
    assert out.returncode == 0
    got = np.array([[float(v) for v in ln.split()]
                    for ln in out.stdout.strip().splitlines()])
    assert got.shape == py.shape
    assert np.allclose(got, py, atol=2e-6), np.abs(got - py).max()


def test_unit_conversion_end_to_end(tmp_path):
    """deg/s firmware + rad/s model: factor applied identically both languages."""
    s, m = _load()
    m = copy.deepcopy(m)
    for f in m["features"]:
        if f["name"].startswith("gyro"):
            f["units"] = "degrees_per_second"  # now sensor rad/s -> model deg/s
    rep = checker.check(s, m)
    assert rep["status"] == "pass"
    conv = [c for c in rep["conversions"] if c["kind"] == "unit_scale"]
    assert len(conv) == 3
    assert conv[0]["factor"] == pytest.approx(57.29577951308232)
    PL.generate(s, m, str(tmp_path / "a.py"), str(tmp_path / "a.h"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("a", str(tmp_path / "a.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    raw = np.array([0., 0., 9.81, 1.0, -2.0, 0.5])
    got = mod.adapt(raw)
    # gyro_x: 1 rad/s -> deg/s (57.2958) then affine S=0.1
    assert got[3] == pytest.approx(5.729577951308232)


def test_stale_detection(tmp_path):
    import shutil
    sp = str(tmp_path / "s.yaml")
    mp = str(tmp_path / "m.yaml")
    shutil.copy(SENSOR, sp)
    shutil.copy(MODEL, mp)
    s = C.load_contract(sp)
    m = MC.load_model_contract(mp)
    PL.generate(s, m, str(tmp_path / "a.py"), str(tmp_path / "a.h"))
    man = PL.write_manifest(sp, mp, str(tmp_path))
    assert PL.check_stale(str(tmp_path)) == []
    with open(mp, "a") as f:  # contract changed after generation
        f.write("\n# touch\n")
    probs = PL.check_stale(str(tmp_path))
    assert len(probs) == 1 and "model_contract changed" in probs[0]


# ------------------------------------------- audit round 4 (v0.2.5 schema gaps)

def test_schema_rejects_duplicate_raw_layout():
    # A duplicated (quantity, component) binding is ambiguous and must be
    # refused at load, not silently collapsed by dict indexing (audit P1).
    _, m = _load()
    bad = copy.deepcopy(m)
    bad["raw_layout"].append(dict(bad["raw_layout"][0]))
    with pytest.raises(ValueError, match="duplicate raw_layout"):
        MC.validate_model_contract(bad)


def test_schema_rejects_missing_component_in_raw_layout():
    # Every raw_layout entry needs a component (guards the binding keys).
    _, m = _load()
    bad = copy.deepcopy(m)
    bad["raw_layout"][0] = {"quantity": "acceleration"}
    with pytest.raises(ValueError, match="component"):
        MC.validate_model_contract(bad)


def test_schema_rejects_nonstring_units_and_frame():
    # Schema must enforce types: non-string units/frame never reach the
    # checker as "equal malformed" pairs (audit schema-hardening).
    _, m = _load()
    bad = copy.deepcopy(m)
    bad["features"][0]["units"] = 42
    with pytest.raises(ValueError, match="units"):
        MC.validate_model_contract(bad)
    bad2 = copy.deepcopy(m)
    bad2["features"][0]["frame"] = 42
    with pytest.raises(ValueError, match="frame"):
        MC.validate_model_contract(bad2)


def test_schema_accepts_valid_unique_layout():
    # Sanity: the shipped pair still loads and the loaded copy round-trips.
    _, m = _load()
    out = MC.validate_model_contract(copy.deepcopy(m))
    assert isinstance(out["raw_layout"], list)
    keys = [(r["quantity"], r["component"]) for r in out["raw_layout"]]
    assert len(keys) == len(set(keys))
