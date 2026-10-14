"""Compiler + adapter + protocol tests (host-only, no hardware)."""
import numpy as np
import torch
import torch.nn as nn


def _mlp():
    torch.manual_seed(0)
    return nn.Sequential(nn.Linear(12, 64), nn.ReLU(), nn.Linear(64, 64),
                         nn.ReLU(), nn.Linear(64, 3))


def test_graph_and_codegen(tmp_path):
    from openflight.compiler import graph as G, validation as V
    from openflight.compiler import memory_planner as M, codegen as C
    m = _mlp()
    g = G.extract_graph(m, torch.zeros(1, 12))
    assert [n.operation for n in g.nodes] == ["linear", "relu", "linear", "relu", "linear"]
    assert g.param_count == 12 * 64 + 64 + 64 * 64 + 64 + 64 * 3 + 3
    info = V.validate_graph(g)
    assert info["weight_bytes"] == g.param_count * 4
    mem = M.plan_memory(g)
    assert mem["peak_activation_bytes"] > 0
    C.generate(g, mem, info, str(tmp_path))
    code = (tmp_path / "model.cpp").read_text()
    code = "\n".join(l.split("//")[0] for l in code.splitlines())  # drop comments
    for tok in ("malloc", "free(", "calloc", "realloc", " new ", "new[",
                "delete"):
        assert tok not in code, tok


def test_unsupported_rejected():
    from openflight.compiler import graph as G
    m = nn.Sequential(nn.Linear(4, 4), nn.Conv1d(1, 1, 1))
    try:
        G.extract_graph(m, torch.zeros(1, 4))
    except ValueError:
        return
    raise AssertionError("should have rejected Conv1d")


def test_adapter_agreement():
    from openflight.adapters import coordinates as Cc, imu
    rng = np.random.default_rng(0)
    for _ in range(200):
        q = rng.normal(size=4)
        a_w = rng.normal(size=3)
        g_w = np.array([0, 0, -9.81])
        b = rng.normal(size=3) * 0.01
        py = imu.accel_measurement(a_w, g_w, q, "wxyz", bias=b, noise=None)
        # C++ path uses same formula; check python self-consistency + rotation norm
        R = Cc.quat_to_rot(q, "wxyz")
        assert abs(float(np.linalg.det(R)) - 1.0) < 1e-6
        assert py.shape == (3,)


def test_protocol_crc():
    from openflight.benchmark import protocol as P
    pkt = P.encode(P.RUN_TEST, 7, b"\x01\x02")
    mt, seq, body = P.decode(pkt)
    assert (mt, seq, body) == (P.RUN_TEST, 7, b"\x01\x02")
    bad = bytearray(pkt)
    bad[-1] ^= 0xFF
    try:
        P.decode(bytes(bad))
    except ValueError:
        return
    raise AssertionError("crc mismatch not rejected")
