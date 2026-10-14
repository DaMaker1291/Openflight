"""Safe model loading. Never unpickle arbitrary .pt files with pickle.

Supported inputs:
  1. Observer-style checkpoint dict saved with weights_only-compatible types:
     {model: state_dict, mean, std, t_mean, t_std, in_dim, W, H}
  2. Plain state_dict {layer.weight: Tensor, ...} + user-supplied arch module.
  3. (arch_module, state_dict_path) pair via explicit interface.
"""
from __future__ import annotations

import hashlib
import io
import os

import torch
import torch.nn as nn


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_state_dict_safe(path: str) -> dict:
    """Load only tensor data (weights_only=True). Raises on pickle payloads."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"weights not found: {path}")
    try:
        obj = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as e:  # e.g. pickle-only checkpoint
        raise ValueError(
            f"{path}: refusing to unpickle arbitrary objects ({e}). "
            "Export weights via torch.save(state_dict) or a plain dict of "
            "tensors/lists/floats."
        ) from e
    return obj


def bind_weights(arch: nn.Module, state_dict: dict) -> nn.Module:
    """Load a state dict into a user-supplied arch (no deserialization of code)."""
    arch_keys = set(arch.state_dict().keys())
    # remap common prefixes: observer checkpoints use mlp.{i}.*, plain
    # Sequential archs use {i}.* — strip one leading 'mlp.' if that aligns keys
    if set(state_dict.keys()) != arch_keys:
        stripped = {k[4:] if k.startswith("mlp.") else k: v
                    for k, v in state_dict.items()}
        if set(stripped.keys()) == arch_keys:
            state_dict = stripped
    missing, unexpected = arch.load_state_dict(state_dict, strict=False), None
    # load_state_dict returns NamedTuple(missing_keys, unexpected_keys)
    if missing.missing_keys or missing.unexpected_keys:
        raise ValueError(
            f"parameter mismatch: missing={missing.missing_keys} "
            f"unexpected={missing.unexpected_keys}"
        )
    arch.eval()
    return arch


def load_model(arch: nn.Module | None, weights_path: str) -> tuple[nn.Module, dict]:
    """Primary entry: arch supplied by caller + separate weights file.

    Also accepts observer-style checkpoints (dict with 'model' key) when
    arch is None, by reconstructing a Sequential MLP from the state dict
    shapes (Linear+ReLU only — anything else must supply arch explicitly).
    """
    obj = load_state_dict_safe(weights_path)
    if arch is not None:
        if isinstance(obj, dict) and "model" in obj and isinstance(obj["model"], dict):
            sd = obj["model"]
        elif isinstance(obj, dict) and all(hasattr(v, "shape") for v in obj.values()):
            sd = obj
        else:
            raise ValueError(
                f"{weights_path}: unrecognized weights format "
                f"(keys={list(obj)[:8] if isinstance(obj, dict) else type(obj)})"
            )
        model = bind_weights(arch, sd)
        meta = obj if isinstance(obj, dict) and "model" in obj else {}
        return model, meta
    # arch is None: only observer-style or plain MLP state dicts
    if isinstance(obj, dict) and "model" in obj:
        from openflight.compiler.arch_factory import mlp_from_state_dict

        model = mlp_from_state_dict(obj["model"])
        model = bind_weights(model, obj["model"])
        return model, obj
    if isinstance(obj, dict):
        from openflight.compiler.arch_factory import mlp_from_state_dict

        model = mlp_from_state_dict(obj)
        model = bind_weights(model, obj)
        return model, {}
    raise ValueError(f"{weights_path}: cannot infer architecture; pass arch explicitly")
