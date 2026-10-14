"""Memory measurement helpers: estimates vs measured (linker map)."""
from __future__ import annotations

import os
import re


def estimate_from_metadata(metadata: dict, memplan: dict) -> dict:
    return {
        "weight_bytes": metadata["weight_bytes"],
        "activation_bytes": memplan["peak_activation_bytes"],
        "source": "estimated (compiler plan; verify with target linker map)",
    }


def parse_linker_map(text: str) -> dict:
    """Best-effort .text/.rodata/.bss extraction from GNU ld map."""
    out = {}
    for name in (".text", ".rodata", ".data", ".bss"):
        m = re.findall(rf"{re.escape(name)}\s+0x[0-9a-fA-F]+\s+0x([0-9a-fA-F]+)", text)
        out[name] = sum(int(v, 16) for v in m) if m else 0
    out["source"] = "measured (linker map)"
    return out


def binary_size(path: str) -> dict:
    return {"bytes": os.path.getsize(path), "source": "measured (host binary)"}
