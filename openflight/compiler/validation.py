"""Compiler validation: shapes, dtypes, supported ops."""
from __future__ import annotations

import torch

from openflight.compiler.graph import Graph, SUPPORTED

SUPPORTED_DTYPES = {torch.float32}


def validate_graph(graph: Graph, dtype: torch.dtype = torch.float32) -> dict:
    if not graph.nodes:
        raise ValueError("empty graph: no supported operations found")
    if len(graph.input_shape) != 2 or graph.input_shape[0] != 1:
        raise ValueError(
            f"MCU inference is batch-1 only; example input shape "
            f"{tuple(graph.input_shape)} has batch != 1. Re-run with shape (1, F).")
    for n in graph.nodes:
        if n.operation not in SUPPORTED:
            raise ValueError(
                f"unsupported operator '{n.operation}' at {n.name}. Supported: "
                f"{sorted(SUPPORTED)}. Refusing to approximate.")
        if n.operation == "linear":
            w = n.attributes["weight"]
            b = n.attributes["bias"]
            if w.dtype != torch.float32 or b.dtype != torch.float32:
                raise ValueError(f"{n.name}: only float32 supported, got {w.dtype}")
            if w.dim() != 2 or b.dim() != 1 or w.shape[0] != b.shape[0]:
                raise ValueError(f"{n.name}: bad Linear shapes w={tuple(w.shape)} "
                                 f"b={tuple(b.shape)}")
    # consecutive-dimension consistency (defense in depth; tracing matmul
    # already enforces this, but report it explicitly)
    prev = graph.input_shape[-1]
    for n in graph.nodes:
        if n.operation == "linear":
            want = n.attributes["weight"].shape[1]
            if want != prev:
                raise ValueError(
                    f"{n.name}: in_features {want} != previous dim {prev}")
        prev = n.output_shape[-1]
    in_dim = graph.input_shape[-1]
    out_dim = graph.output_shape[-1]
    return {"input_size": in_dim, "output_size": out_dim,
            "params": graph.param_count,
            "weight_bytes": graph.param_count * 4,
            "ops": {op: sum(1 for n in graph.nodes if n.operation == op)
                    for op in SUPPORTED if any(n.operation == op for n in graph.nodes)}}


HEAP_TOKENS = ("malloc", "free(", "calloc", "realloc", " new ", "new[",
               "delete")


def scan_no_heap(path: str) -> list:
    """Source-text scan for heap calls in generated code (comments stripped).

    Evidence level: static text only. Stronger host evidence is the
    `nm -u` object-symbol check (tests); target evidence still requires an
    instrumented on-target run. Never report this as a proof.
    """
    with open(path) as f:
        code = "\n".join(line.split("//")[0] for line in f.read().splitlines())
    return [t for t in HEAP_TOKENS if t in code]
