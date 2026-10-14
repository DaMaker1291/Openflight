"""C++ code generation from Graph + memory plan."""
from __future__ import annotations

import hashlib
import json
import os

import numpy as np

from openflight.compiler.graph import Graph
from openflight.compiler.operators import emit_linear, emit_activation


def _cf(v: float) -> str:
    s = f"{float(v):.9g}"
    if "e" not in s and "E" not in s and "." not in s:
        s += ".0"
    return s + "f"


def _fmt_row(w: np.ndarray) -> str:
    return ", ".join(_cf(v) for v in w.ravel())


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def generate(graph: Graph, memplan: dict, info: dict, outdir: str,
             model_name: str = "model", atol: float = 1e-5,
             rtol: float = 1e-4) -> dict:
    os.makedirs(outdir, exist_ok=True)
    in_dim = info["input_size"]
    out_dim = info["output_size"]

    # dims per tensor
    dims = [n.output_shape[-1] for n in graph.nodes]

    header = [f"#pragma once",
              "#include <cstddef>",
              "#include <cmath>",
              "",
              "namespace openflight {",
              "",
              f"constexpr std::size_t INPUT_SIZE = {in_dim};",
              f"constexpr std::size_t OUTPUT_SIZE = {out_dim};",
              f"constexpr std::size_t SCRATCH_FLOATS = {memplan['peak_activation_floats']};",
              f"constexpr std::size_t SCRATCH_BYTES = {memplan['peak_activation_bytes']};",
              "",
              "// Caller-owned buffers. No malloc/free/new/delete in predict().",
              "void predict(const float* input, float* output);",
              "void predict_scratch(const float* input, float* output, float* scratch);",
              "",
              "}  // namespace openflight"]
    h_text = "\n".join(header) + "\n"

    cpp = ["#include \"model.h\"", "",
           "namespace openflight {", "",
           "// ---- weights (place in Flash via const; verify linker map) ----"]
    for idx, n in enumerate(graph.nodes):
        if n.operation == "linear":
            w = n.attributes["weight"].numpy()
            b = n.attributes["bias"].numpy()
            cpp.append(f"static const float W_{idx}[{w.shape[0]}][{w.shape[1]}] = {{")
            for r in range(w.shape[0]):
                cpp.append("    {" + _fmt_row(w[r]) + "},")
            cpp.append("};")
            cpp.append(f"static const float BIAS_{idx}[{b.shape[0]}] = {{{_fmt_row(b)}}};")
    cpp += ["",
            "// ---- inference: fixed-size stack buffers sized from the memory plan ----",
            "// (no malloc/free/new/delete; input/output buffers are caller-owned) ----",
            "void predict_scratch(const float* input, float* output, float* scratch) {",
            "    (void)scratch;  // reserved for future caller-provided workspace",
            ]
    bufs = memplan["buffers"]
    if not bufs:
        raise ValueError("empty graph: nothing to generate")
    if len(bufs) > 2:
        raise ValueError(
            f"memory plan produced {len(bufs)} buffers; the generated "
            f"ping-pong loop supports 1 or 2 — refusing to silently miscompile")
    for b in bufs:
        cpp.append(f"    float buf_{b['id']}[{max(b['floats'], 1)}];")
    cpp += ["    const float* src = input;",
            f"    float* dst = buf_{bufs[0]['id']};"]
    nb = len(bufs)
    for idx, n in enumerate(graph.nodes):
        ind = n.output_shape[-1]
        if n.operation == "linear":
            indim = in_dim if idx == 0 else dims[idx - 1]
            cpp.append(emit_linear(idx, indim, ind))
        else:
            cpp.append(emit_activation(idx, n.operation, ind))
        if idx < len(graph.nodes) - 1:
            if nb > 1:
                cpp += ["    src = dst;",
                        f"    dst = (dst == buf_{bufs[0]['id']}) ? buf_{bufs[1]['id']} : buf_{bufs[0]['id']};"]
            else:
                cpp += ["    src = dst;"]
        else:
            cpp += ["    for (std::size_t i = 0; i < OUTPUT_SIZE; ++i) output[i] = dst[i];"]
    cpp += ["}",
            "",
            "void predict(const float* input, float* output) {",
            "    predict_scratch(input, output, nullptr);",
            "}",
            "",
            "}  // namespace openflight"]
    cpp_text = "\n".join(cpp) + "\n"

    metadata = {"model": model_name, "input_size": in_dim, "output_size": out_dim,
                "params": info["params"], "weight_bytes": info["weight_bytes"],
                "ops": info["ops"],
                "nodes": [{"op": n.operation, "name": n.name,
                           "out": list(n.output_shape)} for n in graph.nodes]}
    input_contract = {"schema_version": 1, "model": model_name,
                      "input_size": in_dim, "output_size": out_dim, "dtype": "float32",
                      "input_layout": "row-major [1, input_size]",
                      "normalization": "caller responsibility — see deployment contract"}
    memory_report = {"weight_bytes_fp32": info["weight_bytes"],
                     "activation_plan": memplan,
                     "notes": ["weights const (Flash candidate — verify linker map)",
                               "activations are fixed-size stack buffers sized from "
                               "the plan (NOT static storage; measure stack "
                               "high-water mark on target)",
                               "input/output caller-owned; stack measured on target"]}
    manifest = {"schema_version": 1, "model": model_name,
                "header_sha": _sha(h_text), "source_sha": _sha(cpp_text),
                "guarantees": {
                    "no_dynamic_allocation_in_predict": "static inspection "
                    "(predict/predict_scratch contain no malloc/free/new/delete; "
                    "verify by grepping generated model.cpp + allocation "
                    "instrumentation on target)",
                    "fixed_size_buffers": True,
                    "numerical_equivalence": "pending host differential test",
                    "flash_sram_wcet": "measured on target, not proven by compile"}}
    test_py = f'''"""Auto-generated differential test: PyTorch vs compiled C++."""
import json, subprocess, os, struct, sys
import numpy as np
import torch
ATOL={atol}; RTOL={rtol}
def main(weights, n=200, seed=0):
    rng = np.random.default_rng(seed)
    # NOTE: fill input generation per your normalization; default U(-1,1)
    X = rng.uniform(-1, 1, size=(n, {in_dim})).astype(np.float32)
    np.save(os.path.join(os.path.dirname(__file__), "test_inputs.npy"), X)
    print(f"wrote {{n}} test vectors; compile host harness and compare (see docs)")
if __name__ == "__main__":
    main(*sys.argv[1:])
'''
    paths = {}
    for name, text in [("model.h", h_text), ("model.cpp", cpp_text),
                       ("model_metadata.json", json.dumps(metadata, indent=2)),
                       ("input_contract.json", json.dumps(input_contract, indent=2)),
                       ("memory_report.json", json.dumps(memory_report, indent=2)),
                       ("manifest.json", json.dumps(manifest, indent=2)),
                       ("numerical_tests.py", test_py)]:
        p = os.path.join(outdir, name)
        with open(p, "w") as f:
            f.write(text)
        paths[name] = p
    return {"paths": paths, "header_sha": manifest["header_sha"],
            "source_sha": manifest["source_sha"], "metadata": metadata}
