"""C++ emitters per operator. Generated code: no malloc/free/new/delete."""
from __future__ import annotations


def emit_linear(idx: int, in_dim: int, out_dim: int) -> str:
    return (
        f"    // node {idx}: linear {in_dim}->{out_dim}\n"
        f"    for (std::size_t j = 0; j < {out_dim}; ++j) {{\n"
        f"        float s = BIAS_{idx}[j];\n"
        f"        for (std::size_t i = 0; i < {in_dim}; ++i) s += W_{idx}[j][i] * src[i];\n"
        f"        dst[j] = s;\n"
        f"    }}\n"
    )


def emit_activation(idx: int, kind: str, dim: int) -> str:
    if kind == "relu":
        fn = "    dst[i] = src[i] > 0.0f ? src[i] : 0.0f;"
    elif kind == "tanh":
        fn = "    dst[i] = tanhf(src[i]);"
    elif kind == "sigmoid":
        fn = "    dst[i] = 1.0f / (1.0f + expf(-src[i]));"
    else:
        raise ValueError(kind)
    return (
        f"    // node {idx}: {kind} ({dim})\n"
        f"    for (std::size_t i = 0; i < {dim}; ++i) {{\n"
        f"{fn}\n"
        f"    }}\n"
    )
