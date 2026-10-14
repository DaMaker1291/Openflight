"""Phase 3 audit: adapter math, conventions, Py-vs-C parity, contract checks."""
import os
import subprocess

import numpy as np
import pytest

from openflight.adapters import coordinates as Cc, imu
from openflight.adapters import contracts as K, codegen as CG


def test_quat_ordering_consistency():
    rng = np.random.default_rng(11)
    for _ in range(100):
        qx = rng.normal(size=4)
        qw = Cc.convert_quat(qx, "xyzw", "wxyz")
        assert np.allclose(Cc.quat_to_rot(qx, "xyzw"), Cc.quat_to_rot(qw, "wxyz"),
                           atol=1e-12)


def test_quat_roundtrip():
    rng = np.random.default_rng(12)
    for _ in range(100):
        q = rng.normal(size=4)
        assert np.allclose(Cc.convert_quat(Cc.convert_quat(q, "wxyz", "xyzw"),
                                           "xyzw", "wxyz"), q, atol=1e-12)


def test_rotation_properties():
    rng = np.random.default_rng(13)
    for ordering in ("wxyz", "xyzw"):
        for _ in range(100):
            R = Cc.quat_to_rot(rng.normal(size=4), ordering)
            assert np.allclose(R @ R.T, np.eye(3), atol=1e-12)
            assert abs(float(np.linalg.det(R)) - 1.0) < 1e-9


def test_gravity_sign_convention():
    """Identity orientation, zero acceleration: sensor reads +9.81 on z
    for g_w=(0,0,-9.81) (specific force opposes gravity). Sign is load-bearing."""
    out = imu.accel_measurement(np.zeros(3), np.array([0., 0., -9.81]),
                                np.array([1., 0., 0., 0.]), ordering="wxyz")
    assert np.allclose(out, [0., 0., 9.81])


def test_known_90deg_z_rotation():
    c = np.cos(np.pi / 4)
    q = np.array([c, 0., 0., c])  # +90 deg about z, wxyz
    got = Cc.world_to_body(np.array([1., 0., 0.]), q, "wxyz")
    assert np.allclose(got, [0., -1., 0.], atol=1e-12)
    back = Cc.body_to_world(got, q, "wxyz")
    assert np.allclose(back, [1., 0., 0.], atol=1e-12)


def test_gyro_bias_and_zero_bias():
    o = np.array([0.1, -0.2, 0.3])
    assert np.allclose(imu.gyro_measurement(o), o)
    assert np.allclose(imu.gyro_measurement(o, bias=np.array([0.01, 0., -0.01])),
                       o + [0.01, 0., -0.01])


def test_zero_quaternion_rejected():
    with pytest.raises(ValueError):
        Cc.quat_to_rot(np.zeros(4), "wxyz")
    with pytest.raises(ValueError):
        Cc.quat_to_rot(np.zeros(4), "xyzw")
    with pytest.raises(ValueError):
        Cc.quat_to_rot(np.ones(4), "bad-order")


def test_py_vs_c_parity(tmp_path):
    """Generated C adapter vs float64 Python on deterministic vectors."""
    c = K.load_contract("examples/quadrotor_adapter/drone_contract.yaml")
    CG.generate(c, str(tmp_path / "ad.py"), str(tmp_path / "ad.h"))
    rng = np.random.default_rng(7)
    vecs = []
    for _ in range(50):
        q = rng.normal(size=4)
        q /= np.linalg.norm(q)
        a = rng.normal(size=3) * 5
        b = rng.normal(size=3) * 0.05
        vecs.append((a, q, b))
    g = np.array([0., 0., -9.81])
    py = np.array([imu.accel_measurement(a, g, q, "wxyz", bias=b) for a, q, b in vecs])
    lines = ["#include <stdio.h>", f'#include "{tmp_path}/ad.h"',
             "int main(){", "float g[3]={0,0,-9.81f};"]
    for i, (a, q, b) in enumerate(vecs):
        av = ",".join(f"{v:.9g}f" for v in a)
        qv = ",".join(f"{v:.9g}f" for v in q)
        bv = ",".join(f"{v:.9g}f" for v in b)
        lines += [f"float a{i}[3]={{{av}}};", f"float q{i}[4]={{{qv}}};",
                  f"float b{i}[3]={{{bv}}};", f"float o{i}[3];",
                  f"accel_measurement(a{i},g,q{i},b{i},o{i});",
                  f'printf("%.9g %.9g %.9g\\n",o{i}[0],o{i}[1],o{i}[2]);',
                  f"float w{i}[3]={{0.1f,-0.2f,0.3f}}; float go{i}[3];",
                  f"gyro_measurement(w{i},b{i},go{i});",
                  f'printf("%.9g %.9g %.9g\\n",go{i}[0],go{i}[1],go{i}[2]);']
    lines += ["return 0;}"]
    open(tmp_path / "t.c", "w").write("\n".join(lines))
    exe = str(tmp_path / "t")
    r = subprocess.run(["cc", "-O2", str(tmp_path / "t.c"), "-o", exe, "-lm"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[:2000]
    out = subprocess.run([exe], capture_output=True, text=True)
    assert out.returncode == 0
    rows = np.array([[float(v) for v in ln.split()]
                     for ln in out.stdout.strip().splitlines()])
    assert rows.shape == (100, 3)
    assert np.allclose(rows[0::2], py, atol=2e-6), \
        np.abs(rows[0::2] - py).max()
    gy = np.array([np.array([0.1, -0.2, 0.3]) + b for _, _, b in vecs])
    assert np.allclose(rows[1::2], gy, atol=2e-6)


def test_contract_rejections(tmp_path):
    base = {"schema_version": 1,
            "state": {"position": {"frame": "world", "units": "metres"},
                      "velocity": {"frame": "world", "units": "m/s"},
                      "orientation": {"representation": "quaternion",
                                      "ordering": "wxyz"},
                      "angular_velocity": {"frame": "body", "units": "rad/s"}}}
    K.validate_contract(base)
    bad = {**base, "state": {**base["state"], "orientation": {
        "representation": "quaternion", "ordering": "Hamilton"}}}
    with pytest.raises(ValueError):
        K.validate_contract(bad)
    missing = {"schema_version": 1, "state": {"position": base["state"]["position"]}}
    with pytest.raises(ValueError):
        K.validate_contract(missing)
    nounits = {**base, "imu": {"accelerometer": {"frame": "body"}}}
    with pytest.raises(ValueError):
        K.validate_contract(nounits)


def test_mismatch_detection():
    assert K.check_compat({"ordering": "xyzw"}, {"ordering": "wxyz"}) != []
    assert K.check_compat({"frame": "world"}, {"frame": "body"}) != []
    assert K.check_compat({"units": "m"}, {"units": "cm"}) != []
    assert K.check_compat({"ordering": "wxyz"}, {"ordering": "wxyz"}) == []
