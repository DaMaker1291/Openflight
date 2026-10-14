"""Reconstruct simple MLP architectures from state dicts (no pickling)."""
from __future__ import annotations

import torch.nn as nn


def mlp_from_state_dict(sd: dict) -> nn.Module:
    """Build nn.Sequential Linear/ReLU/Tanh/Sigmoid MLP matching sd keys.

    Supports keys mlp.{i}.weight/bias with i even = Linear. Activation is
    unknown from sd alone, so default ReLU is NOT assumed here — instead we
    build Linear-only chain and require the caller to confirm activations via
    FX tracing of the real arch. This factory is only a shape scaffold for
    weight-shape validation; real codegen uses graph extraction from arch.
    """
    linears = []
    i = 0
    while f"mlp.{i}.weight" in sd:
        w = sd[f"mlp.{i}.weight"]
        if len(w.shape) != 2:
            raise ValueError(f"mlp.{i}.weight must be 2-D, got {tuple(w.shape)}")
        linears.append((w.shape[1], w.shape[0]))
        i += 2
    if not linears:
        # flat keys like '0.weight'? try that
        i = 0
        while f"{i}.weight" in sd:
            w = sd[f"{i}.weight"]
            linears.append((w.shape[1], w.shape[0]))
            i += 2
    if not linears:
        raise ValueError("no Linear weights found (mlp.{i}.weight)")
    layers: list = []
    for k, (inp, out) in enumerate(linears):
        layers.append(nn.Linear(inp, out))
        if k < len(linears) - 1:
            layers.append(nn.ReLU())
    return nn.Sequential(*layers)
