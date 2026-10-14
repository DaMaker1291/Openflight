"""Phase 2 audit: per-operator correctness, shapes, memory plan, reproducibility.

All tests execute for real (host toolchain). No hardware claims.
"""
import json
import os
import subprocess

import numpy as np
import pytest
import torch
import torch.nn as nn
import torch.nn.functional as F

from openflight.compiler import graph as G, validation as V
from openflight.compiler import memory_planner as M, codegen as C
from openflight.compiler.api import compile_model


def _compile_seq(mods, in_dim, tmp_path, name="m"):
    torch.manual_seed(0)
    m = nn.Sequential(*mods)
    m.eval()
    g = G.extract_graph(m, torch.zeros(1, in_dim))
    info = V.validate_graph(g)
    mem = M.plan_memory(g)
    out = os.path.join(str(tmp_path), name)
    C.generate(g, mem, info, out)
    return m, g, info, mem, out


def test_linear_only_differential(tmp_path):
    from openflight.benchmark import runner
    torch.manual_seed(3)
    m = nn.Sequential(nn.Linear(5, 7), nn.Linear(7, 2))
    m.eval()
    torch.save({k: v.cpu() for k, v in m.state_dict().items()},
               str(tmp_path / "w.pt"))
    arch = nn.Sequential(nn.Linear(5, 7), nn.Linear(7, 2))
    out = compile_model(arch, str(tmp_path / "w.pt"), str(tmp_path / "b"))
    res = runner.run_host(out["model"], str(tmp_path / "b"), runs=200)
    assert res["max_abs_err"] < 1e-5, res["max_abs_err"]


def test_all_activations_saturation_differential(tmp_path):
    """relu+tanh+sigmoid chain on U(-100,100): saturation, expf extremes, no NaN."""
    from openflight.benchmark import runner
    torch.manual_seed(1)
    m = nn.Sequential(nn.Linear(4, 8), nn.ReLU(), nn.Linear(8, 8), nn.Tanh(),
                      nn.Linear(8, 8), nn.Sigmoid(), nn.Linear(8, 2))
    m.eval()
    g = G.extract_graph(m, torch.zeros(1, 4))
    info = V.validate_graph(g)
    mem = M.plan_memory(g)
    C.generate(g, mem, info, str(tmp_path / "b"))
    res = runner.run_host(m, str(tmp_path / "b"), runs=500,
                          input_range=(-100.0, 100.0))
    assert np.isfinite(res["got"]).all()
    assert res["max_abs_err"] < 1e-5, res["max_abs_err"]


@pytest.mark.parametrize("bad_mods", [
    [nn.Linear(4, 4), nn.Conv1d(1, 1, 1)],
    [nn.Linear(4, 4), nn.BatchNorm1d(4)],
    [nn.Linear(4, 4), nn.GELU()],
    [nn.Linear(4, 4, bias=False)],
])
def test_unsupported_modules_rejected(bad_mods):
    m = nn.Sequential(*bad_mods)
    with pytest.raises(ValueError):
        G.extract_graph(m, torch.zeros(1, 4))


def test_functional_relu_rejected():
    class FM(nn.Module):
        def __init__(self):
            super().__init__()
            self.fc = nn.Linear(4, 4)

        def forward(self, x):
            return F.relu(self.fc(x))
    with pytest.raises(ValueError):
        G.extract_graph(FM(), torch.zeros(1, 4))


def test_batch_not_one_rejected():
    m = nn.Sequential(nn.Linear(4, 4))
    g = G.extract_graph(m, torch.zeros(3, 4))
    with pytest.raises(ValueError):
        V.validate_graph(g)


def test_consecutive_dim_mismatch_rejected():
    w = torch.randn(8, 4)
    g = G.Graph(
        nodes=[G.Node("linear", ["input"],
                      {"weight": w, "bias": torch.randn(3)},
                      (1, 3), "linear0")],
        input_shape=(1, 4), output_shape=(1, 3), param_count=4 * 8 + 3)
    with pytest.raises(ValueError):
        V.validate_graph(g)


def test_empty_graph_rejected():
    g = G.Graph(nodes=[], input_shape=(1, 4), output_shape=(1, 4))
    with pytest.raises(ValueError):
        V.validate_graph(g)


def test_plan_matches_generated_code(tmp_path):
    """Peak/buffers in memory_report must equal sizes emitted in model.cpp."""
    m, g, info, mem, out = _compile_seq(
        [nn.Linear(12, 64), nn.ReLU(), nn.Linear(64, 64), nn.ReLU(),
         nn.Linear(64, 3)], 12, tmp_path)
    assert mem["peak_activation_bytes"] == 512
    assert mem["peak_activation_bytes"] == sum(
        b["bytes"] for b in mem["buffers"])
    cpp = open(os.path.join(out, "model.cpp")).read()
    for b in mem["buffers"]:
        assert f"float buf_{b['id']}[{b['floats']}];" in cpp
    assert "float scratch[" not in cpp  # no dead stack allocation
    h = open(os.path.join(out, "model.h")).read()
    assert f"SCRATCH_FLOATS = {mem['peak_activation_floats']}" in h
    assert f"SCRATCH_BYTES = {mem['peak_activation_bytes']}" in h


def test_output_alias_safe(tmp_path):
    """predict(in, in) must equal predict(in, out): writes land only at the end."""
    m, g, info, mem, out = _compile_seq(
        [nn.Linear(6, 16), nn.ReLU(), nn.Linear(16, 3)], 6, tmp_path, "al")
    src = ('#include <cstdio>\n#include "model.h"\n'
           'int main(){float io[6]={0.5f,-1.25f,3.0f,0.0f,2.5f,-0.75f};'
           'float ref[3]; openflight::predict(io,ref);'
           'openflight::predict(io,io);'
           'for(int i=0;i<3;i++){float d=io[i]-ref[i]; if(!(d<1e-6f&&d>-1e-6f)) return 1;}'
           'printf("alias-ok\\n"); return 0;}')
    t = str(tmp_path / "alias.cpp")
    open(t, "w").write(src)
    exe = str(tmp_path / "alias")
    r = subprocess.run(["c++", "-O2", "-std=c++17", "-I", out, t,
                        os.path.join(out, "model.cpp"), "-o", exe],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[:2000]
    r2 = subprocess.run([exe], capture_output=True, text=True)
    assert r2.returncode == 0, "aliased output buffer diverges"
    assert "alias-ok" in r2.stdout


def test_reproducible_artifacts(tmp_path):
    torch.manual_seed(0)
    m = nn.Sequential(nn.Linear(12, 64), nn.ReLU(), nn.Linear(64, 3))
    torch.save({k: v.cpu() for k, v in m.state_dict().items()},
               str(tmp_path / "w.pt"))
    a1 = compile_model(nn.Sequential(nn.Linear(12, 64), nn.ReLU(),
                                     nn.Linear(64, 3)),
                       str(tmp_path / "w.pt"), str(tmp_path / "b1"))
    a2 = compile_model(nn.Sequential(nn.Linear(12, 64), nn.ReLU(),
                                     nn.Linear(64, 3)),
                       str(tmp_path / "w.pt"), str(tmp_path / "b2"))
    for f in ("model.h", "model.cpp", "model_metadata.json",
              "input_contract.json", "memory_report.json", "manifest.json"):
        assert open(a1["gen"]["paths"][f]).read() == open(
            a2["gen"]["paths"][f]).read(), f
    assert a1["gen"]["header_sha"] == a2["gen"]["header_sha"]
    assert a1["gen"]["source_sha"] == a2["gen"]["source_sha"]


def test_no_heap_symbols_in_object(tmp_path):
    """Compiled-path evidence: model.o has no undefined heap symbols.

    Stronger than the source grep in the CLI; still host-only (target needs
    its own link + instrumented run — see HARDWARE_PLAN.md).
    """
    m, g, info, mem, out = _compile_seq(
        [nn.Linear(8, 16), nn.Tanh(), nn.Linear(16, 2)], 8, tmp_path, "nm")
    obj = str(tmp_path / "model.o")
    r = subprocess.run(["c++", "-O2", "-std=c++17", "-I", out, "-c",
                        os.path.join(out, "model.cpp"), "-o", obj],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[:2000]
    r2 = subprocess.run(["nm", "-u", obj], capture_output=True, text=True)
    undefined = r2.stdout
    for sym in ("malloc", "free", "calloc", "realloc",
                "operator new", "operator delete"):
        assert sym not in undefined, f"heap symbol {sym} in model.o:\n{undefined}"


def test_runner_single_run(tmp_path):
    from openflight.benchmark import runner
    torch.manual_seed(0)
    m = nn.Sequential(nn.Linear(3, 4), nn.ReLU(), nn.Linear(4, 2))
    m.eval()
    g = G.extract_graph(m, torch.zeros(1, 3))
    C.generate(g, M.plan_memory(g), V.validate_graph(g), str(tmp_path / "b"))
    res = runner.run_host(m, str(tmp_path / "b"), runs=1)
    assert res["latency"]["n"] == 1


def test_planner_overlap_semantics():
    from openflight.compiler.memory_planner import _overlaps, plan_memory
    from openflight.compiler.graph import Graph, Node
    # handoff endpoints conflict; disjoint intervals do not
    assert _overlaps((0, 1), (1, 2))
    assert _overlaps((2, 2), (1, 2))
    assert not _overlaps((0, 1), (2, 3))
    assert not _overlaps((0, 0), (1, 1))

    def chain(dims):
        nodes = [Node("linear", [f"t{k-1}" if k else "input"],
                      {"weight": __import__("torch").zeros(d, 4),
                       "bias": __import__("torch").zeros(4)},
                      (1, d), f"linear{k}") for k, d in enumerate(dims)]
        return Graph(nodes, (1, dims[0]), (1, dims[-1]),
                     sum(d * 4 + 4 for d in dims))

    mem = plan_memory(chain([8, 16, 8, 2]))
    colors = [t["buffer"] for t in mem["tensors"]]
    assert colors == [0, 1, 0, 1]  # ping-pong: adjacency conflicts, nothing else
    assert mem["peak_activation_bytes"] == (8 + 16) * 4
    assert mem["peak_activation_bytes"] == sum(
        b["bytes"] for b in mem["buffers"])
