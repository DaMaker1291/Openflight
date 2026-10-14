"""High-level compile entry: model -> build dir."""
from __future__ import annotations

import torch

from openflight.compiler import loader as _loader
from openflight.compiler import graph as _graph
from openflight.compiler import validation as _validation
from openflight.compiler import memory_planner as _mem
from openflight.compiler import codegen as _codegen


def compile_model(arch=None, weights_path: str = "", outdir: str = "build",
                  example_input=None, model_name: str = "model",
                  atol: float = 1e-5, rtol: float = 1e-4) -> dict:
    model, meta = _loader.load_model(arch, weights_path)
    model.eval()
    if example_input is None:
        # infer input dim from weights
        try:
            sd = model.state_dict()
            first = [v for k, v in sd.items() if k.endswith(".weight")][0]
            ind = first.shape[1]
        except Exception:
            ind = 12
        example_input = torch.zeros(1, ind)
    g = _graph.extract_graph(model, example_input)
    info = _validation.validate_graph(g)
    mem = _mem.plan_memory(g)
    gen = _codegen.generate(g, mem, info, outdir, model_name, atol, rtol)
    return {"graph": g, "info": info, "mem": mem, "gen": gen,
            "weights_sha": _loader.sha256_file(weights_path),
            "meta": meta, "model": model}
